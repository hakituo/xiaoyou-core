# Scheduler Service (调度服务)

> 最后更新：2026-06-18，反映 2026-06 调度器子目录重构

## 概述

调度服务是Xiaoyou-Core系统的任务调度核心，负责GPU/CPU任务的统一调度、资源管理、优先级队列等功能。该服务集成了C++高性能调度引擎，支持生物学状态驱动的智能调度。

## 目录结构

调度服务已从扁平结构重构为按职责分层的子目录组织，顶层仅保留主引擎与 C++ 扩展绑定层。

```
scheduler/
├── cpp_scheduler_engine.py    # CPPSchedulerEngine（单例）主引擎，协调各子模块
├── scheduler_wrapper.py       # C++ 扩展绑定层（_import_scheduler_py 查找并导入 C++ scheduler 扩展，处理 Windows DLL 搜索路径）
│
├── bio/                       # 生物系统
│   ├── bio_state.py           # build_biological_status(bio_system)：从 C++ bio_system 抽取神经递质/energy/sleep_debt/circadian_phase/cognitive_delay
│   └── bio_system_manager.py  # BioSystemManager：get_biological_system / apply_bio_before_infer
│
├── client/                    # C++ 调度器 HTTP 客户端
│   ├── cpp_client.py          # CPPSchedulerClient（httpx.AsyncClient，30s 超时）
│   └── cpp_config_builder.py  # CPPConfigBuilder：dict 配置映射到 C++ LLMModelConfig
│
├── inference/                 # 推理执行
│   ├── inference_executor.py  # InferenceExecutor：推理任务执行器（架构明确为"Python 路由层 → C++ 执行层，不存在 Python 后端降级"）
│   ├── cpp_llm_handler.py     # C++ 后端 LLM 推理路径（on_token 回调 + asyncio.Queue + call_soon_threadsafe 桥接异步流）
│   ├── python_llm_handler.py  # Python 后端 LLM 推理路径（llama_cpp，.gguf 模型热切换）
│   ├── inference_stats.py     # record_llm_inference_stats / get_last_llm_stats
│   └── inference_utils.py     # messages_to_text / clamp_messages / clamp_text / token 估算
│
├── lifecycle/                 # 调度器生命周期
│   ├── scheduler_lifecycle.py # SchedulerLifecycle：start(worker_count, gpu_config, preload_llm)
│   └── health_monitor.py      # HealthMonitor：health_check_gpu_worker
│
├── model/                     # 模型与 GPU 资源
│   ├── llm_model_manager.py   # LLMModelManager：LLM 模型生命周期管理
│   └── gpu_resource_manager.py# GPU 资源管理（_cleanup_gpu_instance 清理旧 LLM 实例）
│
├── task/                      # 任务调度
│   ├── task_scheduler.py          # GlobalTaskScheduler：统一全局任务调度器（TaskPriority/TaskType/TaskInfo，状态对齐 core.contracts.TaskStatus）
│   ├── task_scheduler_adapter.py  # TaskSchedulerAdapter：适配器，支持无缝切换到 C++ 资源隔离调度器
│   └── async_task_wrapper.py      # 异步任务包装器（扩展 TaskType：CPU/GPU/IO/TTS/STT/IMAGE/LLM）
│
├── utils/                     # 工具函数
│   ├── circuit_breaker.py     # 断路器机制（BreakerState/BreakerRegistry，指数退避）
│   ├── error_utils.py         # 错误检测与友好转换（is_oom_error / friendly_llm_error）
│   ├── kv_cache_manager.py    # KV Cache 紧急保存/恢复
│   ├── nvidia_smi_monitor.py  # nvidia-smi 显存读取（优先 pynvml，回退子进程，2 秒 TTL 缓存）
│   ├── resource_utils.py      # 资源管理公共工具（check_memory_pressure / offload_tts_services / get_cuda_free_mb）
│   └── startup_config.py      # 启动配置（resolve_llm_backend 决定 cpp/python）
│
├── README.md                  # 本文档
├── REFACTORING_NOTES.md       # 重构说明
└── 评估报告.md                 # 评估报告
```

### 顶层文件

- `cpp_scheduler_engine.py` — `CPPSchedulerEngine`（单例）主引擎，协调各子模块
- `scheduler_wrapper.py` — C++ 扩展绑定层（`_import_scheduler_py` 查找并导入 C++ scheduler 扩展，处理 Windows DLL 搜索路径）

### `bio/` 生物系统

- `bio_state.py` — `build_biological_status(bio_system)`：从 C++ bio_system 抽取神经递质/energy/sleep_debt/circadian_phase/cognitive_delay
- `bio_system_manager.py` — `BioSystemManager`：`get_biological_system` / `apply_bio_before_infer`

### `client/` C++ 调度器 HTTP 客户端

- `cpp_client.py` — `CPPSchedulerClient`（httpx.AsyncClient，30s 超时）
- `cpp_config_builder.py` — `CPPConfigBuilder`：dict 配置映射到 C++ `LLMModelConfig`

### `inference/` 推理执行

- `inference_executor.py` — `InferenceExecutor`：推理任务执行器（架构明确为"Python 路由层 → C++ 执行层，不存在 Python 后端降级"）
- `cpp_llm_handler.py` — C++ 后端 LLM 推理路径（`on_token` 回调 + `asyncio.Queue` + `call_soon_threadsafe` 桥接异步流）
- `python_llm_handler.py` — Python 后端 LLM 推理路径（`llama_cpp`，.gguf 模型热切换）
- `inference_stats.py` — `record_llm_inference_stats` / `get_last_llm_stats`
- `inference_utils.py` — `messages_to_text`/`clamp_messages`/`clamp_text`/token 估算

### `lifecycle/` 调度器生命周期

- `scheduler_lifecycle.py` — `SchedulerLifecycle`：`start(worker_count, gpu_config, preload_llm)`
- `health_monitor.py` — `HealthMonitor`：`health_check_gpu_worker`

### `model/` 模型与 GPU 资源

- `llm_model_manager.py` — `LLMModelManager`：LLM 模型生命周期管理
- `gpu_resource_manager.py` — GPU 资源管理（`_cleanup_gpu_instance` 清理旧 LLM 实例）

### `task/` 任务调度

- `task_scheduler.py` — `GlobalTaskScheduler`：统一全局任务调度器（`TaskPriority`/`TaskType`/`TaskInfo`，状态对齐 `core.contracts.TaskStatus`）
- `task_scheduler_adapter.py` — `TaskSchedulerAdapter`：适配器，支持无缝切换到 C++ 资源隔离调度器
- `async_task_wrapper.py` — 异步任务包装器（扩展 `TaskType`：CPU/GPU/IO/TTS/STT/IMAGE/LLM）

### `utils/` 工具函数

- `circuit_breaker.py` — 断路器机制（`BreakerState`/`BreakerRegistry`，指数退避）
- `error_utils.py` — 错误检测与友好转换（`is_oom_error`/`friendly_llm_error`）
- `kv_cache_manager.py` — KV Cache 紧急保存/恢复
- `nvidia_smi_monitor.py` — nvidia-smi 显存读取（优先 pynvml，回退子进程，2 秒 TTL 缓存）
- `resource_utils.py` — 资源管理公共工具（`check_memory_pressure`/`offload_tts_services`/`get_cuda_free_mb`）
- `startup_config.py` — 启动配置（`resolve_llm_backend` 决定 cpp/python）

## 核心组件

### 1. GlobalTaskScheduler (全局任务调度器)

**文件**: `task_scheduler.py`

统一全局任务调度器，管理所有后台任务：

```python
class GlobalTaskScheduler:
    def __init__(self):
        self._tasks: Dict[str, Dict] = {}
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._worker_count: int = 3
    
    async def submit_task(
        self,
        name: str,
        coro: Callable,
        priority: TaskPriority = TaskPriority.MEDIUM,
        task_type: TaskType = TaskType.DEFAULT,
    ) -> str:
        """提交任务到调度器"""
        
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        
    async def get_task_status(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务状态"""
```

**任务优先级**:
| 优先级 | 值 | 说明 |
|--------|---|------|
| LOW | 0 | 低优先级 |
| MEDIUM | 1 | 中优先级 |
| HIGH | 2 | 高优先级 |
| CRITICAL | 3 | 关键任务 |

**任务类型**:
| 类型 | 说明 |
|------|------|
| DEFAULT | 默认（IO密集型或普通异步任务） |
| CPU_BOUND | CPU密集型（使用线程池） |
| GPU_BOUND | GPU密集型（使用GPU锁） |

**任务状态（统一契约）**:

为避免 Python/C++/API 字段漂移，任务状态已统一对齐 `core/contracts/states.py::TaskStatus`：

| 状态 | 说明 |
|------|------|
| pending | 等待执行 |
| running | 正在执行 |
| completed | 执行完成 |
| failed | 执行失败 |
| cancelled | 已取消 |

> 说明：C++ Scheduler 的 HTTP API 也已同步输出 `pending/running/...`，不再使用 `queued/processing` 等非标准字符串。

### 2. CPPSchedulerEngine (C++调度引擎)

**文件**: `cpp_scheduler_engine.py`

C++高性能调度引擎的Python集成：

```python
class CPPSchedulerEngine:
    async def submit_llm_task(
        self,
        prompt: str,
        model_config: LLMModelConfig,
        priority: int = 1,
    ) -> AsyncGenerator:
        """提交LLM任务"""
        
    async def get_status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        
    async def shutdown(self):
        """关闭调度器"""
```

**特性**:
- 高性能C++调度核心
- GPU资源隔离
- 多Worker支持
- 生物学状态驱动
- C++→Python 熔断降级
- KV Cache 紧急保存/恢复
- 按会话清理 KV Cache：短期记忆重置会同步失效对应 `conversationId` 的显存 sequence、token 镜像和 KV Swap
- M-RoPE 兼容回退：llama.cpp 不支持局部 sequence 裁剪时，整条清空并从位置 0 重新 prefill
- Llama C++ 实现按推理、会话缓存、生命周期、运行时辅助拆为四个翻译单元，避免模型加载与缓存状态继续堆入生成循环文件
- 推理统计与显存监控

### 3. Biological Status (生物学状态)

**文件**: `bio_state.py`

生物学状态构建，用于驱动智能调度：

```python
def build_biological_status(bio_system: Any) -> Optional[Dict[str, Any]]:
    """构建生物学状态"""
    return {
        "neurotransmitters": {
            "dopamine": float,
            "serotonin": float,
            "norepinephrine": float,
            "oxytocin": float,
            "cortisol": float,
        },
        "energy": float,
        "sleep_debt": float,
        "circadian_phase": str,
        "cognitive_delay": float,
    }
```

**神经递质影响**:
| 神经递质 | 影响 |
|---------|------|
| dopamine | 奖励/动机，影响任务优先级 |
| serotonin | 情绪稳定，影响响应延迟 |
| norepinephrine | 注意力，影响并发度 |
| oxytocin | 社交连接，影响交互频率 |
| cortisol | 压力水平，影响资源分配 |

### 4. GPU Resource Manager (GPU资源管理器)

**文件**: `gpu_resource_manager.py`

GPU资源管理：

```python
class GPUResourceManager:
    async def acquire_gpu(self, task_id: str, memory_required: int) -> bool:
        """获取GPU资源"""
        
    async def release_gpu(self, task_id: str):
        """释放GPU资源"""
        
    def get_available_memory(self) -> int:
        """获取可用显存"""
```

### 5. LLM Model Manager (LLM模型管理器)

**文件**: `llm_model_manager.py`

LLM模型生命周期管理：

```python
class LLMModelManager:
    async def load_model(self, model_id: str, config: Dict) -> bool:
        """加载模型"""
        
    async def unload_model(self, model_id: str):
        """卸载模型"""
        
    async def get_model(self, model_id: str) -> Optional[Any]:
        """获取模型实例"""
```

## 架构设计

### 调度流程

```
┌─────────────────────────────────────────────────────────────┐
│                    Task Submission                          │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  GlobalTaskScheduler                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Priority Queue                          │   │
│  │  CRITICAL > HIGH > MEDIUM > LOW                     │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Task Type Router                        │   │
│  │  DEFAULT → Async Pool                               │   │
│  │  CPU_BOUND → Thread Pool                            │   │
│  │  GPU_BOUND → GPU Lock + C++ Engine                  │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ Async Pool  │   │ Thread Pool │   │ C++ Engine  │
│ (IO Tasks)  │   │ (CPU Tasks) │   │ (GPU Tasks) │
└─────────────┘   └─────────────┘   └─────────────┘
```

### C++调度引擎架构

```
┌─────────────────────────────────────────────────────────────┐
│                    CPPSchedulerEngine                        │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ResourceIsolationScheduler              │   │
│  │  - 任务队列管理                                      │   │
│  │  - 资源隔离                                          │   │
│  │  - 优先级调度                                        │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  GPULLMWorker                        │   │
│  │  - GPU资源管理                                       │   │
│  │  - 模型加载/卸载                                     │   │
│  │  - 推理执行                                          │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              BiologicalState                         │   │
│  │  - 神经递质状态                                      │   │
│  │  - 能量/睡眠债务                                     │   │
│  │  - 认知延迟计算                                      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 使用示例

### 提交任务

```python
from core.services.scheduler.task_scheduler import get_task_scheduler, TaskPriority, TaskType

scheduler = get_task_scheduler()

# 提交普通异步任务
task_id = await scheduler.submit_task(
    name="data_processing",
    coro=process_data(),
    priority=TaskPriority.MEDIUM,
    task_type=TaskType.DEFAULT,
)

# 提交CPU密集型任务
task_id = await scheduler.submit_task(
    name="heavy_computation",
    coro=compute_heavy(),
    priority=TaskPriority.HIGH,
    task_type=TaskType.CPU_BOUND,
)

# 提交GPU任务
task_id = await scheduler.submit_task(
    name="llm_inference",
    coro=run_llm_inference(),
    priority=TaskPriority.CRITICAL,
    task_type=TaskType.GPU_BOUND,
)
```

### 查询任务状态

```python
# 获取任务状态
status = await scheduler.get_task_status(task_id)
if status:
    print(f"Task {task_id}: {status.status}")
    if status.result:
        print(f"Result: {status.result}")
    if status.error:
        print(f"Error: {status.error}")
```

### 取消任务

```python
# 取消任务
success = await scheduler.cancel_task(task_id)
if success:
    print(f"Task {task_id} cancelled")
```

### 使用C++调度引擎

```python
from core.services.scheduler.cpp_scheduler_engine import cpp_scheduler_engine

# 提交LLM任务
async for chunk in cpp_scheduler_engine.submit_llm_task(
    prompt="你好，请介绍一下自己。",
    model_config=LLMModelConfig(
        model_path="models/qwen-7b.gguf",
        n_gpu_layers=35,
        n_ctx=4096,
    ),
    priority=2,
):
    print(chunk, end="", flush=True)

# 获取状态
status = await cpp_scheduler_engine.get_status()
print(f"Running tasks: {status['running']}")
print(f"Pending tasks: {status['pending']}")
```

## 配置

### 启动配置

**文件**: `startup_config.py`

```python
# LLM后端配置
LLM_BACKEND = "cpp"  # "cpp" | "python" | "cloud"

# Worker数量
WORKER_COUNT = 3

# GPU配置
GPU_MEMORY_FRACTION = 0.8

# 生物学配置
BIOLOGICAL_CONFIG = {
    "base_energy": 100.0,
    "sleep_debt_rate": 0.1,
    "recovery_rate": 0.05,
}
```

### 任务调度配置

**文件**: `config/task_scheduler_config.py`

```python
# 任务超时
TASK_TIMEOUT = 300  # 秒

# 最大并发任务
MAX_CONCURRENT_TASKS = 10

# 重试次数
MAX_RETRIES = 3

# 重试延迟
RETRY_DELAY = 5  # 秒
```

## 性能特性

### 吞吐量

- **GPU任务**: 支持多Worker并行
- **CPU任务**: 线程池隔离
- **IO任务**: 异步并发

### 延迟

- **首token延迟**: 生物学状态自适应
- **任务调度延迟**: 优先级队列保证
- **资源等待延迟**: GPU锁管理

### 资源利用率

- **GPU显存**: 动态分配与回收
- **CPU核心**: 线程池管理
- **内存**: 自动垃圾回收

## 错误处理

### OOM错误

```python
def _is_oom_error(msg: str) -> bool:
    lowered = (msg or "").lower()
    return any(
        k in lowered
        for k in [
            "out of memory",
            "cuda error",
            "ggml-cuda",
            "cublas",
            "vram",
            "memory allocation",
        ]
    )
```

### CUDA后端错误

```python
def _is_cuda_backend_error(msg: str) -> bool:
    lowered = (msg or "").lower()
    return any(
        k in lowered
        for k in [
            "ggml-cuda",
            "cuda error",
            "cublas",
            "hip error",
            "illegal memory access",
        ]
    )
```

## 相关文档

- [系统架构文档](../../../PROJECT_TECHNICAL_REFERENCE.md)
- [服务层文档](../README.md)
- [核心层文档](../../README.md)
- [C++调度器文档](../../../cpp_scheduler/README.md)
- [重构说明](./REFACTORING_NOTES.md)
- [评估报告](./评估报告.md)

## 重构说明

调度服务已从扁平结构重构为子目录组织，按职责清晰分层：

- **重构前**：所有 `.py` 文件平铺在 `scheduler/` 根目录下（如 `task_scheduler.py`、`bio_state.py`、`cpp_client.py`、`inference_utils.py` 等共 20+ 个文件混在一起），职责边界模糊，难以导航与维护。
- **重构后**：按职责拆分为 7 个子目录，顶层仅保留主引擎与 C++ 扩展绑定层：
  - `bio/` — 生物系统（神经递质、能量、睡眠债务等状态）
  - `client/` — C++ 调度器 HTTP 客户端与配置构建
  - `inference/` — 推理执行（C++ / Python 双后端、统计、工具）
  - `lifecycle/` — 调度器生命周期管理与健康检查
  - `model/` — LLM 模型与 GPU 资源管理
  - `task/` — 任务调度核心（调度器、适配器、异步包装器）
  - `utils/` — 通用工具（断路器、错误处理、KV Cache、显存监控、资源工具、启动配置）

此次重构未改变对外 API 与导入路径的兼容性（通过 `__init__.py` 重新导出），仅调整内部组织结构，便于后续按模块独立演进与测试。
