"""验证 peer chat 双方在线门禁

背景（QR-20260907-PEER-CHAT-OFFLINE）：
Ling（ling）的 QQ 没开时，Aveline（aveline）仍会触发 peer chat 并向 123456789 发私聊。
根因是 aveline/ling 属于常驻白名单，can_send_proactive_message 对它们恒为 True，
且 CharacterDailyEngine 的触发链路完全不看对方是否真的接入。

检查项：
1. 只有发起方在线（ling 掉线）时，门禁拦截互聊
2. 双方都有带角色标识的 WS 连接时，门禁放行
3. 旧客户端不上报 role_id（无法识别角色）时放行，避免误伤
4. trigger_via_scheduler 在对方离线时直接返回 False，不调用决策 LLM / 不生成剧本
5. 配置项 peer_chat_require_live_connections 已落地（settings + app.yaml）
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class _FakeWebSocket:
    """假 WebSocket 对象（可哈希，作为 connections 的键）。"""

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id


class _FakeConnection:
    """假 ClientConnection：只提供门禁需要的字段。"""

    def __init__(self, websocket: _FakeWebSocket, platform: str = "qq") -> None:
        self.websocket = websocket
        self.platform = platform

    def is_alive(self, timeout: float) -> bool:  # noqa: ARG002
        return True


def _fake_ws_manager(client_ids: list[str]) -> SimpleNamespace:
    """构造带指定 client_id 的假 WebSocket 管理器。"""
    connections = {}
    for cid in client_ids:
        ws = _FakeWebSocket(cid)
        connections[ws] = _FakeConnection(ws)
    return SimpleNamespace(connections=connections, heartbeat_timeout=60.0)


def _patch_ws_manager(monkeypatch, client_ids: list[str]) -> None:
    import core.interfaces.websocket.websocket_manager as ws_mod

    monkeypatch.setattr(
        ws_mod, "get_websocket_manager", lambda: _fake_ws_manager(client_ids)
    )
    # 注册表（adapter 与后端同进程时才有值）保持为空，确保只由 WS 连接判定
    import core.services.active_care.core.qq_connection_resolver as resolver

    monkeypatch.setattr(resolver, "has_live_client_connection", lambda role_id: False)


def check_gate_matrix() -> None:
    from core.services.active_care.core.qq_connection_resolver import (
        check_peer_chat_participants_online,
        get_live_qq_role_ids,
    )

    cases = [
        # (client_ids, 期望放行, 场景说明)
        (["qq_aveline_private_10001"], False, "Ling QQ 未开（只有Aveline的连接）"),
        (
            ["qq_aveline_private_10001", "qq_ling_private_10001"],
            True,
            "双方都在线",
        ),
        ([], True, "无任何可识别连接（旧客户端/未接入），不误伤"),
        (["qq_private_10001"], True, "旧客户端 client_id 无 role 前缀，无法判定→放行"),
    ]
    for client_ids, expected, desc in cases:
        import pytest

        monkeypatch = pytest.MonkeyPatch()
        try:
            _patch_ws_manager(monkeypatch, client_ids)
            allowed, reason = check_peer_chat_participants_online("aveline", "ling")
            assert allowed is expected, (
                f"[FAIL] {desc}: 期望 allowed={expected}，实际 {allowed}（{reason}）"
            )
            live = sorted(get_live_qq_role_ids())
            print(f"[OK] {desc}: allowed={allowed} live={live} reason={reason}")
        finally:
            monkeypatch.undo()

    # 只认带角色前缀的连接：Aveline在线而Ling不在线时，live 集合只应有 aveline
    import pytest

    monkeypatch = pytest.MonkeyPatch()
    try:
        _patch_ws_manager(monkeypatch, ["qq_aveline_private_10001"])
        assert get_live_qq_role_ids() == {"aveline"}, (
            f"[FAIL] 在线角色集合解析错误: {get_live_qq_role_ids()}"
        )
        print("[OK] 在线角色集合解析正确: {'aveline'}")
    finally:
        monkeypatch.undo()


def check_trigger_blocked_when_peer_offline() -> None:
    """对方离线时 trigger_via_scheduler 应直接返回 False，不调用 LLM。"""
    import pytest

    from core.services.character_daily import engine_peer_chat_support as support

    calls = {"decision": 0, "script": 0}

    class FakeDecision:
        async def decide_peer_chat(self, *args, **kwargs):
            calls["decision"] += 1
            return {"should_send": True, "topic": "晚饭吃什么"}

    class FakeExecutor:
        async def generate_peer_script(self, *args, **kwargs):
            calls["script"] += 1
            return True

    class FakeScheduler:
        _decision = FakeDecision()
        _executor = FakeExecutor()

        async def _get_multi_qq_connections(self):
            return [
                {"role_id": "aveline", "persona_filename": "core_aveline.json"},
                {"role_id": "ling", "persona_filename": "core_ling.json"},
            ]

        def _resolve_peer_qq_id(self, peer_role_id: str) -> str:
            return "123456789"

    fake_engine = SimpleNamespace(
        _peer_chat_scheduler=FakeScheduler(),
        _state=SimpleNamespace(global_last_peer_chat_ts=0.0),
    )

    monkeypatch = pytest.MonkeyPatch()
    try:
        _patch_ws_manager(monkeypatch, ["qq_aveline_private_10001"])
        sent = asyncio.run(support.trigger_via_scheduler(fake_engine, "aveline", "情境"))
        assert sent is False, "[FAIL] Ling离线时仍返回 sent=True"
        assert calls["decision"] == 0 and calls["script"] == 0, (
            f"[FAIL] Ling离线时仍调用了 LLM: {calls}"
        )
        print("[OK] Ling离线：trigger_via_scheduler 返回 False 且未调用 LLM")
    finally:
        monkeypatch.undo()

    monkeypatch = pytest.MonkeyPatch()
    try:
        _patch_ws_manager(
            monkeypatch, ["qq_aveline_private_10001", "qq_ling_private_10001"]
        )
        sent = asyncio.run(support.trigger_via_scheduler(fake_engine, "aveline", "情境"))
        assert sent is True, "[FAIL] 双方在线时仍被门禁拦截"
        assert calls["decision"] == 1 and calls["script"] == 1, (
            f"[FAIL] 双方在线时未走完整剧本流程: {calls}"
        )
        print("[OK] 双方在线：trigger_via_scheduler 正常走决策+剧本流程")
    finally:
        monkeypatch.undo()


def check_config_landed() -> None:
    src = (ROOT / "config" / "settings_life.py").read_text(encoding="utf-8")
    assert "peer_chat_require_live_connections" in src, (
        "[FAIL] DualRoleSettings 缺少 peer_chat_require_live_connections"
    )
    yaml_text = (ROOT / "config" / "yaml" / "app.yaml").read_text(encoding="utf-8")
    assert "peer_chat_require_live_connections" in yaml_text, (
        "[FAIL] app.yaml 缺少 peer_chat_require_live_connections"
    )
    print("[OK] 配置项 peer_chat_require_live_connections 已落地")


def main() -> int:
    check_gate_matrix()
    check_trigger_blocked_when_peer_offline()
    check_config_landed()
    print("\n所有验证通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
