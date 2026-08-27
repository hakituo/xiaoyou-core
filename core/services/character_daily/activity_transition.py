"""活动自然切换时的告别消息管理。

当角色从"可聊天"活动切到"忙碌/睡觉"活动时，若用户最近在聊天，
主动发一条告别/顺延消息，让 LLM 判断是继续聊还是去做事。

触发场景：
1. 用户在休息时间跟角色聊天，到了下一个计划时段（如学习/做饭），
   角色应该主动说一句"我要去做XX了"或"再聊会儿，待会儿去做XX"。
2. 用户在聊天，到了角色睡觉时间，角色应该主动说一句告别话或顺延一会儿。

与 /打断 接口的区别：
- /打断 是用户主动要求角色停下来聊天，回归消息由 interrupt_window 调度
- 本模块是角色自然活动切换时主动发告别消息，不需要用户调用任何指令

与 sleep_manager._on_enter_sleeping 的区别：
- sleep_manager 触发的是固定晚安消息（每日去重）
- 本模块在用户正在聊天时，用"聊天中入睡"的 instruction，让 LLM 判断顺延还是告别
"""

from __future__ import annotations
from core.utils.logger import get_logger


import time
from typing import Any, Optional

from core.services.character_daily.activity_model import (
    ActivityType,
    BUSY_ACTIVITIES,
    CHAT_ELIGIBLE_ACTIVITIES,
    DO_NOT_DISTURB_ACTIVITIES,
)
from core.services.character_daily.config import ReplyPolicyConfig

logger = get_logger(__name__)

# 去重：记录每个 role_id 最近一次发送告别消息的活动和时间戳
# key: role_id, value: {"activity": str, "ts": float}
_last_farewell: dict[str, dict[str, Any]] = {}

# 做事结束主动处理累积消息的去重记录
# key: role_id, value: {"activity": str, "ts": float}
_last_done_notify: dict[str, dict[str, Any]] = {}


def _is_user_in_conversation(
    scheduler: Any,
    user_active_seconds: float,
) -> bool:
    """检查用户是否最近在聊天。

    用比 peer_chat 更长的窗口（默认 300 秒）来判断用户是否"最近在聊天"，
    而不是 peer_chat 的 45 秒 grace 期。

    Args:
        scheduler: PeerChatScheduler 实例（通过 engine._peer_chat_scheduler 获取）
        user_active_seconds: 判断窗口（秒）

    Returns:
        True 如果用户在最近 user_active_seconds 内发过消息
    """
    if scheduler is None:
        return False
    try:
        now = time.time()
        threshold = float(user_active_seconds)
        # 遍历所有 conversation 的活跃时间戳，任一在窗口内即视为"在聊天"
        for _, ts in scheduler._last_user_activity_ts.items():  # noqa: SLF001
            if ts > 0 and (now - float(ts)) < threshold:
                return True
        return False
    except Exception:
        return False


def _classify_transition(
    prev_activity: ActivityType,
    new_activity: ActivityType,
) -> str:
    """分类活动切换方向。

    Returns:
        "to_busy": 从可聊天切到忙碌（学习/做饭/运动等）
        "to_sleep": 从可聊天切到睡觉/午睡等 DND 活动（已交给 sleep_manager 处理，这里返回 none）
        "none": 不需要告别
    """
    # 切换前后活动相同，不需要告别
    if prev_activity == new_activity:
        return "none"

    # 切换前不是"可聊天"活动，不需要告别
    # （比如从睡觉切到学习，本身就没在聊天）
    if prev_activity not in CHAT_ELIGIBLE_ACTIVITIES:
        return "none"

    # 切换后是 DND（睡觉/午睡/起床洗漱/睡过头恢复）
    # 注意：SLEEPING 切换由 sleep_manager._on_enter_sleeping → trigger_character_goodnight
    # 实时触发，比 engine._tick（2分钟一次）更及时。
    # trigger_character_goodnight 内部会检查用户是否在聊天并选择不同 instruction。
    # 所以这里对 DND 活动返回 "none"，避免与 sleep_manager 重复发送。
    if new_activity in DO_NOT_DISTURB_ACTIVITIES:
        return "none"

    # 切换后是忙碌（学习/做饭/运动等，不含 DND）
    # 注意：SOFT_REPLY_DELAY_ACTIVITIES 包含很多活动（如 HOUSEWORK/BREAKFAST），
    # 这些活动只是"回复慢一点"不是"完全不回"，不需要发告别消息。
    # 只对 HARD_BUSY_ACTIVITIES（学习）发告别消息。
    # 但 BUSY_ACTIVITIES = HARD_BUSY + SOFT_REPLY_DELAY，范围太大。
    # 这里用 BUSY_ACTIVITIES - CHAT_ELIGIBLE_ACTIVITIES 取差集，
    # 即"忙碌但不可聊天"的活动（如 STUDYING/COOKING/EXERCISING/BREAKFAST/LUNCH/DINNER）。
    busy_non_chat = BUSY_ACTIVITIES - CHAT_ELIGIBLE_ACTIVITIES
    if new_activity in busy_non_chat:
        return "to_busy"

    return "none"


def _should_send_farewell(
    role_id: str,
    new_activity: ActivityType,
    farewell_type: str,
    config: ReplyPolicyConfig,
) -> bool:
    """检查是否应该发送告别消息（去重检查）。

    同一 role_id + 同一 new_activity 在冷却时间内只发一次。
    """
    if farewell_type == "none":
        return False

    role_id = str(role_id or "").strip().lower()
    now = time.time()
    cooldown = float(config.activity_transition_farewell_cooldown_seconds)

    last = _last_farewell.get(role_id)
    if last:
        last_activity = str(last.get("activity") or "")
        last_ts = float(last.get("ts") or 0.0)
        # 同一活动 + 冷却期内 → 跳过
        if (
            last_activity == new_activity.value
            and (now - last_ts) < cooldown
        ):
            logger.debug(
                "ActivityTransition: role=%s 活动 %s 告别消息在冷却期内（%.0fs/%.0fs），跳过",
                role_id, new_activity.value, now - last_ts, cooldown,
            )
            return False

    return True


def _mark_farewell_sent(
    role_id: str,
    new_activity: ActivityType,
) -> None:
    """记录已发送告别消息。"""
    role_id = str(role_id or "").strip().lower()
    _last_farewell[role_id] = {
        "activity": new_activity.value,
        "ts": time.time(),
    }


async def _send_farewell_message(
    role_id: str,
    new_activity: ActivityType,
    farewell_type: str,
) -> bool:
    """发送告别消息。

    复用 active_care executor.trigger_message 管线发送。
    对于 to_sleep 类型，使用专门的"聊天中入睡"instruction。
    对于 to_busy 类型，使用"活动开始告别"instruction。

    Args:
        role_id: 角色 ID
        new_activity: 即将开始的新活动
        farewell_type: "to_busy" 或 "to_sleep"

    Returns:
        True 如果发送成功
    """
    role_id = str(role_id or "").strip().lower()
    if not role_id:
        return False

    try:
        from core.services.active_care.core.service import get_active_care_service
        from core.services.character_daily.activity_return.instruction import (
            build_activity_start_farewell_instruction,
            build_sleep_during_chat_farewell_instruction,
        )

        ac = get_active_care_service()
        if not ac or not getattr(ac, "executor", None):
            logger.warning(
                "ActivityTransition: Active Care 未就绪，跳过 role=%s 的告别消息",
                role_id,
            )
            return False

        # 根据切换类型选择 instruction 和 sys_prompt_type
        if farewell_type == "to_sleep":
            specific_instruction = build_sleep_during_chat_farewell_instruction(role_id)
            sys_prompt_type = "goodnight_proactive"
            user_input_mock = "[CHARACTER_SLEEP_DURING_CHAT]"
            thought = f"activity_transition_sleep_{role_id}"
        else:
            specific_instruction = build_activity_start_farewell_instruction(
                role_id, new_activity.value
            )
            sys_prompt_type = "activity_return_proactive"
            user_input_mock = "[ACTIVITY_TRANSITION_FAREWELL]"
            thought = f"activity_transition_busy_{role_id}_{new_activity.value}"

        # 解析 persona 文件名
        from core.services.character_daily.activity_return.instruction import (
            resolve_persona_filename,
        )
        persona_filename = resolve_persona_filename(role_id)
        if not persona_filename:
            logger.warning(
                "ActivityTransition: 角色 %s 无 persona 映射，跳过告别消息发送"
                "（避免误挂到其他角色）",
                role_id,
            )
            return False

        delivered = await ac.executor.trigger_message(
            sys_prompt_type=sys_prompt_type,
            user_input_mock=user_input_mock,
            thought=thought,
            specific_instruction=specific_instruction,
            persona_filename=persona_filename,
            client_type="qq",
            # 自发做事（日程切换告别/入睡告别）：不需要用户回复，
            # 不记录题材、不进 MDP/bandit 学习闭环
            self_activity=True,
        )

        if delivered:
            _mark_farewell_sent(role_id, new_activity)
            logger.info(
                "ActivityTransition: 角色 %s 已发送%s告别消息（new_activity=%s）",
                role_id,
                "入睡" if farewell_type == "to_sleep" else "活动切换",
                new_activity.value,
            )
        else:
            logger.warning(
                "ActivityTransition: 角色 %s 的%s告别消息未发送（可能被间隔保护拦住）",
                role_id,
                "入睡" if farewell_type == "to_sleep" else "活动切换",
            )
        return bool(delivered)
    except Exception as e:
        logger.error(
            "ActivityTransition: 发送告别消息异常 (role=%s, activity=%s): %s",
            role_id, new_activity.value, e, exc_info=True,
        )
        return False


async def check_and_send_farewell_on_transition(
    engine: Any,
    role_id: str,
    prev_activity: ActivityType,
    new_activity: ActivityType,
    config: Optional[ReplyPolicyConfig] = None,
) -> bool:
    """检测活动切换并发告别消息。

    在 CharacterDailyEngine._tick 中，sync_current_activities 之后调用。
    检查切换方向 + 用户是否在聊天 + 去重，满足条件则发告别消息。

    Args:
        engine: CharacterDailyEngine 实例（用于获取 peer_chat_scheduler）
        role_id: 角色 ID
        prev_activity: 切换前的活动
        new_activity: 切换后的活动
        config: ReplyPolicyConfig，None 时用默认值

    Returns:
        True 如果发送了告别消息
    """
    if config is None:
        config = ReplyPolicyConfig()

    if not config.activity_transition_farewell_enabled:
        return False

    # 1. 分类切换方向
    farewell_type = _classify_transition(prev_activity, new_activity)
    if farewell_type == "none":
        return False

    # 2. 去重检查
    if not _should_send_farewell(role_id, new_activity, farewell_type, config):
        return False

    # 3. 检查用户是否最近在聊天
    scheduler = getattr(engine, "_peer_chat_scheduler", None)
    if not _is_user_in_conversation(scheduler, config.activity_transition_user_active_seconds):
        logger.debug(
            "ActivityTransition: role=%s 从 %s 切到 %s，但用户最近未在聊天，跳过告别消息",
            role_id, prev_activity.value, new_activity.value,
        )
        return False

    logger.info(
        "ActivityTransition: role=%s 从 %s 切到 %s，用户正在聊天，发送%s告别消息",
        role_id, prev_activity.value, new_activity.value,
        "入睡" if farewell_type == "to_sleep" else "活动切换",
    )

    # 4. 发送告别消息
    return await _send_farewell_message(role_id, new_activity, farewell_type)


def reset_farewell_state(role_id: str = "") -> None:
    """重置告别消息去重状态（测试用）。"""
    if role_id:
        _last_farewell.pop(str(role_id).strip().lower(), None)
    else:
        _last_farewell.clear()


def _classify_done_transition(
    prev_activity: ActivityType,
    new_activity: ActivityType,
) -> bool:
    """判断是否是"做事结束"切换：从忙碌切到可聊天。

    Returns:
        True 如果 prev 是 BUSY（非 CHAT_ELIGIBLE 的忙碌活动），new 是 CHAT_ELIGIBLE
    """
    if prev_activity == new_activity:
        return False
    # prev 必须是"忙碌但不可聊天"的活动（HARD_BUSY + SOFT_REPLY_DELAY 中非 CHAT_ELIGIBLE 的）
    # 这里直接用 BUSY_ACTIVITIES - CHAT_ELIGIBLE_ACTIVITIES
    busy_non_chat = BUSY_ACTIVITIES - CHAT_ELIGIBLE_ACTIVITIES
    if prev_activity not in busy_non_chat:
        return False
    # new 必须是"可聊天"活动
    if new_activity not in CHAT_ELIGIBLE_ACTIVITIES:
        return False
    return True


def _should_process_done_pending(
    role_id: str,
    prev_activity: ActivityType,
    config: ReplyPolicyConfig,
) -> bool:
    """检查是否应该处理做事结束后的累积消息（去重检查）。

    同一 role_id + 同一 prev_activity 在冷却时间内只触发一次，
    避免 engine._tick 间隔内重复触发。
    """
    role_id = str(role_id or "").strip().lower()
    now = time.time()
    cooldown = float(config.activity_done_pending_cooldown_seconds)

    last = _last_done_notify.get(role_id)
    if last:
        last_activity = str(last.get("activity") or "")
        last_ts = float(last.get("ts") or 0.0)
        if (
            last_activity == prev_activity.value
            and (now - last_ts) < cooldown
        ):
            logger.debug(
                "ActivityTransition: role=%s 做事结束（%s）触发在冷却期内"
                "（%.0fs/%.0fs），跳过",
                role_id, prev_activity.value, now - last_ts, cooldown,
            )
            return False
    return True


def _mark_done_pending_processed(
    role_id: str,
    prev_activity: ActivityType,
) -> None:
    """记录已处理过该 role + 活动的做事结束累积消息。"""
    role_id = str(role_id or "").strip().lower()
    _last_done_notify[role_id] = {
        "activity": prev_activity.value,
        "ts": time.time(),
    }


async def check_and_process_pending_on_activity_done(
    engine: Any,
    role_id: str,
    prev_activity: ActivityType,
    new_activity: ActivityType,
    config: Optional[ReplyPolicyConfig] = None,
) -> int:
    """做事结束后主动处理累积消息。

    在 CharacterDailyEngine._tick 中，sync_current_activities 之后调用。
    当角色从"忙碌"切回"可聊天"时，主动把做事期间静默累积的用户消息
    走 active_care 主动管线发回去，而不是等用户再发新消息才会被注入处理。

    修复原"做完事休息时为什么没回我"的体验缺失：
    旧逻辑下 _DND_PENDING 中的累积消息只在用户再发新消息时才会被
    build_after_activity_done_hint 注入到下一条用户消息上下文，
    没有"做事结束"的主动触发器。

    Args:
        engine: CharacterDailyEngine 实例（保留参数与 farewell 函数对齐）
        role_id: 角色 ID
        prev_activity: 切换前的活动
        new_activity: 切换后的活动
        config: ReplyPolicyConfig，None 时用默认值

    Returns:
        本次触发主动消息的会话数
    """
    if config is None:
        config = ReplyPolicyConfig()

    if not config.activity_done_pending_process_enabled:
        return 0

    # 1. 判断是否是"做事结束"切换
    if not _classify_done_transition(prev_activity, new_activity):
        return 0

    role_id = str(role_id or "").strip().lower()
    if not role_id:
        return 0

    # 2. 去重检查
    if not _should_process_done_pending(role_id, prev_activity, config):
        return 0

    # 3. 按 role_id 反查累积消息（避免遍历所有会话）
    try:
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            clear_pending_messages,
            get_pending_by_role_id,
        )
    except Exception as e:
        logger.debug("ActivityTransition: 导入 chat_reply_runtime 失败: %s", e)
        return 0

    pending_list = get_pending_by_role_id(role_id)
    if not pending_list:
        return 0

    # 4. 触发主动消息
    try:
        from core.services.active_care.core.service import get_active_care_service
        from core.services.character_daily.activity_return.instruction import (
            build_busy_done_active_instruction,
            resolve_persona_filename,
        )

        ac = get_active_care_service()
        if not ac or not getattr(ac, "executor", None):
            logger.warning(
                "ActivityTransition: Active Care 未就绪，跳过 role=%s 的做事结束累积消息处理",
                role_id,
            )
            return 0

        persona_filename = resolve_persona_filename(role_id)
        if not persona_filename:
            logger.debug(
                "ActivityTransition: 角色 %s 无 persona 映射，跳过做事结束累积消息处理",
                role_id,
            )
            return 0

        triggered_count = 0
        for item in pending_list:
            cid = str(item.get("cid") or "").strip()
            messages = list(item.get("messages") or [])
            activity_str = str(item.get("activity") or "").strip()

            if not cid or not messages:
                continue
            # 跳过 DND 累积（如 sleeping 期间的累积）—— 这些由 sleep_recovery / morning_after 处理
            try:
                pending_activity_type = ActivityType.from_str(activity_str)
            except Exception:
                pending_activity_type = ActivityType.IDLE
            if pending_activity_type in DO_NOT_DISTURB_ACTIVITIES:
                continue
            # 条数太少时跳过（避免单条小事也强触发）
            if len(messages) < int(config.activity_done_pending_min_count):
                continue

            specific_instruction = build_busy_done_active_instruction(
                role_id=role_id,
                activity=activity_str or prev_activity.value,
                pending_messages=messages,
            )

            try:
                delivered = await ac.executor.trigger_message(
                    sys_prompt_type="activity_return_proactive",
                    user_input_mock="[BUSY_DONE_PENDING]",
                    thought=f"activity_done_pending_{role_id}_{activity_str}",
                    specific_instruction=specific_instruction,
                    persona_filename=persona_filename,
                    client_type="qq",
                    # 自发做事（做事结束主动回应）：不需要用户回复触发，
                    # 不记录题材、不进 MDP/bandit 学习闭环
                    self_activity=True,
                )
            except Exception as e:
                logger.warning(
                    "ActivityTransition: 角色 %s cid=%s 触发做事结束累积消息失败: %s",
                    role_id, cid, e,
                )
                delivered = False

            if delivered:
                # 主动消息发出后，清空该 cid 的累积消息，避免用户再发新消息时被二次注入
                clear_pending_messages(cid)
                triggered_count += 1
                logger.info(
                    "ActivityTransition: 角色 %s 已主动发送做事结束累积消息"
                    "（cid=%s, prev_activity=%s, new_activity=%s, 消息数=%d）",
                    role_id, cid, prev_activity.value, new_activity.value, len(messages),
                )

        # 5. 标记本次触发，用于去重
        if triggered_count > 0:
            _mark_done_pending_processed(role_id, prev_activity)
        return triggered_count
    except Exception as e:
        logger.error(
            "ActivityTransition: 做事结束累积消息处理异常 (role=%s): %s",
            role_id, e, exc_info=True,
        )
        return 0


def reset_done_pending_state(role_id: str = "") -> None:
    """重置做事结束累积消息去重状态（测试用）。"""
    if role_id:
        _last_done_notify.pop(str(role_id).strip().lower(), None)
    else:
        _last_done_notify.clear()
