"""主动关怀 Prompt 的静态段与可选动态段组装。"""

from __future__ import annotations

from typing import List

from core.agents.chat_agent_components.persona_system.prompt import active_care_prompts as prompts
from core.services.active_care.prompt.sections.models import PromptSection


def _compat_module():
    from core.services.active_care.prompt import prompt_builder

    return prompt_builder


def resolve_care_role_id(persona_filename: str, persona_name: str) -> str:
    try:
        from core.services.dual_role.personas import resolve_role_id

        return resolve_role_id(persona_filename) or resolve_role_id(persona_name) or ""
    except Exception:  # noqa: BLE001
        return ""


def build_role_activity_anchor(role_activity_text: str) -> str:
    role_activity = str(role_activity_text or "").strip()
    if not role_activity or any(
        keyword in role_activity.lower()
        for keyword in ("sleeping", "napping", "睡觉", "午休", "睡梦中")
    ):
        return ""
    return prompts.ROLE_ACTIVITY_ANCHOR_TEMPLATE.format(role_activity_text=role_activity)


def build_static_sections(
    persona_prompt: str,
    persona_filename: str,
    style_enforcement: str,
) -> List[PromptSection]:
    compat = _compat_module()
    fixed_prefix = compat.get_fixed_prefix()
    sensitive_prefix = compat.select_sensitive_prefix(persona_filename)
    persona_prompt = compat.strip_fixed_prefix(persona_prompt, fixed_prefix)
    persona_prompt = compat.strip_fixed_prefix(persona_prompt, sensitive_prefix)
    sections = []
    if fixed_prefix:
        sections.append(PromptSection("fixed_prefix", fixed_prefix + "\n\n"))
    if sensitive_prefix:
        sections.append(PromptSection("sensitive_prefix", sensitive_prefix + "\n\n"))
    sections.extend(
        [
            PromptSection("core_constraints", prompts.CORE_CONSTRAINTS),
            PromptSection("persona_prompt", f"{persona_prompt}\n\n"),
            PromptSection("style_enforcement", style_enforcement),
            PromptSection("voice_guide", prompts.VOICE_GUIDE),
        ]
    )
    return sections


def append_optional_sections(
    sections: List[PromptSection],
    *,
    tomorrow_tone: str,
    user_off_study: bool,
    proactive_state: dict | None,
    persona_filename: str,
) -> None:
    tone = str(tomorrow_tone or "").strip()
    if tone:
        sections.append(
            PromptSection(
                "tomorrow_tone",
                prompts.TOMORROW_TONE_TEMPLATE.format(tomorrow_tone=tone),
            )
        )
    compat = _compat_module()
    today_plan = "" if user_off_study else compat._build_today_plan_text()
    if today_plan:
        sections.append(
            PromptSection("today_plan", prompts.TODAY_PLAN_TEMPLATE.format(plan_text=today_plan))
        )
    if proactive_state:
        deferred = compat.build_deferred_reminders_text(proactive_state)
        if deferred:
            sections.append(
                PromptSection(
                    "deferred_reminders",
                    prompts.DEFERRED_REMINDERS_TEMPLATE.format(deferred_text=deferred),
                )
            )
    other_reminders = compat._build_other_persona_reminders_text(persona_filename)
    if other_reminders:
        sections.append(PromptSection("other_persona_reminders", other_reminders))
