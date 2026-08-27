import sys
import time
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services.active_care.checker.checker_event_handler import CheckerEventHandler
from core.services.active_care.decision.decision_context import DecisionFlowContext


class FakeWriteStore:
    def __init__(self) -> None:
        self.awaited_payload = None

    def is_user_recently_active(self, threshold_seconds: int = 600) -> bool:
        return True

    def get_recent_chat_context(self) -> str:
        return "用户刚刚在聊数学作业"

    async def set_pending_reminder(self, **kwargs) -> None:
        self.awaited_payload = kwargs


class FakeReadStore:
    def __init__(self, payload):
        self.payload = payload
        self.awaited = False

    async def get_and_clear(self):
        self.awaited = True
        return self.payload


class DummyEmotionManager:
    def ingest_life_stats(self, *args, **kwargs) -> None:
        return None

    def process_text(self, *args, **kwargs) -> None:
        return None

    def build_dialogue_affect_instruction(self, **kwargs) -> str:
        return ""


class DummyToolRegistry:
    def get_active_tools(self):
        return []

    def get_openai_tools(self, *args, **kwargs):
        return None

    def get_tool(self, *args, **kwargs):
        return None


class DummyLLM:
    def get_current_model_name(self) -> str:
        return "local"

    async def stream_chat(self, **kwargs):
        yield {"content": "好的"}


class DummyAgent:
    def __init__(self) -> None:
        self.is_initialized = True
        self.llm_module = DummyLLM()
        self.config = SimpleNamespace(temperature=0.7)
        self.dependency_manager = None
        self.defect_manager = None
        self.tool_registry = DummyToolRegistry()
        self.emotion_manager = DummyEmotionManager()
        self.last_extra_dynamic_context = None

    async def initialize(self) -> None:
        self.is_initialized = True

    async def _build_conversation_history(
        self,
        user_id,
        message,
        model_hint=None,
        extra_dynamic_context=None,
        **kwargs,
    ):
        self.last_extra_dynamic_context = extra_dynamic_context
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": str(message)},
        ]

    async def _check_daily_routine(self, user_id):
        return None

    async def _save_conversation_history(self, **kwargs) -> None:
        return None


@pytest.mark.asyncio
async def test_handle_due_reminder_awaits_set_pending_reminder(monkeypatch):
    import config.integrated_config as integrated_config_module
    import core.services.active_care.checker.checker_event_handler as handler_module

    fake_store = FakeWriteStore()
    fake_constants = types.ModuleType("fake_active_care_constants")
    fake_constants.REMINDER_MAX_CONSECUTIVE_RETRIES = 3
    fake_constants.REMINDER_RETRY_BACKOFF_BASE_SECONDS = 60

    monkeypatch.setitem(
        sys.modules,
        "core.services.active_care.shared.constants",
        fake_constants,
    )
    monkeypatch.setattr(
        handler_module, "get_reminder_injection_store", lambda: fake_store
    )
    monkeypatch.setattr(
        integrated_config_module,
        "get_settings",
        lambda: SimpleNamespace(
            life_simulation=SimpleNamespace(
                active_care_reminder_inject_to_chat=True,
                active_care_reminder_inject_window_seconds=600,
            )
        ),
    )

    due_reminder = SimpleNamespace(
        id="r1",
        message="该开始数学作业了",
        trigger_ts=time.time(),
        metadata={"task_title": "数学作业"},
    )
    executor = SimpleNamespace(
        check_reminders=AsyncMock(return_value=due_reminder),
        format_due_reminder_message=lambda reminder: "任务「数学作业」到时间该开始了",
        complete_reminder=AsyncMock(),
        trigger_message=AsyncMock(return_value=False),
    )
    checker = SimpleNamespace(
        executor=executor,
        set_next_decision_ts=AsyncMock(),
        last_intent=None,
        last_skip_reason=None,
        _consecutive_reminder_retries=0,
    )
    handler = CheckerEventHandler(checker)
    ctx = DecisionFlowContext(
        now=time.time(),
        default_next_check=300,
        min_gap_seconds=0,
        state_data={},
        client_type="test",
    )

    result = await handler.handle_due_reminder(ctx)

    assert result is True
    assert fake_store.awaited_payload is not None
    assert fake_store.awaited_payload["task_title"] == "数学作业"
    executor.complete_reminder.assert_awaited_once_with("r1", triggered_at=ctx.now)
    executor.trigger_message.assert_not_called()


@pytest.mark.asyncio
async def test_stream_chat_impl_awaits_get_and_clear(monkeypatch):
    import core.agents.chat_agent_components.streaming as streaming_module
    import core.agents.chat_agent_components.context_persona as context_persona_module
    import core.services.active_care.shared.reminder_injection as reminder_module
    import core.services.journal.service as journal_service_module

    fake_store = FakeReadStore(
        {
            "task_title": "数学作业",
            "reminder_text": "任务「数学作业」到时间该开始了",
            "recent_chat_summary": "用户刚刚在聊数学作业",
        }
    )
    monkeypatch.setattr(
        reminder_module, "get_reminder_injection_store", lambda: fake_store
    )

    async def fake_detect_sensitive_mode(*args, **kwargs):
        return False

    async def fake_process_all(*args, **kwargs):
        return {
            "life_stats": {},
            "sensory_feedback": None,
            "behavior_chain": None,
            "dep_result": {"new_unlocks": []},
            "triggered_defects": [],
        }

    async def fake_handle_intimacy_context(*args, **kwargs):
        return None

    monkeypatch.setattr(
        streaming_module.StreamContextBuilder,
        "detect_sensitive_mode",
        fake_detect_sensitive_mode,
    )
    monkeypatch.setattr(
        streaming_module.StreamContextBuilder, "detect_mode", lambda *args, **kwargs: "chat"
    )
    monkeypatch.setattr(
        streaming_module.StreamContextBuilder, "detect_wants_long", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        streaming_module.StreamContextBuilder,
        "infer_max_tokens",
        lambda *args, **kwargs: 256,
    )
    monkeypatch.setattr(
        streaming_module.StreamContextBuilder,
        "infer_soft_reply_limit",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        context_persona_module, "detect_cloud_mode", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        streaming_module.ParallelProcessor, "process_all", fake_process_all
    )
    monkeypatch.setattr(
        streaming_module.ParallelProcessor,
        "extract_life_stats",
        lambda *args, **kwargs: (0.5, 0.1, False, 0.0, "normal"),
    )
    monkeypatch.setattr(
        streaming_module.ParallelProcessor,
        "handle_intimacy_context",
        fake_handle_intimacy_context,
    )
    monkeypatch.setattr(
        journal_service_module,
        "get_journal_service",
        lambda: SimpleNamespace(
            get_tomorrow_tone=AsyncMock(return_value=None),
            get_plan=AsyncMock(return_value=None),
            format_plan_for_injection=lambda plan: "",
        ),
    )

    agent = DummyAgent()
    chunks = []
    async for chunk in streaming_module.stream_chat_impl(
        agent=agent,
        user_id="u1",
        message="我刚写完一点数学作业",
        message_id="m1",
        save_history=False,
        model_hint="local",
    ):
        chunks.append(chunk)
        if chunk.get("done") is True:
            break

    assert fake_store.awaited is True
    assert agent.last_extra_dynamic_context is not None
    assert "【计划提醒】" in agent.last_extra_dynamic_context
    assert "数学作业" in agent.last_extra_dynamic_context
    assert any(chunk.get("done") is True for chunk in chunks)
