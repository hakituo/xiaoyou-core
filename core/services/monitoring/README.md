# Monitoring (监控)

本模块提供系统资源监控与降级建议，并输出可用于 API / Dashboard 的**稳定快照**。

## 关键文件

- `core/services/monitoring/resource_monitor.py`
  - `ResourceMonitor.get_status()`：采集 CPU/内存/GPU/磁盘等信息
  - `ResourceStatus.is_healthy`：健康判定
  - `ResourceStatus.severities`：资源严重度（已对齐 `core.contracts.ResourceSeverity`）
  - `ResourceMonitor.to_contract_dict()`：输出稳定的 JSON schema（供 `/health` 聚合使用）

## 与 ResourceManager 的关系

项目里存在两类“资源相关模块”，职责不同：

- `core/services/monitoring/resource_monitor.py`：
  - 偏“系统级监控与降级”，提供 `to_contract_dict()` 给监控端点使用
- `core/resource_manager.py`：
  - 偏“模型级资源调度与回收”，维护 `ModelResource` 注册表，输出 `get_resource_stats()["snapshot"]`

建议：
- API 层（如 `/health`）聚合两者，以获得“系统资源视角 + 模型/显存调度视角”的完整图景。

