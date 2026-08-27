# Resource Management Layer (资源管理层)

## 概述

资源管理层是Xiaoyou-Core系统的核心资源管理基础设施，负责统一管理系统资源（内存、CPU、GPU、磁盘）。该层采用单例模式和观察者模式，实现了智能的资源监控、模型管理和自动优化。

## 核心组件

### ResourceManager (资源管理器)

**目录**: `core/resource/`（主模块）, `core/resource_manager.py`（兼容层）

资源管理器是系统的资源管理中心，负责监控、分配和优化系统资源。

#### 模块结构（2026-05-29重构）
```
core/resource/
├── __init__.py          # 模块入口，导出所有公共接口
├── config.py            # 配置管理（ResourceConfig数据类）
├── monitor.py           # 资源监控 + GPU缓存优化（0.5秒TTL）
├── model_manager.py     # 模型生命周期管理
├── cleanup.py           # 清理策略（策略模式，支持动态冷却时间）
├── gpu.py               # GPU显存管理和模型卸载/加载
└── manager.py           # 主管理器，整合所有子模块
```

**主要功能**:
- **资源监控**:
  - 实时内存/CPU/GPU监控
  - 多级阈值（警告、临界、紧急）
  - NVML和nvidia-smi双检测
  - GPU内存查询缓存（0.5秒TTL，减少nvidia-smi调用）
- **模型管理**:
  - 模型注册/卸载
  - 设备判定（GPU/CPU）
  - VRAM占用估算
  - 优先级管理
  - 并行卸载/加载
- **自动优化**:
  - 三级清理模式（常规、临界、紧急）
  - 模型超时卸载
  - 缓存清理
  - GPU模型自动回迁
- **资源处理器**:
  - 注册资源处理器
  - 按优先级释放资源
- **重负载任务准备**:
  - 为LLM/图像生成/视觉任务准备资源
  - 并行卸载冲突模型
  - 显存充足时跳过激进清理

**使用示例**:
```python
# 新导入方式（推荐）
from core.resource import ResourceManager, get_resource_manager
from core.resource_components import ResourcePriority

# 旧导入方式（仍然兼容）
from core.resource_manager import get_resource_manager, ResourcePriority

# 获取资源管理器
rm = get_resource_manager()

# 注册模型
rm.register_model(
    model_id="llm_model",
    model_type="llm",
    priority=ResourcePriority.HIGH,
    load_func=load_llm_model,
    unload_func=unload_llm_model,
    instance=llm_instance
)

# 准备重负载任务
await rm.prepare_for_heavy_task(task_type="llm")

# 获取系统资源
resources = rm.get_resource_stats()
print(f"GPU显存: {resources['gpu_memory_used_mb']} MB")
print(f"CPU使用率: {resources['cpu_usage_percent']}%")

# 手动触发清理
await rm.optimize_resources()
```

---

## 弹性资源管理（Elastic Recycling）

### 核心思想

根据任务类型和资源压力，动态调整模型运行设备。

### 实现机制

#### 1. GPU/CPU热切换

```python
# GPU/CPU热切换
async def switch_device(self, model_id: str, target_device: str):
    if target_device == "cpu":
        await self._try_offload_model_to_cpu(model_id)
    else:
        await self._try_load_model_to_gpu(model_id)
```

#### 2. 资源压力感知

```python
# 多级阈值
class ResourceThreshold:
    WARNING = 70   # 警告阈值
    CRITICAL = 85  # 临界阈值
    EMERGENCY = 95 # 紧急阈值
```

#### 3. 智能清理策略

```python
# 三级清理模式
async def cleanup_resources(self, level: str):
    if level == "normal":
        # 常规清理：PyTorch缓存清理
        torch.cuda.empty_cache()
        
    elif level == "critical":
        # 临界清理：卸载中等优先级模型
        await self._unload_medium_priority_models()
        
    elif level == "emergency":
        # 紧急清理：卸载所有非高优先级模型
        await self._unload_all_non_critical_models()
```

#### 4. 模型自动回迁

```python
# 显存充足时自动回迁
async def _auto_recover_gpu_models(self):
    gpu_free_mb = await self._get_gpu_free_mb_async()
    if gpu_free_mb > self._gpu_recovery_threshold:
        await self._recover_cpu_models_to_gpu()
```

---

## 资源监控

### 实时监控

资源管理器实时监控以下资源：

```python
class SystemResources:
    # 内存
    memory_total_mb: int
    memory_used_mb: int
    memory_percent: float
    
    # CPU
    cpu_percent: float
    cpu_cores: int
    
    # GPU
    gpu_memory_total_mb: int
    gpu_memory_used_mb: int
    gpu_memory_free_mb: int
    gpu_utilization: float
    gpu_temperature: float
```

### 多级阈值

```python
class ResourceThreshold:
    WARNING = 70   # 警告阈值
    CRITICAL = 85  # 临界阈值
    EMERGENCY = 95 # 紧急阈值
```

---

## 模型管理

### 模型注册

```python
rm.register_model(
    model_id="llm_model",
    model_type="llm",
    priority=ResourcePriority.HIGH,
    load_func=load_llm_model,
    unload_func=unload_llm_model,
    instance=llm_instance,
    vram_mb=8000  # 预估VRAM占用
)
```

### 模型优先级

```python
class ResourcePriority:
    CRITICAL = 0  # 关键模型（如LLM）
    HIGH = 1      # 高优先级（如Vision）
    MEDIUM = 2    # 中优先级（如TTS）
    LOW = 3       # 低优先级（如Image）
```

### 设备判定

```python
# 自动判定设备
device = rm.detect_device(model_id)
# 返回: "gpu" 或 "cpu"
```

---

## 自动优化

### 三级清理模式

#### 1. 常规清理（Normal）
- PyTorch缓存清理
- Python垃圾回收
- 轻量级内存优化

#### 2. 临界清理（Critical）
- 卸载中等优先级模型
- 清理所有缓存
- 激进的内存优化

#### 3. 紧急清理（Emergency）
- 卸载所有非高优先级模型
- 强制垃圾回收
- 最大程度的资源释放

### 模型超时卸载

```python
# 模型超时自动卸载
async def _check_model_timeout(self):
    for model_id, info in self._models.items():
        if time.time() - info['last_used'] > info['timeout']:
            await self._unload_model(model_id)
```

### GPU模型自动回迁

```python
# 显存充足时自动回迁
async def _auto_recover_gpu_models(self):
    gpu_free_mb = await self._get_gpu_free_mb_async()
    if gpu_free_mb > self._gpu_recovery_threshold:
        await self._recover_cpu_models_to_gpu()
```

---

## 重负载任务准备

### 任务类型

```python
class HeavyTaskType:
    LLM = "llm"              # LLM推理任务
    IMAGE_GEN = "image_gen"    # 图像生成任务
    VISION = "vision"        # 视觉理解任务
```

### 准备流程

```python
async def prepare_for_heavy_task(self, task_type: str = "llm"):
    # 1. 检查显存是否充足
    gpu_free_mb = await self._get_gpu_free_mb_async()
    
    # 2. 确定冲突模型
    conflicts = self._get_conflicting_models(task_type)
    
    # 3. 并行卸载冲突模型
    offload_tasks = [self._try_offload_model_to_cpu(mid) for mid in conflicts]
    await asyncio.gather(*offload_tasks)
    
    # 4. 清理缓存
    torch.cuda.empty_cache()
```

---

## 资源处理器

### 注册处理器

```python
# 注册资源处理器
rm.register_resource_handler(
    handler_id="my_handler",
    handler=my_resource_handler,
    priority=ResourcePriority.MEDIUM
)

# 处理器接口
async def my_resource_handler(level: str):
    if level == "critical":
        # 临界处理逻辑
        pass
```

### 按优先级释放

```python
# 按优先级释放资源
await rm.release_resources_by_priority(
    min_priority=ResourcePriority.MEDIUM
)
```

---

## 架构设计

### 设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| 单例模式 | ResourceManager | 确保全局唯一实例 |
| 观察者模式 | ResourceManager | 资源处理器注册 |
| 策略模式 | 三级清理模式 | 不同清理策略 |

### 架构原则

- **单一职责原则**: 资源管理职责明确
- **开闭原则**: 易于扩展新资源类型
- **依赖倒置原则**: 通过接口实现松耦合
- **接口隔离原则**: 接口定义清晰

---

## 性能特性

### 资源监控性能
- 实时监控高效
- NVML和nvidia-smi双检测准确
- 无明显性能开销

### 资源利用率
- GPU/CPU热切换优秀
- 资源分配智能
- 自动优化高效

### 清理效率
- 三级清理策略合理
- 并行卸载高效
- 自动回迁及时

---

## 扩展指南

### 添加新资源类型

1. **定义资源类型**:
```python
class ResourceType:
    NEW_RESOURCE = "new_resource"
```

2. **实现监控逻辑**:
```python
async def monitor_new_resource(self):
    # 监控逻辑
    pass
```

3. **注册到资源管理器**:
```python
rm.register_resource_monitor(
    ResourceType.NEW_RESOURCE,
    monitor_new_resource
)
```

---

## 常见问题

**Q: 如何调整资源阈值？**  
A: 修改ResourceThreshold类的阈值定义。

**Q: 如何手动触发清理？**  
A: 使用ResourceManager.cleanup_resources(level="critical")。

**Q: 如何查看当前资源使用情况？**  
A: 使用ResourceManager.get_system_resources()获取资源信息。

**Q: 如何禁用自动回迁？**  
A: 设置ResourceManager._auto_recovery_enabled = False。

---

## 相关文档

- [系统架构文档](../PROJECT_TECHNICAL_REFERENCE.md)
- [评估报告](./评估报告_资源管理层.md)
- [核心引擎层文档](./core_engine/README.md)
- [调度与执行层文档](./services/scheduler/README.md)
