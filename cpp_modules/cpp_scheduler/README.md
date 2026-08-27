# cpp_scheduler：资源隔离调度器

## 概述

`cpp_scheduler` 是一个面向本地多模态负载的单机资源隔离调度器，目标是把 LLM/TTS/图像三类任务拆到不同执行域中，降低资源互抢导致的卡顿。

```
┌──────────────────┐
│  ResourceIsolation │
│     Scheduler      │
└───────┬──────────┘
        │
        ├── GPU LLM Worker  ──► LLM 推理（高优先级、独占管线）
        │
        ├── CPU TTS Worker  ──► TTS 合成（CPU 侧）
        │
        └── GPU Image Worker ─► 图像生成（独立队列/异步线程）
```

当前仓库内的 LLM/TTS/图像后端以 Mock 为主，用于验证调度与隔离策略；`APIServer` 属于 Mock 形态（只注册路由与构造响应体，不做真实 HTTP 监听）。

## 核心机制（按代码实现）

- 三队列隔离：LLM 与 TTS 走主队列，图像生成走独立队列与线程，互不阻塞。
- LLM 专用 Worker：首个 LLM Worker 被固定为专用执行器，避免与图像任务互相抢 GPU。
- 任务生命周期：PENDING/RUNNING/COMPLETED/FAILED/CANCELLED 全流程状态管理，完成任务保留在任务表以便结果读取。
- 取消策略：对 PENDING/RUNNING 任务标记取消并从任务表移除，属于软取消。
- 生物系统驱动：默认启用 NativeExecutor 的定时器，每 100ms 刷新生物系统并计数。
- LLM Worker 内部队列：LLM Worker 自带队列与执行线程，避免调度器阻塞模型推理。

## 主要模块

- 调度器：`core/resource_isolation_scheduler.*`
- Worker：`workers/gpu_llm_worker.*`、`workers/cpu_tts_worker.*`（图像生成已迁移至 Python 侧）
- Llama 推理实现按职责拆分：
  - `workers/llama_model_impl.cpp` — tokenization 与生成循环
  - `workers/llama_model_cache.cpp` — 会话 sequence、KV Cache 与 KV Swap
  - `workers/llama_model_lifecycle.cpp` — 模型/context 初始化、关闭与状态
  - `workers/llama_model_runtime.cpp` — decode 超时、batch、采样与 UTF-8 辅助
- NativeExecutor：`core/native_executor.*`
- 仿生系统：`core/biological_system.*`
- API（Mock）：`api/api_server.*`、`api/api_client.*`
- Python 绑定：`bindings/python_bindings.cpp`（模块名：`scheduler_py`）

## 仿生系统 (Biological System) 详解

本系统通过模拟人类的神经递质和昼夜节律，为 AI Agent 引入了动态的“性格”与“认知状态”。这些数据不仅是展示用的数值，还会直接影响任务调度的响应延迟。

### 1. 核心指标计算逻辑

- **神经递质 (Neurotransmitters)**：
    - **多巴胺 (Dopamine)**：驱动好奇心与动力。
    - **血清素 (Serotonin)**：维持情绪稳定。
    - **去甲腺上腺素 (Norepinephrine)**：决定警觉度与压力响应。
    - **催产素 (Oxytocin)**：模拟社交纽带与信任感。
    - **皮质醇 (Cortisol)**：表征长期压力与威胁感。
    - **计算公式**：采用自然衰减模型 `val += (baseline - val) * decay_rate * deltaTime`。所有递质随时间推移自动向基准值（Baseline）靠拢。

- **生理状态 (Physiological State)**：
    - **能量 (Energy)**：清醒时按 `energy_awake_decay` 消耗，睡眠时通过 `energy_sleep_recover` 恢复。
    - **睡眠债 (Sleep Debt)**：长时间不进入睡眠状态会累积睡眠债，影响认知效率。
    - **昼夜节律 (Circadian Rhythm)**：根据系统时间自动切换：
        - `07:00 - 09:00`：苏醒 (WAKE)
        - `09:00 - 21:00`：活跃 (ACTIVE)
        - `21:00 - 23:00`：疲劳 (TIRED)
        - `23:00 - 07:00`：睡眠 (SLEEP)

### 2. 认知延迟 (Cognitive Latency) 计算模型

这是仿生系统最核心的输出，用于模拟 AI 在不同情绪/生理状态下的“思考时间”：

```cpp
// 核心公式
TotalDelay = (BaseDelay + ComplexityDelay) * EnergyFactor * DopamineFactor * SerotoninFactor * CortisolFactor * SleepDebtFactor
```

- **基础延迟 (BaseDelay)**：0.5s。
- **复杂度影响 (ComplexityDelay)**：`任务复杂度 * 2.0s`。
- **因子修正 (Factors)**：
    - **能量因子**：`1.0 + (1.0 - energy) * 2.0`（能量越低，思考越慢）。
    - **多巴胺因子**：`1.0 - (dopamine - baseline) * 0.5`（多巴胺高时，响应更敏捷）。
    - **皮质醇因子**：`1.0 + (cortisol - baseline) * 0.8`（压力过大导致犹豫和延迟）。
    - **睡眠债因子**：`1.0 + sleep_debt * 1.0`（疲劳会导致反应迟钝）。

通过该模型，小友在深夜或低能量状态下的回复速度会自然变慢，从而在交互层面体现出“生命感”。

- `ResourceUsage` 目前返回占位值，未接入真实采样。
- 调度器未对 TaskPriority 做队列级排序，优先级主要体现在 LLM 队列的优先处理逻辑。
- Mock 后端为主，真实推理依赖 `llama_model_impl` 与实际模型配置。
- API Server 为 Mock，不提供真实 HTTP 服务。

## 状态输出一致性（与 Python 侧对齐）

为避免状态字符串在不同模块漂移，C++ Scheduler 的 API 输出已与 Python 侧契约对齐：

- `/health.status`: `healthy` / `degraded`
- `/task/{id}.status`: `pending` / `running` / `completed` / `failed` / `cancelled`

不再使用 `queued/processing` 等非标准状态字符串。

## 构建

### 依赖说明（以当前实现为准）

- CMake 会自动拉取 `libuv`、`pybind11`、`llama.cpp` 源码（需要联网）。
- `cpp_scheduler/CMakeLists.txt` 当前通过导入库方式链接 `llama_cpp` 的预编译 `llama.dll/.lib`，路径为固定值；若环境不同需调整 `IMPORTED_LOCATION/IMPORTED_IMPLIB`。

### Windows（Visual Studio）

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
```

#### CUDA / CPU 双版本共存

默认 `cmake` 构建的是纯 CPU 版（`build/Release`）。需要 GPU 加速时，推荐直接用项目根目录下的一键脚本（它会自动用 `subst` 映射无空格盘符规避 nvcc 对含空格路径的兼容性问题，并复用本地 `libuv-1.x` 与 `external/llama.cpp-master`，输出到独立的 `build/cuda/Release`，不影响 CPU 版）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/cpp_scheduler/build_cuda.ps1
```

运行时可切换后端（`scheduler_wrapper` 按此环境变量选版本）：

```powershell
$env:XIAOYOU_CPP_BACKEND="cuda"   # GPU 推理
$env:XIAOYOU_CPP_BACKEND="cpu"    # CPU 推理
# 不设置 = auto：存在 CUDA 版则优先 CUDA，否则 CPU
```

### Linux（单配置生成器）

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

构建产物：

- 可执行文件：`ai_scheduler`
- Python 扩展：`scheduler_py`（Windows 通常为 `.pyd`，Linux 为 `.so`）

## 运行

```powershell
.\build\Release\ai_scheduler.exe
```

程序会初始化调度器与三个 worker，并启动一个 Mock API Server 线程（端口参数仅用于日志展示）。

## 文档

- 部署与构建：`docs/DEPLOYMENT_GUIDE.md`
- API 说明（Mock 路由与入参解析规则）：`docs/api_reference.md`
- 架构与实现现状：`docs/architecture_and_deployment.md`

## 目录结构

```
cpp_scheduler/
├── api/          # Mock API（路由表/请求体解析/响应拼装）
├── bindings/     # pybind11 绑定（scheduler_py）
├── config/       # 配置抽象（当前主程序未接入配置文件）
├── core/         # 调度器与生物系统
├── monitoring/   # 监控（基础骨架）
├── optimization/ # 优化（基础骨架）
├── queue/        # 队列实现
├── tests/        # 集成测试（可选构建）
├── workers/      # LLM/TTS worker（当前以 Mock 后端为主；图像生成已迁移至 Python 侧）
├── CMakeLists.txt
└── main.cpp      # 演示入口
```
