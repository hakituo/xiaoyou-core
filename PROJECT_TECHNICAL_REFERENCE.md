# 小友核心 (Xiaoyou Core) 技术架构与开发参考手册

**版本**: 1.4.0
**最后更新**: 2025-12-09
**状态**: 维护中

---

## 1. 项目概述 (Project Overview)

**Xiaoyou Core** 是一个高性能、异步驱动的 AI Agent 后端系统，旨在为多模态交互（文本、语音、图像）提供统一的服务支持。系统采用 Python (FastAPI/WebSocket) 作为核心后端，结合 C++ 调度器进行资源隔离，前端采用 React (TypeScript) 构建现代化用户界面。

### 1.1 核心特性
*   **混合服务架构**: 结合 HTTP (REST) 的无状态优势与 WebSocket 的实时双向通信能力。
*   **资源隔离调度**: 引入 C++ 编写的 `cpp_scheduler`，实现 LLM（GPU）、TTS（CPU）和 图像生成（GPU 异步队列）的硬件级资源隔离，防止资源争抢导致的系统卡顿。
*   **多模态融合**: 原生支持 LLM 对话、Stable Diffusion 图像生成、本地/云端语音合成与识别。
*   **模块化与重构**: 采用 Clean Architecture 思想，将情绪、生命周期、错误处理等逻辑解耦为独立模块，提升可维护性。
*   **插件化设计**: 核心业务逻辑封装在 `core/services` 与 `core/modules` 中，易于扩展。

### 1.2 技术栈
*   **后端语言**: Python 3.10+, C++17 (调度器)
*   **Web 框架**: FastAPI (HTTP/WebSocket), Uvicorn (ASGI Server)
*   **AI 框架**: PyTorch, Diffusers (SD), LangChain/LlamaIndex (LLM), FunASR/Paraformer (语音)
*   **前端框架**: React 18, Vite, TailwindCSS, TypeScript, Electron (Desktop App)
*   **数据存储**: SQLite (短期记忆/配置), FAISS/Chroma (向量记忆 - 计划中)
*   **配置管理**: YAML (`app.yaml`) + 环境变量

---

## 2. 系统架构 (System Architecture)

### 2.1 顶层架构图
系统分为 **接入层**、**服务层**、**核心层** 和 **基础设施层**。

```mermaid
graph TD
    Client[前端客户端 (Web/Mobile/QQ Bot)] -->|WebSocket (6789)| WS_Server[WebSocket Server]
    Client -->|HTTP (8000)| API_Server[FastAPI Server]

    subgraph AccessLayer [接入层]
        WS_Server --> ConnectionManager
        API_Server --> APIRouters
    end

    subgraph ServiceLayer [服务层]
        direction TB
        Aveline[Aveline Service (主业务)]
        ActiveCare[Active Care (主动关怀)]
        LifeSim[Life Simulation (生活模拟)]
        CmdHandler[Command Handler]
    end

    subgraph CoreLayer [核心层]
        CoreEngine[Core Engine]
        EventBus[Event Bus]
        ModelMgr[Model Manager]
        ConfigMgr[Config Manager]
        Scheduler[Task Scheduler (Py)]
    end

    subgraph Infrastructure [基础设施层]
        CPPSched[C++ Scheduler API (Port 8080)]
        GPU[GPU Resources]
        CPU[CPU Resources]
    end

    subgraph ModuleLayer [能力模块]
        LLM[LLM Connector]
        Image[Image Manager (SD)]
        Voice[Voice Manager (TTS/STT)]
        Memory[Memory Module]
    end

    ConnectionManager --> Aveline
    APIRouters --> Image & Aveline
    
    Aveline --> CoreEngine
    Aveline --> LLM & Memory & Voice
    
    CoreEngine --> ModelMgr & ConfigMgr & EventBus
    ModelMgr --> LLM & Image
    
    Scheduler -->|HTTP Request| CPPSched
    CPPSched -->|Resource Isolation| GPU & CPU
```

### 2.2 混合通信机制
系统同时监听两个端口（配置见 `app.yaml`，实际代码中通常为 `5000/8000` 和 `6789/8999`，需以实际启动日志为准）：
1.  **WebSocket 服务 (Port 6789)**:
    *   负责长连接、心跳检测、实时对话流、语音流传输。
    *   入口类: `XiaoyouServer` (`core/server/server.py`).
2.  **HTTP API 服务 (Port 5000/8000)**:
    *   负责一次性请求，如图像生成 (`/api/v1/image/generate`)、系统状态查询 (`/health`)、文件上传。
    *   路由模块: `routers/` 目录下的 `api_router.py`, `health_router.py`。

---

## 3. 核心模块详解 (Core Modules)

### 3.1 智能代理 (ChatAgent)
*   **核心逻辑**: 负责处理用户对话、上下文管理、Prompt 构建及 LLM 调用。
*   **双模态人设系统 (Dual Persona System)**:
    *   **日常模式 (Stheno)**: 加载完整 `Aveline.json` 配置，展现傲娇、亲密及“拒绝服务”特性。
    *   **辅导模式 (Qwen)**: 自动检测模型类型，当使用 Qwen 模型时，注入 `[SYSTEM OVERRIDE]` 指令，暂时抑制负面情绪，转为专业、正经的教学风格。
*   **感官反馈 (Sensory Integration)**:
    *   集成 `Aveline` 角色管理器的感官触发器。
    *   **Sensory Triggers**: 识别特定关键词（如“晚安”、“抱歉”），实时输出 UI 控制信号（呼吸灯颜色、语音语调调整）。
*   **语音消息能力 (Voice Message Capability)**:
    *   **机制**: 支持 AI 主动决定发送语音消息（通过 `[VOICE: style]` 标签）。
    *   **展现**: 语音消息文本内容在前端默认隐藏，仅显示“Voice Message”，点击播放后通过听觉获取信息，增强私密感与沉浸感。
*   **文件路径**: `core/agents/chat_agent.py`

### 3.3 图像生成与视觉 (Image & Vision)
*   **图像生成 (Generation)**:
    *   **入口**: POST `/api/v1/image/generate` 或 聊天指令 "画一个..."。
    *   **管理器**: `core.image.image_manager.ImageManager`。
    *   **模型架构**: 
        *   **Stable Diffusion 1.5**: 支持 Checkpoint + LoRA (动态加载，目录 `models/img/sd1.5/check_point` 及 `models/img/sd1.5/lora`)。
        *   **SDXL**: 支持 Checkpoint (目录 `models/img/sdxl/checkpoints`)。虽已预留 `models/img/sdxl/lora` 目录，但在前端暂未启用 LoRA 加载以防冲突。
    *   **安全机制**: 严格隔离 SD1.5 与 SDXL 的 LoRA 加载，防止后端因模型架构不匹配而崩溃。
*   **视觉感知 (Vision)**:
    *   **模块**: `core.modules.vision.module.VisionModule`。
    *   **模型**: Qwen2-VL-2B (支持图像理解与描述)。
    *   **功能**: 支持多模态对话，能够理解并描述用户上传的图片内容。

### 3.4 语音模块 (Voice Manager)
*   **模块**: `core/voice/` 及 `core/modules/voice/`。
*   **功能**:
    *   **TTS (文本转语音)**: 
        *   集成 GPT-SoVITS (通过 `gpt_sovits_adapter`)，支持动态权重切换 (`gpt_sovits_weights`) 以实现不同声线。
        *   集成本地引擎 (EdgeTTS) 作为备用。
    *   **STT (语音转文本)**: 集成 Whisper (large-v3/tiny) 进行高精度语音识别。
*   **调度**: 语音任务通常被分配到 CPU Worker (通过 `cpp_scheduler` 或 Python 线程池) 以释放 GPU 给 LLM/SD。

### 3.5 情绪管理模块 (Emotion Module)
*   **定位**: `core/emotion`，独立的、完整的情绪识别与响应系统。
*   **功能**: 
    1.  **多模态检测**: 支持从 LLM 标记 (`[EMO: happy]`)、文本关键词等多种来源检测情绪。
    2.  **细粒度分类**: 支持 12 种情绪类型 (Happy, Sad, Angry, Anxious, Tired, Shy, Excited, Jealous, Wronged, Lost, Coquetry, Neutral)。
    3.  **状态管理**: 维护用户当前的实时情绪状态，包含主情绪、置信度、强度等。
    4.  **响应策略**: 提供基于情绪的响应策略，包括安慰话术模板、硬件控制指令（呼吸灯颜色 RGB、呼吸频率）。
    5.  **计算与累积**: `EmotionCalculator` 实现非线性情绪累积与时间衰减，支持复杂的情绪动态变化。
    6.  **历史记录**: 持久化存储用户情绪变化历史。
*   **核心类**: `EmotionManager` (Facade), `EmotionDetector`, `EmotionResponder`, `EmotionStore`, `EmotionState`, `EmotionCalculator`.

### 3.6 记忆系统 (Memory System)
*   **架构理念**: 单一事实来源 (Single Source of Truth)，统一使用加权记忆模型，已移除冗余的 EnhancedMemory。
*   **模块化结构 (Modular Design)**:
    *   **WeightedMemoryManager (Facade)**: `memory/weighted_memory_manager.py`。负责对外统一接口、并发控制 (Async Lock) 与数据持久化。
    *   **Core Logic**: `memory/core/`
        *   **权重计算 (Weights)**: `memory/core/weights.py`。负责计算基础权重、时间衰减、重要性加成与情绪奖励。
        *   **工具集 (Utils)**: `memory/core/utils.py`。提供无状态的 NLP 工具，如关键词提取、话题自动检测、用户偏好分析。
*   **核心机制**:
    *   **混合检索**: 结合关键词匹配、向量相似度 (Vector Search) 与动态权重排序。
    *   **CPU Offload Summary**: 使用 Qwen 模型在 CPU 端异步执行长对话总结，避免阻塞主对话流 (GPU)。
    *   **自动优化**: 每次交互自动更新记忆权重 (Access Count)，低权重记忆随时间自然衰减。
*   **交互**: 紧密集成 `EmotionModule`，支持“情绪-记忆”共鸣检索。

### 3.7 任务调度 (Task Scheduler)
*   **Python 端**: `core/services/scheduler` 处理业务逻辑任务调度，如定时任务、异步任务包装。
*   **C++ 端**: `cpp_scheduler` (独立服务)。
    *   **交互方式**: 通过 HTTP API (`InferServiceClient`) 进行通信。
    *   **核心价值**: 解决 Python GIL 限制和 GPU 显存争抢。
    *   **架构**: 异步事件驱动 (libuv)，将 LLM 推理(GPU)、TTS(CPU)、绘图(GPU队列) 分发到不同 Worker 进程/线程。

### 3.8 Aveline 角色与情感系统 (Aveline Character & Emotion System)
*   **角色核心 (AvelineCharacter)**:
    *   负责加载 `Aveline.json` 完整配置，管理角色人设、触发器与反射机制。
    *   **双重触发机制**: 同时支持 **Sensory Triggers** (感官触发，如“晚安”控制UI) 与 **Behavior Chains** (行为链，如调用外部服务)。
*   **依恋机制 (Dependency Mechanism)**:
    *   **管理器**: `core.character.managers.dependency_manager.DependencyManager`。
    *   **功能**: 追踪用户互动（如连续天数、特定亲密行为），计算依恋度 (Intimacy Level)。
    *   **特性解锁**: 根据依恋度解锁新功能（如“耳语模式”）。
*   **人格缺陷模拟 (Personality Defects)**:
    *   **管理器**: `core.character.managers.defect_manager.DefectManager`。
    *   **功能**: 模拟人类的非理性行为（如“占有欲”、“过度补偿”）。
    *   **触发**: 基于上下文（如被忽视、用户急躁）触发特定状态，并注入 System Prompt 强制改变短期行为。
*   **系统反射 (System Reflexes)**:
    *   **管理器**: `core.services.reaction.reaction_manager.ReactionManager`。
    *   **功能**: 监控硬件状态（CPU温度、电量）与闲置时间，触发自发性对话（如“好热...”、“人呢？”）。
*   **用户档案注入 (User Profile Injection)**:
    *   **功能**: 自动从 `Aveline.json` 加载用户档案（姓名、性格、对 Aveline 的态度），并动态注入 System Prompt。
    *   **目的**: 增强 Aveline 对当前交互对象（如 Leslie）的认知与个性化回应。
*   **硬件集成 (Hardware Integration - Planned/Mock)**:
    *   **呼吸灯 (Breathing Light)**: 配置已加载，感官触发器会返回颜色代码，前端/硬件层需对接实现。
    *   **视觉摘要 (Vision Summary)**: 目前由 `LifeSimulationService` 提供 Mock 数据（基于时间判断光照），预留了对接真实视觉模型的接口。
*   **日常仪式 (Rituals)**:
    *   **管理器**: `LifeSimulationService.RitualManager`。
    *   **功能**: 每日固定时间触发的特定互动（如晨间打卡、睡前小结）。
    *   **实现**: `RitualManager` 在 `_monitor_loop` 中运行，根据时间和活动分钟数触发。
*   **简笔画生成 (Stick Figure Generation)**:
    *   **触发**: 当 `ChatAgent` 检测到强情绪（权重>=0.6）时。
    *   **实现**: 生成 `ui_interaction` 类型的 WebSocket 消息，前端需解析并展示。

### 3.9 工具与实用程序 (Tools & Utilities)
*   **向量搜索工具**: `core/vector_search.py` (独立工具类，当前核心业务主要使用 `WeightedMemoryManager`，但向量搜索已准备就绪，支持 RAG 知识库扩展)。

### 3.10 智能代理工具链 (Intelligent Agent Tool Chain)
*   **定位**: `core/tools`，赋予 AI 使用外部工具与系统功能的能力。
*   **架构**: 
    *   **Registry**: `core.tools.registry.ToolRegistry` 负责工具的注册与管理。
    *   **BaseTool**: 所有工具的基类，定义标准接口与 Schema。
    *   **ChatAgent 集成**: `ChatAgent` 在系统提示词中动态注入工具描述，并解析 `[TOOL_USE]` 指令执行工具（支持 ReAct 循环）。
*   **内置工具**:
    *   **WebSearch**: 调用 Bocha API 进行联网搜索。
    *   **ImageGeneration**: 调用 `ImageManager` 生成图像。
    *   **Time**: 获取系统当前时间。
    *   **Calculator**: 安全的数学表达式计算。

### 3.11 Electron 桌面宠物 (Electron Desktop Pet)
*   **定位**: `clients/frontend/Aveline_UI/electron`，基于 Electron 的桌面端宿主。
*   **特性**:
    *   **透明窗口**: 背景透明，无边框，完美融入桌面环境。
    *   **Always on Top**: 始终置顶，确保小友随时可见。
    *   **Pet Mode**: 通过 URL Hash (`#/pet-mode`) 激活精简 UI，仅展示角色与必要交互，隐藏无关面板。
*   **启动**: `npm run electron:dev` (开发模式) 或构建后运行。

### 3.12 语音管理器 (Voice Manager)
*   **定位**: `core/voice/`，负责 TTS (语音合成) 和 STT (语音识别) 的统一管理。
*   **核心功能**:
    *   **多引擎支持**: 支持 Edge-TTS (在线/轻量) 和 GPT-SoVITS (本地/高质量) 引擎切换。
    *   **自动转录 (Auto-Transcription)**: 针对用户自定义的参考音频，若缺失 `.txt` 标注文件，系统会自动调用 STT 引擎进行识别并缓存，确保克隆效果（音调/韵律）的准确性。
    *   **参数透传**: 完整支持 `speed`, `pitch`, `top_k`, `top_p`, `temperature` 等参数从 API 到推理引擎的透传，允许精细化控制语音表现。
    *   **采样率自适应**: 自动识别 TTS 引擎（GPT-SoVITS 32k / Edge-TTS 24k）的采样率，防止因重采样错误导致的音调异常（变低/变慢）。

---

## 4. 项目结构说明 (Directory Structure)

```text
d:\AI\xiaoyou-core\
├── main.py                     # [入口] 主程序入口，启动 FastAPI/WebSocket 服务器
├── legacy\                     # [归档] 旧代码与未使用文件 (mvp_core, app_main.py 等)
├── backups\                    # [备份] 自动备份与环境备份
├── clients\                    # [客户端] 多端接入 (Android, QQ Bot, Frontend)
│   ├── android\                # Android App 源码
│   ├── bots\                   # QQ/Discord 机器人适配
│   └── frontend\               # Aveline_UI 前端项目
├── config\                     # [配置]
│   └── yaml\
│       └── app.yaml            # 主配置文件 (端口、模型路径、功能开关)
├── memory\                     # [记忆系统] (Modular)
│   ├── weighted_memory_manager.py # [Facade] 统一入口
│   └── core\                   # [核心组件]
│       ├── weights.py          # 权重计算逻辑
│       └── utils.py            # NLP 工具集
├── core\                       # [核心代码]
│   ├── core_engine\            # 引擎核心 (配置管理、生命周期、事件总线)
│   ├── emotion\                # [新增] 独立情绪管理模块
│   ├── image\                  # 图像生成业务逻辑 (ImageManager)
│   ├── lifecycle\              # [新增] 应用生命周期管理 (lifespan)
│   ├── server\                 # WebSocket 服务器实现
│   ├── services\               # 业务服务 (Aveline, Scheduler, LifeSim)
│   ├── modules\                # AI 能力模块 (LLM, Vision, Memory)
│   ├── voice\                  # 语音底层引擎
│   ├── character\              # 角色管理 (aveline.py - Aveline 逻辑核心)
│   ├── utils\                  # 通用工具 (错误处理、静态文件挂载、文本处理)
│   └── interfaces\             # 接口适配器 (WebSocket Adapter)
├── routers\                    # [路由] FastAPI 路由定义
│   ├── api_router.py           # 通用 API
│   ├── session_router.py       # [新增] 会话管理 API
│   ├── health_router.py        # 健康检查 API
│   └── websocket_router.py     # WebSocket 握手与升级
├── docs\                       # [文档] 技术文档、开发指南、计划书
├── external\                   # [外部依赖] 第三方工具与库 (Gradle, llama.cpp)
├── cpp_scheduler\              # [高性能组件] C++ 资源隔离调度器源码
├── models\                     # [模型存储]
│   ├── img\                    # 存放 .safetensors 图像模型
│   └── llm\                    # 存放 .gguf 等大语言模型
└── tests\                      # [测试] 单元测试与集成测试脚本
```

---

## 5. 开发与协作规范 (Development Guidelines)

### 5.1 AI 助手开发准则
1.  **任务追踪**: 必须使用 `TodoWrite` 工具规划复杂任务，保持上下文清晰。
2.  **代码搜索**: 优先使用 `SearchCodebase` 进行语义搜索，而非简单的 `Grep`。
3.  **验证优先**: 修改代码后，**必须**编写或运行测试脚本（如 `tests/` 下的脚本）验证功能，严禁盲目提交。
4.  **文件操作**: 修改文件前先 `Read` 确认内容，使用 `SearchReplace` 进行精准修改。

### 5.2 配置管理
*   **统一配置中心**: 所有核心配置已迁移至 `config/integrated_config.py`，采用 Pydantic 模型 (`BaseSettings`) 进行强类型管理。
*   **环境变量**: 支持通过 `.env` 文件或系统环境变量覆盖默认配置（前缀 `XIAOYOU_`）。
*   **遗留配置**: 部分旧模块仍可能读取 `config/yaml/app.yaml`，正逐步迁移中。

### 5.3 异常处理
*   API 层应捕获所有异常并返回标准 JSON 错误格式 (`{"success": False, "error": "..."}`)。
*   WebSocket 处理器应捕获异常并记录日志，避免连接意外断开。

### 5.4 已知问题与重构计划 (Known Issues)
*   **测试不足**: `tests/` 目录覆盖率低，需补充核心模块单元测试。
*   **配置冗余**: `config/` 下存在多个加载脚本，需整合。

---

## 6. 部署与运行 (Deployment)

### 6.1 环境要求
*   Windows 10/11 (推荐) 或 Linux。
*   Python 3.10+。
*   NVIDIA GPU (推荐 8GB+ 显存) 用于本地推理。

### 6.2 启动方式
1.  **启动核心服务**:
    ```bash
    python main.py
    ```
2.  **启动 C++ 调度器 (可选，高性能模式)**:
    ```bash
    cd cpp_scheduler/build
    ./server/blackbox_server --config ../config.json
    ```
3.  **启动前端**:
    ```bash
    cd clients/frontend/Aveline_UI
    npm run dev
    ```
4.  **启动桌面宠物 (Electron)**:
    ```bash
    cd clients/frontend/Aveline_UI
    npm run electron:dev
    ```
    *(注：推荐使用根目录下的 `start_services.bat` 一键启动所有服务)*


### 6.3 常见问题
*   **模型加载失败**: 检查 `models/` 目录下是否存在模型文件，或检查 `app.yaml` 中的路径配置。
*   **端口冲突**: 修改 `app.yaml` 中的 `server.port` 或 `websocket.port`。
*   **HuggingFace 超时**: 确保 `local_files_only=True` 已在 `ImageManager` 和 `ModelLoader` 中启用。
