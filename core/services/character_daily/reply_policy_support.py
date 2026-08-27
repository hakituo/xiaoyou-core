"""ReplyPolicy 辅助函数：状态读取、计划提示、轻活动延迟分档。"""

from __future__ import annotations
from core.utils.logger import get_logger


import time
from dataclasses import dataclass
from typing import Any

from core.utils.time_utils import get_current_time

from core.services.character_daily.activity_model import (
    ACTIVITY_VERBS_ONGOING,
    ActivityType,
)
from core.services.character_daily.config import ReplyPolicyConfig
from core.services.character_daily.reply_hints import build_plan_transition_hint

logger = get_logger(__name__)


# 判定"用户是否仍在活跃聊天"的宽限秒数：最近这么久内有用户消息即视为还在聊，
# 此时不应急着回到原状态（睡觉 / 原活动）。与"被叫醒后静默窗口"共用同一思路。
RECENT_ACTIVITY_GRACE_SECONDS = 90.0


def is_user_recently_active(
    conversation_id: str,
    lookback_seconds: float = RECENT_ACTIVITY_GRACE_SECONDS,
) -> bool:
    """判断用户是否仍在活跃聊天。

    统一服务于两条"交互结束→回原状态"链路（被叫醒后睡回 / 被中断后回做事）：
    只要最近 ``lookback_seconds`` 内有用户消息，就视为"还在聊"，不应回到原状态。

    信号来自 active_care 的"最近用户消息"缓存（每条用户消息都会更新时间戳），
    因此精确反映会话级的最近活跃时间。
    """
    cid = str(conversation_id or "").strip()
    if not cid:
        return False
    try:
        from core.services.active_care.core.service import get_active_care_service

        ac = get_active_care_service()
        if not ac or not getattr(ac, "executor", None):
            return False
        context = getattr(ac.executor, "context", None)
        if context is None or not hasattr(context, "get_recent_user_message"):
            return False
        recent = context.get_recent_user_message(cid)
        if not isinstance(recent, dict):
            return False
        ts = recent.get("timestamp")
        if not ts:
            return False
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            return False
        return (time.time() - ts) <= float(lookback_seconds)
    except Exception as exc:  # pragma: no cover - 判定失败时保守返回 False（不阻断回原状态）
        logger.warning("判断用户是否仍在活跃聊天失败 (cid=%s): %s", cid, exc)
        return False


@dataclass(frozen=True)
class SoftDelayProfile:
    """轻活动静默后回复的延迟档位。"""

    profile_name: str
    min_seconds: float
    max_seconds: float


@dataclass(frozen=True)
class DndWakeProfile:
    """DND 场景下的唤醒概率画像。"""

    effective_probability: float
    probability_bonus: float = 0.0
    fresh_sleep_seconds: float = -1.0


_QUICK_REPLY_DELAY_ACTIVITIES = frozenset(
    {
        ActivityType.IDLE,
        ActivityType.PHONE_SCROLLING,
        ActivityType.READING,
        ActivityType.GAMING,
    }
)

_SLOW_REPLY_DELAY_ACTIVITIES = frozenset(
    {
        ActivityType.COOKING,
        ActivityType.HOUSEWORK,
        ActivityType.EXERCISING,
        ActivityType.BREAKFAST,
        ActivityType.LUNCH,
        ActivityType.DINNER,
    }
)

_RECOVERY_REPLY_DELAY_ACTIVITIES = frozenset({ActivityType.SLEEP_RECOVERY})


def resolve_reply_scope(role_id: str, persona_filename: str = "") -> str:
    """解析当前被动回复应使用的角色 scope。

    yeye/rushuang 已接入独立 QQ 账号参与 active_care；xiaolu/mianmian 仅接
    character_daily + sleep_manager。都返回它们自己的 scope，让 reply_policy
    查它们自己的 plan/sleep 状态，而不是误用 aveline 的状态。
    """
    normalized_role = str(role_id or "").strip().lower()
    if normalized_role in {"ling", "yeye", "xiaolu", "rushuang", "mianmian", "chiba"}:
        fallback_scope = normalized_role
    else:
        fallback_scope = "aveline"

    if not persona_filename:
        return fallback_scope

    try:
        from core.services.active_care.core.service import get_active_care_service

        ac = get_active_care_service()
        if ac is not None and ac.storage is not None:
            scope = ac.storage.resolve_scope_from_persona_filename(persona_filename)
            if scope:
                return str(scope).strip().lower()
    except Exception as e:
        logger.debug("根据 persona_filename 解析回复 scope 失败: %s", e)

    persona_lower = str(persona_filename).strip().lower()
    if "yeye" in persona_lower or "Coco" in persona_lower:
        return "yeye"
    if "xiaolu" in persona_lower or "小鹿" in persona_lower:
        return "xiaolu"
    if "rushuang" in persona_lower or "Frost" in persona_lower:
        return "rushuang"
    if "mianmian" in persona_lower or "Mian" in persona_lower:
        return "mianmian"
    if "chiba" in persona_lower or "Chiba" in persona_lower or "千葉" in persona_lower:
        return "chiba"
    if "ling" in persona_lower:
        return "ling"
    return fallback_scope


def is_role_recently_woken(scope: str, grace_seconds: float) -> bool:
    """判断同 role 是否在宽限窗口内被唤醒过。

    读取 sleep_manager 的 per-scope 摘要里的 last_wake_ts（force_wake / /wake 都会写）。
    sleep 状态本身是 per-scope（ling/aveline）共享的，所以同 role 不同人设的会话
    都能读到同一个 last_wake_ts——这正是"唤醒Ling后，她所有人设都算醒过"的依据。

    用途：用户在人设 A 把角色吵醒后，切到人设 B；若在宽限窗口内，B 直接放行回复，
    不重新走 DND 静默累积，避免"切人设就说还在睡觉"。
    """
    s = str(scope or "").strip().lower()
    if not s or grace_seconds <= 0:
        return False
    try:
        from core.services.life_simulation import get_sleep_manager

        sm = get_sleep_manager()
        if sm is None:
            return False
        summary = sm.get_summary(s) or {}
        last_wake_ts = float(summary.get("last_wake_ts") or 0.0)
        if last_wake_ts <= 0:
            return False
        return (time.time() - last_wake_ts) <= grace_seconds
    except Exception as e:
        logger.debug("查询 is_role_recently_woken 失败(scope=%s): %s", s, e)
        return False


async def is_active_care_sleeping(scope: str = "") -> bool:
    """查询 Active Care 睡眠会话是否活跃。"""
    try:
        from core.services.life_simulation import get_sleep_manager
        from core.services.active_care.core.service import get_active_care_service
        from core.services.active_care.state.sleep_state import SleepStateManager

        resolved_scope = str(scope or "").strip().lower()
        if resolved_scope:
            sleep_summary = get_sleep_manager().get_summary(resolved_scope)
            phase = str(sleep_summary.get("phase") or "").strip().lower()
            if not bool(sleep_summary.get("is_sleeping")) and phase in {
                "night_awake",
                "stay_up_late",
                "sleep_later",
                "waking_up",
                "fully_awake",
            }:
                return False

        ac = get_active_care_service()
        if ac is None or ac.storage is None:
            return False
        state_data = await ac.storage.get_proactive_state(scope=resolved_scope or None)
        last_goodnight = float(state_data.get("last_goodnight_ts") or 0)
        last_goodmorning = float(state_data.get("last_goodmorning_ts") or 0)
        return SleepStateManager.is_sleep_session_active_from_state(
            last_goodnight, last_goodmorning
        )
    except Exception as e:
        logger.debug("查询 active_care 睡眠会话失败: %s", e)
        return False


async def get_recent_proactive_sent_elapsed(scope: str = "") -> float:
    """读取当前 persona 最近一次主动发消息距今多久。"""
    try:
        from core.services.active_care.core.service import get_active_care_service

        ac = get_active_care_service()
        if ac is None or ac.storage is None:
            return -1.0

        state_data = await ac.storage.get_proactive_state(scope=scope or None)
        last_sent_ts = float(state_data.get("last_sent_ts") or 0.0)
        if last_sent_ts <= 0:
            return -1.0
        return max(0.0, time.time() - last_sent_ts)
    except Exception as e:
        logger.debug("查询最近主动发消息时间失败: %s", e)
        return -1.0


def build_sleep_recovery_reason_suffix(scope: str, activity: ActivityType) -> str:
    """为 sleep_recovery 日志补充更直观的来源说明。"""
    if activity != ActivityType.SLEEP_RECOVERY:
        return ""

    try:
        from core.services.life_simulation import get_sleep_manager

        sleep_manager = get_sleep_manager()
        if sleep_manager is None:
            return ""

        summary = sleep_manager.get_summary(scope)
        nightmare_level = str(summary.get("nightmare_level") or "none")
        impact_level = str(summary.get("impact_level") or "none")
        sleep_debt_hours = float(summary.get("sleep_debt_hours") or 0.0)

        detail_parts: list[str] = []
        if nightmare_level != "none":
            detail_parts.append(f"nightmare={nightmare_level}")
        if sleep_debt_hours >= 0.3:
            detail_parts.append(f"sleep_debt={sleep_debt_hours:.1f}h")
        if impact_level != "none":
            detail_parts.append(f"impact={impact_level}")

        if not detail_parts:
            return ", sleep_recovery_source=unknown"
        return ", sleep_recovery_source=" + "|".join(detail_parts)
    except Exception as e:
        logger.debug("构建 sleep_recovery 日志说明失败: %s", e)
        return ""


def build_plan_transition_persona_hint(
    scope: str,
    config: ReplyPolicyConfig,
) -> str:
    """当下一个计划即将开始时，给回复注入自然收尾/顺延提示。"""
    if config.plan_transition_notice_seconds <= 0:
        return ""

    try:
        from core.services.character_daily.engine import get_character_daily_engine

        engine = get_character_daily_engine()
        if engine is None:
            return ""

        plan = engine.state.get_plan(scope)
        if plan is None:
            return ""

        now = get_current_time()
        next_slot = None
        for slot in plan.slots:
            if slot.planned_start > now:
                next_slot = slot
                break

        if next_slot is None:
            return ""

        remaining_seconds = (next_slot.planned_start - now).total_seconds()
        if (
            remaining_seconds <= 0
            or remaining_seconds > config.plan_transition_notice_seconds
        ):
            return ""

        remaining_minutes = max(1, int((remaining_seconds + 59) // 60))
        next_activity = ACTIVITY_VERBS_ONGOING.get(
            next_slot.activity, next_slot.activity.value
        )
        return build_plan_transition_hint(
            next_activity=next_activity,
            start_time=next_slot.planned_start.strftime("%H:%M"),
            remaining_minutes=remaining_minutes,
        )
    except Exception as e:
        logger.debug("构建计划切换提示失败: %s", e)
        return ""


def get_manual_interrupt_window_state(
    scope: str,
    conversation_id: str,
) -> dict[str, Any] | None:
    """读取当前会话的手动打断聊天窗口。"""
    cid = str(conversation_id or "").strip()
    if not cid:
        return None
    try:
        from core.services.character_daily.interrupt_window import (
            get_manual_interrupt_window,
        )

        return get_manual_interrupt_window(conversation_id=cid, role_id=scope)
    except Exception as e:
        logger.debug("读取手动打断窗口失败: %s", e)
        return None


def get_activity_return_pending_state(
    conversation_id: str,
) -> dict[str, Any] | None:
    """读取当前会话是否有待处理的回归消息状态。"""
    cid = str(conversation_id or "").strip()
    if not cid:
        return None
    try:
        from core.services.character_daily.activity_return import (
            get_pending_return,
        )

        return get_pending_return(cid)
    except Exception as e:
        logger.debug("读取活动回归 pending 状态失败: %s", e)
        return None


def build_activity_return_reply_hint(conversation_id: str) -> str:
    """用户在回归消息等待期内回复时，注入的决策提示。"""
    pending = get_activity_return_pending_state(conversation_id)
    if not pending:
        return ""
    activity = str(pending.get("activity") or "").strip()
    return_type = pending.get("return_type") or "work"
    try:
        from core.services.character_daily.activity_return import (
            build_return_decision_hint,
        )

        return build_return_decision_hint(activity, return_type)
    except Exception as e:
        logger.debug("构建回归决策提示失败: %s", e)
        return ""


async def extend_window_on_return_reply(conversation_id: str, user_message: str) -> bool:
    """用户在回归消息等待期内回复时，延长窗口并返回是否处理。"""
    cid = str(conversation_id or "").strip()
    if not cid:
        return False
    try:
        from core.services.character_daily.activity_return import (
            handle_user_reply_during_return,
        )

        result = await handle_user_reply_during_return(cid, user_message)
        return bool(result.get("handled"))
    except Exception as e:
        logger.debug("处理回归消息回复失败: %s", e)
        return False


def build_manual_interrupt_window_hint(
    activity: ActivityType,
    remaining_seconds: float,
) -> str:
    """构建手动打断窗口期间的人设提示。

    Args:
        activity: 被中断的活动类型
        remaining_seconds: 窗口剩余时间（秒）
        ending_threshold_seconds: 窗口即将结束的阈值（秒），默认 60 秒

    Returns:
        注入 prompt 的人设提示
    """
    activity_verb = ACTIVITY_VERBS_ONGOING.get(activity, "做事")
    remaining_minutes = max(1, int((max(0.0, remaining_seconds) + 59) // 60))

    # 窗口即将结束时，注入不同的提示
    if remaining_seconds <= 60.0:
        return (
            f"你刚才被用户打断，暂时放下了「{activity_verb}」来陪他聊天。"
            f"不过聊天窗口快要结束了（只剩下约 {remaining_minutes} 分钟），"
            f"你需要在这条回复里自然地提及自己差不多该回去继续{activity_verb}了。"
            "不要突然硬切断，也不要完全不提。"
            "可以说类似「差不多该回去接着做了」「再聊一会儿我得去忙了」之类的话，"
            "让用户知道你的窗口快结束了。"
        )

    # 窗口正常进行中
    return (
        f"你刚刚被用户明确要求从「{activity_verb}」里先抽身出来陪他聊天，"
        f"当前仍处于手动打断后的聊天窗口期内，至少还会继续聊约 {remaining_minutes} 分钟。"
        "请先自然接话，不要一开口就急着说自己要马上回去忙。"
    )


def resolve_soft_delay_profile(
    activity: ActivityType,
    config: ReplyPolicyConfig,
) -> SoftDelayProfile:
    """按活动类型返回轻活动静默后回复的延迟档位。"""
    if activity in _QUICK_REPLY_DELAY_ACTIVITIES:
        return SoftDelayProfile(
            profile_name="quick",
            min_seconds=config.soft_delay_quick_min_seconds,
            max_seconds=config.soft_delay_quick_max_seconds,
        )
    if activity in _SLOW_REPLY_DELAY_ACTIVITIES:
        return SoftDelayProfile(
            profile_name="slow",
            min_seconds=config.soft_delay_slow_min_seconds,
            max_seconds=config.soft_delay_slow_max_seconds,
        )
    if activity in _RECOVERY_REPLY_DELAY_ACTIVITIES:
        return SoftDelayProfile(
            profile_name="recovery",
            min_seconds=config.soft_delay_recovery_min_seconds,
            max_seconds=config.soft_delay_recovery_max_seconds,
        )
    return SoftDelayProfile(
        profile_name="normal",
        min_seconds=config.soft_delay_normal_min_seconds,
        max_seconds=config.soft_delay_normal_max_seconds,
    )


def _get_sleep_profile_value(profile: Any, attr_name: str, default: float) -> float:
    """从睡眠性格配置中读取概率值。"""
    try:
        return float(getattr(profile, attr_name, default))
    except Exception:
        return float(default)


def resolve_dnd_wake_profile(
    role_id: str,
    activity: ActivityType,
    base_probability: float,
) -> DndWakeProfile:
    """根据睡眠深度修正 DND 场景下的唤醒概率。"""
    effective_probability = max(0.0, min(1.0, float(base_probability)))
    if activity != ActivityType.SLEEPING:
        return DndWakeProfile(effective_probability=effective_probability)

    try:
        from core.services.life_simulation.sleep_manager import get_sleep_manager

        sleep_manager = get_sleep_manager()
        state = sleep_manager.get_state(role_id)
        if not state.is_sleeping or state.actual_sleep_start_ts <= 0:
            return DndWakeProfile(effective_probability=effective_probability)

        fresh_sleep_seconds = max(
            0.0,
            time.time() - float(state.actual_sleep_start_ts),
        )
        # 刚睡下的前 15 分钟最容易被叫醒，随后快速衰减到 0。
        if fresh_sleep_seconds > 15 * 60:
            return DndWakeProfile(
                effective_probability=effective_probability,
                fresh_sleep_seconds=fresh_sleep_seconds,
            )

        profile = sleep_manager._get_profile(role_id)  # noqa: SLF001 - 复用既有睡眠画像
        sensitivity = _get_sleep_profile_value(
            profile,
            "wake_by_message_sensitivity",
            0.5,
        )
        freshness_ratio = max(0.0, 1.0 - fresh_sleep_seconds / (15 * 60))
        probability_bonus = freshness_ratio * (0.25 + 0.35 * sensitivity)
        effective_probability = min(1.0, effective_probability + probability_bonus)
        return DndWakeProfile(
            effective_probability=effective_probability,
            probability_bonus=probability_bonus,
            fresh_sleep_seconds=fresh_sleep_seconds,
        )
    except Exception as e:
        logger.debug("计算刚睡下唤醒增益失败: %s", e)
        return DndWakeProfile(effective_probability=effective_probability)
