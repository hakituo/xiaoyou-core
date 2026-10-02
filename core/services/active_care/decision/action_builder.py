"""
动作构建模块
负责构建可用动作列表、应用动作覆盖规则、判断是否强制发送等纯规则逻辑。
不依赖 LLM 调用，所有决策均基于输入参数的规则判断。
"""
import random
from typing import Dict, List, Tuple

from core.utils.logger import get_module_logger
from core.services.active_care.decision.decision_context import DecisionFlowContext

logger = get_module_logger("ACTIVE_CARE", "active_care_schedule.log")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")


def build_available_actions(
    mood_intensity: float,
    primary_emo: str,
    aveline_is_sick: bool,
    aveline_energy: float,
    priority_focus: Dict,
    sleep_session_active: bool,
    probe_policy: Dict,
    reduced_mode_active: bool = False,
    reduced_mode_reason: str = "none",
) -> List[str]:
    """构建可用动作列表"""
    available_actions = [
        "do_nothing",
        "share_thought",
        "curious_question",
    ]

    if mood_intensity > 0.6 or primary_emo in ["sad", "anxious", "tired"]:
        available_actions.append("emotional_support")

    if aveline_is_sick or aveline_energy < 30:
        available_actions.append("bio_complaint")

    # 使用 priority_focus 中已过滤的 portrait_priority
    filtered_portrait = priority_focus.get("portrait_priority") or []
    covered_topics = priority_focus.get("covered_topics") or []

    if filtered_portrait and any(item in filtered_portrait for item in ["wakeup", "sleep", "meal"]):
        available_actions.append("user_health_reminder")
        if covered_topics:
            logger.info(
                f"Active Care: user_health_reminder 基于过滤后画像, "
                f"filtered_portrait={filtered_portrait}, covered={covered_topics}"
            )

    if priority_focus.get("must_probe") and "curious_question" not in available_actions:
        available_actions.append("curious_question")

    # 双角色互聊后可分享给主人
    if priority_focus.get("has_recent_peer_chat"):
        available_actions.append("share_peer_chat")

    # 如果处于睡眠模式，大幅降低打扰频率
    if sleep_session_active:
        allowed_in_sleep = {"do_nothing", "share_thought", "emotional_support"}
        if probe_policy.get("is_probe") and probe_policy.get("is_first_probe"):
            allowed_in_sleep.add("curious_question")

        available_actions = [a for a in available_actions if a in allowed_in_sleep]
        available_actions.extend(["do_nothing"] * 1)

    # 如果处于 sleep_hint 模式（用户暗示"不回就是睡了"），限制动作
    # probable_sleep 已于 2026-07-30 移除，不再基于长时间无响应推断入睡
    elif reduced_mode_active and reduced_mode_reason == "sleep_hint":
        is_first_probe = probe_policy.get("is_probe") and probe_policy.get("is_first_probe")
        if is_first_probe:
            allowed_in_sleep_hint = {"curious_question", "share_thought", "emotional_support"}
            available_actions = [a for a in available_actions if a in allowed_in_sleep_hint]
        else:
            allowed_in_sleep_hint = {"do_nothing", "share_thought", "emotional_support"}
            available_actions = [a for a in available_actions if a in allowed_in_sleep_hint]
            available_actions.append("do_nothing")

    random.shuffle(available_actions)
    return available_actions


def _is_override_allowed(ctx: "DecisionFlowContext", has_non_response_pressure: bool = False) -> bool:
    """判断是否允许覆盖 do_nothing 的公共条件，消除 apply_action_overrides 和 should_force_send 的重复"""
    if ctx.quiet_mode_active or ctx.sleep_session_active:
        return False
    if ctx.reduced_mode_active:
        if ctx.reduced_mode_reason == "sleep_hint":
            return not has_non_response_pressure
        if ctx.reduced_mode_reason == "goodnight":
            is_daytime = False
            if ctx.now_dt is not None:
                try:
                    is_daytime = 10 <= ctx.now_dt.hour < 18
                except (AttributeError, TypeError):
                    pass
            if is_daytime:
                return not has_non_response_pressure
        return False
    if ctx.count >= ctx.daily_limit:
        return False
    return True


def apply_action_overrides(
    chosen_action: str,
    ctx: "DecisionFlowContext",
) -> Tuple[str, int]:
    """
    应用动作覆盖规则

    Returns:
        (chosen_action, next_check_seconds_override or 0)
    """
    next_check_seconds_override = 0

    if (
        ctx.conversation_incomplete
        and not ctx.quiet_mode_active
        and not ctx.reduced_mode_active
        and ctx.count < ctx.daily_limit
        and not ctx.sleep_session_active
    ):
        non_resp = ctx.non_response_count
        if ctx.incomplete_type == "conversation_stalled" and non_resp >= 1:
            logger.info(
                "Active Care: conversation_stalled 被抑制，"
                "用户已连续%d次不回复，不再强制跟进。沉默时长=%d秒",
                non_resp, int(ctx.elapsed),
            )
        else:
            chosen_action = "curious_question"
            logger.info(
                f"Active Care: 检测到对话未完成 ({ctx.incomplete_type}), "
                f"缩短跟进间隔。沉默时长={int(ctx.elapsed)}秒, 提示={ctx.incomplete_hint}"
                f", non_response={non_resp}"
            )
            if ctx.incomplete_type == "ai_question_unanswered":
                next_check_seconds_override = max(180, 300 - ctx.elapsed)
            elif ctx.incomplete_type == "user_story_interrupted":
                next_check_seconds_override = max(180, 360 - ctx.elapsed)
            elif ctx.incomplete_type == "conversation_stalled":
                base_override = 180
                if non_resp >= 1:
                    base_override = max(base_override, int(ctx.min_gap_seconds * (non_resp + 1)))
                next_check_seconds_override = base_override
            else:
                next_check_seconds_override = 180

    if (
        chosen_action == "do_nothing"
        and ctx.has_long_silence
        and ctx.has_recent_signal_for_long_silence
        and _is_override_allowed(ctx)
    ):
        chosen_action = "curious_question"
        msg_logger.info(
            "Active Care: Overriding do_nothing due to long silence (>%ss).",
            int(ctx.long_silence_seconds),
        )

    if (
        chosen_action == "do_nothing"
        and ctx.no_send_for_too_long
        and ctx.user_silent_long_enough
        and _is_override_allowed(ctx)
    ):
        chosen_action = "share_thought"
        msg_logger.info(
            "Active Care: Overriding do_nothing due to no-send timeout (last_sent=%ss ago, user_silent=%ss).",
            int(ctx.now - ctx.last_sent_ts) if ctx.last_sent_ts > 0 else -1,
            int(ctx.elapsed),
        )

    return chosen_action, next_check_seconds_override


def should_force_send(
    ctx: "DecisionFlowContext",
    non_response_count: int = 0,
) -> Tuple[bool, str]:
    """
    判断是否应该强制发送（覆盖 LLM 的 should_send=False 决策）

    使用 _is_override_allowed 统一公共条件，与 apply_action_overrides 保持一致。
    当 non_response_count > 0 时，使用更严格的沉默时间阈值。

    Returns:
        (should_force, reason)
    """
    has_non_response_pressure = non_response_count > 0

    if has_non_response_pressure:
        min_silence_for_force = max(ctx.min_gap_seconds * (non_response_count + 2), 7200)
        last_attempt = max(ctx.last_sent_ts, ctx.last_attempt_ts)
        silence_duration = (ctx.now - last_attempt) if last_attempt > 0 else float("inf")
        if silence_duration < min_silence_for_force:
            return False, ""

    if (
        ctx.has_long_silence
        and ctx.has_recent_signal_for_long_silence
        and _is_override_allowed(ctx, has_non_response_pressure)
    ):
        return True, "long_silence_fallback"

    if (
        ctx.no_send_for_too_long
        and ctx.user_silent_long_enough
        and _is_override_allowed(ctx, has_non_response_pressure)
    ):
        return True, "no_send_timeout_fallback"

    return False, ""
