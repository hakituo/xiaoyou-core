# Core Engine Layer (核心引擎层)

> ## 已删除说明
>
> `core/core_engine/engine.py`（即 `CoreEngine` 类，含 `get_core_engine`、`load_module`、`unload_module`、`shutdown` 等方法）已于 **2026-06-17** 作为死代码删除。
>
> - 该文件头部明确标注："已废弃，已被 ServiceLifecycle + EventBus 完全覆盖"。
> - 全项目搜索确认生产代码无任何 `import` 引用。
> - 其职责已由 `LifecycleManager`（生命周期）、`EventBus`（事件通信）、`ServiceRegistry` / `ServiceSingletons` / `ServiceHelpers`（服务注册与单例管理）共同承接。
>
> 本文档不再描述 `CoreEngine` 相关内容。

## 概述

核心引擎层是Xiaoyou-Core系统的核心基础设施，负责系统的生命周期管理、服务注册、事件通信和配置管理。该层采用单例模式和事件驱动架构，为整个系统提供稳定、高效的基础服务。

## 状态契约（重要）

为了避免“资源状态/模型状态/服务健康/任务状态”在多个模块中各自表达导致长期漂移，项目新增了统一契约目录：

- `core/contracts/`
- 统一枚举定义：`core/contracts/states.py`

建议新代码统一从 `core.contracts` 引用状态枚举（例如 `TaskStatus`/`HealthStatus`/`ResourceSeverity`），避免自由字符串或重复定义。

## 核心组件

### EventBus (事件总线)

**文件**: `core/core_engine/event_bus.py`

事件总线实现了发布-订阅模式，用于模块间的异步通信和解耦。

**主要功能**:
- 异步事件发布/订阅
- 优先级订阅（数字越小优先级越高）
- 事件过滤器
- 异常隔离
- 预定义事件类型

**预定义事件类型**:
```python
class EventTypes:
    # 系统事件
    SYSTEM_START = "system.start"
    SYSTEM_SHUTDOWN = "system.shutdown"
    
    # 对话事件
    CHAT_START = "chat.start"
    MESSAGE_SEND = "message.send"
    
    # 任务事件
    TASK_SCHEDULE = "task.schedule"
    TASK_COMPLETE = "task.complete"
    
    # LLM事件
    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"
    
    # 内存事件
    MEMORY_ADD = "memory.add"
    MEMORY_RETRIEVE = "memory.retrieve"
```

**使用示例**:
```python
from core.core_engine.event_bus import get_event_bus, EventTypes

# 获取事件总线
event_bus = get_event_bus()

# 订阅事件
async def handle_message(data):
    print(f"收到消息: {data}")

await event_bus.subscribe(
    EventTypes.MESSAGE_SEND,
    handle_message,
    priority=0
)

# 发布事件
await event_bus.publish(
    EventTypes.MESSAGE_SEND,
    {"content": "Hello, World!"}
)
```

---

### LifecycleManager (生命周期管理器)

**文件**: `core/core_engine/lifecycle_manager.py`

生命周期管理器负责统一管理所有异步服务的初始化和关闭。

**主要功能**:
- 服务优先级管理（数字越小优先级越高）
- 分批关闭（先关闭高内存服务）
- 超时控制
- 健康检查
- 服务重启支持

**服务优先级示例**:
```python
# 高优先级服务（优先启动，最后关闭）
Resource Manager (Priority: 3)
Config Manager (Priority: 6)

# 中优先级服务
C++ Scheduler Engine (Priority: 9)
Task Scheduler (Priority: 11)

# 低优先级服务（最后启动，优先关闭）
WebSocket Adapter (Priority: 20)
Aveline Service (Priority: 30)
```

**使用示例**:
```python
from core.core_engine.lifecycle_manager import get_lifecycle_manager

# 获取生命周期管理器
lifecycle = get_lifecycle_manager()

# 初始化所有服务
await lifecycle.initialize_all()

# 关闭所有服务
await lifecycle.shutdown_all()

# 重启特定服务
await lifecycle.restart_service("aveline_service")
```

---

### ConfigManager (配置管理器)

**文件**: `core/core_engine/config_manager.py`

配置管理器负责加载、管理和验证系统配置。

**主要功能**:
- 配置文件加载
- 配置热更新
- 配置验证
- 多环境支持

**使用示例**:
```python
from core.core_engine.config_manager import get_config_manager

# 获取配置管理器
config = get_config_manager()

# 获取配置
llm_model = config.get("model.llm.model")
image_width = config.get("model.image_gen_width")

# 监听配置变更
async def on_config_change(key, old_value, new_value):
    print(f"配置变更: {key} = {old_value} -> {new_value}")

config.add_change_listener(on_config_change)
```

---

### ModelManager (模型管理器)

**文件**: `core/core_engine/model_manager.py`

模型管理器负责集中管理所有模型的加载、卸载和检测。

**主要功能**:
- 本地模型扫描（LLM、图像、LORA）
- 云端模型注册（通义千问、DeepSeek、Aveline）
- 量化检测
- 设备管理
- 系统资源检测

**使用示例**:
```python
from core.core_engine.model_manager import get_model_manager

# 获取模型管理器
model_manager = get_model_manager()

# 扫描本地模型
local_models = model_manager.scan_local_models()

# 注册云端模型
model_manager.register_cloud_model(
    model_id="deepseek-chat",
    provider="deepseek",
    model_name="deepseek-chat"
)

# 检测系统资源
resources = model_manager.detect_system_resources()
print(f"GPU内存: {resources['gpu_memory_mb']} MB")
print(f"CPU核心数: {resources['cpu_cores']}")
```

---

### ServiceRegistry (服务注册中心)

**文件**: `core/core_engine/service_registry.py`

服务注册中心统一管理所有服务的注册、查询与生命周期元数据，是 `LifecycleManager` 与业务层之间的桥梁。

**主要功能**:
- 服务注册与注销
- 按名称/类型查询服务实例
- 维护服务元数据（优先级、状态、依赖等）
- 提供服务列表快照，便于健康检查与诊断

**使用示例**:
```python
from core.core_engine.service_registry import get_service_registry

registry = get_service_registry()

# 注册服务
registry.register("aveline_service", instance, priority=30)

# 按名称查询
service = registry.get("aveline_service")
```

---

### ServiceSingletons (业务单例管理)

**文件**: `core/core_engine/service_singletons.py`

业务单例管理器集中持有跨模块共享的核心业务单例，避免单例在多处分散初始化导致的状态漂移。

**主要功能**:
- 统一持有核心业务单例（如 LLM、记忆、调度器等）
- 提供全局访问入口，避免重复实例化
- 与 `LifecycleManager` 协同，确保单例在生命周期内可用
- 单例懒加载与显式释放

**使用示例**:
```python
from core.core_engine.service_singletons import get_singletons

singletons = get_singletons()
llm = singletons.llm
memory = singletons.memory
```

---

### ServiceHelpers (生命周期辅助工具)

**文件**: `core/core_engine/service_helpers.py`

生命周期辅助工具为 `LifecycleManager` 与业务层提供通用的服务初始化、关闭、依赖编排等辅助函数。

**主要功能**:
- 封装常见服务的初始化/关闭样板代码
- 提供依赖顺序编排工具
- 协助 `initialize_default_services()` 构建默认服务集合
- 减少业务层与生命周期管理器之间的重复代码

**使用示例**:
```python
from core.core_engine.service_helpers import initialize_default_services

# 初始化默认服务集合（由 lifespan 调用）
await initialize_default_services()
```

---

## 架构设计

### 设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| 单例模式 | EventBus, ModelManager, ConfigManager, ServiceRegistry, ServiceSingletons | 确保全局唯一实例 |
| 发布-订阅模式 | EventBus | 模块间解耦通信 |
| 生命周期模式 | LifecycleManager, ServiceHelpers | 服务生命周期管理 |
| 注册表模式 | ServiceRegistry | 服务统一注册与查询 |

### 架构原则

- **单一职责原则**: 每个组件职责明确
- **开闭原则**: 易于扩展新模块
- **依赖倒置原则**: 通过事件总线实现松耦合
- **接口隔离原则**: 接口定义清晰

---

## 系统启动流程

```
1. main.py
   ↓
2. core/lifecycle/lifespan.py
   ↓
3. lifecycle_manager.initialize_default_services()
   - 通过 ServiceHelpers 构建默认服务集合
   - 经 ServiceRegistry 注册服务元数据
   - 由 ServiceSingletons 持有跨模块共享单例
   ↓
4. lifecycle_manager.initialize_all()
   - 按优先级初始化服务：
     - Resource Manager (Priority: 3)
     - Config Manager (Priority: 6)
     - C++ Scheduler Engine (Priority: 9)
     - Task Scheduler (Priority: 11)
     - WebSocket Adapter (Priority: 20)
     - Aveline Service (Priority: 30)
   ↓
5. 各服务初始化：
   - ResourceManager.start() → 启动资源监控
   - EventBus.start() → 启动事件总线
   - ModelManager.scan_local_models() → 扫描本地模型
   ↓
6. 系统就绪，等待请求
```

---

## 性能特性

### 异步性能
- 全异步设计，性能优秀
- 事件发布/订阅高效
- 无明显性能瓶颈

### 内存占用
- 内存占用合理
- 服务按优先级分批初始化
- 支持服务关闭释放内存（LifecycleManager 分批关闭）

### 启动时间
- 启动速度较快
- 模型扫描可优化

---

## 扩展指南

### 添加新服务

1. **实现服务接口**:
```python
class NewService:
    def __init__(self, config=None):
        self.config = config or {}
    
    async def initialize(self):
        pass
    
    async def shutdown(self):
        pass
```

2. **注册到 ServiceRegistry / LifecycleManager**:
```python
from core.core_engine.service_registry import get_service_registry
from core.core_engine.lifecycle_manager import get_lifecycle_manager

registry = get_service_registry()
lifecycle = get_lifecycle_manager()

registry.register("new_service", NewService(), priority=15)
# 或通过 lifecycle 注册以纳入统一生命周期管理
```

3. **订阅事件**:
```python
event_bus = get_event_bus()
await event_bus.subscribe(EventTypes.NEW_EVENT, handler, priority=0)
```

---

## 常见问题

**Q: 如何添加新的服务？**  
A: 创建服务类，实现initialize()和shutdown()方法，然后在LifecycleManager中注册。

**Q: 如何监听配置变更？**  
A: 使用ConfigManager的add_change_listener()方法添加监听器。

**Q: 如何发布自定义事件？**  
A: 在EventTypes中定义新的事件类型，然后使用EventBus.publish()发布。

---

## 相关文档

- [系统架构文档](../../PROJECT_TECHNICAL_REFERENCE.md)
- [评估报告](./评估报告.md)
- [服务层文档](../services/README.md)
- [模块层文档](../modules/README.md)

---

最后更新：2026-06-18
