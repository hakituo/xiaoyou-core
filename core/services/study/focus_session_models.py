# -*- coding: utf-8 -*-
"""专注会话数据模型（后端权威会话）。

设计要点：
- 后端是唯一计时权威。前端只负责摄像头抽帧 + 端侧轻量检测，并上报结构化观察。
- 默认不上传连续视频、不录音、不保存原始画面；观察里只允许 presence/activity/confidence/signals。
- 会话状态机：created -> active <-> paused -> finished。
- 每次 observation 都带 sequence 做幂等；后端按序列号去重，乱序/重复直接忽略。
"""
from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, now_str, today_str

# companion_data/user_data 下按 YYYY/MM/DD 存放（与 DailyActivityManager 一致）
try:
    from core.utils.data.data_paths import get_user_data_dir
except Exception:  # pragma: no cover
    get_user_data_dir = None  # type: ignore

logger = get_logger("FOCUS_SESSION")


# ---------------------------------------------------------------------------
# 枚举：可观察状态（只描述现象，不判断"学习/玩"）
# ---------------------------------------------------------------------------
class PresenceState(str, Enum):
    PRESENT = "present"                  # 人在镜头内
    AWAY = "away"                        # 人离开
    CAMERA_BLOCKED = "camera_blocked"    # 镜头被遮挡
    UNKNOWN = "unknown"                  # 无信号 / 无法判断


class ActivityState(str, Enum):
    FOCUSED = "focused"                              # 姿态稳定、在专注
    POSSIBLY_DISTRACTED = "possibly_distracted"     # 持续看向别处 / 手机长期出现
    UNKNOWN = "unknown"


class SessionStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    FINISHED = "finished"


# 允许的 observation 取值白名单（前端上报若不在此范围，后端拒绝）
PRESENCE_WHITELIST = {p.value for p in PresenceState}
ACTIVITY_WHITELIST = {a.value for a in ActivityState}


# ---------------------------------------------------------------------------
# 观察点（前端抽帧 -> 端侧检测 -> 上报）
# ---------------------------------------------------------------------------
@dataclass
class Observation:
    sequence: int                       # 单调递增序列号（前端维护，用于幂等）
    observed_at: float                  # 该帧被观察到的 unix 时间戳（秒，前端时钟）
    presence: str
    activity: str
    confidence: float = 0.0             # 0~1
    signals: List[str] = field(default_factory=list)   # e.g. ["head_away","phone_visible"]
    page_visible: bool = True           # 浏览器标签页是否可见（Page Visibility API）
    client_ts: float = 0.0              # 冗余：上报时刻前端时钟
    server_ts: float = 0.0              # 后端接收时刻（写入时填）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 专注监控协调器产出的"探班"事件（记录用，不直接发消息）
# ---------------------------------------------------------------------------
@dataclass
class NudgeEvent:
    at: float                           # 触发时刻 unix ts
    reason: str                         # e.g. "distraction_sustained"
    mode: str                           # gentle / strict
    message: str                        # 实际发送的探班文案
    recovered: Optional[bool] = None    # 用户后续是否恢复专注（结束/后续观察判定）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 会话（后端权威）
# ---------------------------------------------------------------------------
@dataclass
class FocusSession:
    session_id: str
    user_id: str
    subject: str                        # 学习事项
    planned_minutes: int                # 计划时长（分钟）
    mode: str = "gentle"                # gentle / strict
    monitoring: bool = True             # 是否有摄像头监控（Android 无摄像头时为 False）
    created_at: float = 0.0
    started_at: float = 0.0             # 真正进入 active 的时刻（含暂停恢复重算）
    finished_at: float = 0.0
    status: str = SessionStatus.CREATED.value
    reminders_muted: bool = False       # "暂时不要提醒"

    # 计时累计（秒）：后端权威，不依赖前端累加
    accumulated_active_seconds: float = 0.0   # 实际处于 active 的总秒数
    last_resume_at: float = 0.0               # 最近一次 resume 的 unix ts
    paused_at: float = 0.0                    # 最近一次 pause 的 unix ts

    # 观察聚合（秒）
    sec_focused: float = 0.0
    sec_possibly_distracted: float = 0.0
    sec_away: float = 0.0
    sec_unknown: float = 0.0

    # 中断 / 最长连续专注段
    interruption_count: int = 0
    longest_focus_streak_sec: float = 0.0

    # 探班
    nudge_events: List[Dict[str, Any]] = field(default_factory=list)

    # 观察落盘（保留可配置天数，这里是全量；清理由 service 负责）
    observations: List[Dict[str, Any]] = field(default_factory=list)

    # 重复性检测用的序列号集合
    _seen_sequences: set = field(default_factory=set, repr=False, compare=False)

    # 最近一次有效状态（供 current 接口与策略使用）
    last_presence: str = PresenceState.UNKNOWN.value
    last_activity: str = ActivityState.UNKNOWN.value
    last_confidence: float = 0.0
    last_observed_at: float = 0.0

    # 用户自评 / 备注
    self_rating: Optional[int] = None
    note: Optional[str] = None

    # 自然语言总结（结束生成）
    summary_text: Optional[str] = None

    # 当前连续分心起点（策略用，运行时态）
    _distraction_since: float = field(default=0.0, repr=False, compare=False)

    # 最近一次低频视觉复核触发时刻（冷却用）
    vision_review_last_at: float = 0.0

    # 低频视觉复核结果记录（只存结构化结论，绝不存图像/帧）
    vision_review_events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("_seen_sequences", None)
        d.pop("_distraction_since", None)
        return d

    # ---- 路径与持久化 ----
    def storage_dir(self) -> str:
        """companion_data/user_data 下按 YYYY/MM/DD 存放。"""
        if get_user_data_dir is None:  # pragma: no cover
            base = os.path.join(os.getcwd(), "companion_data", "user_data")
        else:
            base = str(get_user_data_dir())
        date_str = today_str()
        y, m, d = date_str.split("-")
        return os.path.join(base, "focus_sessions", str(int(y)), str(int(m)), str(int(d)))

    def file_path(self) -> str:
        os.makedirs(self.storage_dir(), exist_ok=True)
        return os.path.join(self.storage_dir(), f"{self.session_id}.json")

    def lock_path(self) -> str:
        return self.file_path() + ".lock"

    # ---- 计时辅助 ----
    def _now(self) -> float:
        return get_current_time().timestamp()

    def effective_elapsed(self) -> float:
        """当前有效专注秒数（含正在进行的 active 段）。"""
        if self.status == SessionStatus.ACTIVE.value and self.last_resume_at > 0:
            return self.accumulated_active_seconds + (self._now() - self.last_resume_at)
        return self.accumulated_active_seconds

    def remaining_seconds(self) -> float:
        planned = self.planned_minutes * 60
        return max(0.0, planned - self.effective_elapsed())
