# 小友核心 (Xiaoyou Core) 技术架构与开发参考手册

**版本**: 1.6.1
**最后更新**: 2025-12-12
**状态**: 维护中

---

## 1. 项目概述 (Project Overview)

**Xiaoyou Core** 是一个高性能、异步驱动的 AI Agent 后端系统，旨在为多模态交互（文本、语音、图像）提供统一的服务支持。系统采用 Python (FastAPI/WebSocket) 作为核心后端，结合 C++ 调度器进行资源隔离，前端采用 React (TypeScript) 构建现代化用户界面。

### 1.1 核心特性
*   **混合服务架构**: 结合 HTTP (REST) 的无状态优势与 WebSocket 的实时双向通信能力。
*   **资源隔离调度**: 引入 C++ 编写的 `cpp_scheduler`，实现 LLM（GPU）、TTS（CPU）和 图像生成（GPU 异步队列）的硬件级资源隔离，防止资源争抢导致的系统卡顿。
*   **多模态融合**: 原生支持 LLM 对话（支持本地 GGUF 模型与云端 API 切换）、Stable Diffusion 图像生成、GPT-SoVITS 语音合成。
*   **模块化与重构**: 采用 Clean Architecture 思想，将情绪、生命周期、错误处理等逻辑解耦为独立模块，提升可维护性。
*   **插件化设计**: 核心业务逻辑封装在 `core/services` 与 `core/modules` 中，易于扩展。
*   **RAG 知识库与学习系统**: 集成 ChromaDB 向量数据库，支持本地文档（Study Data、Gao Kao）的语义检索与学习辅助功能。新增 **学习模式 (Study Mode)** 与 **英语词汇管理系统 (Vocabulary Manager)**。

### 1.2 技术栈
*   **后端语言**: Python 3.10+, C++17 (调度器)
*   **Web 框架**: FastAPI (HTTP/WebSocket), Uvicorn (ASGI Server)
*   **AI 框架**: PyTorch, Diffusers (SD), llama-cpp-python (Local LLM - GGUF Support), GPT-SoVITS (TTS)
*   **前端框架**: React 18, Vite, TailwindCSS, TypeScript, Electron (Desktop App)
*   **数据存储**: SQLite (短期记忆/配置), ChromaDB (向量记忆)
*   **配置管理**: YAML (`app.yaml`) + 环境变量 (.env)
*   **嵌入模型**: all-MiniLM-L6-v2 (本地化部署)

---

## 2. 系统架构 (System Architecture)

### 2.1 顶层架构图
系统分为 **接口层 (Interface Layer)**、**服务层 (Service Layer)**、**模块层 (Module Layer)** 和 **核心引擎层 (Core Engine Layer)**。

```mermaid
graph TD
    %% 客户端层
    Client[前端客户端 (Web/Mobile/QQ Bot)] -->|WebSocket| WebSocketRouter[WebSocket Router]
    Client -->|HTTP API| APIRouter[API Router]

    %% 接口层
    subgraph InterfaceLayer [接口层]
        WebSocketRouter -->|消息处理| WSManager[WebSocket Manager]
        APIRouter -->|请求处理| APIManager[API Manager]
        WSManager -->|事件发布| EventBus[Event Bus]
        APIManager -->|调用服务| ServiceManager[Service Manager]
    end

    %% 服务层
    subgraph ServiceLayer [服务层]
        ServiceManager -->|调用| AvelineService[Aveline Service]
        ServiceManager -->|调用| LifeSimulationService[Life Simulation Service]
        ServiceManager -->|调用| ActiveCareService[Active Care Service]
        ServiceManager -->|调用| CommandHandler[Command Handler]
        AvelineService -->|事件订阅| EventBus
        LifeSimulationService -->|事件订阅| EventBus
        ActiveCareService -->|事件订阅| EventBus
        CommandHandler -->|事件订阅| EventBus
    end

    %% 模块层
    subgraph ModuleLayer [模块层]
        AvelineService -->|调用| LLMModule[LLM Module]
        AvelineService -->|调用| ImageModule[Image Module]
        AvelineService -->|调用| VisionModule[Vision Module]
        AvelineService -->|调用| VoiceModule[Voice Module]
        AvelineService -->|调用| MemoryModule[Memory Module]
        LifeSimulationService -->|调用| MemoryModule
        ActiveCareService -->|调用| MemoryModule
        LLMModule -->|模型管理| ModelManager[Model Manager]
        ImageModule -->|模型管理| ModelManager
        VisionModule -->|模型管理| ModelManager
        VoiceModule -->|模型管理| ModelManager
    end

    %% 核心引擎层
    subgraph CoreEngineLayer [核心引擎层]
        ModelManager -->|配置管理| ConfigManager[Config Manager]
        ServiceManager -->|生命周期管理| LifecycleManager[Lifecycle Manager]
        AvelineService -->|事件发布| EventBus
        ConfigManager -->|配置加载| AppSettings[App Settings]
        LifecycleManager -->|服务注册| ServiceRegistry[Service Registry]
        EventBus -->|事件处理| EventHandlers[Event Handlers]
        ConfigManager -->|自动检测| ModelDetector[Model Detector]
    end

    %% 基础设施层
    subgraph Infrastructure [基础设施层]
        ModelManager -->|资源管理| ResourceMonitor[Resource Monitor]
        ResourceMonitor -->|GPU监控| GPU[GPU Resources]
        ResourceMonitor -->|CPU监控| CPU[CPU Resources]
        ResourceMonitor -->|内存监控| Memory[Memory Resources]
    end

    %% 数据流
    WSManager -->|请求| AvelineService
    APIManager -->|请求| AvelineService
    AvelineService -->|响应| WSManager
    AvelineService -->|响应| APIManager
    WSManager -->|返回响应| WebSocketRouter
    APIManager -->|返回响应| APIRouter
    WebSocketRouter -->|返回响应| Client
    APIRouter -->|返回响应| Client
end
```

### 2.2 核心引擎层详细图
核心引擎层包含系统的核心组件，负责系统的生命周期管理、配置管理、事件处理和模型管理。

```mermaid
graph TD
    subgraph CoreEngineLayer [核心引擎层]
        %% 核心引擎组件
        CoreEngine[Core Engine]
        ConfigManager[Config Manager]
        EventBus[Event Bus]
        LifecycleManager[Lifecycle Manager]
        ModelManager[Model Manager]
        ResourceMonitor[Resource Monitor]
        ServiceRegistry[Service Registry]
        ModelDetector[Model Detector]
        AppSettings[App Settings]
        EventHandlers[Event Handlers]

        %% 组件关系
        CoreEngine -->|初始化| ConfigManager
        CoreEngine -->|初始化| EventBus
        CoreEngine -->|初始化| LifecycleManager
        CoreEngine -->|初始化| ModelManager
        CoreEngine -->|初始化| ResourceMonitor
        
        ConfigManager -->|加载配置| AppSettings
        ConfigManager -->|自动检测模型| ModelDetector
        ConfigManager -->|配置更新| EventBus
        
        EventBus -->|事件订阅| EventHandlers
        EventBus -->|事件发布| LifecycleManager
        EventBus -->|事件发布| ModelManager
        
        LifecycleManager -->|注册服务| ServiceRegistry
        LifecycleManager -->|初始化服务| ServiceRegistry
        LifecycleManager -->|关闭服务| ServiceRegistry
        
        ModelManager -->|模型注册| ModelDetector
        ModelManager -->|资源监控| ResourceMonitor
        ModelManager -->|事件发布| EventBus
        
        ResourceMonitor -->|监控数据| EventBus
        ResourceMonitor -->|资源告警| EventHandlers
    end

    %% 外部依赖
    AppSettings -->|配置文件| YAMLConfig[YAML 配置文件]
    AppSettings -->|环境变量| EnvVars[环境变量]
    ModelDetector -->|模型文件| ModelFiles[模型文件]
end
```

### 2.3 服务层详细图
服务层包含系统的业务逻辑组件，负责处理业务请求、协调模块调用和管理服务状态。

```mermaid
graph TD
    subgraph ServiceLayer [服务层]
        %% 服务组件
        AvelineService[Aveline Service]
        LifeSimulationService[Life Simulation Service]
        ActiveCareService[Active Care Service]
        CommandHandler[Command Handler]
        ServiceManager[Service Manager]
        ChatAgent[Chat Agent]
        ResourceMonitor[Resource Monitor]

        %% 组件关系
        ServiceManager -->|管理| AvelineService
        ServiceManager -->|管理| LifeSimulationService
        ServiceManager -->|管理| ActiveCareService
        ServiceManager -->|管理| CommandHandler
        
        AvelineService -->|使用| ChatAgent
        AvelineService -->|监控资源| ResourceMonitor
        
        LifeSimulationService -->|监控资源| ResourceMonitor
        ActiveCareService -->|监控资源| ResourceMonitor
        
        AvelineService -->|事件发布| EventBus[Event Bus]
        LifeSimulationService -->|事件发布| EventBus
        ActiveCareService -->|事件发布| EventBus
        CommandHandler -->|事件发布| EventBus
        
        AvelineService -->|调用| ModuleManager[Module Manager]
        LifeSimulationService -->|调用| ModuleManager
        ActiveCareService -->|调用| ModuleManager
    end

    %% 服务交互
    AvelineService -->|生成响应| ResponseGenerator[Response Generator]
    AvelineService -->|管理记忆| MemoryManager[Memory Manager]
    AvelineService -->|处理命令| CommandProcessor[Command Processor]
    
    LifeSimulationService -->|模拟生活| LifeSimulator[Life Simulator]
    LifeSimulationService -->|生成事件| EventGenerator[Event Generator]
    
    ActiveCareService -->|主动关怀| CareGenerator[Care Generator]
    ActiveCareService -->|用户分析| UserAnalyzer[User Analyzer]
    
    CommandHandler -->|处理指令| CommandExecutor[Command Executor]
    CommandHandler -->|验证权限| PermissionChecker[Permission Checker]
end
```

### 2.4 模块层详细图
模块层包含系统的功能模块，负责处理特定类型的请求和实现特定功能。

```mermaid
graph TD
    subgraph ModuleLayer [模块层]
        %% 模块组件
        ModuleManager[Module Manager]
        LLMModule[LLM Module]
        ImageModule[Image Module]
        VisionModule[Vision Module]
        VoiceModule[Voice Module]
        MemoryModule[Memory Module]
        ModelAdapter[Model Adapter]

        %% 组件关系
        ModuleManager -->|管理| LLMModule
        ModuleManager -->|管理| ImageModule
        ModuleManager -->|管理| VisionModule
        ModuleManager -->|管理| VoiceModule
        ModuleManager -->|管理| MemoryModule
        
        LLMModule -->|使用| ModelAdapter
        ImageModule -->|使用| ModelAdapter
        VisionModule -->|使用| ModelAdapter
        
        LLMModule -->|模型管理| ModelManager[Model Manager]
        ImageModule -->|模型管理| ModelManager
        VisionModule -->|模型管理| ModelManager
        VoiceModule -->|模型管理| ModelManager
        
        MemoryModule -->|存储| LocalStorage[Local Storage]
        MemoryModule -->|向量检索| VectorDB[Vector Database]
    end

    %% 模块内部结构
    LLMModule -->|文本生成| TextGenerator[Text Generator]
    LLMModule -->|对话管理| ChatManager[Chat Manager]
    LLMModule -->|提示工程| PromptEngineer[Prompt Engineer]
    
    ImageModule -->|图像生成| ImageGenerator[Image Generator]
    ImageModule -->|图像处理| ImageProcessor[Image Processor]
    ImageModule -->|模型管理| SDModelManager[SD Model Manager]
    
    VisionModule -->|图像理解| ImageUnderstanding[Image Understanding]
    VisionModule -->|OCR| OCR[OCR]
    VisionModule -->|目标检测| ObjectDetection[Object Detection]
    
    VoiceModule -->|语音合成| TTS[Text-to-Speech]
    VoiceModule -->|语音识别| ASR[Automatic Speech Recognition]
    VoiceModule -->|声音处理| AudioProcessor[Audio Processor]
    
    MemoryModule -->|短期记忆| ShortTermMemory[Short-term Memory]
    MemoryModule -->|长期记忆| LongTermMemory[Long-term Memory]
    MemoryModule -->|记忆优化| MemoryOptimizer[Memory Optimizer]
end
```

### 2.5 接口层详细图
接口层包含系统的通信组件，负责处理外部请求和响应。

```mermaid
graph TD
    subgraph InterfaceLayer [接口层]
        %% 接口组件
        InterfaceManager[Interface Manager]
        APIRouter[API Router]
        WebSocketRouter[WebSocket Router]
        APIManager[API Manager]
        WSManager[WebSocket Manager]
        ConnectionManager[Connection Manager]
        RateLimiter[Rate Limiter]
        AuthManager[Authentication Manager]

        %% 组件关系
        InterfaceManager -->|管理| APIRouter
        InterfaceManager -->|管理| WebSocketRouter
        InterfaceManager -->|管理| RateLimiter
        InterfaceManager -->|管理| AuthManager
        
        APIRouter -->|请求处理| APIManager
        WebSocketRouter -->|连接管理| WSManager
        WSManager -->|连接管理| ConnectionManager
        
        APIManager -->|速率限制| RateLimiter
        WSManager -->|速率限制| RateLimiter
        
        APIManager -->|认证授权| AuthManager
        WSManager -->|认证授权| AuthManager
    end

    %% 接口路由
    APIRouter -->|API端点| Endpoints[API Endpoints]
    Endpoints -->|消息处理| MessageEndpoint[/api/v1/message/]
    Endpoints -->|图像生成| ImageEndpoint[/api/v1/image/generate/]
    Endpoints -->|语音处理| VoiceEndpoint[/api/v1/voice/]
    Endpoints -->|系统状态| StatusEndpoint[/api/v1/system/]
    
    WebSocketRouter -->|WebSocket端点| WSEndpoints[WebSocket Endpoints]
    WSEndpoints -->|消息通信| MessageWSEndpoint[/ws/message/]
    WSEndpoints -->|语音流| VoiceWSEndpoint[/ws/voice/]
    WSEndpoints -->|图像流| ImageWSEndpoint[/ws/image/]
    
    %% 请求处理流程
    APIManager -->|请求验证| RequestValidator[Request Validator]
    APIManager -->|请求解析| RequestParser[Request Parser]
    APIManager -->|响应生成| ResponseGenerator[Response Generator]
    
    WSManager -->|消息解析| MessageParser[Message Parser]
    WSManager -->|心跳处理| HeartbeatHandler[Heartbeat Handler]
    WSManager -->|连接监控| ConnectionMonitor[Connection Monitor]
    WSManager -->|消息路由| MessageRouter[Message Router]
end
```

### 2.6 数据流图
数据流图展示了请求和响应的处理流程，从客户端发起请求到系统返回响应的完整过程。

```mermaid
graph TD
    %% 客户端
    Client[客户端] -->|1. 发送请求| InterfaceLayer[接口层]
    
    %% 接口层处理
    InterfaceLayer -->|2. 验证请求| RequestValidator[请求验证]
    RequestValidator -->|3. 解析请求| RequestParser[请求解析]
    RequestParser -->|4. 路由请求| RequestRouter[请求路由]
    
    %% 服务层处理
    RequestRouter -->|5. 调用服务| ServiceLayer[服务层]
    ServiceLayer -->|6. 业务处理| BusinessLogic[业务逻辑处理]
    BusinessLogic -->|7. 调用模块| ModuleLayer[模块层]
    
    %% 模块层处理
    ModuleLayer -->|8. 功能实现| FeatureImplementation[功能实现]
    FeatureImplementation -->|9. 模型调用| ModelManager[模型管理]
    ModelManager -->|10. 模型推理| ModelInference[模型推理]
    ModelInference -->|11. 返回结果| FeatureImplementation
    
    %% 响应处理
    FeatureImplementation -->|12. 处理结果| BusinessLogic
    BusinessLogic -->|13. 生成响应| ResponseGenerator[响应生成]
    ResponseGenerator -->|14. 格式化响应| ResponseFormatter[响应格式化]
    ResponseFormatter -->|15. 返回响应| InterfaceLayer
    InterfaceLayer -->|16. 返回客户端| Client
    
    %% 内部事件处理
    ServiceLayer -->|17. 发布事件| EventBus[事件总线]
    EventBus -->|18. 事件处理| EventHandlers[事件处理器]
    EventHandlers -->|19. 更新状态| ServiceLayer
    
    %% 记忆管理
    ServiceLayer -->|20. 保存记忆| MemoryModule[记忆模块]
    MemoryModule -->|21. 检索记忆| ServiceLayer
    
    %% 资源监控
    ServiceLayer -->|22. 资源监控| ResourceMonitor[资源监控]
    ResourceMonitor -->|23. 资源告警| EventBus
end
```

### 2.7 服务初始化流程图
服务初始化流程图展示了系统启动时服务的初始化流程，从系统启动到所有服务初始化完成的完整过程。

```mermaid
graph TD
    %% 系统启动
    Start[系统启动] -->|1. 加载配置| ConfigLoader[配置加载]
    ConfigLoader -->|2. 初始化日志| LogInitializer[日志初始化]
    LogInitializer -->|3. 创建FastAPI应用| AppCreator[FastAPI应用创建]
    
    %% 核心引擎初始化
    AppCreator -->|4. 初始化核心引擎| CoreEngineInit[核心引擎初始化]
    CoreEngineInit -->|5. 初始化配置管理器| ConfigManagerInit[配置管理器初始化]
    ConfigManagerInit -->|6. 初始化事件总线| EventBusInit[事件总线初始化]
    EventBusInit -->|7. 初始化生命周期管理器| LifecycleManagerInit[生命周期管理器初始化]
    LifecycleManagerInit -->|8. 初始化模型管理器| ModelManagerInit[模型管理器初始化]
    ModelManagerInit -->|9. 初始化资源监控| ResourceMonitorInit[资源监控初始化]
    
    %% 服务注册和初始化
    ResourceMonitorInit -->|10. 注册默认服务| ServiceRegistrar[服务注册器]
    ServiceRegistrar -->|11. 初始化服务| ServiceInitializer[服务初始化器]
    ServiceInitializer -->|12. 初始化Aveline服务| AvelineInit[Aveline服务初始化]
    AvelineInit -->|13. 初始化生活模拟服务| LifeSimInit[生活模拟服务初始化]
    LifeSimInit -->|14. 初始化主动关怀服务| ActiveCareInit[主动关怀服务初始化]
    ActiveCareInit -->|15. 初始化命令处理器| CommandHandlerInit[命令处理器初始化]
    
    %% 模块初始化
    CommandHandlerInit -->|16. 初始化模块| ModuleInitializer[模块初始化器]
    ModuleInitializer -->|17. 初始化LLM模块| LLMModuleInit[LLM模块初始化]
    LLMModuleInit -->|18. 初始化图像模块| ImageModuleInit[图像模块初始化]
    ImageModuleInit -->|19. 初始化视觉模块| VisionModuleInit[视觉模块初始化]
    VisionModuleInit -->|20. 初始化语音模块| VoiceModuleInit[语音模块初始化]
    VoiceModuleInit -->|21. 初始化记忆模块| MemoryModuleInit[记忆模块初始化]
    
    %% 接口初始化
    MemoryModuleInit -->|22. 初始化接口| InterfaceInitializer[接口初始化器]
    InterfaceInitializer -->|23. 初始化API路由| APIRouterInit[API路由初始化]
    APIRouterInit -->|24. 初始化WebSocket路由| WebSocketRouterInit[WebSocket路由初始化]
    WebSocketRouterInit -->|25. 初始化中间件| MiddlewareInit[中间件初始化]
    
    %% 系统就绪
    MiddlewareInit -->|26. 系统就绪| SystemReady[系统就绪]
    SystemReady -->|27. 启动服务器| ServerStart[服务器启动]
    ServerStart -->|28. 监听请求| ListenRequests[监听请求]
end
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
*   **工具使用优化 (Tool Optimization)**:
    *   **计算器守卫**: 在 System Prompt 中明确禁止针对简单计算（如 "2+2"）调用计算器工具，强制要求 LLM 进行心算，仅允许复杂运算调用工具，减少不必要的工具调用开销。
*   **文件路径**: `core/agents/chat_agent.py`

### 3.3 图像生成与视觉 (Image & Vision)
*   **图像生成 (Generation)**:
    *   **入口**: POST `/api/v1/image/generate` 或 聊天指令 "画一个..."。
    *   **管理器**: `core.image.image_manager.ImageManager`。
    *   **核心架构**: 全面重构为 **Stable Diffusion WebUI Forge** 客户端模式。
        *   **ForgeClient**: `core.modules.forge_client.ForgeClient` 负责与本地运行的 Forge API (`127.0.0.1:7860`) 通信。
        *   **模型映射**:
            *   **SD1.5**: 用于 "二次元/快/普通画质" 模式，对应 Forge 中的 `nsfw_v10.safetensors`。
            *   **SDXL**: 用于 "写实/慢/超清画质" 模式，对应 Forge 中的 `sd_xl_base_1.0.safetensors`。
            *   **Pony**: 用于特定动漫风格，对应 `ponyDiffusionV6XL_v6StartWithThisOne.safetensors`。
        *   **LoRA 集成**: 通过 Prompt 注入 (`<lora:name:weight>`) 直接由 Forge 处理，无需后端复杂的模型加载逻辑。
        *   **优势**: 极大简化了后端代码，利用 Forge 的优化实现更快的生成速度和更低的显存占用，支持动态模型切换。
*   **视觉感知 (Vision)**:
    *   **模块**: `core.modules.vision.module.VisionModule`。
    *   **模型**: Qwen2-VL-2B (支持图像理解与描述)。
    *   **功能**: 支持多模态对话，能够理解并描述用户上传的图片内容。

### 3.4 语音模块 (Voice Manager)
*   **模块**: `core/voice/` 及 `core/modules/voice/`。
*   **功能**:
    *   **TTS (文本转语音)**: 
        *   集成 GPT-SoVITS (通过 `gpt_sovits_adapter`)，支持动态权重切换 (`gpt_sovits_weights`) 以实现不同声线。
        *   集成本地引擎 (EdgeTTS) 作为备用。已移除废弃的 Coqui TTS。
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
*   **三层记忆架构 (3-Layer Memory Hierarchy)**:
    *   **Layer 1 (普通聊天记录)**: 基础对话历史，用于保持短时上下文连贯性。
    *   **Layer 2 (加权聊天记录)**: 经过权重算法筛选的高价值对话。通过混合检索（关键词+向量）召回，支持话题聚类与情感共鸣。
    *   **Layer 3 (重要Prompt层)**: **[新增]** 核心指令与长期事实层。
        *   **晋升机制**: 当记忆权重超过阈值 (>= 4.0) 或被标记为重要用户指令 ("user_instruction") 时，自动晋升至此层。
        *   **持久化**: 独立存储于 `important_prompts.json`，在 System Prompt 构建时具有最高优先级注入，确保核心设定不被遗忘。
*   **核心机制**:
    *   **混合检索与智能过滤**: 结合关键词匹配与向量相似度。引入智能过滤机制（Length Check, Distance Threshold），避免短文本（如“你好”）触发大规模 RAG 检索导致 Token 爆炸。
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

### 3.13 知识库与学习辅助系统 (Knowledge Base & Learning System)
*   **定位**: `core/vector_search.py` (知识库检索) 及 `core/tools/study/` (学习工具集)。
*   **知识库 (RAG)**:
    *   **引擎**: ChromaDB (持久化模式)。
    *   **数据源**: 集成 "Gao Kao" 资料集与 "data/study_data" 学习资料。
    *   **检索机制**: 
        *   **触发条件 (Study Mode)**: 仅在用户显式进入“学习模式”或使用特定模型（如 "GaoKao"）时触发，避免日常闲聊干扰。
        *   **智能分类 (Subject Classification)**: 根据用户输入自动分类学科（如 Biology, Math, English），并进行精准过滤。
        *   **每日单词 (Surprise)**: 在学习模式下，偶发性（或英语学科下）主动推送 CET4 单词进行复习。
    *   **容错**: 支持向量相似度检索 (Semantic Search)，并在 SSL 证书异常时自动回退至哈希嵌入 (Hash Embedding) 以保证可用性。
*   **学习辅助工具 (Study Tools)**:
    *   **VocabularyManager**: `core/tools/study/english/vocabulary_manager.py`。基于 SM-2 算法的英语单词记忆管理系统，支持每日单词推送、进度追踪、外部词表导入。
    *   **VocabTester**: `core/tools/study/english/vocab_tester.py`。统一后端的单词测试 GUI 工具，支持“看词选义”等模式。
    *   **Gao Kao Tools**:
        *   **MathPlotTool**: 基于 Python 代码 (matplotlib) 绘制数学图像。
        *   **FileCreationTool**: 支持生成结构化文件。
        *   **UpdateWordProgressTool**: 允许 LLM 根据用户反馈更新单词记忆状态。
    *   **集成方式**: 通过 `ChatAgent` 的 `ToolRegistry` 注册。

### 3.14 主动关怀与前端模块 (Active Care & Frontend Modules)
*   **Active Care Service**:
    *   **定位**: `core/services/active_care/service.py`。
    *   **功能**: 负责基于时间或用户沉默状态的主动交互。
    *   **每日单词推送**: 每日固定时间（或首次启动）向用户推送20个英语单词。
        *   **一致性**: 使用 `VocabularyManager` 获取单词，确保推送内容与前端展示内容一致。
        *   **调度**: 使用 `APScheduler`，检查间隔已优化为2分钟以减少日志噪音。
*   **前端词汇模块 (Frontend Vocabulary Module)**:
    *   **集成**: 集成至 `Aveline_UI` 侧边栏 "Study" 模块。
    *   **组件**: `clients/frontend/Aveline_UI/src/components/StudyPanel.tsx`。
    *   **功能**: 调用后端 API 获取每日单词，支持新词/复习状态显示，UI 风格与主界面一致 (TailwindCSS + Framer Motion)。
    *   **API**: `/study/vocabulary/daily` (GET)，返回 JSON 格式的单词列表及复习状态。

---

## 4. 项目结构说明 (Directory Structure)

```text
d:\AI\xiaoyou-core\
├── main.py                     # [入口] 主程序入口，启动 FastAPI/WebSocket 服务器
├── legacy\                     # [归档] 旧代码与未使用文件 (mvp_core, app_main.py 等)
├── backups\                    # [备份] 自动备份与环境备份
├── clients\                    # [客户端] 多端接入 (Android, QQ Bot, Frontend)
├── config\                     # [配置]
│   └── yaml\
│       └── app.yaml            # 主配置文件 (端口、模型路径、功能开关)
├── memory\                     # [记忆系统] (Modular)
├── core\                       # [核心代码]
│   ├── core_engine\            # 引擎核心
│   ├── emotion\                # 情绪管理
│   ├── image\                  # 图像生成
│   ├── server\                 # WebSocket 服务器
│   ├── services\               # 业务服务
│   ├── modules\                # AI 能力模块 (LLM, Vision, Memory)
│   ├── tools\                  # [工具集]
│   │   ├── study\              # [新增] 学习辅助工具
│   │   │   ├── english\        # 英语学习 (VocabularyManager, VocabTester)
│   │   │   └── common\         # 通用工具
│   │   ├── registry.py         # 工具注册表
│   │   └── ...
│   ├── voice\                  # 语音引擎
│   └── character\              # 角色管理
├── routers\                    # [路由] FastAPI 路由定义
├── docs\                       # [文档]
├── external\                   # [外部依赖]
├── cpp_scheduler\              # [高性能组件]
├── models\                     # [模型存储]
└── tests\                      # [测试]
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
