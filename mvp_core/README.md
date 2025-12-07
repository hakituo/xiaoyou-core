# MVP Core (最小可行性核心)

## One Page Executive Summary: 高性能异步多模态智能体架构 (xy-core)

### 一、核心架构：三层异步隔离
针对 Python 在多模态任务（如 Stable Diffusion 图像生成、VL 视觉理解、TTS 语音合成）中常见的 GIL 锁阻塞问题，xy-core 设计了三层异步隔离架构，将重计算任务与主事件循环完全解耦，确保系统的高可用性。

*   **L1 接入层 (AsyncIO)**：负责处理 WebSocket/HTTP 连接与心跳，确保在任何负载下网络接口不卡顿。
*   **L2 调度层 (GlobalTaskScheduler)**：负责任务的优先级排序、依赖管理以及流量控制（背压机制）。
*   **L3 执行层 (进程/线程池)**：将图像生成、视觉分析等重计算任务隔离在独立进程中运行，避免阻塞主线程。

### 二、实测性能数据
基于 NVIDIA GeForce RTX 5070 Laptop GPU (8GB) 的实测数据（2025年12月7日），与传统同步架构进行对比：

1.  **系统响应性 (主线程阻塞)**
    *   **xy-core**：平均阻塞时间 **6.5ms**（峰值 38.4ms）。
    *   **传统架构**：图像生成期间常出现 >2000ms 的阻塞，导致连接超时。
    *   *结论*：在 GPU 满载运行时，系统依然能及时响应用户的心跳和中断请求。

2.  **吞吐量与稳定性**
    *   **高并发表现**：在 10 路并发请求下，系统保持 **0.56 RPS** 的稳定吞吐，未发生崩溃。
    *   **流量控制**：背压机制有效工作，成功对超出处理能力的请求进行排队缓冲，60 秒内稳定处理了 32 个多模态任务链。
    *   **资源利用**：压力测试期间 GPU 利用率稳定在高位，硬件资源得到充分利用。

3.  **多模态链路耗时 (端到端)**
    典型任务链（语音输入 → 识别 → LLM → TTS + 图像生成）：
    *   **首字语音延迟**：约 **400ms**（LLM 与 TTS 采用流水线并行）。
    *   **图像生成耗时**：约 **1.0s**（在后台异步生成，不阻塞语音交互）。
    *   *用户体验*：实现了“流式响应”，用户在听到语音回复的同时，图像在后台生成，有效掩盖了生成模型的物理耗时。

### 三、关键技术点
*   **全局任务调度器**：实现了 `系统级 > 用户级 > 后台级` 的优先级队列，并引入**显存互斥锁 (VRAM Mutex)** 防止多模型并发导致的显存溢出 (OOM)。
*   **动态模块加载**：重型模型（如 Qwen2-VL, Stable Diffusion 1.5）采用按需加载与自动卸载策略，降低了约 **40%** 的冷启动内存占用。
*   **边缘侧适配**：针对消费级显卡（8GB-16GB 显存）进行了针对性优化，使其具备本地运行完整多模态链路的能力。

### 四、总结
xy-core 架构通过工程化的异步调度方案，有效解决了多模态模型在本地边缘设备上的资源冲突与阻塞问题。实测表明，该架构在保证低延迟交互的同时，能够最大限度地压榨硬件性能，具备工程落地的可行性。

---

## 目录结构

*   `domain/`: **核心业务逻辑**。纯 Python 代码。
    *   `entities/`: 数据模型 (Character, Message)。
    *   `services/`: 业务工作流 (ChatService)。
    *   `interfaces/`: 基础设施的抽象基类 (Ports/接口)。
*   `data/`: **基础设施与适配器**。
    *   `adapters/`: 接口的具体实现 (LocalLLM 等)。
    *   `repositories/`: 数据访问实现。
*   `presentation/`: **API 与 UI 层**。
    *   `websocket/`: WebSocket 处理器。
    *   `api/`: REST API 端点。
*   `shared/`: **工具类**。
    *   `di.py`: 依赖注入容器。
*   `legacy/`: 来自旧版本的归档代码。

## 基准测试与性能

`mvp_core` 包含一套完整的基准测试套件，用于验证架构性能和调度器效率。

*   **实验文档**: 请参阅 [experiments/README.md](experiments/README.md)
*   **运行基准测试**: `python experiments/comprehensive_experiment.py`
*   **可视化结果**: `python experiments/visualize_benchmark.py`

## 快速开始

1.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **配置**:
    项目支持通过 `config.json` 进行自定义配置（推荐）。在 `mvp_core` 根目录下创建 `config.json` 文件：
    ```json
    {
        "model": {
            "text_path": "models/llm/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
            "sd_path": "models/img/check_point/nsfw_v10.safetensors",
            "vl_path": "models/vision/Qwen2-VL-2B",
            "tts_api": "http://127.0.0.1:9880",
            "device": "cuda"
        }
    }
    ```
    *注：如果未创建该文件，系统将默认使用 `config.py` 中的配置。*

3.  **运行服务器**:
    ```bash
    python main.py
    ```

4.  **运行实验**:
    ```bash
    python experiments/comprehensive_experiment.py --mode xy_core --workload mock
    ```

5.  通过 WebSocket 连接至 `ws://localhost:8000/ws`。

## 关键设计模式

*   **依赖注入 (Dependency Injection)**: 使用 `shared.di.container` 来解析依赖。
*   **策略模式 (Strategy Pattern)**: LLM 和 Memory 实现可通过 `LLMInterface` 和 `MemoryInterface` 进行替换。
*   **异步任务调度 (Asynchronous Task Scheduling)**: 集成 `GlobalTaskScheduler` 以实现高效的 CPU/GPU/IO 任务管理。
