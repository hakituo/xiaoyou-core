import asyncio
import sys
from types import ModuleType
from unittest.mock import patch

from core.agents.chat_agent_components.streaming_pipeline.dynamic_context import (
    build_stream_messages,
)
from core.agents.chat_agent_components.streaming_pipeline.preparation import (
    StreamPreparation,
)


class _EmotionManager:
    def build_dialogue_affect_instruction(self, **kwargs):
        return ""


class _LegacyAgent:
    """模拟当前 ChatAgent wrapper：底层支持 override，但 wrapper 尚未暴露参数。"""

    def __init__(self):
        self.emotion_manager = _EmotionManager()
        self.wrapper_called = False

    async def _build_conversation_history(
        self,
        user_id,
        message,
        model_hint=None,
        system_prompt=None,
        user_name=None,
        persona_filename=None,
        active_tools=None,
    ):
        self.wrapper_called = True
        raise AssertionError(
            "history_override 已传入时不能走会静默丢参数的 legacy wrapper"
        )


def _fake_runtime_modules():
    journal_module = ModuleType("core.services.journal.service")

    class _JournalService:
        async def get_tomorrow_tone(self):
            return None

        async def get_plan(self):
            return None

    journal_module.get_journal_service = lambda: _JournalService()

    reminder_module = ModuleType(
        "core.services.active_care.shared.reminder_injection"
    )

    class _ReminderStore:
        async def get_and_clear(self):
            return None

    reminder_module.get_reminder_injection_store = lambda: _ReminderStore()

    return {
        "core.services.journal.service": journal_module,
        "core.services.active_care.shared.reminder_injection": reminder_module,
    }


def _run_build(history_override):
    import core.agents.chat_agent_components.context as context_module

    agent = _LegacyAgent()
    captured = {}

    async def _canonical_builder(
        agent_arg,
        user_id,
        message,
        model_hint=None,
        scope_override=None,
        system_prompt_override=None,
        user_name=None,
        persona_filename=None,
        extra_dynamic_context=None,
        history_override=None,
        active_tools_override=None,
    ):
        captured["history_override"] = history_override
        captured["active_tools_override"] = active_tools_override
        captured["system_prompt_override"] = system_prompt_override
        return [
            *list(history_override or []),
            {"role": "user", "content": str(message)},
        ]

    prep = StreamPreparation(
        is_cloud=False,
        active_tools=["web_search"],
    )

    with patch.dict(sys.modules, _fake_runtime_modules()), patch.object(
        context_module,
        "build_conversation_history",
        _canonical_builder,
    ):
        messages, events = asyncio.run(
            build_stream_messages(
                agent=agent,
                user_id="shared__persona__test",
                message="edited user message",
                model_hint="cloud:test:model",
                system_prompt="system prompt",
                user_name="tester",
                persona_filename="test.yaml",
                service_dynamic_context=None,
                prep=prep,
                history_override=history_override,
            )
        )

    return agent, captured, messages, events


def test_history_override_bypasses_legacy_wrapper_and_preserves_branch():
    branch_history = [
        {"role": "user", "content": "kept user turn"},
        {"role": "assistant", "content": "kept assistant turn"},
    ]

    agent, captured, messages, _ = _run_build(branch_history)

    assert agent.wrapper_called is False
    assert captured["history_override"] == branch_history
    assert captured["active_tools_override"] == ["web_search"]
    assert captured["system_prompt_override"] == "system prompt"
    assert messages[:2] == branch_history
    assert messages[-1] == {"role": "user", "content": "edited user message"}


def test_empty_history_override_is_not_treated_as_missing_history():
    agent, captured, messages, _ = _run_build([])

    assert agent.wrapper_called is False
    assert captured["history_override"] == []
    assert messages == [{"role": "user", "content": "edited user message"}]
