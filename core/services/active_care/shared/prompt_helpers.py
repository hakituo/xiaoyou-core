"""
主动关怀 Prompt 片段构建器

从原 `shared/constants.py` 拆出：所有函数都只是"拼一段给 LLM 看的文字"，
与状态读写解耦，方便 Prompt 调整时只改本模块。
"""
import random
from typing import Dict, List

from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    ACTION_PROMPT_VARIANTS,
    BIO_COMPLAINT_PROMPT_TEMPLATES,
    DEFAULT_ACTION_PROMPT,
    CORE_CONSTRAINTS,
    SLEEP_CONSTRAINTS_TEMPLATE,
    QUIET_MODE_INSTRUCTION,
    GOODNIGHT_REDUCED_MODE_INSTRUCTION,
    REDUCED_MODE_INSTRUCTION_TEMPLATE,
)


def get_action_prompt(action: str) -> str:
    """按动作类型随机取一条指令 Prompt 变体（无变体时回退默认）。"""
    variants = ACTION_PROMPT_VARIANTS.get(action)
    if variants:
        return random.choice(variants)
    return DEFAULT_ACTION_PROMPT


def format_bio_complaint_prompt(urgent_needs: List[str]) -> str:
    """按当前紧急需求随机取一条"身体不适抱怨"Prompt 变体。"""
    needs_str = ", ".join(urgent_needs) if urgent_needs else "体温/功耗/内存占用略高"
    fallback_str = ", ".join(urgent_needs) if urgent_needs else "有点累/发烫"
    run_str = ", ".join(urgent_needs) if urgent_needs else "运行不畅"
    variants = [
        t.format(needs_str=needs_str, fallback_str=fallback_str, run_str=run_str)
        for t in BIO_COMPLAINT_PROMPT_TEMPLATES
    ]
    return random.choice(variants)


def build_core_constraints() -> str:
    """主动关怀固定约束段。"""
    return CORE_CONSTRAINTS


def build_sleep_constraints(sleep_session: Dict) -> str:
    """睡眠会话约束段（无睡眠会话时返回空串）。"""
    if not sleep_session:
        return ""
    return SLEEP_CONSTRAINTS_TEMPLATE


def build_quiet_mode_instruction(
    quiet_mode_active: bool,
    reduced_mode_active: bool,
    reduced_mode_reason: str,
) -> str:
    """按当前低打扰状态构建静默指令。

    Args:
        quiet_mode_active: 用户说了晚安但可能还没睡
        reduced_mode_active: 处于低打扰模式
        reduced_mode_reason: 低打扰原因
    """
    if quiet_mode_active:
        return QUIET_MODE_INSTRUCTION
    if reduced_mode_active:
        if reduced_mode_reason == "goodnight":
            return GOODNIGHT_REDUCED_MODE_INSTRUCTION
        # probable_sleep 分支已于 2026-07-30 移除
        else:
            return REDUCED_MODE_INSTRUCTION_TEMPLATE.format(reason=reduced_mode_reason)
    return ""


def build_sleep_status_description(
    *,
    sleep_session_active: bool = False,
    quiet_mode_active: bool = False,
    reduced_mode_active: bool = False,
    reduced_mode_reason: str = "none",
    has_late_night_activity: bool = False,
    hours_since_late_night: int = -1,
    latest_late_night_hour: int = -1,
    now_hour: int = -1,
) -> str:
    """统一构建睡眠状态描述文本（decision.py 与 context_builder.py 复用）。"""
    if sleep_session_active:
        return "【用户已进入睡眠模式】用户已说过晚安，正在睡眠中。可以发送轻量关怀消息（如'想你了'、'晚安'），但禁止追问任务或画像，禁止连续打扰。"
    if quiet_mode_active:
        return "【用户处于静默时段】用户已说过晚安但可能还没入睡。可以发送简短关怀，保持低打扰。"
    # probable_sleep 分支已于 2026-07-30 移除
    if (
        has_late_night_activity
        and 0 <= now_hour < 12
        and hours_since_late_night >= 0
        and hours_since_late_night < 6
    ):
        late_hour_text = f"{latest_late_night_hour}点" if latest_late_night_hour >= 0 else "凌晨"
        return (
            f"【用户可能刚睡不久】用户在{late_hour_text}左右有对话（{hours_since_late_night}小时前），"
            f"可能晚睡或通宵。当前早上{now_hour}点，优先假设用户还在睡觉或刚睡不久。"
            f"禁止发送'醒了没/起床了没'类消息，仅允许轻量陪伴如'想你了'。"
        )
    return "【用户未进入睡眠模式】用户还没有说晚安，可能还醒着。"


__all__ = [
    "ACTION_PROMPT_VARIANTS",
    "get_action_prompt",
    "format_bio_complaint_prompt",
    "build_core_constraints",
    "build_sleep_constraints",
    "build_quiet_mode_instruction",
    "build_sleep_status_description",
]
