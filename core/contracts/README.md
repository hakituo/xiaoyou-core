# Contracts (统一契约)

本目录用于放置**跨模块共享**的契约：状态枚举、稳定的字段命名规范等。

## 背景

项目中曾同时存在多套“状态表达”：
- 资源状态：`core/resource_manager.py` 与 `core/services/monitoring/resource_monitor.py`
- 模型状态：`core/resource_manager.ModelResource` 与 `core/core_engine/model_manager.ModelInfo`
- 服务健康：`core/async_monitor.HealthChecker` 与 `core/core_engine/lifecycle_manager.ServiceLifecycle`
- 任务状态：Python 调度器与 C++ 调度器 API 输出字符串不一致（例如 `queued/processing`）

长期来看，这会让 API 返回与监控面板字段漂移，调试成本上升。

## 统一入口

- 文件：`core/contracts/states.py`
- 主要内容：
  - `HealthStatus`: `healthy/degraded/unhealthy/error/unknown`
  - `ServiceRuntimeState`: `initialized/stopped/error/unknown`
  - `TaskStatus`: `pending/running/completed/failed/cancelled`
  - `ResourceType`: `memory/cpu/gpu_memory/disk`
  - `ResourceSeverity`: `normal/warning/critical/emergency`
  - `ModelRuntimeState`: `unloaded/loaded/offloaded`
  - `DeviceType`: `cpu/gpu/unknown`
  - `ModuleInitState`: `not_initialized/initializing/initialized/shutdown/error/unknown`
  - `LLMModuleType`: `local/cloud_router/hybrid`

## 使用建议

- 新代码优先 `from core.contracts import ...`，避免重新定义同名枚举或用自由字符串。
- 旧代码兼容：
  - `core/resource_manager.ResourceState` 目前是 `ResourceSeverity` 的别名（不破坏原有 import）。
  - `core/services/scheduler/task_scheduler.TaskStatus` 已改为直接复用契约枚举。
