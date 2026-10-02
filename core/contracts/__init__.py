"""
Shared contracts (enums / schemas) for cross-module status reporting.

Why this exists:
- Resource state / model state / service health / task state were previously
  represented in multiple places with slightly different fields/strings.
- This package provides a single source of truth for these concepts so API
  responses and internal snapshots don't drift over time.
"""

from .states import (
    AnomalySeverity,
    ApprovalStatus,
    ConnectionState,
    DeviceType,
    HealthStatus,
    LLMModuleType,
    ModelRuntimeState,
    ModuleInitState,
    PatchStatus,
    ResourcePriority,
    ResourceSeverity,
    ResourceType,
    ServiceRuntimeState,
    TaskPriority,
    TaskStatus,
    TaskType,
    TransactionStatus,
)

__all__ = [
    "AnomalySeverity",
    "ApprovalStatus",
    "ConnectionState",
    "DeviceType",
    "HealthStatus",
    "LLMModuleType",
    "ModelRuntimeState",
    "ModuleInitState",
    "PatchStatus",
    "ResourcePriority",
    "ResourceSeverity",
    "ResourceType",
    "ServiceRuntimeState",
    "TaskPriority",
    "TaskStatus",
    "TaskType",
    "TransactionStatus",
]
