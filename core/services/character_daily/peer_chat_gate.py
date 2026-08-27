"""
Peer Chat 触发门控

在角色日常引擎的主循环中判定是否触发 peer chat。
综合考虑：全局间隔、今日次数、双方活动状态、概率。

支持两种触发模式：
- 双方空闲：正常聊天，多轮对话
- 单方空闲（异步聊天）：空闲方发起，忙碌方可能不回/简短回
"""


from core.utils.logger import get_logger
import random
import time
from datetime import datetime
from typing import Optional, Tuple

from core.services.character_daily.activity_model import (
    ActivityType,
    CHAT_ELIGIBLE_ACTIVITIES,
    DO_NOT_DISTURB_ACTIVITIES,
    DailyPlan,
)
from core.services.character_daily.config import CharacterDailyConfig
from core.utils.logger import get_module_logger

logger = get_logger(__name__)

# 诊断专用 logger，写入 peer_chat.log（与 active_care 主流程分离）
_diag_logger = get_module_logger("PEER_CHAT", "peer_chat.log")


# 活动 → 聊天概率修正因子（发起方）
_ACTIVITY_CHAT_MODIFIER = {
    ActivityType.IDLE: 2.0,  # 发呆最容易想找人聊
    ActivityType.PHONE_SCROLLING: 1.5,  # 刷手机时比较闲
    ActivityType.HOUSEWORK: 0.8,  # 做家务偶尔想聊
    ActivityType.READING: 0.5,  # 看书时不太主动聊
    ActivityType.GARDENING: 0.7,  # 浇花时还可以
    ActivityType.WALKING: 0.6,  # 散步时偶尔
    ActivityType.SLEEP_RECOVERY: 0.8,  # 睡眠恢复时比较闲，可以聊
}

# 异步聊天概率修正：对方忙碌时，发起者打断的概率
# 值越低越不容易打断对方
_BUSY_PEER_PROBABILITY_MODIFIER = 0.6


def should_use_urgent_interrupt(
    is_async: bool,
    config: "CharacterDailyConfig",
) -> bool:
    """异步聊天模式下，是否走"紧急打断"路径

    异步聊天（一方空闲一方忙碌）时，按概率决定是否走"打断"路径：
    - 打断路径：忙碌方也会正经回应，剧本体现"被打断的反应"（如"哎我正做饭呢怎么了"）
    - 非打断路径：异步聊天，忙碌方可能不回/简短回（如"忙着呢等下说"）

    Args:
        is_async: 是否为异步聊天模式
        config: 引擎配置

    Returns:
        True 表示走紧急打断路径
    """
    if not is_async:
        return False
    prob = config.peer_chat.urgent_interrupt_probability
    return random.random() < prob


def should_trigger_peer_chat(
    now: datetime,
    plan_a: DailyPlan,
    plan_l: DailyPlan,
    config: CharacterDailyConfig,
) -> Tuple[bool, Optional[str]]:
    """判定是否应该触发 peer chat

    支持两种模式：
    1. 双方空闲 → 正常聊天
    2. 一方空闲 + 另一方忙碌 → 异步聊天（忙碌方可能不回/简短回）

    Args:
        now: 当前时间
        plan_a: Aveline 的当日计划
        plan_l: Ling 的当日计划
        config: 引擎配置

    Returns:
        (是否触发, 发起者 role_id 或 None)
    """
    pc = config.peer_chat

    # ===== 条件 1：全局最小间隔 =====
    global_last = max(plan_a.last_peer_chat_ts, plan_l.last_peer_chat_ts)
    if global_last > 0 and (time.time() - global_last) < pc.min_gap_seconds:
        _diag_logger.info(
            "PeerChat gate 拦截[条件1-间隔]: global_last=%d gap=%.0fs min_gap=%ds",
            int(global_last), time.time() - global_last, pc.min_gap_seconds,
        )
        return False, None

    # ===== 条件 2：今日总次数 =====
    # 只取发起者计数（修复双计数 bug：_record_peer_chat 只给发起者 +1）
    total_today = max(plan_a.today_peer_chat_count, plan_l.today_peer_chat_count)
    if total_today >= pc.daily_hard_limit:  # 硬上限
        _diag_logger.info(
            "PeerChat gate 拦截[条件2-次数]: total_today=%d hard_limit=%d",
            total_today, pc.daily_hard_limit,
        )
        return False, None

    # ===== 条件 3：时间范围 =====
    hour = now.hour
    if hour < pc.eligible_hours_start or hour >= pc.eligible_hours_end:
        _diag_logger.info(
            "PeerChat gate 拦截[条件3-时间]: hour=%d eligible=[%d,%d)",
            hour, pc.eligible_hours_start, pc.eligible_hours_end,
        )
        return False, None

    # ===== 条件 4：至少一方空闲，且对方不在不可打扰状态 =====
    a_eligible = plan_a.current_activity in CHAT_ELIGIBLE_ACTIVITIES
    l_eligible = plan_l.current_activity in CHAT_ELIGIBLE_ACTIVITIES
    a_dnd = plan_a.current_activity in DO_NOT_DISTURB_ACTIVITIES
    l_dnd = plan_l.current_activity in DO_NOT_DISTURB_ACTIVITIES

    # 两人都不可打扰 → 不触发
    if a_dnd and l_dnd:
        _diag_logger.info(
            "PeerChat gate 拦截[条件4-双DND]: aveline=%s ling=%s",
            plan_a.current_activity.value, plan_l.current_activity.value,
        )
        return False, None

    # 两人都在忙碌（studying/cooking 但非 dnd）→ 不触发
    if not a_eligible and not l_eligible:
        _diag_logger.info(
            "PeerChat gate 拦截[条件4-双忙碌]: aveline=%s(eligible=%s) ling=%s(eligible=%s)",
            plan_a.current_activity.value, a_eligible,
            plan_l.current_activity.value, l_eligible,
        )
        return False, None

    # 至少一方空闲才能触发
    if not a_eligible and not l_eligible:
        _diag_logger.info(
            "PeerChat gate 拦截[条件4-均不空闲]: aveline=%s ling=%s",
            plan_a.current_activity.value, plan_l.current_activity.value,
        )
        return False, None

    # 确定是否为异步聊天模式（一方空闲，另一方忙碌）
    is_async = (a_eligible and not l_eligible) or (l_eligible and not a_eligible)

    # ===== 条件 5：概率判定 =====
    probability = pc.base_probability

    if is_async:
        # 异步聊天：发起者空闲，但对方忙碌
        # 用发起者的活动修正因子，再乘以打断修正
        if a_eligible:
            probability *= _ACTIVITY_CHAT_MODIFIER.get(plan_a.current_activity, 0.3)
        else:
            probability *= _ACTIVITY_CHAT_MODIFIER.get(plan_l.current_activity, 0.3)
        # 打断忙碌方的概率降低
        probability *= _BUSY_PEER_PROBABILITY_MODIFIER
    else:
        # 双方空闲：取较高的修正因子
        mod_a = _ACTIVITY_CHAT_MODIFIER.get(plan_a.current_activity, 0.3)
        mod_l = _ACTIVITY_CHAT_MODIFIER.get(plan_l.current_activity, 0.3)
        probability *= max(mod_a, mod_l)

    # 今日已聊次数衰减
    if total_today >= pc.daily_soft_limit:
        probability *= 0.3
    elif total_today >= pc.daily_soft_limit - 1:
        probability *= 0.6

    # 午饭时段降低
    if 12 <= hour <= 13:
        probability *= 0.3

    # 距上次聊天的时间膨胀
    time_since_last = time.time() - global_last if global_last > 0 else 99999
    if time_since_last > 14400:  # 超过 4 小时没聊
        probability *= 2.0
    elif time_since_last > 7200:  # 超过 2 小时没聊
        probability *= 1.5

    if random.random() > probability:
        _diag_logger.info(
            "PeerChat gate 拦截[条件5-概率]: probability=%.4f random>prob aveline=%s ling=%s "
            "is_async=%s total_today=%d hour=%d time_since_last=%.0fs",
            probability,
            plan_a.current_activity.value, plan_l.current_activity.value,
            is_async, total_today, hour,
            time_since_last if global_last > 0 else -1,
        )
        return False, None

    # ===== 触发！选择发起者 =====
    initiator = _pick_initiator(plan_a, plan_l, is_async)

    mode_str = "异步聊天" if is_async else "正常聊天"
    _diag_logger.info(
        "PeerChat gate 通过! 发起者=%s 模式=%s 概率=%.4f 今日已聊=%d aveline=%s ling=%s",
        initiator, mode_str, probability, total_today,
        plan_a.current_activity.value, plan_l.current_activity.value,
    )
    logger.info(
        "CharacterDaily: Peer chat 触发！发起者=%s, 模式=%s, 概率=%.3f, 今日已聊=%d",
        initiator,
        mode_str,
        probability,
        total_today,
    )
    return True, initiator


def _pick_initiator(
    plan_a: DailyPlan,
    plan_l: DailyPlan,
    is_async: bool = False,
) -> str:
    """选择谁先发起聊天

    逻辑：
    - 异步模式：只有空闲方可以发起（忙碌方不会主动找人聊）
    - 正常模式：空闲活动（idle/phone_scrolling）的角色更可能先开口
    """
    idle_activities = {ActivityType.IDLE, ActivityType.PHONE_SCROLLING}

    if is_async:
        # 异步模式：选空闲方作为发起者
        a_eligible = plan_a.current_activity in CHAT_ELIGIBLE_ACTIVITIES
        l_eligible = plan_l.current_activity in CHAT_ELIGIBLE_ACTIVITIES
        if a_eligible and not l_eligible:
            return "aveline"
        if l_eligible and not a_eligible:
            return "ling"

    # 正常模式
    a_is_idle = plan_a.current_activity in idle_activities
    l_is_idle = plan_l.current_activity in idle_activities

    if a_is_idle and not l_is_idle:
        return "aveline"
    if l_is_idle and not a_is_idle:
        return "ling"

    # 都 idle 或都不 idle，随机选
    return random.choice(["aveline", "ling"])


def build_situation_context(
    initiator: str,
    plan_i: DailyPlan,
    plan_p: DailyPlan,
    interrupt_mode: bool = False,
) -> str:
    """为 LLM 构建自然的聊天情境

    根据双方活动状态生成不同风格的情境描述：
    - 双方空闲：正常聊天情境
    - 一方忙碌（interrupt_mode=False）：异步聊天，忙碌方可能不回/简短回
    - 一方忙碌（interrupt_mode=True）：紧急打断，忙碌方被打断后正经回应

    Args:
        initiator: 发起者 role_id
        plan_i: 发起者的计划
        plan_p: 对方的计划
        interrupt_mode: 是否走紧急打断路径（仅当对方忙碌时有意义）

    Returns:
        情境描述字符串
    """
    from core.services.character_daily.activity_model import (
        ACTIVITY_VERBS,
        ACTIVITY_VERBS_ONGOING,
        CHAT_ELIGIBLE_ACTIVITIES,
    )

    from core.services.dual_role.personas import get_persona

    initiator_persona = get_persona(initiator)
    peer_persona = get_persona(plan_p.role_id)
    name_i = initiator_persona.cn_name if initiator_persona else initiator
    name_p = peer_persona.cn_name if peer_persona else plan_p.role_id

    verb_i = ACTIVITY_VERBS.get(plan_i.current_activity, "休息")
    ongoing_p = ACTIVITY_VERBS_ONGOING.get(plan_p.current_activity, "做事")

    peer_is_free = plan_p.current_activity in CHAT_ELIGIBLE_ACTIVITIES

    parts = [f"{name_i}刚{verb_i}，"]

    if peer_is_free:
        # 对方也空闲：正常聊天
        verb_p = ACTIVITY_VERBS.get(plan_p.current_activity, "休息")
        parts.append(f"看到{name_p}也在{verb_p}。")
    elif interrupt_mode:
        # 紧急打断：发起方有急事，忙碌方会被打断并正经回应
        parts.append(f"想到{name_p}正在{ongoing_p}，但有急事要找她。")
        parts.append(f"{name_p}会被打断，可能有点不情愿但会放下手头的事回应，")
        parts.append(f"可以表达「哎我正{ongoing_p}呢怎么了」或者「等下怎么了快说」。")
    else:
        # 对方忙碌：异步聊天
        parts.append(f"想到{name_p}正在{ongoing_p}。")
        parts.append(f"{name_p}可能在忙，不一定马上回，")
        parts.append("也可能简短回一句比如「忙着呢等下说」或者边做边聊两句。")

    # 任一角色发起都属于双方今天已经聊过，不能换发起者后又称首次聊天。
    total = max(plan_i.today_peer_chat_count, plan_p.today_peer_chat_count)
    if total > 0:
        parts.append(f"今天已经聊过{total}次了。")
    else:
        parts.append("今天还没聊过。")

    return "".join(parts)
