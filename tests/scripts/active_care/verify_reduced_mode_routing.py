r"""验证学习低打扰、晚安低打扰和起床意图不会串线。

运行：
    D:\AI\xiaoyou-core\venv_core\Scripts\python.exe -m tests.scripts.active_care.verify_reduced_mode_routing
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


class _FakeContext:
    def update_recent_user_message(self, **_: Any) -> None:
        return None


class _FakeStorage:
    def resolve_scope_from_conversation_id(self, _: str) -> str:
        return "aveline"

    async def get_proactive_state(self) -> Dict[str, Any]:
        return {}


class _FakeModeState:
    def __init__(self, intent: Dict[str, Any]):
        self.intent = intent

    async def detect_transition_intent(self, _: str) -> Dict[str, Any]:
        return dict(self.intent)


class _FakeStateManager:
    def __init__(self, intent: Dict[str, Any]):
        self.mode = _FakeModeState(intent)
        self.applied: list[Dict[str, Any]] = []

    async def apply_transition_intent(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        self.applied.append(dict(intent))
        is_focus = intent.get("reason") == "focus"
        return {
            "focus_changed": is_focus,
            "sleep_changed": False,
            "mode_changed": True,
        }


class _FakeService:
    def __init__(self, intent: Dict[str, Any]):
        self.context = _FakeContext()
        self.storage = _FakeStorage()
        self.state_manager = _FakeStateManager(intent)
        self.sleep_calls: list[tuple[bool, str]] = []

    async def set_sleep_mode(self, active: bool, reason: str = "user_request") -> bool:
        self.sleep_calls.append((active, reason))
        return True


class _FakeSocialEventEngine:
    async def record_user_life_event(self, *_: Any, **__: Any) -> None:
        return None


class _TransientStateStorage:
    def __init__(self) -> None:
        self.state: Dict[str, Any] = {}

    async def save_proactive_state(
        self,
        updates: Dict[str, Any],
        immediate: bool = False,
    ) -> Dict[str, Any]:
        del immediate
        self.state.update(updates)
        return dict(self.state)


async def _run_handler(intent: Dict[str, Any]) -> _FakeService:
    from core.interfaces.websocket.adapters.handlers.chat.active_care import (
        run_active_care_update,
    )
    from core.services.active_care.core import service as service_module
    from core.services.dual_role import social_events as social_events_module

    fake_service = _FakeService(intent)
    old_get_service = service_module.get_active_care_service
    old_get_social_engine = social_events_module.get_social_event_engine
    service_module.get_active_care_service = lambda: fake_service
    social_events_module.get_social_event_engine = lambda: _FakeSocialEventEngine()
    try:
        await run_active_care_update("测试消息", "shared__persona__aveline_qq_master")
    finally:
        service_module.get_active_care_service = old_get_service
        social_events_module.get_social_event_engine = old_get_social_engine
    return fake_service


def test_focus_never_calls_sleep_mode() -> None:
    intent = {
        "action": "enter_reduced",
        "reason": "focus",
        "label": "focus",
        "source": "bert",
        "bert_confidence": 0.74,
    }
    service = asyncio.run(_run_handler(intent))
    assert service.sleep_calls == [], "学习低打扰不能调用睡眠接口"
    assert service.state_manager.applied == [intent], "学习意图应交给状态管理器处理"
    print("[OK] 学习低打扰与晚安低打扰已分流")


def test_goodnight_still_calls_sleep_mode() -> None:
    intent = {
        "action": "enter_reduced",
        "reason": "goodnight",
        "label": "sleep",
        "source": "bert",
        "bert_confidence": 0.80,
    }
    service = asyncio.run(_run_handler(intent))
    assert service.sleep_calls == [(True, "goodnight")], "明确晚安仍应进入睡眠低打扰"
    assert service.state_manager.applied == [], "晚安不应走专注状态分支"
    print("[OK] 明确晚安仍能进入睡眠低打扰")


def test_bert_wakeup_requires_direct_statement() -> None:
    from core.services.active_care.state.mode_state import ModeStateManager

    manager = ModeStateManager()

    async def fake_wakeup(_: str) -> tuple[str, float]:
        return "WAKEUP_NOW", 0.99

    manager._detect_state_event_with_bert_async = fake_wakeup  # type: ignore[method-assign]
    false_positive = asyncio.run(manager.detect_transition_intent("又回多了你"))
    assert false_positive == {"action": "none"}, "无起床语义的文本不能退出睡眠模式"

    direct = asyncio.run(manager.detect_transition_intent("我终于爬起来了"))
    assert direct.get("action") == "exit_reduced"
    assert direct.get("reason") == "morning"
    assert direct.get("source") == "rule"
    print("[OK] BERT WAKEUP_NOW 不能单独改状态，明确起床陈述仍有效")


def test_bert_study_intent_is_preserved() -> None:
    from core.services.active_care.state.mode_state import ModeStateManager

    manager = ModeStateManager()

    async def fake_study(_: str) -> tuple[str, float]:
        return "STUDY_NOW", 0.74

    manager._detect_state_event_with_bert_async = fake_study  # type: ignore[method-assign]
    intent = asyncio.run(manager.detect_transition_intent("我在背单词"))
    assert intent.get("reason") == "focus"
    assert intent.get("label") == "focus"
    print("[OK] BERT 学习意图继续保留")


def test_state_manager_applies_focus_without_sleep_label() -> None:
    from core.services.active_care.state.manager import StateManager

    storage = _TransientStateStorage()
    manager = StateManager(storage=storage)  # type: ignore[arg-type]
    result = asyncio.run(
        manager.apply_transition_intent(
            {
                "action": "enter_reduced",
                "reason": "focus",
                "label": "focus",
                "expected_end_ts": 0.0,
            },
            now_ts=1_000.0,
        )
    )
    assert result.get("focus_changed") is True
    assert result.get("sleep_changed") is False
    assert storage.state.get("reduced_mode_reason") == "focus"
    assert storage.state.get("reduced_mode_label") == "focus"
    print("[OK] 状态管理器写入 focus，而不是 sleep")


def main() -> int:
    tests = (
        test_focus_never_calls_sleep_mode,
        test_goodnight_still_calls_sleep_mode,
        test_bert_wakeup_requires_direct_statement,
        test_bert_study_intent_is_preserved,
        test_state_manager_applies_focus_without_sleep_label,
    )
    for test in tests:
        test()
    print(f"验证通过：{len(tests)}/{len(tests)} 项全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
