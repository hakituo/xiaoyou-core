"""验证 ActiveCareExecutor.generate_peer_script 支持 avoid 参数并正确转发。

背景：engine_peer_chat_support.trigger_via_scheduler 与 peer_chat_scheduler 在调用
executor.generate_peer_script 时传入 avoid 关键字参数，但 executor 签名缺失该参数，
导致 TypeError。底层 PeerScriptGenerator 已支持 avoid，修复为 executor 补参并转发。

校验点：
1. executor.generate_peer_script 签名包含 avoid 参数。
2. executor 调用时会把 avoid 原样转发给底层 PeerScriptGenerator。
3. 不带 avoid 时转发为默认 None（不影响旧调用方）。

全部通过返回 0，否则非 0。
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from unittest import mock

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "venv_core" / "Lib" / "site-packages"))

FAILURES: list[str] = []


def _fail(msg: str) -> None:
    FAILURES.append(msg)
    sys.stderr.write(f"FAIL: {msg}\n")
    sys.stderr.flush()


def check_signature_has_avoid() -> None:
    """1. executor 与 PeerScriptGenerator 的 generate_peer_script 都接受 avoid"""
    try:
        from core.services.active_care.core.executor import ActiveCareExecutor
        from core.services.active_care.peer_chat.peer_script_generator import (
            PeerScriptGenerator,
        )

        exec_sig = inspect.signature(ActiveCareExecutor.generate_peer_script)
        if "avoid" not in exec_sig.parameters:
            _fail("executor.generate_peer_script 签名缺少 avoid 参数")

        gen_sig = inspect.signature(PeerScriptGenerator.generate_peer_script)
        if "avoid" not in gen_sig.parameters:
            _fail("PeerScriptGenerator.generate_peer_script 签名缺少 avoid 参数")
    except Exception as e:  # noqa: BLE001
        _fail(f"签名校验异常: {e}")


def check_avoid_forwarded() -> None:
    """2. executor 把 avoid 原样转发给底层生成器"""
    try:
        from core.services.active_care.core.executor import ActiveCareExecutor

        executor = ActiveCareExecutor(mock.MagicMock(), mock.MagicMock())
        executor._peer_script_gen = mock.MagicMock()

        async def fake_gen(**kwargs):
            return kwargs.get("avoid")

        executor._peer_script_gen.generate_peer_script = mock.AsyncMock(
            side_effect=fake_gen
        )

        loop = asyncio.new_event_loop()
        try:
            got = loop.run_until_complete(
                executor.generate_peer_script(
                    role_id="aveline",
                    peer_qq_id="123",
                    topic="t",
                    situation="s",
                    opening_idea="o",
                    persona_filename="p.json",
                    negotiation_reminders=None,
                    avoid=["甲", "乙"],
                )
            )
        finally:
            loop.close()

        if got != ["甲", "乙"]:
            _fail("executor 未把 avoid 原样转发给底层生成器")
        else:
            executor._peer_script_gen.generate_peer_script.assert_awaited_once()
    except Exception as e:  # noqa: BLE001
        _fail(f"转发校验异常: {e}")


def check_avoid_default_none() -> None:
    """3. 旧调用方不带 avoid 时转发为 None"""
    try:
        from core.services.active_care.core.executor import ActiveCareExecutor

        executor = ActiveCareExecutor(mock.MagicMock(), mock.MagicMock())
        executor._peer_script_gen = mock.MagicMock()
        executor._peer_script_gen.generate_peer_script = mock.AsyncMock(
            return_value=True
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                executor.generate_peer_script(
                    role_id="aveline", peer_qq_id="123", topic="t"
                )
            )
        finally:
            loop.close()

        call_kwargs = executor._peer_script_gen.generate_peer_script.await_args.kwargs
        if call_kwargs.get("avoid") is not None:
            _fail(f"不带 avoid 时应转发 None，实际为 {call_kwargs.get('avoid')}")
    except Exception as e:  # noqa: BLE001
        _fail(f"默认值校验异常: {e}")


def main() -> int:
    check_signature_has_avoid()
    check_avoid_forwarded()
    check_avoid_default_none()

    if FAILURES:
        sys.stderr.write(f"\n共 {len(FAILURES)} 处失败。\n")
        sys.stderr.flush()
        return 1
    sys.stderr.write("avoid 参数修复验证全部通过。\n")
    sys.stderr.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
