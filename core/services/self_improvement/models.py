"""
自我改进系统 — 数据模型

定义学习条目、错误条目、功能请求、纠正记录等核心数据结构。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── 枚举 ──────────────────────────────────────────────


class LearningCategory(str, Enum):
    """学习条目分类"""
    CORRECTION = "correction"       # 被纠正
    INSIGHT = "insight"             # 洞察发现
    KNOWLEDGE_GAP = "knowledge_gap" # 知识缺口
    BEST_PRACTICE = "best_practice" # 最佳实践


class EntryPriority(str, Enum):
    """优先级"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EntryStatus(str, Enum):
    """条目状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    PROMOTED = "promoted"
    WONT_FIX = "wont_fix"


class EntryArea(str, Enum):
    """领域标签"""
    FRONTEND = "frontend"
    BACKEND = "backend"
    INFRA = "infra"
    TESTS = "tests"
    DOCS = "docs"
    CONFIG = "config"
    MEMORY = "memory"
    PROMPT = "prompt"
    CHAT = "chat"


class CorrectionSignal(str, Enum):
    """纠正信号类型"""
    DIRECT_DENY = "direct_deny"           # 直接否定："不对"、"错了"
    DIFFERENT_ANSWER = "different_answer"  # 给出不同答案
    GENTLE_GUIDE = "gentle_guide"         # 温和引导："其实..."、"应该是..."
    DEMONSTRATION = "demonstration"        # 示范正确做法
    QUESTIONING = "questioning"            # 质疑："你确定？"
    GIVE_UP = "give_up"                    # 放弃："算了我来"


class MemorySection(str, Enum):
    """MEMORY.md 分区"""
    PREFERENCES = "preferences"     # 用户偏好（永久）
    ROLE = "role"                   # 角色定位（永久）
    EXPERIENCE = "experience"       # 业务经验（≤15条）
    ACTIVE_TASKS = "active_tasks"   # 活跃任务（完成删）
    CORRECTIONS = "corrections"     # 纠正记录（≤10条）
    SUMMARIES = "summaries"         # 对话摘要（7天精简）


# ── ID 生成 ────────────────────────────────────────────


def _generate_id(prefix: str) -> str:
    """生成条目 ID: TYPE-YYYYMMDD-XXX"""
    now = time.localtime()
    date_str = time.strftime("%Y%m%d", now)
    short_uuid = uuid.uuid4().hex[:3].upper()
    return f"{prefix}-{date_str}-{short_uuid}"


def generate_learning_id() -> str:
    return _generate_id("LRN")


def generate_error_id() -> str:
    return _generate_id("ERR")


def generate_feature_id() -> str:
    return _generate_id("FEAT")


def generate_correction_id() -> str:
    return _generate_id("COR")


# ── 数据类 ─────────────────────────────────────────────


@dataclass
class LearningEntry:
    """学习条目"""
    id: str = field(default_factory=generate_learning_id)
    category: LearningCategory = LearningCategory.INSIGHT
    priority: EntryPriority = EntryPriority.MEDIUM
    status: EntryStatus = EntryStatus.PENDING
    area: EntryArea = EntryArea.BACKEND
    summary: str = ""
    details: str = ""
    suggested_action: str = ""
    source: str = "conversation"  # conversation | error | user_feedback | simplify_and_harden
    related_files: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    see_also: List[str] = field(default_factory=list)
    pattern_key: str = ""           # 模式键（用于模式检测去重）
    recurrence_count: int = 1
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    logged_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    promoted_to: str = ""           # 晋升目标文件

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "area": self.area.value,
            "summary": self.summary,
            "details": self.details,
            "suggested_action": self.suggested_action,
            "source": self.source,
            "related_files": self.related_files,
            "tags": self.tags,
            "see_also": self.see_also,
            "pattern_key": self.pattern_key,
            "recurrence_count": self.recurrence_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "logged_at": self.logged_at,
            "resolved_at": self.resolved_at,
            "promoted_to": self.promoted_to,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LearningEntry":
        return cls(
            id=str(d.get("id", "")),
            category=LearningCategory(d.get("category", "insight")),
            priority=EntryPriority(d.get("priority", "medium")),
            status=EntryStatus(d.get("status", "pending")),
            area=EntryArea(d.get("area", "backend")),
            summary=str(d.get("summary", "")),
            details=str(d.get("details", "")),
            suggested_action=str(d.get("suggested_action", "")),
            source=str(d.get("source", "conversation")),
            related_files=list(d.get("related_files", [])),
            tags=list(d.get("tags", [])),
            see_also=list(d.get("see_also", [])),
            pattern_key=str(d.get("pattern_key", "")),
            recurrence_count=int(d.get("recurrence_count", 1)),
            first_seen=d.get("first_seen"),
            last_seen=d.get("last_seen"),
            logged_at=float(d.get("logged_at", 0) or time.time()),
            resolved_at=float(d["resolved_at"]) if d.get("resolved_at") is not None else None,
            promoted_to=str(d.get("promoted_to", "")),
        )


@dataclass
class ErrorEntry:
    """错误条目"""
    id: str = field(default_factory=generate_error_id)
    priority: EntryPriority = EntryPriority.HIGH
    status: EntryStatus = EntryStatus.PENDING
    area: EntryArea = EntryArea.BACKEND
    summary: str = ""
    error_message: str = ""
    context: str = ""
    suggested_fix: str = ""
    reproducible: str = "unknown"  # yes | no | unknown
    related_files: List[str] = field(default_factory=list)
    see_also: List[str] = field(default_factory=list)
    logged_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "priority": self.priority.value,
            "status": self.status.value,
            "area": self.area.value,
            "summary": self.summary,
            "error_message": self.error_message,
            "context": self.context,
            "suggested_fix": self.suggested_fix,
            "reproducible": self.reproducible,
            "related_files": self.related_files,
            "see_also": self.see_also,
            "logged_at": self.logged_at,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ErrorEntry":
        return cls(
            id=str(d.get("id", "")),
            priority=EntryPriority(d.get("priority", "high")),
            status=EntryStatus(d.get("status", "pending")),
            area=EntryArea(d.get("area", "backend")),
            summary=str(d.get("summary", "")),
            error_message=str(d.get("error_message", "")),
            context=str(d.get("context", "")),
            suggested_fix=str(d.get("suggested_fix", "")),
            reproducible=str(d.get("reproducible", "unknown")),
            related_files=list(d.get("related_files", [])),
            see_also=list(d.get("see_also", [])),
            logged_at=float(d.get("logged_at", 0) or time.time()),
            resolved_at=float(d["resolved_at"]) if d.get("resolved_at") is not None else None,
        )


@dataclass
class FeatureRequestEntry:
    """功能请求条目"""
    id: str = field(default_factory=generate_feature_id)
    priority: EntryPriority = EntryPriority.MEDIUM
    status: EntryStatus = EntryStatus.PENDING
    area: EntryArea = EntryArea.BACKEND
    capability: str = ""
    user_context: str = ""
    complexity: str = "medium"  # simple | medium | complex
    suggested_implementation: str = ""
    frequency: str = "first_time"  # first_time | recurring
    related_features: List[str] = field(default_factory=list)
    logged_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "priority": self.priority.value,
            "status": self.status.value,
            "area": self.area.value,
            "capability": self.capability,
            "user_context": self.user_context,
            "complexity": self.complexity,
            "suggested_implementation": self.suggested_implementation,
            "frequency": self.frequency,
            "related_features": self.related_features,
            "logged_at": self.logged_at,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FeatureRequestEntry":
        return cls(
            id=str(d.get("id", "")),
            priority=EntryPriority(d.get("priority", "medium")),
            status=EntryStatus(d.get("status", "pending")),
            area=EntryArea(d.get("area", "backend")),
            capability=str(d.get("capability", "")),
            user_context=str(d.get("user_context", "")),
            complexity=str(d.get("complexity", "medium")),
            suggested_implementation=str(d.get("suggested_implementation", "")),
            frequency=str(d.get("frequency", "first_time")),
            related_features=list(d.get("related_features", [])),
            logged_at=float(d.get("logged_at", 0) or time.time()),
            resolved_at=float(d["resolved_at"]) if d.get("resolved_at") is not None else None,
        )


@dataclass
class CorrectionEntry:
    """纠正记录条目"""
    id: str = field(default_factory=generate_correction_id)
    signal_type: CorrectionSignal = CorrectionSignal.DIRECT_DENY
    priority: EntryPriority = EntryPriority.HIGH
    status: EntryStatus = EntryStatus.PENDING
    title: str = ""
    correction: str = ""       # 正确的做法
    my_error: str = ""         # 我之前做了什么
    root_cause: str = ""       # 为什么犯错
    lesson: str = ""           # 下次怎么做（一句话）
    how_to_apply: str = ""     # 在什么场景下应用
    tags: List[str] = field(default_factory=list)
    logged_at: float = field(default_factory=time.time)
    promoted_at: Optional[float] = None
    promoted_to: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "signal_type": self.signal_type.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "title": self.title,
            "correction": self.correction,
            "my_error": self.my_error,
            "root_cause": self.root_cause,
            "lesson": self.lesson,
            "how_to_apply": self.how_to_apply,
            "tags": self.tags,
            "logged_at": self.logged_at,
            "promoted_at": self.promoted_at,
            "promoted_to": self.promoted_to,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CorrectionEntry":
        return cls(
            id=str(d.get("id", "")),
            signal_type=CorrectionSignal(d.get("signal_type", "direct_deny")),
            priority=EntryPriority(d.get("priority", "high")),
            status=EntryStatus(d.get("status", "pending")),
            title=str(d.get("title", "")),
            correction=str(d.get("correction", "")),
            my_error=str(d.get("my_error", "")),
            root_cause=str(d.get("root_cause", "")),
            lesson=str(d.get("lesson", "")),
            how_to_apply=str(d.get("how_to_apply", "")),
            tags=list(d.get("tags", [])),
            logged_at=float(d.get("logged_at", 0) or time.time()),
            promoted_at=float(d["promoted_at"]) if d.get("promoted_at") is not None else None,
            promoted_to=str(d.get("promoted_to", "")),
        )


@dataclass
class MemorySectionContent:
    """MEMORY.md 单个分区内容"""
    section: MemorySection = MemorySection.PREFERENCES
    items: List[str] = field(default_factory=list)
    max_items: int = 0  # 0 = 无限制

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section": self.section.value,
            "items": self.items,
            "max_items": self.max_items,
        }


# ── MEMORY.md 默认配置 ─────────────────────────────────

MEMORY_SECTION_LIMITS: Dict[MemorySection, int] = {
    MemorySection.PREFERENCES: 0,       # 永久，不限制
    MemorySection.ROLE: 0,              # 永久，不限制
    MemorySection.EXPERIENCE: 15,       # ≤15条
    MemorySection.ACTIVE_TASKS: 10,     # 完成删
    MemorySection.CORRECTIONS: 10,      # ≤10条
    MemorySection.SUMMARIES: 20,        # 7天精简
}

MEMORY_MAX_SIZE_BYTES = 5 * 1024  # 5KB

# ── NOT-to-save 列表 ──────────────────────────────────

NOT_TO_SAVE_PATTERNS = [
    "代码模式/架构/文件结构",    # grep/find 可查
    "Git 历史/谁改了什么",       # git log/blame 权威
    "调试方案/修复步骤",         # fix 在代码里
    "AGENTS.md/SOUL.md 已有内容", # 不重复
    "临时任务状态/当前对话细节",  # 完成后无价值
    "活动日志/PR列表汇总",       # 记意外发现，不记列表
]
