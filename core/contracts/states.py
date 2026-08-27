from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Enum that serializes to its value (string)."""

    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    ERROR = "error"
    UNKNOWN = "unknown"


class ServiceRuntimeState(StrEnum):
    INITIALIZED = "initialized"
    STOPPED = "stopped"
    ERROR = "error"
    UNKNOWN = "unknown"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResourceSeverity(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class ResourceType(StrEnum):
    MEMORY = "memory"
    CPU = "cpu"
    GPU_MEMORY = "gpu_memory"
    DISK = "disk"


class DeviceType(StrEnum):
    CPU = "cpu"
    GPU = "gpu"
    UNKNOWN = "unknown"


class ModelRuntimeState(StrEnum):
    UNLOADED = "unloaded"
    LOADED = "loaded"
    OFFLOADED = "offloaded"


class ModuleInitState(StrEnum):
    """
    Canonical module initialization state (separate from model runtime state).

    Examples:
    - LLM module may be initialized (clients ready) while a local model is unloaded.
    - Model runtime state is tracked separately via ModelRuntimeState.
    """

    NOT_INITIALIZED = "not_initialized"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    SHUTDOWN = "shutdown"
    ERROR = "error"
    UNKNOWN = "unknown"


class LLMModuleType(StrEnum):
    """
    Canonical LLM routing/module type.
    """

    LOCAL = "local"
    CLOUD_ROUTER = "cloud_router"
    HYBRID = "hybrid"


# --- 连接状态 ---
class ConnectionState(StrEnum):
    """WebSocket/网络连接状态"""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    CLOSED = "closed"


# --- 审批状态 ---
class ApprovalStatus(StrEnum):
    """审批流程状态"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


# --- 事务状态 ---
class TransactionStatus(StrEnum):
    """Saga 事务状态"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    COMPENSATION_FAILED = "compensation_failed"


# --- 补丁状态 ---
class PatchStatus(StrEnum):
    """自动修复补丁状态"""
    PENDING = "pending"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    VERIFYING = "verifying"
    TESTING = "testing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SUGGESTION_ONLY = "suggestion_only"


# --- 异常严重度 ---
class AnomalySeverity(StrEnum):
    """异常严重程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# --- 任务优先级 ---
class TaskPriority(StrEnum):
    """任务调度优先级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# --- 任务类型 ---
class TaskType(StrEnum):
    """任务类型"""
    DEFAULT = "default"
    CPU = "cpu"
    GPU = "gpu"
    IO = "io"
    TTS = "tts"
    STT = "stt"
    IMAGE = "image"
    LLM = "llm"


# --- 资源优先级 ---
class ResourcePriority(StrEnum):
    """资源管理优先级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    IDLE = "idle"
