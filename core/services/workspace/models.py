from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import time
import uuid


class DiaryEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = Field(default_factory=time.time)
    time_str: str = ""
    type: str = "daily"  # daily, proactive, event
    content: str
    thought: Optional[str] = None
    mood: str = "neutral"
    tags: List[str] = []
    # 日记作者：user(用户自己) / aveline(Aveline角色) / ling(Ling角色)
    # 从 JournalEntry.source 透传，用于前端按作者分组显示
    source: str = "user"


class ScheduledMessage(BaseModel):
    id: str
    trigger_ts: float
    message: str
    message_type: str = "text"  # text, voice, image
    created_at: float = Field(default_factory=time.time)
    status: str = "pending"  # pending, completed, cancelled, failed
    metadata: Dict[str, Any] = {}

    # 允许指定发送时的情绪
    target_emotion: Optional[str] = None

    # P1-5: 周期性提醒支持
    # recurrence: 重复类型，none=单次（默认），daily=每天，weekly=每周，monthly=每月
    # weekdays: weekly 模式下生效，[1..7] 表示周一..周日（1=周一,7=周日）
    # time_of_day: 每日触发时间（HH:MM），用于 daily/weekly/monthly 模式
    # next_trigger_ts: 下次触发时间戳，触发后由 check_due_messages 自动滚动
    recurrence: str = "none"  # none, daily, weekly, monthly
    weekdays: List[int] = Field(default_factory=list)
    time_of_day: str = ""  # "HH:MM" 格式
    next_trigger_ts: Optional[float] = None


class DailyTask(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str
    category: str = "untimed"
    source: str = "manual"
    execution_time: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    duration_minutes: int = 30
    linked_study_topic: Optional[str] = None
    linked_study_path: Optional[str] = None
    notes: str = ""
    status: str = "pending"
    created_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None
