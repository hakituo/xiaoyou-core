import uuid
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, model_validator
import time
import time as _time  # 别名导入，避免 PlanItem.time 字段名遮蔽 time 模块

from core.utils.time_utils import ts_to_str


class JournalEntry(BaseModel):
    id: str = Field(default_factory=lambda: f"entry_{uuid.uuid4().hex[:12]}")
    timestamp: float = Field(default_factory=time.time)
    time_str: str = Field(default="", description="HH:MM:SS，留空则从timestamp自动生成")
    type: str = Field(
        default="daily", description="daily, proactive, memory_distillation, etc."
    )
    content: str
    mood: str = "neutral"
    thought: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source: str = Field(default="user", description="user, system, memory_distillation")

    @model_validator(mode="after")
    def _auto_fill_time_str(self) -> "JournalEntry":
        if not self.time_str and self.timestamp > 0:
            self.time_str = ts_to_str(self.timestamp, "%H:%M:%S")
        return self


class DailySummary(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    summary: str = Field(description="Overall summary of the day")
    stats: Dict[str, Any] = Field(
        default_factory=dict, description="Statistics like study_count, chat_count"
    )
    tomorrow_tone: Optional[str] = Field(
        default=None,
        description="LLM生成的明日总基调，包含情绪方向、关注重点、互动风格建议",
    )
    generated_at: float = Field(default_factory=time.time)

    # 向后兼容：允许旧数据中的 highlights/mood/tags 字段存在但不存储
    @model_validator(mode="before")
    @classmethod
    def _strip_deprecated_fields(cls, data):
        if isinstance(data, dict):
            data.pop("highlights", None)
            data.pop("mood", None)
            data.pop("tags", None)
        return data


class MonthlySummary(BaseModel):
    month: str = Field(description="YYYY-MM")
    summary: str
    key_events: List[str] = Field(default_factory=list)
    mood_trend: str = Field(description="Description of mood trend")
    stats: Dict[str, Any] = Field(default_factory=dict)
    persona_evolution: Optional[Dict[str, Any]] = Field(
        default=None, description="Evolved traits and interests"
    )
    generated_at: float = Field(default_factory=time.time)


# ── 明日学习生活计划 ──────────────────────────────────────────
class PlanItem(BaseModel):
    """单个计划项（学习/生活/休息等）"""
    id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:12]}")
    # 可选具体时间，格式 HH:MM（24小时制），供排序与 MDP 计划跟进使用。
    time: Optional[str] = Field(default=None, description="HH:MM 格式的具体时间，留空表示无固定时间")
    title: str = Field(description="计划项标题，简短一句话")
    description: Optional[str] = Field(default=None, description="详细说明/备注")
    # study/life/rest/other；study 时 subject 标明学科
    category: str = Field(default="study", description="study/life/rest/other")
    subject: Optional[str] = Field(
        default=None,
        description="学科：语文/数学/英语/物理/化学/生物（仅 study 类别使用）",
    )
    priority: str = Field(default="normal", description="high/normal/low")
    estimated_duration_minutes: int = Field(default=60, description="预计耗时（分钟）")
    status: str = Field(
        default="pending",
        description="pending/in_progress/completed/skipped",
    )
    # 用户明确新增或修改计划项时，关联的 Workspace 硬提醒 ID。
    reminder_id: Optional[str] = Field(default=None, description="关联的开始提醒消息 ID")
    end_reminder_id: Optional[str] = Field(default=None, description="关联的结束提醒消息 ID")
    source_key: str = Field(
        default="",
        description="候选事实或模板的稳定键；旧计划缺失时为空",
    )
    source_type: str = Field(
        default="algorithm",
        description="algorithm/manual/carryover 等来源类型",
    )
    score: float = Field(default=0.0, description="确定性引擎最终评分")
    carryover_count: int = Field(default=0, ge=0, description="跨日滚动次数")
    deferred_from_date: Optional[str] = Field(
        default=None,
        description="首次延期来源日期 YYYY-MM-DD",
    )
    settlement_reason: Optional[str] = Field(
        default=None,
        description="自动结算原因，如 sleep/checkpoint_capacity",
    )
    created_at: float = Field(default_factory=_time.time)
    updated_at: float = Field(default_factory=_time.time)


class DailyPlan(BaseModel):
    """某日的学习生活计划"""
    date: str = Field(description="YYYY-MM-DD，计划执行日期")
    items: List[PlanItem] = Field(default_factory=list)
    # 自动算法生成时的整体说明。
    notes: Optional[str] = Field(default=None, description="计划整体说明")
    source: str = Field(
        default="algorithm_generated",
        description="algorithm_generated/algorithm_adjusted/manual；兼容读取旧 ai_* 值",
    )
    checkpoint_reviews: Dict[str, float] = Field(
        default_factory=dict,
        description="已执行的自动检查点复盘记录，key 形如 YYYY-MM-DD:noon/evening",
    )
    revision_count: int = Field(default=0, description="当日计划被自动重排的次数")
    generated_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
