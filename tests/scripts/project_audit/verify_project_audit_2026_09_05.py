"""2026-09-05 全仓审查首批修复验证。

覆盖：
1. WebSocket 聊天超时、聊天异常、问候异常都能返回带时间戳的错误包；
2. 两个历史维护脚本可被 Python 解析；
3. 健康工具类型依赖完整，食物效果映射没有重复键；
4. 敏感资料有真实 Git 忽略规则。
"""

from __future__ import annotations

import ast
import asyncio
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interfaces.websocket.adapters.handlers.chat import streaming  # noqa: E402
from routers.v1.system import search_web  # noqa: E402
from scripts.sherpa_ncnn.download_assets import _safe_extract_tar  # noqa: E402
from tests.scripts.audit_tests import (  # noqa: E402
    audit_dead_imports,
    audit_pycache,
)


class _WebSocket:
    platform = "web"

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


class _Adapter:
    async def _register_chat_task(
        self, _websocket: _WebSocket, _message_id: str, task: asyncio.Task
    ) -> None:
        await task


class _FailingStreamingHandler:
    async def handle_stream(self, **_kwargs) -> None:
        raise RuntimeError("stream failed")


class _SlowStreamingHandler:
    async def handle_stream(self, **_kwargs) -> None:
        await asyncio.sleep(1)


class _FailingGreetingService:
    async def generate_proactive_message(self, **_kwargs):
        raise RuntimeError("greeting failed")
        yield  # pragma: no cover - 保持异步生成器协议


async def _verify_websocket_error_packets() -> None:
    websocket = _WebSocket()
    with patch(
        "core.core_engine.service_singletons.get_aveline_service",
        return_value=object(),
    ):
        await streaming.run_chat_stream_task(
            _Adapter(),
            websocket=websocket,
            streaming_handler=_FailingStreamingHandler(),
            content="hello",
            msg_id="msg-1",
            conversation_id="cid-1",
            request_id="req-1",
            model="test",
            persona_filename="test.json",
            service_dynamic_context="",
            api_key_env="",
            user_name="tester",
        )

    assert len(websocket.messages) == 1
    packet = websocket.messages[0]
    assert packet["message_id"] == "msg-1"
    assert packet["conversation_id"] == "cid-1"
    assert packet["request_id"] == "req-1"
    assert isinstance(packet["timestamp"], float)

    timeout_socket = _WebSocket()
    with (
        patch(
            "core.core_engine.service_singletons.get_aveline_service",
            return_value=object(),
        ),
        patch.object(streaming, "_CHAT_TASK_TIMEOUT", 0.001),
    ):
        await streaming.run_chat_stream_task(
            _Adapter(),
            websocket=timeout_socket,
            streaming_handler=_SlowStreamingHandler(),
            content="hello",
            msg_id="msg-timeout",
            conversation_id="cid-timeout",
            request_id="req-timeout",
            model="test",
            persona_filename="test.json",
            service_dynamic_context="",
            api_key_env="",
            user_name="tester",
        )
    assert len(timeout_socket.messages) == 1
    timeout_packet = timeout_socket.messages[0]
    assert timeout_packet["content"] == "响应超时，请重试"
    assert isinstance(timeout_packet["timestamp"], float)

    greeting_socket = _WebSocket()
    with patch(
        "core.core_engine.service_singletons.get_aveline_service",
        return_value=_FailingGreetingService(),
    ):
        await streaming.run_greeting_stream_task(
            _Adapter(),
            websocket=greeting_socket,
            msg_id="msg-2",
            conversation_id="cid-2",
            request_id="req-2",
            user_name="tester",
        )

    assert len(greeting_socket.messages) == 1
    greeting_packet = greeting_socket.messages[0]
    assert greeting_packet["message_id"] == "msg-2"
    assert isinstance(greeting_packet["timestamp"], float)


def _verify_scripts_parse() -> None:
    for relative_path in (
        "scripts/import/import_chiba_chat_to_memory.py",
        "scripts/migrate_to_shared_conversation.py",
    ):
        path = ROOT / relative_path
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _verify_no_duplicate_effect_keys() -> None:
    path = ROOT / "core/food/manager.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_EFFECT_ATTR_MAP"
            for target in node.targets
        ):
            continue
        assert isinstance(node.value, ast.Dict)
        keys = [ast.literal_eval(key) for key in node.value.keys if key is not None]
        assert len(keys) == len(set(keys)), "_EFFECT_ATTR_MAP 存在重复键"
        return
    raise AssertionError("未找到 _EFFECT_ATTR_MAP")


def _verify_sensitive_ignore_rules() -> None:
    targets = (
        "core/character/configs/sensitive/example.json",
        "core/tools/sensitive_meme_tool.py",
        "core/tools/scene_tool.py",
        "config/yaml/character_daily_sensitive.yaml",
    )
    for target in targets:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", target],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 0, f"缺少 Git 忽略规则: {target}"


async def _verify_search_does_not_block_event_loop() -> None:
    class _Response:
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict:
            return {"ok": True}

    def _slow_post(*_args, **_kwargs) -> _Response:
        time.sleep(0.05)
        return _Response()

    ticker_finished = False

    async def _ticker() -> None:
        nonlocal ticker_finished
        await asyncio.sleep(0.005)
        ticker_finished = True

    fake_requests = types.SimpleNamespace(post=_slow_post)
    with (
        patch.dict(os.environ, {"BOCHA_API_KEY": "test-key"}),
        patch.dict(sys.modules, {"requests": fake_requests}),
    ):
        search_task = asyncio.create_task(search_web({"query": "test"}))
        ticker_task = asyncio.create_task(_ticker())
        await ticker_task
        assert ticker_finished
        assert not search_task.done(), "同步 HTTP 调用阻塞了事件循环"
        response = await search_task
    assert response["status"] == "success"


def _verify_safe_tar_extraction() -> None:
    with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
        base = Path(temp_dir)
        archive_path = base / "malicious.tar"
        with tarfile.open(archive_path, "w") as archive:
            member = tarfile.TarInfo("../escaped.txt")
            payload = b"blocked"
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        with tarfile.open(archive_path, "r") as archive:
            try:
                _safe_extract_tar(archive, base / "extract")
            except ValueError as exc:
                assert "越界" in str(exc)
            else:
                raise AssertionError("路径穿越归档未被拒绝")
        assert not (base / "escaped.txt").exists()


def _verify_test_audit_signal() -> None:
    assert audit_pycache() == [], "已忽略的本地缓存不应让仓库审计失败"
    false_positive = "import core.utils.time_utils"
    assert all(false_positive not in issue for issue in audit_dead_imports())


def main() -> int:
    asyncio.run(_verify_websocket_error_packets())
    asyncio.run(_verify_search_does_not_block_event_loop())
    _verify_scripts_parse()
    _verify_no_duplicate_effect_keys()
    _verify_sensitive_ignore_rules()
    _verify_safe_tar_extraction()
    _verify_test_audit_signal()
    print("项目审查首批修复验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
