"""被动回复策略（Reply Policy）

用户发消息时，根据角色当前活动状态 + Active Care 睡眠会话，
决定是否延迟回复、是否延后处理（累积消息）、注入什么人设提示。

核心解决"睡觉/忙碌时不立即回消息"的需求：
- 不可打扰活动（sleeping/napping/waking_up）：第 1 条起即静默累积，
  消息留到起床后处理；连发多条后递增概率强制唤醒（被吵醒）
- 忙碌活动（studying/cooking）：第 1 条起即静默累积，
  消息留到做完后处理；连发多条后递增概率强制打断
- 空闲活动：正常回复

设计变更（2026-06-27）：
- 去掉占位消息（zZz.../专注中...），统一静默累积，更接近"消息没回"的真实体验
- BUSY 不再延迟回复分支（不再 30%/70% 概率分流），统一延后处理
- 加回复窗口期：BUSY 回复后窗口期内（默认 120s）继续聊不走延后处理；
  DND 强制唤醒后不享受窗口期（被吵醒后用户继续聊仍按 DND 处理）

人设提示通过 service_dynamic_context 注入，让 LLM"表演"被吵醒/被打断/刚做完的状态。
hint 模板和 builder 集中在 reply_hints.py（按单文件 ≤500 行规则拆出）。

注意：evaluate_reply_state 是无状态的（每次调用独立），
连续消息的累积状态由 chat_handlers 维护（per-conversation）。
"""


from core.utils.logger import get_logger
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional

from core.services.character_daily.activity_model import (
    ACTIVITY_VERBS_ONGOING,
    ActivityType,
    BUSY_ACTIVITIES,
    DO_NOT_DISTURB_ACTIVITIES,
    HARD_BUSY_ACTIVITIES,
    SOFT_REPLY_DELAY_ACTIVITIES,
)
from core.services.character_daily.config import ReplyPolicyConfig
from core.services.character_daily.reply_hints import (
    build_busy_done_hint,
    build_busy_interrupt_hint,
    build_force_wake_hint,
    build_morning_after_hint,
    build_soft_delay_reply_hint,
    force_wake_probability,
)
from core.services.character_daily.reply_policy_support import (
    build_activity_return_reply_hint,
    build_manual_interrupt_window_hint,
    build_plan_transition_persona_hint,
    build_sleep_recovery_reason_suffix,
    get_manual_interrupt_window_state,
    get_recent_proactive_sent_elapsed,
    is_active_care_sleeping,
    is_role_recently_woken,
    resolve_dnd_wake_profile,
    resolve_reply_scope,
    resolve_soft_delay_profile,
)
from core.services.character_daily.role_wake_context import (
    bump_role_dnd_count,
    get_role_dnd_count,
    reset_role_dnd_count,
)

logger = get_logger(__name__)


@dataclass
class ReplyDecision:
    """被动回复决策结果"""
    should_reply: bool = True      # 是否走完整 LLM 回复
    delay_seconds: float = 0.0     # 回复前延迟（秒）
    skip_message: str = ""        # 保留字段（向后兼容），现统一为空字符串
    persona_hint: str = ""         # 注入 prompt 的人设提示
    activity: str = "idle"         # 当前活动
    reason: str = ""               # 判定原因（用于日志）
    accumulated_messages: List[str] = field(default_factory=list)  # 强制唤醒时附带的累积消息


def _merge_persona_hint(base_hint: str, extra_hint: str) -> str:
    """合并两段 persona 提示。"""
    base = str(base_hint or "").strip()
    extra = str(extra_hint or "").strip()
    if not base:
        return extra
    if not extra:
        return base
    return f"{base}\n\n{extra}"


def _apply_extra_persona_hint(
    decision: ReplyDecision,
    extra_hint: str,
) -> ReplyDecision:
    """仅对会真正回复的决策补充额外提示。"""
    if decision.should_reply and extra_hint:
        decision.persona_hint = _merge_persona_hint(
            decision.persona_hint,
            extra_hint,
        )
    return decision


async def evaluate_reply_state(
    role_id: str = "aveline",
    config: Optional[ReplyPolicyConfig] = None,
    consecutive_dnd_count: int = 0,
    accumulated_messages: Optional[List[str]] = None,
    last_reply_ts: float = 0.0,
    last_reply_activity: str = "",
    persona_filename: str = "",
    conversation_id: str = "",
) -> ReplyDecision:
    """评估当前被动回复应该怎么处理（async）

    综合判断：character_daily 当前活动 + active_care 睡眠会话 + 回复窗口期。
    任一判定为"睡眠/不可打扰"即按不可打扰处理（用户选的"两者结合"）。

    连续消息强制唤醒/打断：递增概率表 + hard_threshold 兜底，
    醒了之后把前几条累积消息一起发给 LLM。

    回复窗口期：BUSY 回复后窗口期内（默认 120s）继续聊不走延后处理，
    让用户能趁着角色"被打断"的间隙自然延续对话；
    DND 强制唤醒后不享受窗口期（被吵醒后用户继续聊仍按 DND 处理，
    避免被刷屏式消息消耗本就不多的睡眠）。

    Args:
        role_id: 角色 ID（默认 aveline，被动回复主角色）
        config: 回复策略配置，None 时用默认值
        consecutive_dnd_count: 当前 conversation 已拒回的消息数（不含本次）
        accumulated_messages: 之前拒回的消息内容列表（按时间顺序，不含本次）
        last_reply_ts: 最近一次角色成功回复（should_reply=True）的时间戳（秒）
        last_reply_activity: 最近一次成功回复时角色所处的活动类型字符串
        persona_filename: 当前会话对应的人设文件名，用于双QQ按 persona 读取主动关怀状态
        conversation_id: 当前会话 ID，用于手动打断后的持续聊天窗口

    Returns:
        ReplyDecision 决策结果（accumulated_messages 字段会回传用于日志）
    """
    if config is None:
        config = ReplyPolicyConfig()

    if not config.enabled:
        return ReplyDecision(reason="reply_policy disabled")

    accumulated_messages = accumulated_messages or []

    # 1. 查 character_daily 当前活动
    effective_scope = resolve_reply_scope(role_id, persona_filename)
    activity = ActivityType.IDLE
    try:
        from core.services.character_daily.engine import get_character_daily_engine
        engine = get_character_daily_engine()
        if engine:
            activity = engine.get_current_activity(effective_scope)
            # 如果当前活动是 DND（睡觉/午睡/起床洗漱/睡过头恢复），
            # 强制刷新一次，避免使用过时的缓存值。
            # 场景：用户半夜被唤醒后，sleep_manager 的 phase 已变为 night_awake，
            # 但 plan.current_activity 仍停留在 sleeping（engine tick 间隔 2 分钟），
            # 导致 reply_policy 错误地走 DND 分支静默累积消息，角色不回复。
            if activity in DO_NOT_DISTURB_ACTIVITIES:
                activity = engine.refresh_current_activity(effective_scope)
    except Exception as e:
        logger.debug("查询 character_daily 活动失败: %s", e)

    combined_hint = build_plan_transition_persona_hint(
        effective_scope, config
    )
    # 回归消息等待期内的用户回复，需要让 LLM 决定继续聊还是回去
    activity_return_hint = build_activity_return_reply_hint(conversation_id)
    combined_hint = _merge_persona_hint(
        combined_hint,
        activity_return_hint,
    )

    # 2. 同 persona 最近主动发起过消息时，短窗口内直接放行回接
    proactive_elapsed = await get_recent_proactive_sent_elapsed(effective_scope)
    if (
        config.proactive_reply_window_seconds > 0
        and proactive_elapsed >= 0
        and proactive_elapsed <= config.proactive_reply_window_seconds
    ):
        reason = (
            f"proactive_reply_window(active={activity.value}, scope={effective_scope}, "
            f"elapsed={proactive_elapsed:.1f}s, "
            f"window={config.proactive_reply_window_seconds}s)"
        )
        logger.info(
            "ReplyPolicy: 命中主动回接窗口（persona=%s，%.1fs 前刚主动发过消息），正常回复 (%s)",
            effective_scope, proactive_elapsed, reason,
        )
        return _apply_extra_persona_hint(
            ReplyDecision(
                should_reply=True,
                activity=activity.value,
                reason=reason,
            ),
            combined_hint,
        )

    # 3. 查 active_care 睡眠会话（用户说晚安/早安驱动）
    ac_sleeping = await is_active_care_sleeping(effective_scope)

    manual_interrupt_window = get_manual_interrupt_window_state(
        effective_scope,
        conversation_id,
    )
    # /wake 或 /打断 激活的中断窗口存在时，即使当前 activity 仍是 DND
    # （如 waking_up/napping/overslept_recovery），也走中断窗口分支正常回复。
    # 因为 /wake 的语义就是"用户主动叫醒并要求聊天"，
    # 不应被这些过渡态挡住退回静默累积（否则 /wake 形同虚设）。
    # SLEEPING 例外：真正在睡觉时即使残留中断窗口也不绕过（防御性，
    # /wake 在 sleeping 时走 notify_sleep_interruption，不会激活中断窗口）。
    if (
        manual_interrupt_window
        and activity != ActivityType.SLEEPING
        and not ac_sleeping
    ):
        remaining_seconds = max(
            0.0,
            float(manual_interrupt_window.get("expire_ts") or 0.0) - time.time(),
        )
        # 使用中断窗口中记录的活动（被中断的活动），而不是当前活动
        interrupted_activity_str = str(manual_interrupt_window.get("activity") or "").strip()
        interrupted_activity = ActivityType.from_str(interrupted_activity_str)
        interrupted_activity_verb = ACTIVITY_VERBS_ONGOING.get(interrupted_activity, "做事")
        # 检查是否已跳过当前活动
        skip_activity = bool(manual_interrupt_window.get("skip_activity"))
        extended_count = int(manual_interrupt_window.get("extended_count") or 0)

        reason = (
            f"manual_interrupt_window(active={activity.value}, interrupted={interrupted_activity.value}, "
            f"scope={effective_scope}, remaining={remaining_seconds:.1f}s, "
            f"skip={skip_activity}, extended={extended_count}, accumulated={len(accumulated_messages)})"
        )
        logger.info(
            "ReplyPolicy: 命中手动打断聊天窗口（persona=%s，剩余 %.1fs，被中断活动=%s，跳过=%s，累积消息=%d），正常回复 (%s)",
            effective_scope,
            remaining_seconds,
            interrupted_activity.value,
            skip_activity,
            len(accumulated_messages),
            reason,
        )
        # 如果有累积消息，构建带累积消息的提示
        if accumulated_messages:
            hint = build_busy_interrupt_hint(accumulated_messages, interrupted_activity_verb)
        elif skip_activity:
            # 已跳过活动，不需要提及"回去做事"
            hint = (
                f"用户决定跳过你今天的「{interrupted_activity_verb}」任务，专心陪用户聊天。"
                "继续自然地聊天就好。"
                "你今天已经不打算做这个任务了。"
            )
        else:
            hint = build_manual_interrupt_window_hint(interrupted_activity, remaining_seconds)

        return _apply_extra_persona_hint(
            ReplyDecision(
                should_reply=True,
                activity=activity.value,
                reason=reason,
                accumulated_messages=list(accumulated_messages),  # 返回累积消息供 chat_handlers 处理
            ),
            _merge_persona_hint(
                hint,
                combined_hint,
            ),
        )

    # 4. 回复窗口期检查：BUSY 回复后窗口期内继续聊，正常回复
    # 仅当上次回复时的活动是"忙碌但非 DND"（studying/cooking）时才享受窗口期
    # DND 类活动（sleeping/napping/waking_up）即使强制唤醒后也不享受窗口期
    # （避免被刷屏消息消耗本就不多的睡眠）
    _window_eligible_activities = {
        a.value for a in (BUSY_ACTIVITIES - DO_NOT_DISTURB_ACTIVITIES)
    }
    if (
        last_reply_ts > 0
        and last_reply_activity
        and last_reply_activity in _window_eligible_activities
        and (time.time() - last_reply_ts) <= config.reply_window_seconds
    ):
        elapsed = time.time() - last_reply_ts
        reason = (
            f"reply_window(active={activity.value}, last_activity={last_reply_activity}, "
            f"elapsed={elapsed:.1f}s, window={config.reply_window_seconds}s)"
        )
        logger.info(
            "ReplyPolicy: 命中回复窗口期（上次 BUSY 回复 %.1fs 前），正常回复 (%s)",
            elapsed, reason,
        )
        return _apply_extra_persona_hint(
            ReplyDecision(
                should_reply=True,
                activity=activity.value,
                reason=reason,
            ),
            combined_hint,
        )

    # 5. 分级决策（两者结合）
    # 不可打扰：角色在睡觉/午睡/起床，或 active_care 判定睡眠会话活跃
    is_dnd = activity in DO_NOT_DISTURB_ACTIVITIES or ac_sleeping

    if is_dnd:
        # 同 role 跨人设唤醒宽限：角色刚被唤醒（force_wake / /wake）后，
        # 在 role_wake_grace_seconds 窗口内，切到同 role 的另一个人设时直接放行，
        # 不重新走 DND 静默累积。last_wake_ts 是 per-scope 共享的，
        # 所以人设A吵醒Ling后，人设B也能读到这次唤醒，避免"切人设就说还在睡觉"。
        if is_role_recently_woken(effective_scope, config.role_wake_grace_seconds):
            reason = (
                f"role_recently_woken(scope={effective_scope}, "
                f"grace={config.role_wake_grace_seconds:.0f}s, activity={activity.value})"
            )
            logger.info(
                "ReplyPolicy: 同 role 最近被唤醒过，宽限放行（persona=%s，不再静默累积）(%s)",
                effective_scope, reason,
            )
            return _apply_extra_persona_hint(
                ReplyDecision(
                    should_reply=True,
                    activity=activity.value,
                    reason=reason,
                ),
                combined_hint,
            )

        return _apply_extra_persona_hint(
            _evaluate_dnd(
                effective_scope,
                activity,
                ac_sleeping,
                config,
                consecutive_dnd_count,
                accumulated_messages,
            ),
            combined_hint,
        )

    if activity in HARD_BUSY_ACTIVITIES:
        busy_reason_suffix = build_sleep_recovery_reason_suffix(
            effective_scope, activity
        )
        return _apply_extra_persona_hint(
            _evaluate_busy(
                activity,
                config,
                consecutive_dnd_count,
                accumulated_messages,
                reason_suffix=busy_reason_suffix,
            ),
            combined_hint,
        )

    if activity in SOFT_REPLY_DELAY_ACTIVITIES:
        soft_reason_suffix = build_sleep_recovery_reason_suffix(
            effective_scope, activity
        )
        return _apply_extra_persona_hint(
            _evaluate_soft_delay(activity, config, reason_suffix=soft_reason_suffix),
            combined_hint,
        )

    # 空闲：正常回复
    return _apply_extra_persona_hint(
        ReplyDecision(
            should_reply=True,
            activity=activity.value,
            reason="idle/free",
        ),
        combined_hint,
    )


def _evaluate_dnd(
    role_id: str,
    activity: ActivityType,
    ac_sleeping: bool,
    config: ReplyPolicyConfig,
    consecutive_dnd_count: int,
    accumulated_messages: List[str],
) -> ReplyDecision:
    """DND（不可打扰）分支：睡觉/午睡/起床洗漱

    策略：第 1 条起即静默累积，消息留到起床后处理。
    连发多条后递增概率强制唤醒。
    """
    # === 连续消息强制唤醒检查（递增概率，非固定阈值）===
    # 取 per-cid 累积与 per-scope（同 role 跨人设）累积的较大值，
    # 让"人设A攒了3条还没醒，切到人设B"能继承累积进度，不从0攒。
    scope_count = get_role_dnd_count(role_id)
    effective_count = max(consecutive_dnd_count, scope_count)
    base_wake_prob = force_wake_probability(
        effective_count, config.force_reply_threshold
    )
    wake_profile = resolve_dnd_wake_profile(role_id, activity, base_wake_prob)
    wake_prob = wake_profile.effective_probability
    wake_reason_suffix = ""
    if wake_profile.probability_bonus > 0:
        wake_reason_suffix = (
            f", fresh_sleep_bonus={wake_profile.probability_bonus:.2f}, "
            f"fresh_sleep_seconds={wake_profile.fresh_sleep_seconds:.0f}"
        )

    if random.random() < wake_prob:
        # 强制唤醒：连发 N 条后被吵醒，立刻回复 + 把前几条一起发给 LLM
        hint = build_force_wake_hint(accumulated_messages)
        # 唤醒延迟缩短（已经被吵得不行了）；累计越多醒得越快
        delay_ratio = 0.3 + 0.4 * (1.0 - wake_prob)  # 0.3 ~ 0.7
        delay = random.uniform(
            config.dnd_delay_min * delay_ratio,
            config.dnd_delay_min * (delay_ratio + 0.3),
        )
        # 成功唤醒：重置同 role 跨人设的累积计数
        reset_role_dnd_count(role_id)
        total_count = effective_count + 1
        reason = (
            f"dnd_force_wake(activity={activity.value}, ac_sleeping={ac_sleeping}, "
            f"count={total_count}, scope_count={scope_count}, wake_prob={wake_prob:.2f}"
            f"{wake_reason_suffix})"
        )
        logger.info(
            "ReplyPolicy: 不可打扰但被强制唤醒（prob=%.2f），延迟 %.1fs 回复 (%s)",
            wake_prob, delay, reason,
        )
        return ReplyDecision(
            should_reply=True,
            delay_seconds=delay,
            persona_hint=hint,
            activity=activity.value,
            reason=reason,
            accumulated_messages=list(accumulated_messages),
        )

    # === 未唤醒：静默累积，不回任何消息 ===
    # 累积的消息会在角色起床后（活动变为非 DND）统一处理
    # 注意：不再发占位消息（zZz...），统一静默，更接近"消息没回"的真实体验
    # 同步递增同 role 跨人设累积计数，供其它人设会话继承
    bump_role_dnd_count(role_id)
    total_count = effective_count + 1
    reason = (
        f"dnd_sleeping_silent(activity={activity.value}, ac_sleeping={ac_sleeping}) "
        f"count={total_count}, scope_count={scope_count}, will_process_on_wake"
        f"{wake_reason_suffix})"
    )
    logger.info("ReplyPolicy: 睡觉中，静默累积消息 (%s)", reason)
    return ReplyDecision(
        should_reply=False,
        skip_message="",  # 统一静默累积，不发占位消息
        activity=activity.value,
        reason=reason,
    )


def _evaluate_busy(
    activity: ActivityType,
    config: ReplyPolicyConfig,
    consecutive_dnd_count: int,
    accumulated_messages: List[str],
    reason_suffix: str = "",
) -> ReplyDecision:
    """BUSY（忙碌）分支：学习/做饭

    策略：
    - 第 1 条起即静默累积（不再延迟回复），消息留到做完后处理
    - 连发多条后递增概率强制打断（与 DND 共用概率表）

    设计变更：去掉延迟回复分支（之前 30%/70% 概率分流），
    统一延后处理，让"消息没回"更真实，留到做完再统一处理。
    回复窗口期由 evaluate_reply_state 顶层检查处理。
    """
    activity_verb = ACTIVITY_VERBS_ONGOING.get(activity, "做事")

    # 连续消息强制打断检查（与 DND 共用概率表）
    wake_prob = force_wake_probability(
        consecutive_dnd_count, config.force_reply_threshold
    )
    if random.random() < wake_prob:
        # 强制打断：把前几条一起发给 LLM
        hint = build_busy_interrupt_hint(accumulated_messages, activity_verb)
        # 打断延迟缩短（已经被吵到不行）；累计越多醒得越快
        delay_ratio = 0.3 + 0.4 * (1.0 - wake_prob)
        delay = random.uniform(
            config.busy_delay_min * delay_ratio,
            config.busy_delay_min * (delay_ratio + 0.3),
        )
        total_count = consecutive_dnd_count + 1
        reason = (
            f"busy_force_interrupt(activity={activity.value}, "
            f"count={total_count}, wake_prob={wake_prob:.2f}"
            f"{reason_suffix})"
        )
        logger.info(
            "ReplyPolicy: 忙碌被强制打断（prob=%.2f），延迟 %.1fs 回复 (%s)",
            wake_prob, delay, reason,
        )
        return ReplyDecision(
            should_reply=True,
            delay_seconds=delay,
            persona_hint=hint,
            activity=activity.value,
            reason=reason,
            accumulated_messages=list(accumulated_messages),
        )

    # 未强制打断：静默累积，消息留到做完后处理
    # 不再发占位消息（专注中...），统一静默，更接近"消息没回"的真实体验
    total_count = consecutive_dnd_count + 1
    reason = (
        f"busy_defer_silent(activity={activity.value}) "
        f"count={total_count}, will_process_on_done"
        f"{reason_suffix})"
    )
    logger.info("ReplyPolicy: 忙碌延后处理，静默累积消息 (%s)", reason)
    return ReplyDecision(
        should_reply=False,
        skip_message="",  # 统一静默累积
        activity=activity.value,
        reason=reason,
    )


def _evaluate_soft_delay(
    activity: ActivityType,
    config: ReplyPolicyConfig,
    reason_suffix: str = "",
) -> ReplyDecision:
    """轻活动分支：静默几十秒后再回，而不是直接拒回。"""
    profile = resolve_soft_delay_profile(activity, config)
    delay = random.uniform(
        profile.min_seconds,
        max(profile.min_seconds, profile.max_seconds),
    )
    activity_verb = ACTIVITY_VERBS_ONGOING.get(activity, "忙点别的")
    hint = build_soft_delay_reply_hint(activity_verb, int(round(delay)))
    reason = (
        f"soft_delay_reply(activity={activity.value}, profile={profile.profile_name}, delay={delay:.1f}s"
        f"{reason_suffix})"
    )
    logger.info(
        "ReplyPolicy: 轻活动静默 %.1fs 后回复 (%s)",
        delay, reason,
    )
    return ReplyDecision(
        should_reply=True,
        delay_seconds=delay,
        persona_hint=hint,
        activity=activity.value,
        reason=reason,
    )


# 为了向后兼容（chat_handlers 直接 import build_morning_after_hint 等）
# 从 reply_hints 重新导出
__all__ = [
    "ReplyDecision",
    "evaluate_reply_state",
    # re-export from reply_hints（保持旧 import 路径不变）
    "build_force_wake_hint",
    "build_morning_after_hint",
    "build_busy_interrupt_hint",
    "build_busy_done_hint",
]
