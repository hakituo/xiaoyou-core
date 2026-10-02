"""验证 Active Care 与主人设 Prompt V2 的共享分层和缓存边界。"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agents.chat_agent_components.persona_system.prompt.data import (  # noqa: E402
    PersonaPromptLayers,
    get_persona_prompt_layers,
)
from core.services.active_care.checker.checker_client_gate import (  # noqa: E402
    CheckerClientGate,
)
from core.services.active_care.core.context_builder import TriggerContextBuilder  # noqa: E402
from core.services.active_care.core.persona_resolver import PersonaResolver  # noqa: E402
from core.services.active_care.core.proactive_checker import ProactiveChecker  # noqa: E402
from core.services.active_care.prompt.prompt_builder import (  # noqa: E402
    build_active_care_prompt,
)


class _Storage:
    @staticmethod
    def resolve_scope_from_conversation_id(_conversation_id: str) -> str:
        return "ye"


def _build_prompt(
    *,
    persona_dynamic_prompt: str = "[PERSONA_DYNAMIC_V2]",
    tone_reference_text: str = "[DYNAMIC_TONE_V2]",
):
    return build_active_care_prompt(
        user_id="shared__persona__ye",
        sys_prompt_type="proactive_chat",
        user_input_mock="[PROACTIVE_CHAT_TRIGGER]",
        reminder_msg=None,
        thought="自然接续",
        tod="晚上",
        now=1_788_275_200.0,
        user_display_name="用户",
        persona_prompt="[STATIC_PERSONA_V2]",
        persona_dynamic_prompt=persona_dynamic_prompt,
        recent_history_text="[RECENT_HISTORY_V2]",
        tone_reference_text=tone_reference_text,
        elapsed_seconds=600.0,
        persona_filename="core_ye.json",
        persona_name="Ye",
    )


def verify_shared_persona_layers() -> None:
    resolver = PersonaResolver(_Storage())
    assert resolver.resolve_persona_filename("shared__persona__ye") == "core_ye.json"
    decision_summary = resolver.build_decision_persona_summary(
        "shared__persona__ye"
    )
    assert "Ye" in decision_summary
    assert "scope=ye" in decision_summary
    assert len(decision_summary) < 500

    layers = resolver.load_persona_prompt_layers(
        "shared__persona__ye",
        "你本科哪里？",
    )
    assert layers.uses_layered_prompt
    assert "[GLOBAL CONVERSATION POLICY]" in layers.static_prompt
    assert "[CHARACTER CORE]" in layers.static_prompt
    assert "[CHARACTER VOICE]" in layers.static_prompt
    assert "[RETRIEVED PROFILE]" in layers.dynamic_prompt
    assert "education" in layers.knowledge_topics

    legacy = get_persona_prompt_layers(
        persona_filename="core_aveline.json",
        message="在吗",
        persona_data={"meta": {"scope": "aveline"}},
        fallback_static_prompt="[LEGACY_PERSONA]",
    )
    assert not legacy.uses_layered_prompt
    assert legacy.static_prompt == "[LEGACY_PERSONA]"
    assert not legacy.dynamic_prompt


def verify_active_care_v2_split_and_order() -> None:
    first = _build_prompt()
    second = _build_prompt(
        persona_dynamic_prompt="[PERSONA_DYNAMIC_CHANGED]",
        tone_reference_text="[DYNAMIC_TONE_CHANGED]",
    )

    assert first.static_prompt == second.static_prompt
    assert "[STATIC_PERSONA_V2]" in first.static_prompt
    assert "[PERSONA_DYNAMIC_V2]" not in first.static_prompt
    assert "[DYNAMIC_TONE_V2]" not in first.static_prompt
    assert "[RECENT_HISTORY_V2]" not in first.static_prompt

    dynamic = first.dynamic_prompt
    assert "[PERSONA_DYNAMIC_V2]" in dynamic
    assert "[DYNAMIC_TONE_V2]" in dynamic
    assert "[RECENT_HISTORY_V2]" in dynamic
    # P0~P6 装配：P2 当前任务 → P3 上下文/历史 → P4 Persona。
    # 低优先级不得覆盖高优先级，故 task 与 recent_history 应排在 persona 之前。
    assert dynamic.index("[RECENT_HISTORY_V2]") < dynamic.index("[PERSONA_DYNAMIC_V2]")

    section_names = [section.name for section in first.sections]
    assert section_names.index("task_block_dynamic") < section_names.index("recent_history_text")
    assert section_names.index("recent_history_text") < section_names.index("persona_dynamic_prompt")


def verify_runtime_private_mode_contract() -> None:
    import core.services.active_care.core.persona_resolver as resolver_module

    original_loader = resolver_module.get_persona_prompt_layers
    resolver_module.get_persona_prompt_layers = lambda **_kwargs: PersonaPromptLayers(
        static_prompt="[STATIC]",
        dynamic_prompt="[PRIVATE]",
        uses_layered_prompt=True,
        private_overlay_active=True,
    )
    try:
        assert PersonaResolver(_Storage()).is_runtime_private_mode(
            "shared__persona__ye"
        )
    finally:
        resolver_module.get_persona_prompt_layers = original_loader

    class _Context:
        @staticmethod
        async def resolve_primary_conversation_id() -> str:
            return "shared__persona__ye"

    original_private_check = PersonaResolver.is_runtime_private_mode
    PersonaResolver.is_runtime_private_mode = lambda _self, _cid: True
    try:
        gate = CheckerClientGate(
            context=_Context(),
            storage=_Storage(),
            get_config_value=lambda _key, default: default,
        )
        assert asyncio.run(gate.check_private_mode())
    finally:
        PersonaResolver.is_runtime_private_mode = original_private_check


def verify_context_builder_wiring() -> None:
    build_context_source = inspect.getsource(TriggerContextBuilder.build_trigger_context)
    build_prompt_source = inspect.getsource(TriggerContextBuilder.build_prompt)
    assert "load_persona_prompt_layers" in build_context_source
    assert '"persona_dynamic_prompt"' in build_context_source
    assert "persona_dynamic_prompt=" in build_prompt_source

    decision_source = inspect.getsource(ProactiveChecker._run_decision_core)
    assert "build_decision_persona_summary" in decision_source


def main() -> int:
    checks = (
        verify_shared_persona_layers,
        verify_active_care_v2_split_and_order,
        verify_runtime_private_mode_contract,
        verify_context_builder_wiring,
    )
    for check in checks:
        check()
        print(f"[PASS] {check.__name__}")
    print(f"[PASS] Active Care Prompt V2 验证完成：{len(checks)}/{len(checks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
