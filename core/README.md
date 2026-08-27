# Core Layer (核心层)

## 已删除说明（2026-06-17 死代码清理）

以下文件已于 2026-06-17 作为死代码删除，本文档不再描述其实现细节：

- `core/core_engine/engine.py` —— 已被 `ServiceLifecycle` + `EventBus` 完全覆盖，原 `CoreEngine` 类（含 `load_module` 等方法）已不存在
- `core/server/` 目录（5 个文件）—— 基于 `websockets` 库的独立 WS 服务器，从未被启动脚本调用，生产环境使用 FastAPI 的 `/api/v1/ws`
- `core/text_model_adapter.py` + `text_adapter_request_utils.py` + `text_adapter_remote_backends.py`（共 1154 行）—— 功能已被 `core/llm/` 体系完全取代
- `core/model_adapter.py` —— 模型适配旧实现，已由 `core/llm/` 与 `core/core_engine/model_manager.py` 取代
- `multimodal/image_gen.py`（216 行）—— 直接使用 `torch` 访问 GPU 绕过 C++ 调度器，违反项目规则（GPU 访问必须走 `CPPSchedulerEngine`）

## 概述

核心层是Xiaoyou-Core系统的核心功能层，包含核心引擎、模块层、服务层、工具层等多个子层。该层负责AI能力封装、业务逻辑编排、资源管理等核心功能。

## 状态契约（避免漂移）

为了避免资源状态/模型状态/服务健康/任务状态在不同模块中重复定义导致字段漂移，项目新增：

- `core/contracts/`：跨模块统一契约（状态枚举/稳定 schema）

对外输出（API/WS/监控面板）建议优先使用契约中的枚举值。

## 目录结构

```
core/
├── api/                       # API契约层（contract.py 统一响应封装, error_response.py ErrorCode 枚举）
│   ├── contract.py            # API契约定义
│   └── error_response.py      # 错误响应格式
├── config/                    # 配置管理
│   └── task_scheduler_config.py # 任务调度配置
├── core_engine/               # 核心引擎层（engine.py 已删除，职责由 EventBus/LifecycleManager/ModelManager/ConfigManager 承担）
│   ├── event_bus.py           # 事件总线
│   ├── lifecycle_manager.py   # 生命周期管理
│   ├── model_manager.py       # 模型管理器
│   └── config_manager.py      # 配置管理器
├── emotion/                   # 情绪系统
│   ├── calculator.py          # 情绪计算
│   ├── detector.py            # 情绪检测
│   ├── manager.py             # 情绪管理
│   ├── models.py              # 情绪模型
│   ├── responder.py           # 情绪响应
│   └── store.py               # 情绪存储
├── env/                       # 虚拟环境间通信（env_communication_manager, websocket_client）
│   ├── env_communication_manager.py # 环境通信管理
│   └── websocket_client.py    # WebSocket客户端
├── food/                      # 食物系统
│   ├── data.py                # 食物数据
│   ├── manager.py             # 食物管理
│   └── models.py              # 食物模型
├── hardware/                  # 硬件适配
│   └── npu_adapter.py         # NPU适配器
├── image/                     # 图像处理
│   ├── image_manager.py       # 图像管理器
│   ├── image_service_client.py # 图像服务客户端
│   ├── image_utils.py         # 图像工具
│   ├── model_loader.py        # 模型加载器
│   ├── prompt_processor.py    # 提示词处理
│   └── siliconflow_image_client.py # SiliconFlow客户端
├── interfaces/                # 接口层
│   └── websocket/             # WebSocket接口
│       ├── adapters/          # 适配器
│       │   ├── adapter.py
│       │   ├── handlers.py
│       │   ├── streaming.py
│       │   └── utils.py
│       ├── fastapi_websocket_adapter.py
│       └── websocket_manager.py
├── lifecycle/                 # 应用生命周期（lifespan.py FastAPI lifespan + Windows 控制台关闭处理）
│   └── lifespan.py            # 生命周期管理
├── llm/                       # LLM客户端
│   ├── dashscope_client.py    # 通义千问客户端
│   ├── infer_service_client.py # 推理服务客户端
│   ├── openai_client.py       # OpenAI客户端
│   └── siliconflow_client.py  # SiliconFlow客户端
├── managers/                  # 业务管理器（notification_manager, preference_manager, session_manager）
│   ├── notification_manager.py # 通知管理
│   ├── preference_manager.py  # 偏好管理
│   └── session_manager.py     # 会话管理
├── modules/                   # 模块层
│   ├── llm/                   # LLM模块
│   ├── vision/                # 视觉模块
│   ├── memory/                # 记忆模块
│   ├── voice/                 # 语音模块
│   └── image/                 # 图像模块
├── services/                  # 服务层
│   ├── aveline/               # Aveline对话服务
│   ├── active_care/           # 主动关怀服务
│   ├── workspace/             # 工作空间服务
│   ├── scheduler/             # 调度服务
│   ├── journal/               # 日记服务
│   ├── daily/                 # 每日数据服务
│   ├── immune/                # 免疫系统服务
│   ├── monitoring/            # 监控服务
│   ├── life_simulation/       # 生命模拟服务（门面+协调器架构）
│   │   ├── service.py         # LifeSimulationService 门面（API兼容层）
│   │   ├── orchestrator.py    # LifeOrchestrator 总协调器
│   │   └── coordinators/      # 六大专职协调器
│   │       ├── hardware_coordinator.py
│   │       ├── actor_coordinator.py
│   │       ├── food_coordinator.py
│   │       ├── sleep_coordinator.py
│   │       ├── reaction_coordinator.py
│   │       └── websocket_coordinator.py
│   ├── study/                 # 学习服务
│   └── ...                    # 其他服务
├── tools/                     # 工具层
│   ├── study/                 # 学习工具
│   ├── base.py                # 工具基类
│   ├── implementations.py     # 工具实现
│   └── registry.py            # 工具注册
├── utils/                     # 工具函数
│   ├── logger.py              # 日志工具
│   ├── error_handler.py       # 错误处理
│   ├── performance_tracker.py # 性能追踪
│   └── ...                    # 其他工具
├── voice/                     # 语音处理
│   ├── tts_engine.py          # TTS引擎
│   ├── stt_engine.py          # STT引擎
│   └── qwen3_tts_cloud.py     # 云端TTS
├── async_cache.py             # 异步缓存
├── async_monitor.py           # 异步监控
├── exceptions.py              # 异常定义
├── log_config.py              # 日志配置
├── model_manifest.py          # 模型清单
├── model_registry.py          # 模型注册
├── resource/                  # 资源管理模块（重构后）
│   ├── __init__.py            # 模块入口
│   ├── config.py              # 配置管理
│   ├── monitor.py             # 资源监控+GPU缓存
│   ├── model_manager.py       # 模型生命周期管理
│   ├── cleanup.py             # 清理策略
│   ├── gpu.py                 # GPU管理
│   └── manager.py             # 主管理器
├── resource_manager.py        # 资源管理器（兼容层）
├── stt_connector.py           # STT连接器
├── trm_adapter.py             # TRM适配器
├── vector_search.py           # 向量搜索
└── vl_model_adapter.py        # 视觉语言模型适配器
```

## 架构层次

```
┌─────────────────────────────────────────────────────────────┐
│                      Core Layer (核心层)                     │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │          核心引擎层 (engine.py 已删除)               │   │
│  │  EventBus │ LifecycleManager │ ModelManager         │   │
│  │  ConfigManager │ ServiceRegistry │ ServiceSingletons│   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                Modules (模块层)                      │   │
│  │  LLM │ Vision │ Memory │ Voice │ Image              │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                Services (服务层)                     │   │
│  │  Aveline │ ActiveCare │ Workspace │ Scheduler ...   │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 Tools (工具层)                       │   │
│  │  Study │ Daily │ Diary │ Reminder │ Status          │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Resource Manager (资源管理)             │   │
│  │  GPU/CPU切换 │ 模型加载/卸载 │ 优先级管理            │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. 核心引擎层（engine.py 已删除）

**说明**: `core/core_engine/engine.py` 已于 2026-06-17 作为死代码删除，原 `CoreEngine` 类（含 `load_module` 等方法）已不存在。

当前核心引擎层职责由以下组件承担：

- **EventBus**（`core/core_engine/event_bus.py`）：事件总线，模块间通信
- **LifecycleManager**（`core/core_engine/lifecycle_manager.py`）：生命周期管理，编排服务初始化与关闭
- **ModelManager**（`core/core_engine/model_manager.py`）：模型管理器，模型加载/卸载
- **ConfigManager**（`core/core_engine/config_manager.py`）：配置管理器
- **ServiceRegistry / ServiceSingletons**：服务注册与单例管理，由 `core/lifecycle/lifespan.py` 统一编排

### 2. Resource Manager (资源管理器)

**目录**: `core/resource/`（主模块）, `core/resource_manager.py`（兼容层）

资源管理器负责GPU/CPU资源调度：
- 模型优先级管理
- GPU显存监控（带缓存优化）
- 自动卸载低优先级模型
- 资源压力检测
- 清理策略管理（紧急/临界/常规）

#### 模块结构
- `config.py` — 配置管理（ResourceConfig数据类）
- `monitor.py` — 资源监控 + GPU缓存（0.5秒TTL）
- `model_manager.py` — 模型生命周期管理
- `cleanup.py` — 清理策略（策略模式）
- `gpu.py` — GPU显存管理和模型卸载/加载
- `manager.py` — 主管理器，整合所有子模块

### 3. Event Bus (事件总线)

**文件**: `core/core_engine/event_bus.py`

事件总线提供模块间通信：
- 发布/订阅模式
- 异步事件处理
- 事件类型定义

### 4. 模块层

#### LLMModule

**文件**: `core/modules/llm/module.py`

大语言模型模块，支持：
- GGUF模式（llama-cpp-python）
- Transformers模式（HuggingFace）
- 云端API（通义千问、DeepSeek、SiliconFlow）
- 流式生成
- GPU/CPU切换

#### VisionModule

**文件**: `core/modules/vision/module.py`

视觉模块，支持：
- Qwen-VL/Qwen2-VL
- SiliconFlow云端
- 图像描述
- 多轮对话

#### MemoryModule

**文件**: `core/modules/memory/module.py`

记忆模块，支持：
- L1/L2缓存
- 文件存储
- 向量检索
- 权重记忆

### 5. 服务层

#### Aveline Service

**文件**: `core/services/aveline/service.py`

对话主编排服务：
- 对话流程控制
- 工具调用
- 记忆整合
- 流式响应

#### Active Care Service

**文件**: `core/services/active_care/service.py`

主动关怀服务：
- 主动关怀决策
- 消息推送
- 日记记录
- 提醒管理

#### Scheduler Service

**文件**: `core/services/scheduler/task_scheduler.py`

任务调度服务：
- C++调度引擎集成
- GPU/CPU任务分发
- 优先级队列
- 资源管理

#### Workspace Service

**文件**: `core/services/workspace/service.py`

工作空间服务：
- 状态管理
- 提醒管理
- 日记聚合
- 学习数据同步

### 6. 工具层

#### Study Tools

**文件**: `core/tools/study/`

学习工具集：
- 数学工具（图像生成、题目生成）
- 英语工具（词汇测试）
- 生物工具（3D可视化）
- 地理工具（3D可视化）
- 语文工具（作文素材、诗词测验）

#### Daily Tool

**文件**: `core/tools/daily_tool.py`

每日数据工具：
- 数据聚合
- 统计分析
- 报告生成

## 关键联动链路

### 1. 对话主链路

```
routers/api_v1/chat
    → core/services/aveline/service.py
    → core/services/scheduler/* (LLM任务)
    → 记忆写入
    → WebSocket/HTTP返回
```

### 2. 主动关怀链路

```
core/services/active_care/proactive_checker.py
    → 读取 workspace snapshot + life_simulation + emotion
    → core/services/active_care/decision.py
    → core/services/active_care/executor.py
    → WebSocket推送
    → workspace/journal记录
```

### 3. 记录落盘链路

```
core/services/workspace/service.py
    → core/services/journal/storage.py (日记)
    → core/services/daily/manager.py (画像)
    → status_manager.py (状态)
    → 本地JSON存储
```

### 4. 稳定性保护链路

```
core/services/monitoring/*
    → 运行时错误回调
    → core/services/immune/service.py
    → 生命周期重启与降级保护
```

## 设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| 单例模式 | ResourceManager, ServiceSingletons | 确保全局唯一实例 |
| 策略模式 | LLMModule, VisionModule | 多模式/多后端切换 |
| 工厂模式 | TTSEngine, STTEngine | 多引擎创建 |
| 观察者模式 | EventBus | 事件发布/订阅 |
| 门面模式 | WorkspaceService | 统一入口 |

## 启动流程

系统启动由 FastAPI lifespan 编排，链路如下：

```
main.py
    → core/lifecycle/lifespan.py (FastAPI lifespan)
    → lifecycle_manager.initialize_default_services()
    → lifecycle_manager.initialize_all()
```

- `lifespan.py` 负责挂载 FastAPI lifespan 与 Windows 控制台关闭处理
- `initialize_default_services()` 注册默认服务到 `ServiceRegistry`
- `initialize_all()` 完成所有服务的异步初始化，失败时通过免疫系统降级

## 扩展指南

### 添加新模块

1. 创建模块文件 `core/modules/new_module/module.py`
2. 实现模块接口：

```python
class NewModule:
    def __init__(self, config=None):
        self.config = config or {}
    
    async def initialize(self):
        pass
    
    async def shutdown(self):
        pass
```

3. 在生命周期中注册（`engine.py` 已删除，统一走 lifespan 编排）：

```python
# core/lifecycle/lifespan.py
from core.modules.new_module.module import NewModule

new_module = NewModule()
await new_module.initialize()
# 如需纳入 ServiceRegistry，调用 lifecycle_manager.register_service(...)
```

### 添加新服务

1. 创建服务目录 `core/services/new_service/`
2. 实现服务类：

```python
class NewService:
    async def initialize(self):
        pass
    
    async def shutdown(self):
        pass
```

3. 在生命周期中注册：

```python
# core/lifecycle/lifespan.py
from core.services.new_service.service import NewService

new_service = NewService()
await new_service.initialize()
```

### 添加新工具

1. 创建工具文件 `core/tools/new_tool.py`
2. 继承工具基类：

```python
from core.tools.base import BaseTool

class NewTool(BaseTool):
    name = "new_tool"
    description = "新工具描述"
    
    async def execute(self, **kwargs):
        # 工具逻辑
        return result
```

3. 在工具注册表中注册：

```python
# core/tools/registry.py
from core.tools.new_tool import NewTool

register_tool(NewTool())
```

## 相关文档

- [系统架构文档](../PROJECT_TECHNICAL_REFERENCE.md)
- [核心引擎文档](./core_engine/README.md)
- [模块层文档](./modules/README.md)
- [服务层文档](./services/README.md)
- [工具与辅助系统文档](./工具与辅助系统README.md)
- [资源管理层文档](./资源管理层README.md)

---

最后更新：2026-07-11
