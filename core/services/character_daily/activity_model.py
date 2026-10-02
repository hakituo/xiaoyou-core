"""
角色日常数据模型

定义活动类型、活动槽位、每日计划等核心数据结构。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class ActivityType(str, Enum):
    """角色日常活动类型"""

    # 日常活动
    SLEEPING = "sleeping"  # 睡觉
    WAKING_UP = "waking_up"  # 起床/洗漱
    BREAKFAST = "breakfast"  # 吃早饭
    LUNCH = "lunch"  # 吃午饭
    DINNER = "dinner"  # 吃晚饭
    COOKING = "cooking"  # 做饭
    STUDYING = "studying"  # 学习/做题
    READING = "reading"  # 看书/看番/看剧
    HOUSEWORK = "housework"  # 做家务
    NAPPING = "napping"  # 午休
    WALKING = "walking"  # 出门散步/买东西
    PHONE_SCROLLING = "phone_scrolling"  # 刷手机/看视频
    GARDENING = "gardening"  # 浇花
    EXERCISING = "exercising"  # 运动/拉伸
    GAMING = "gaming"  # 玩游戏
    SELF_CARE = "self_care"  # 洗澡/护肤/整理
    CREATIVE_HOBBY = "creative_hobby"  # 手工/写字/画画
    SHOPPING = "shopping"  # 出门购物/买小东西
    STAYING_UP_LATE = "staying_up_late"  # 熬夜中
    LATE_SNACK = "late_snack"  # 夜宵
    OVERSLEPT_RECOVERY = "overslept_recovery"  # 睡过头后的缓冲
    SLEEP_RECOVERY = "sleep_recovery"  # 睡眠不足后的缓恢复
    IDLE = "idle"  # 发呆/休息

    # 社交活动
    PEER_CHAT = "peer_chat"  # 和对方聊天（结果，非计划项）

    @classmethod
    def from_str(cls, value: str) -> "ActivityType":
        """安全地从字符串转换，未知值返回 IDLE"""
        try:
            return cls(value)
        except ValueError:
            return cls.IDLE


class ActivityExecutionStatus(str, Enum):
    """活动槽位执行状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# 允许在此活动期间发起 peer chat 的活动集合（空闲活动）
CHAT_ELIGIBLE_ACTIVITIES = frozenset(
    {
        ActivityType.IDLE,
        ActivityType.PHONE_SCROLLING,
        ActivityType.READING,
        ActivityType.HOUSEWORK,
        ActivityType.GARDENING,
        ActivityType.WALKING,
        ActivityType.GAMING,
        ActivityType.CREATIVE_HOBBY,
        ActivityType.SHOPPING,
        ActivityType.STAYING_UP_LATE,
        ActivityType.SLEEP_RECOVERY,  # 睡眠恢复状态可以聊天（缓过神来就能聊）
    }
)

# 硬忙碌活动：这些事优先不回，留到做完再处理
HARD_BUSY_ACTIVITIES = frozenset(
    {
        ActivityType.STUDYING,
    }
)

# 软延迟活动：不直接拒回，而是静默几十秒后自然回复
SOFT_REPLY_DELAY_ACTIVITIES = frozenset(
    set(ActivityType)
    - {
        ActivityType.SLEEPING,
        ActivityType.NAPPING,
        ActivityType.WAKING_UP,
        ActivityType.OVERSLEPT_RECOVERY,
        ActivityType.STUDYING,
        ActivityType.PEER_CHAT,
    }
)

# 忙碌活动总集合：保留给旧逻辑/窗口期复用
BUSY_ACTIVITIES = frozenset(HARD_BUSY_ACTIVITIES | SOFT_REPLY_DELAY_ACTIVITIES)

# 不可打扰的活动（吃饭、睡觉）：不会触发 peer chat
DO_NOT_DISTURB_ACTIVITIES = frozenset(
    {
        ActivityType.SLEEPING,
        ActivityType.NAPPING,
        ActivityType.WAKING_UP,
        ActivityType.OVERSLEPT_RECOVERY,
    }
)

# 忙碌活动 → 正在进行时动词（用于情境描述："正在做题"）
BUSY_ACTIVITY_VERBS: Dict[ActivityType, str] = {
    ActivityType.STUDYING: "做题",
    ActivityType.COOKING: "做饭",
    ActivityType.READING: "看书",
    ActivityType.HOUSEWORK: "做家务",
    ActivityType.EXERCISING: "运动",
}

# 活动 → 自然语言动词映射（用于构建 LLM 情境上下文）
ACTIVITY_VERBS: Dict[ActivityType, str] = {
    ActivityType.STUDYING: "做完题",
    ActivityType.READING: "看完书",
    ActivityType.HOUSEWORK: "做完家务",
    ActivityType.PHONE_SCROLLING: "刷完手机",
    ActivityType.GARDENING: "浇完花",
    ActivityType.EXERCISING: "运动完",
    ActivityType.GAMING: "打完游戏",
    ActivityType.SELF_CARE: "洗漱整理完",
    ActivityType.CREATIVE_HOBBY: "做完手工",
    ActivityType.SHOPPING: "买完东西",
    ActivityType.STAYING_UP_LATE: "熬了会夜",
    ActivityType.LATE_SNACK: "吃了夜宵",
    ActivityType.OVERSLEPT_RECOVERY: "缓过神来",
    ActivityType.SLEEP_RECOVERY: "慢慢恢复精神",
    ActivityType.IDLE: "发了会呆",
    ActivityType.WALKING: "散完步",
    ActivityType.NAPPING: "睡醒",
    ActivityType.COOKING: "做完饭",
    ActivityType.BREAKFAST: "吃完早饭",
    ActivityType.LUNCH: "吃完午饭",
    ActivityType.DINNER: "吃完晚饭",
    ActivityType.WAKING_UP: "起床洗漱完",
    ActivityType.SLEEPING: "睡觉",
}

# 活动 → 进行时动词映射（用于 "现在在..." 的上下文描述）
ACTIVITY_VERBS_ONGOING: Dict[ActivityType, str] = {
    ActivityType.STUDYING: "学习",
    ActivityType.READING: "看书",
    ActivityType.HOUSEWORK: "做家务",
    ActivityType.PHONE_SCROLLING: "刷手机",
    ActivityType.GARDENING: "浇花",
    ActivityType.EXERCISING: "运动",
    ActivityType.GAMING: "玩游戏",
    ActivityType.SELF_CARE: "洗澡护肤/整理",
    ActivityType.CREATIVE_HOBBY: "做手工/写写画画",
    ActivityType.SHOPPING: "出门买东西",
    ActivityType.STAYING_UP_LATE: "熬夜",
    ActivityType.LATE_SNACK: "吃夜宵",
    ActivityType.OVERSLEPT_RECOVERY: "睡过头后缓神",
    ActivityType.SLEEP_RECOVERY: "慢慢恢复精神",
    ActivityType.IDLE: "发呆",
    ActivityType.WALKING: "散步",
    ActivityType.NAPPING: "午休",
    ActivityType.COOKING: "做饭",
    ActivityType.BREAKFAST: "吃早饭",
    ActivityType.LUNCH: "吃午饭",
    ActivityType.DINNER: "吃晚饭",
    ActivityType.WAKING_UP: "起床洗漱",
    ActivityType.SLEEPING: "睡觉",
}


def normalize_datetime_for_reference(
    reference: datetime,
    value: datetime,
) -> datetime:
    """把待比较时间归一化成与参考时间相同的时区形态。

    CharacterDaily 里的计划槽位历史上一直按本地墙上时间持久化，大多是 naive
    datetime；而外层模块有时会传入带时区的当前时间。这里不做时区换算，只统一
    aware/naive 形态，避免比较时抛出 TypeError。
    """
    reference_is_aware = reference.tzinfo is not None
    value_is_aware = value.tzinfo is not None
    if reference_is_aware == value_is_aware:
        return value
    if reference_is_aware:
        return value.replace(tzinfo=reference.tzinfo)
    return value.replace(tzinfo=None)


@dataclass
class ActivitySlot:
    """每日计划中的一个活动槽位"""

    activity: ActivityType
    planned_start: datetime  # 计划开始时间
    planned_end: datetime  # 计划结束时间
    flexible: bool = True  # 是否可提前/延后（meal/sleep 不可变）
    chat_eligible: bool = True  # 此活动期间是否适合发起 peer chat
    execution_status: ActivityExecutionStatus = ActivityExecutionStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    produced_food_ids: List[str] = field(default_factory=list)

    def contains(self, dt: datetime) -> bool:
        """判断给定时间是否在此槽位内"""
        normalized_dt = normalize_datetime_for_reference(self.planned_start, dt)
        return self.planned_start <= normalized_dt < self.planned_end

    def slot_key(self) -> str:
        """返回稳定的槽位唯一键。"""
        return f"{self.activity.value}@{self.planned_start.isoformat()}"

    def duration_minutes(self) -> float:
        """活动计划持续时间（分钟）"""
        return (self.planned_end - self.planned_start).total_seconds() / 60.0

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "activity": self.activity.value,
            "planned_start": self.planned_start.isoformat(),
            "planned_end": self.planned_end.isoformat(),
            "flexible": self.flexible,
            "chat_eligible": self.chat_eligible,
            "execution_status": self.execution_status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "produced_food_ids": list(self.produced_food_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ActivitySlot":
        """从字典反序列化"""
        return cls(
            activity=ActivityType.from_str(data.get("activity", "idle")),
            planned_start=datetime.fromisoformat(data["planned_start"]),
            planned_end=datetime.fromisoformat(data["planned_end"]),
            flexible=data.get("flexible", True),
            chat_eligible=data.get("chat_eligible", True),
            execution_status=ActivityExecutionStatus(
                data.get("execution_status", ActivityExecutionStatus.PENDING.value)
            ),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            produced_food_ids=list(data.get("produced_food_ids") or []),
        )


@dataclass
class DailyPlan:
    """角色一天的活动计划"""

    role_id: str
    date: str  # "2026-06-25"
    generated_at: float = 0.0  # 生成时间戳
    slots: List[ActivitySlot] = field(default_factory=list)
    current_activity: ActivityType = ActivityType.IDLE
    today_peer_chat_count: int = 0
    last_peer_chat_ts: float = 0.0  # 上次 peer chat 时间戳（全局）

    def find_current_slot(self, now: datetime) -> Optional[ActivitySlot]:
        """根据当前时间找到对应的活动槽位"""
        for slot in self.slots:
            if slot.contains(now):
                return slot
        return None

    def get_activity_start(self, now: datetime) -> Optional[datetime]:
        """获取当前活动的开始时间"""
        slot = self.find_current_slot(now)
        return slot.planned_start if slot else None

    def to_dict(self) -> dict:
        """序列化为字典（用于持久化）"""
        return {
            "role_id": self.role_id,
            "date": self.date,
            "generated_at": self.generated_at,
            "slots": [s.to_dict() for s in self.slots],
            "current_activity": self.current_activity.value,
            "today_peer_chat_count": self.today_peer_chat_count,
            "last_peer_chat_ts": self.last_peer_chat_ts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DailyPlan":
        """从字典反序列化"""
        return cls(
            role_id=data.get("role_id", ""),
            date=data.get("date", ""),
            generated_at=data.get("generated_at", 0.0),
            slots=[ActivitySlot.from_dict(s) for s in data.get("slots", [])],
            current_activity=ActivityType.from_str(
                data.get("current_activity", "idle")
            ),
            today_peer_chat_count=data.get("today_peer_chat_count", 0),
            last_peer_chat_ts=data.get("last_peer_chat_ts", 0.0),
        )


@dataclass
class DailyState:
    """角色日常引擎的完整运行时状态（含两个角色的计划）"""

    date: str = ""  # 当前日期
    plans: Dict[str, DailyPlan] = field(default_factory=dict)
    global_last_peer_chat_ts: float = 0.0  # 全局最后 peer chat 时间戳

    def get_plan(self, role_id: str) -> Optional[DailyPlan]:
        return self.plans.get(role_id)

    def set_plan(self, plan: DailyPlan) -> None:
        self.plans[plan.role_id] = plan

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "plans": {rid: p.to_dict() for rid, p in self.plans.items()},
            "global_last_peer_chat_ts": self.global_last_peer_chat_ts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DailyState":
        plans = {}
        for rid, pdata in data.get("plans", {}).items():
            plans[rid] = DailyPlan.from_dict(pdata)
        return cls(
            date=data.get("date", ""),
            plans=plans,
            global_last_peer_chat_ts=data.get("global_last_peer_chat_ts", 0.0),
        )
