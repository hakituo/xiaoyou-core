# MVP Core (最小可行性核心)

小优项目 (Xiaoyou Project) 的重构核心引擎，遵循整洁架构 (Clean Architecture) 原则。

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

2.  **配置 (可选)**:
    项目默认使用 `config.py` 中的配置。如需修改模型路径，请在 `mvp_core` 目录下创建 `config.json` 文件：
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
