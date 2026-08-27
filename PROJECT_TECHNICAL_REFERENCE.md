# Xiaoyou Core 项目技术参考文档

**文档版本**: 3.6.0
**最后更新**: 2026-08-18
**维护者**: Xiaoyou Core Team

> **本次更新摘要 (3.6.0)**：
> - 对话流式响应改为真流式：普通文本逐块发送（`tag_stream_parser.py` `rt_emits` 实时队列 + `stream_chat_impl` 逐块 yield）
> - 新增 `response_reset` 事件：AI 开始调用工具时下发，前端清空当前生成中的临时消息（不影响历史），随后 `discard_turn()` 丢弃中间轮次缓冲
> - 历史落库推迟到 `response_done` 之后调度，保证写入完整结果
> - Android 端同步：`StreamEvent.Reset` / `WebSocketMessage.ResponseReset` / `ChatFlushManager.onResponseReset()`，HTTP SSE 与 WebSocket 两路处理

> **历史更新摘要 (3.5.2)**：
> - 独立 debug 日志统一收敛：`active_care_debug.log` / `ws_handshake_debug.log` / `api_calls_simple.log` / `server_debug.log` 全部归口 `logs/` 目录
> - `debug_config.py` 开关体系更新：新增 `active_care_ws`（实时晚安/唤醒检测落盘调试）、`server_debug`（桌面端 server 进程调试）两个开关，全部默认关闭
> - 新增 `logs/server_debug.log` 受控开关，`desktop_app.py` 不再无条件落盘

> **历史更新摘要 (3.5.1)**：
> - 同步更新分层架构图，增加 iOS、Obsidian、OpenAI Compatible、Agent 层、情绪系统、人物档案、Redis 等组件
> - 与 readme.md 中 Mermaid 架构图及 static/demo/architecture.svg 保持一致

> **历史更新摘要 (3.5.0)**：
> - 新增 3.10 CharacterDailyService（角色日常服务）技术详解：每日计划生成、活动状态机、Peer Chat门控、Active Care集成
> - 新增 Character Daily 完整文件清单与架构说明
> - 更新服务层架构图，添加 CharacterDaily 模块

## 目录

1. [技术架构总览](#1-技术架构总览)
2. [核心引擎层技术详解](#2-核心引擎层技术详解)
3. [服务层技术详解](#3-服务层技术详解) (含 3.11 数字健康)
4. [模块层技术详解](#4-模块层技术详解)
5. [记忆系统技术详解](#5-记忆系统技术详解)
6. [调度系统技术详解](#6-调度系统技术详解)
7. [接口层技术详解](#7-接口层技术详解)
8. [客户端层技术详解](#8-客户端层技术详解)
9. [数据流与调用链路](#9-数据流与调用链路)
10. [配置系统详解](#10-配置系统详解)
11. [错误处理与日志系统](#11-错误处理与日志系统)
12. [性能优化指南](#12-性能优化指南)

***

## 1. 技术架构总览

### 1.1 分层架构

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              Clients Layer (客户端层)                                │
│  Web (React) │ Android (Kotlin) │ iOS (Swift) │ Electron │ QQ Bot │ Telegram │ Obsidian │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                              Interface Layer (接口层)                                │
│                    HTTP REST API │ WebSocket │ OpenAI Compatible                    │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                               Core Layer (核心层)                                    │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                          Core Engine (核心引擎)                              │   │
│  │  Engine │ EventBus │ LifecycleManager │ ModelManager │ ConfigManager │ ServiceRegistry │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         Services (服务层 - 25+ 子模块)                       │   │
│  │  Aveline │ ActiveCare │ Workspace │ Scheduler │ Immune │ AutoHeal │ CharacterDaily │   │
│  │  SelfImprovement │ DataOps │ Study │ LifeSim │ Journal │ Daily │ VTube │ ...         │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           Agents (Agent 层)                                  │   │
│  │  ChatAgent │ PersonaSystem / Prompt                                          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                          Modules (模块层)                                    │   │
│  │  LLM │ Vision │ Voice │ Image │ Memory                                        │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                          Tools (工具层 - 26+ 工具)                           │   │
│  │  Study │ Daily │ Diary │ Reminder │ Status │ Food │ Search │ ...             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Emotion (情绪系统) │ People Profile (人物档案)                                │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                              Memory Layer (记忆层)                                   │
│              WeightedMemory │ VectorSearch │ KeywordIndex │ Distillation          │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                             Scheduler Layer (调度层)                                 │
│              C++ Scheduler │ GlobalTaskScheduler │ BioSystem                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                              Storage Layer (存储层)                                  │
│                    JSON Files │ ChromaDB │ SQLite │ Redis (L2)                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 技术栈详情

| 层级    | 技术组件               | 版本要求    | 说明            |
| ----- | ------------------ | ------- | ------------- |
| 后端框架  | FastAPI            | 0.100+  | 异步Web框架       |
| 后端运行时 | Uvicorn            | 0.23+   | ASGI服务器       |
| LLM推理 | llama-cpp-python   | 0.2.50+ | GGUF模型推理      |
| LLM推理 | Transformers       | 4.35+   | HuggingFace模型 |
| 向量数据库 | ChromaDB           | 0.4+    | 向量存储与检索       |
| 前端框架  | React              | 18.2+   | UI框架          |
| 前端构建  | Vite               | 5.0+    | 构建工具          |
| 状态管理  | Zustand            | 5.0+    | 轻量级状态管理       |
| 移动端   | Capacitor\&jetpack | 8.0+    | 跨平台桥接         |
| 桌面端   | Electron           | 33.0+   | 桌面应用框架        |
| 调度与计算 | C++17 / Pybind11   | -       | 高性能算子与硬件调度    |

#### Python 依赖与运行环境

- `venv_cpu` 是 Windows 日常默认环境，使用 CPU 版 Torch；QQ Adapter 与主程序共用该环境。
- `venv_core` 保留 CUDA 版 Torch，用于确实需要 GPU 的本地推理任务。
- `pyproject.toml` / `uv.lock` 管理项目包的直接依赖与跨平台解析；`requirements/base.txt`
  是完整 Windows 运行环境锁，CPU/GPU Torch 锁必须在其后分步安装。
- 两套环境统一使用 `tests/scripts/environment/verify_runtime_dependencies.py` 检查
  `pip check`、重复元数据、关键导入、OpenCV 所有权和 Torch 设备状态。
- SoX / FFmpeg 是部分语音链的外部原生工具，Python requirements 仅安装封装库；
  需要时应提供项目本地可执行文件并加入服务进程 `PATH`。

### 1.3 混合架构设计原则 (Hybrid Architecture)

本项目采用严格的 **"Python 做胶水与业务编排，C++ 做引擎与重度计算"** 的混合架构范式：

- **Python 负责“大脑”**：处理高变动的业务逻辑（如 Active Care 决策流）、FastAPI 路由、WebSocket 连接并发、以及大模型 Prompt 的动态组装。
- **C++ 负责“肌肉”**：通过 Pybind11 提供零内存拷贝（Zero-Copy）的 Python Binding，专门解决 Python GIL 锁导致的 CPU 瓶颈。目前 C++ 接管了以下五大核心算子（均已集成到主程序）：
  1. **调度器 (`cpp_scheduler`)**：硬件资源与任务排队。
  2. **记忆检索 (`cpp_memory_index`)**：海量记忆的 SIMD 余弦距离计算。
  3. **极速分词 (`cpp_fast_tokenizer`)**：BPE Token 估算与长文本防爆显存截断。→ 集成到 `inference_utils.py`
  4. **音频流处理 (`cpp_audio_processor`)**：毫秒级 VAD (语音活动检测) 与去静音。→ 集成到 `stt_connector.py` / `stt_engine.py`
  5. **模型推理 (`cpp_bert_engine`)**：基于 ONNX Runtime 的轻量级意图识别。→ 集成到 `bert_runtime_mixin.py`

### C++ 模块集成策略
所有C++模块均采用 **动态检测 + 优雅降级** 模式：
- 通过 `importlib.util.find_spec()` 检测模块是否可用
- 不可用时自动回退到原有Python实现
- C++模块不作为硬性依赖，保证项目在无编译环境下的可用性

### 1.4 目录结构详解

> 注：本结构反映 2026-06-18 实际代码状态。已删除的模块（`core/core_engine/engine.py`、`core/server/`、`core/text_model_adapter.py`、`core/model_adapter.py`、`routers/api_v1/`、`routers/*_router.py`、`multimodal/image_gen.py`、`surprise_manager.py`、`topic_generator.py`）不再列出。

```
xiaoyou-core/
├── clients/                      # 客户端层
│   ├── bots/                     # 机器人适配器
│   │   ├── handlers/             # Handler 模块（base/command_router/config/dashboard/food/intent/lifecycle/media/meme/openclaw/resources/system/telegram）
│   │   ├── utils/                # 工具函数（status_renderer）
│   │   ├── tests/                # 测试文件
│   │   ├── qq_adapter_main.py    # QQ 适配器主入口
│   │   ├── qq_adapter_config.py  # QQ 适配器配置类（QQAdapterConfig，66 字段）
│   │   ├── qq_adapter_session.py # 会话管理（XiaoyouSession）
│   │   ├── qq_adapter_intent.py  # 意图识别
│   │   ├── qq_adapter_peer_chat.py # Peer Chat 管理
│   │   ├── qq_adapter_face.py    # 表情注入
│   │   ├── qq_adapter_emotion.py # 情绪处理
│   │   ├── qq_adapter_transport.py # 传输层
│   │   ├── qq_adapter_settings.py # 设置处理
│   │   ├── qq_adapter_aggregator.py # 聚合器
│   │   ├── qq_official_adapter.py # QQ 官方适配器
│   │   ├── multi_qq_adapter.py   # 多 QQ 适配器入口
│   │   ├── multi_qq_config.json  # 多 QQ 角色配置
│   │   └── telegram_adapter.py   # Telegram 适配器
│   └── frontend/                 # 前端项目
│       ├── aveline-web/          # Web 前端（React+Vite+Zustand）
│       │   ├── src/{api,components,hooks,store,systems,types,utils}
│       │   ├── index.html        # Web 入口
│       │   ├── mobile.html       # 移动端入口
│       │   └── vite.config.ts    # Vite 配置
│       ├── aveline-android/      # Android 应用（Jetpack Compose + Kotlin）
│       ├── aveline-ios/          # iOS 应用（Swift）
│       └── packages/api-client/  # 共享 API 客户端包
├── core/                         # 核心层
│   ├── api/                      # API 契约层（新增）
│   │   ├── contract.py           # 统一响应封装（success_response/error_response）+ internal token 校验
│   │   └── error_response.py     # ErrorCode 枚举（系统/请求/认证/资源/LLM/任务/限流/业务）
│   ├── core_engine/              # 核心引擎（engine.py 已删除）
│   │   ├── event_bus.py          # 事件总线
│   │   ├── lifecycle_manager.py  # 生命周期管理（ServiceLifecycle 类）
│   │   ├── service_registry.py   # 默认服务注册逻辑
│   │   ├── service_singletons.py # 业务单例管理（Aveline/Vision/ActiveCare）
│   │   ├── service_helpers.py    # 生命周期辅助函数
│   │   ├── model_manager.py      # 模型管理器
│   │   └── config_manager.py     # 配置管理器
│   ├── contracts/                # 跨模块契约（状态枚举/稳定 schema）
│   │   ├── states.py             # 统一状态枚举：Health/Task/Resource/Model/Service/Approval/ModuleInit
│   │   └── README.md             # 契约说明
│   ├── env/                      # 虚拟环境间通信（新增）
│   │   ├── env_communication_manager.py # 环境通信管理器（Message/MessageQueue）
│   │   └── websocket_client.py   # WebSocket 客户端（WebSocketMessage）
│   ├── lifecycle/                # 应用生命周期（新增）
│   │   └── lifespan.py           # FastAPI lifespan + Windows 控制台关闭处理
│   ├── managers/                 # 业务管理器（新增）
│   │   ├── notification_manager.py # 通知管理（deque(maxlen=50)，活跃轮询判定）
│   │   ├── preference_manager.py  # 用户偏好管理（runtime/user_preferences.json）
│   │   └── session_manager.py     # 多会话管理（按 scope 聚合）
│   ├── middleware/               # 中间件层
│   │   └── security.py           # 安全中间件（认证/授权/速率限制）
│   ├── modules/                  # 模块层
│   │   ├── llm/                  # LLM 模块（module.py + error_handler/gpu_manager/inference_utils/model_loader/stream_generator/sync_generator/utils）
│   │   ├── openai_compat/        # OpenAI 兼容客户端子包
│   │   │   ├── client.py         # OpenAIClient 通用客户端
│   │   │   ├── aveline_client.py # AvelineClient
│   │   │   ├── deepseek_client.py # DeepSeekClient
│   │   │   ├── minimax_client.py # MiniMaxClient
│   │   │   ├── ark_client.py     # ArkClient（火山方舟）
│   │   │   ├── zhipu_client.py   # ZhipuClient（智谱 AI，思考/联网/视觉）
│   │   │   ├── dsml_parser.py    # DSML 解析器
│   │   │   ├── api_monitor.py    # API 调用监控
│   │   │   ├── message_utils.py  # 消息规范化
│   │   │   ├── error_handling.py # 错误处理
│   │   │   └── stream_parser.py  # 流式解析
│   │   ├── vision/               # 视觉模块
│   │   ├── voice/                # 语音模块（含 utils/text_processor）
│   │   ├── memory/               # 记忆模块
│   │   ├── comfy_client.py       # ComfyUI 客户端
│   │   └── forge_client.py       # Forge 客户端
│   ├── llm/                      # LLM 客户端（与 modules/llm 互补）
│   │   ├── openai_compat/        # OpenAI 兼容客户端子包（同上）
│   │   ├── dashscope_client.py   # 通义千问客户端
│   │   ├── siliconflow_client.py # SiliconFlow 客户端
│   │   ├── infer_service_client.py # 推理服务客户端
│   │   └── llm_logger.py         # LLM 日志
│   ├── services/                 # 服务层
│   │   ├── aveline/              # Aveline 对话服务
│   │   │   ├── service.py        # 服务主类
│   │   │   ├── stream_orchestrator.py # 流式编排
│   │   │   ├── response_postprocess.py # 响应后处理链
│   │   │   ├── response_media.py # 媒体富化
│   │   │   ├── control_intent.py # 控制意图识别
│   │   │   ├── command_handler.py # 命令处理
│   │   │   ├── mode_control.py   # 模式切换
│   │   │   ├── prompt_policy.py  # 提示词策略
│   │   │   └── dual_role/        # 双角色协调子系统（含多QQ角色扩展）
│   │   ├── active_care/          # 主动关怀服务（详见 §3.2，已整理为子目录）
│   │   │   ├── core/              # 核心编排与服务入口（21个文件）
│   │   │   │   ├── service.py     # 服务主类
│   │   │   │   ├── proactive_checker.py # 检查器薄壳门面（初始化/门控/节流/状态检测/事件处理/动作流程/时间检测/睡眠会话兼容已拆分到 checker/，保留 perform_check/_run_decision_core 核心协调 + 转发方法）
│   │   │   │   ├── proactive_loop.py # 主动关怀循环
│   │   │   │   ├── watchdog.py    # 看门狗
│   │   │   │   ├── startup_handler.py # 启动处理
│   │   │   │   ├── executor.py    # 消息执行器薄壳门面（历史解析/LLM输入构建/上下文组装/会话路由/消息分发/提醒处理已拆分到 6 个子模块，保留 trigger_message 核心调度 + 12 兼容入口 + 8 委托方法 + get_active_care_executor 工厂函数）
│   │   │   │   ├── history_processor.py # 历史消息纯解析（从 executor 拆分，HistoryProcessor 类）
│   │   │   │   ├── input_builder.py # LLM 输入构建（从 executor 拆分，ModelInputBuilder 类）
│   │   │   │   ├── context_builder.py # 上下文组装+Prompt（从 executor 拆分，TriggerContextBuilder 类）
│   │   │   │   ├── conversation_router.py # 会话路由（从 executor 拆分，ConversationRouter 类）
│   │   │   │   ├── message_dispatcher.py # 消息分发+回调（从 executor 拆分，MessageDispatcher 类）
│   │   │   │   ├── reminder_handler.py # 提醒处理（从 executor 拆分，ReminderHandler 类）
│   │   │   │   ├── context.py     # 上下文管理（会话解析/作息配置已拆分，保留转发方法）
│   │   │   │   ├── conversation_resolver.py # 会话 ID 解析与候选排序
│   │   │   │   ├── response_generator.py # LLM 响应生成与 fallback
│   │   │   │   ├── qq_connection_resolver.py # QQ/NapCat/官方机器人/WebSocket 连接解析
│   │   │   │   ├── hardware_intent.py # 硬件震动/灯效意图策略
│   │   │   │   ├── sleep_policy.py # 睡眠策略
│   │   │   │   ├── sleep_session_manager.py # 睡眠会话状态机（从 proactive_checker 拆分，10 方法）
│   │   │   │   ├── user_response_handler.py # 用户响应处理
│   │   │   │   └── persona_resolver.py # 人设解析
│   │   │   ├── decision/          # 决策引擎与执行（11个文件）
│   │   │   │   ├── decision.py    # LLM 决策 + Bandit（输出解析/指令构建已拆分，保留转发方法）
│   │   │   │   ├── decision_executor.py # 决策执行器（动作构建/上下文采集已拆分，保留转发方法）
│   │   │   │   ├── decision_context.py # 决策上下文
│   │   │   │   ├── decision_tools.py # 决策工具
│   │   │   │   ├── decision_output_parser.py # 决策输出解析（JSON 修复，regex fallback，peer chat 解析）
│   │   │   │   ├── decision_instruction_builder.py # 决策指令构建（日常探测指令，特定动作指令）
│   │   │   │   ├── action_builder.py # 动作构建器（build_available_actions，apply_action_overrides，should_force_send）
│   │   │   │   ├── context_gatherer.py # 上下文采集器（workspace 快照，历史记录，用户信号，紧急需求）
│   │   │   │   ├── daily_push_priority.py # 每日推送优先级（候选构建，LLM 分析，持久化）
│   │   │   │   ├── portrait_keyword_map.py # 画像关键词映射（统一 decision.py 和 priority_analyzer.py 的重复映射）
│   │   │   │   └── priority_analyzer.py # 优先级分析（每日推送/画像关键词已拆分，保留转发方法）
│   │   │   ├── detection/         # 检测与识别（4个文件）
│   │   │   │   ├── activity_detector.py # 活动检测（活动映射已拆分到 activity_maps.py，保留转发方法）
│   │   │   │   ├── activity_maps.py # 活动映射表（进程名/窗口标题分类）
│   │   │   │   ├── intent_detector.py # 意图检测（BERT 语义先行 + 关键词兜底）
│   │   │   │   └── gate_scorer.py # 软评分门控系统（7 层）
│   │   │   ├── postprocess/       # 后处理管线（4个文件）
│   │   │   │   ├── postprocessor.py # 后处理管线（睡眠净化/去重/泄露检测已拆分，保留转发方法）
│   │   │   │   ├── sleep_sanitizer.py # 睡眠净化器（SleepSanitizer）
│   │   │   │   ├── deduplicator.py # 去重器（Deduplicator）
│   │   │   │   └── leak_detector.py # 泄露检测器（LeakDetector）
│   │   │   ├── peer_chat/         # 同伴对话（5个文件）
│   │   │   │   ├── peer_chat_scheduler.py # 同伴对话调度
│   │   │   │   ├── peer_script_generator.py # 剧本生成（分发/钩子已拆分，保留转发方法）
│   │   │   │   ├── peer_script_dispatch.py # 剧本分发（逐条 WebSocket 广播）
│   │   │   │   ├── peer_script_hooks.py # 剧本后处理钩子（日记/社交事件/巡逻触发）
│   │   │   │   └── peer_chat_metrics.py # 同伴对话指标
│   │   │   ├── prompt/            # 提示词构建（3个文件）
│   │   │   │   ├── prompt_builder.py # Prompt 组装（上下文构建/话题多样性已拆分，保留转发方法）
│   │   │   │   ├── prompt_context_builders.py # Prompt 上下文构建（设备/生物/健康/食物/学习上下文）
│   │   │   │   └── topic_diversity.py # 话题多样性控制
│   │   │   ├── scheduling/        # 调度与时间管理（5个文件）
│   │   │   │   ├── scheduler_logic.py # 心跳间隔计算
│   │   │   │   ├── schedule_adapter.py # 作息学习适配器
│   │   │   │   ├── schedule_config_loader.py # 作息调度配置加载
│   │   │   │   ├── delayed_scheduler.py # 延迟调度
│   │   │   │   └── delayed_task_handler.py # 延迟任务处理
│   │   │   ├── storage/           # 存储与持久化（3个文件）
│   │   │   │   ├── storage.py     # 存储层（JSON + 延迟写入缓冲）
│   │   │   │   ├── state_persistence.py # 状态持久化（事件记录、发送历史）
│   │   │   │   └── user_profile_service.py # 用户画像
│   │   │   ├── checker/           # 检查器子模块（8个文件）
│   │   │   │   ├── checker_init_state.py # 检查器初始化与状态恢复（CheckerInitState）
│   │   │   │   ├── checker_client_gate.py # 检查器客户端门控（CheckerClientGate，活跃检测、私密模式）
│   │   │   │   ├── checker_throttle.py # 检查器节流与时间调度（CheckerThrottle，抖动、退避）
│   │   │   │   ├── checker_state_detector.py # 状态检测（CheckerStateDetector，决策流程准备、上下文构建、起床检测）
│   │   │   │   ├── checker_event_handler.py # 事件检测（CheckerEventHandler，到期提醒处理）
│   │   │   │   ├── checker_action_flow.py # 动作流程（CheckerActionFlow，优先级构建、发送/跳过）
│   │   │   │   ├── checker_time_gate.py # 时间检测（CheckerTimeGate，沉默覆盖）
│   │   │   │   └── sleep_session_compat.py # 睡眠会话兼容 mixin（SleepSessionCompatMixin，10 个委托垫片）
│   │   │   ├── shared/            # 共享常量与工具（2个文件）
│   │   │   │   ├── constants.py   # 常量（SkipReasons, 退避算法, 睡眠状态描述）
│   │   │   │   └── vocabulary.py  # 词汇学习
│   │   │   └── state/             # 统一状态管理模块（5个文件）
│   │   │       ├── base.py        # 状态管理基类
│   │   │       ├── sleep_state.py # 睡眠状态
│   │   │       ├── focus_state.py # 专注/学习状态
│   │   │       ├── mode_state.py  # 模式状态
│   │   │       └── manager.py     # 统一状态管理器
│   │   ├── scheduler/            # 调度服务（详见 §6，已重构为子目录）
│   │   │   ├── cpp_scheduler_engine.py # C++ 引擎集成（主入口）
│   │   │   ├── scheduler_wrapper.py # C++ 扩展绑定层
│   │   │   ├── bio/              # 生物系统（bio_state, bio_system_manager）
│   │   │   ├── client/           # C++ HTTP 客户端（cpp_client, cpp_config_builder）
│   │   │   ├── inference/        # 推理执行（inference_executor, cpp_llm_handler, python_llm_handler, inference_stats, inference_utils）
│   │   │   ├── lifecycle/        # 生命周期（scheduler_lifecycle, health_monitor）
│   │   │   ├── model/            # 模型与 GPU（llm_model_manager, gpu_resource_manager）
│   │   │   ├── task/             # 任务调度（task_scheduler, task_scheduler_adapter, async_task_wrapper）
│   │   │   └── utils/            # 工具（circuit_breaker, error_utils, kv_cache_manager, nvidia_smi_monitor, resource_utils, startup_config）
│   │   ├── workspace/            # 工作空间服务
│   │   │   ├── service.py        # 服务主类
│   │   │   ├── status_manager.py # 状态管理
│   │   │   ├── reminder_service.py # 提醒服务
│   │   │   ├── reminder_store.py # 提醒存储
│   │   │   ├── daily_task_service.py # 每日任务
│   │   │   ├── history_store.py  # 历史存储
│   │   │   ├── snapshot.py       # 快照
│   │   │   ├── study_bridge.py   # 学习桥接
│   │   │   └── models.py         # 数据模型
│   │   ├── journal/              # 日记服务（service, storage, models, persona_exports）
│   │   ├── daily/                # 每日数据服务（manager, extractor, correction）
│   │   ├── immune/               # 免疫系统服务
│   │   ├── auto_heal/            # 自愈服务（日志驱动自动修 bug，7 层安全机制，详见 §3.7）
│   │   │   ├── heal_service.py   # 自愈服务主类
│   │   │   ├── anomaly_detector.py # 异常检测器
│   │   │   ├── root_cause_analyzer.py # 根因分析器
│   │   │   ├── patch_generator.py # 补丁生成器
│   │   │   ├── patch_sandbox.py  # 补丁验证器
│   │   │   ├── patch_manager.py  # 补丁管理器（应用/回滚/拒绝）
│   │   │   ├── report_generator.py # 报告生成器
│   │   │   ├── models.py         # 数据模型
│   │   │   └── README.md         # 安全机制说明
│   │   ├── metacognition/        # 元认知服务（意图线索记忆与注入，待定模块）
│   │   ├── self_improvement/     # 自我改进系统（学习日志+纠正追踪+核心记忆+晋升+漂移防护）
│   │   │   ├── service.py        # SelfImprovementService 主服务
│   │   │   ├── models.py         # 数据模型
│   │   │   ├── learning_logger.py # 结构化学习/错误/功能请求日志
│   │   │   ├── correction_tracker.py # 通用纠正检测（6 种信号）+ 纠正晋升
│   │   │   ├── core_memory.py    # MEMORY.md 核心记忆管理（6 分区+自动瘦身+归档）
│   │   │   ├── learning_promoter.py # 学习晋升与模式检测
│   │   │   ├── daily_logger.py   # 每日日志
│   │   │   └── drift_guard.py    # 记忆漂移防护
│   │   ├── monitoring/           # 监控服务（hardware_monitor, resource_monitor, system_memory_service）
│   │   ├── life_simulation/      # 生命模拟服务（service 门面 + orchestrator 协调器 + coordinators/ 六大专职协调器 + life_stats, auto_eat, food_system, actor_manager, health_monitor, ritual_manager, meal_policy, meal_chat, sleep_food_effects, sleep_manager, sleep_models, sleep_state_store, protocols）
│   │   ├── study/                # 学习服务（service, dispatch, summary_generator, catalog, mode_detector, session, student_state, subject_analyzer, summary_builder, tutor_engine, weakness_tracker, daily_tracker, persona/；专注番茄钟: focus_session_service, focus_session_models, focus_monitor_policy）
│   │   ├── data_ops/             # 数据操作服务（BERT 语义分析流水线 + 日报/周报 + 记忆去噪 + 任务规划）
│   │   │   ├── service.py        # DataOpsService 单例（线程安全双重检查锁）
│   │   │   ├── analysis_pipeline.py # 三级异步 Worker 流水线（rule→ai-shadow→fusion）
│   │   │   ├── bert_analyzer.py  # BertAnalyzer 单例（意图识别+内容分析）
│   │   │   ├── bert_runtime_mixin.py # BERT ONNX 模型加载/推理/Embedding 缓存
│   │   │   ├── bert_proactive_mixin.py # 主动关怀分析
│   │   │   ├── bert_definitions.py # 静态定义数据
│   │   │   ├── queue.py          # DataOpsQueue（TTL 清理+最大数量限制）
│   │   │   ├── summary_worker.py # 日报/周报数据聚合
│   │   │   ├── task_planner_worker.py # 每日任务规划
│   │   │   ├── human_digest_worker.py # 人类可读日报/周报
│   │   │   ├── memory_compactor.py # 记忆去噪
│   │   │   └── api.py            # API 门面层
│   │   ├── command/              # 命令处理服务（新增）
│   │   │   └── handler.py        # CommandHandler（斜杠命令字典映射）
│   │   ├── communication/        # 通信服务（新增）
│   │   │   └── composer.py       # MessageComposer（UnifiedMessage 构造）
│   │   ├── discovery/            # 服务发现（新增）
│   │   │   └── udp_beacon.py     # UDPBeaconService（局域网广播，端口 28899）
│   │   ├── intent/               # 意图识别服务（新增）
│   │   │   └── service.py        # BERT + 正则规则混合意图识别
│   │   ├── maintenance/          # 维护服务（新增）
│   │   │   └── memory_sync.py    # sync_recent_memories_to_status
│   │   ├── reaction/             # 自发反应（新增）
│   │   │   └── reaction_manager.py # ReactionManager（冷却 5 分钟）
│   │   ├── remote_ops/           # 远程操作服务（新增）
│   │   │   ├── service.py        # RemoteOpsService（文件操作 list/read/write/append/mkdir/exists）
│   │   │   ├── approval.py       # ApprovalService（审批流，ApprovalRequest）
│   │   │   └── RemoteOps-Spec.md # 规范文档
│   │   ├── user_physiology/      # 用户生理状态（新增）
│   │   │   └── service.py        # UserPhysiologyService（runtime/user_physiology.json）
│   │   ├── vtube/                # VTube Studio 集成（新增）
│   │   │   └── service.py        # VTubeStudioService（pyvts，情绪驱动 hotkey）
│   │   ├── chat_history_store.py # 聊天历史存储
│   │   ├── error_log_store.py    # 错误日志存储
│   │   └── study_service.py      # 学习服务兼容入口
│   ├── tools/                    # 工具层（26+ 工具，详见 §4.6）
│   │   ├── study/                # 学习工具（math/english/chinese/biology/geography/common/libs/assets）
│   │   ├── base.py               # 工具基类
│   │   ├── file_tool_base.py     # 文件工具基类
│   │   ├── implementations.py    # 基础工具（Time/Calculator/WebSearch）
│   │   ├── registry.py           # 工具注册（register_all_tools 统一入口）
│   │   ├── daily_tool.py         # 日常记录工具
│   │   ├── diary_tool.py         # 日记工具
│   │   ├── plan_tool.py         # 明日学习生活计划工具（生成/查询/增删改查/TODO勾选）
│   │   ├── physiology_tool.py    # 生理数据工具
│   │   ├── food_tool.py          # 食物工具
│   │   ├── aveline_daily_data_tool.py # Aveline 每日数据
│   │   ├── study_data_tool.py    # 学习数据
│   │   ├── study_profile_tool.py # 学习画像
│   │   ├── study_tools.py        # 学习工具集
│   │   ├── study_mode_tool.py    # 学习模式开关
│   │   ├── reminder_tool.py      # 提醒工具
│   │   ├── status_tool.py        # 状态管理工具
│   │   ├── active_care_tool.py   # 主动关怀控制
│   │   ├── search_memory_tool.py # 记忆搜索
│   │   ├── search_chat_history_tool.py # 聊天历史搜索
│   │   ├── check_peer_status_tool.py # 查看对方角色状态
│   │   ├── character_daily_plan_tool.py # 查看自己/同伴角色日常计划
│   │   ├── message_peer_tool.py  # 给对方角色发消息
│   │   ├── notify_master_tool.py # 通知主人
│   │   ├── process_tool.py       # 系统进程查看
│   │   └── ad_classifier.py      # 广告分类器
│   ├── emotion/                  # 情绪系统
│   │   ├── calculator.py         # 情绪计算（衰减/累积，指数时间衰减模型）
│   │   ├── detector_smart.py     # 智能检测器（关键词+BERT）
│   │   ├── detector_v2.py        # LLM 标签提取器（[EMO: sad]/[难过]）
│   │   ├── manager.py            # 情绪管理器（Facade，RLock 线程安全）
│   │   ├── models.py             # 情绪模型
│   │   ├── constants.py          # 常量
│   │   └── store.py              # 情绪存储（JSONL 后台批量写入）
│   ├── voice/                    # 语音处理
│   │   ├── tts_engine.py         # TTS 引擎管理器
│   │   ├── engines/              # TTS 引擎实现
│   │   │   ├── base.py           # 引擎基类
│   │   │   ├── gpt_sovits_engine.py # GPT-SoVITS 引擎
│   │   │   ├── cloud_tts_engine.py # 云 TTS 引擎
│   │   │   ├── qwen3_tts_engine.py # Qwen3 TTS 引擎
│   │   │   ├── f5_tts_engine.py  # F5 TTS 引擎
│   │   │   └── mock_transformer.py # Mock Transformer
│   │   ├── cloud_tts_helpers.py  # Cloud TTS 会话与请求辅助
│   │   ├── stt_engine.py         # STT 引擎
│   │   └── qwen3_tts_cloud.py    # 云端 TTS
│   ├── image/                    # 图像处理
│   │   ├── image_manager.py      # 图像管理器
│   │   ├── forge_runtime.py      # Forge 运行时管理
│   │   ├── image_service_client.py # 图像服务客户端
│   │   ├── siliconflow_image_client.py # SiliconFlow 客户端
│   │   ├── image_utils.py        # 图像工具
│   │   ├── model_loader.py       # 模型加载器
│   │   └── prompt_processor.py   # 提示词处理器
│   ├── interfaces/               # 接口层
│   │   └── websocket/            # WebSocket 接口
│   │       ├── adapters/         # 适配器
│   │       │   ├── handlers/     # 消息处理器（connection/settings/chat 门面）
│   │       │   │   ├── chat/     # 聊天处理子包：merge(合并)/model_pref(模型偏好)/context(对话隔离)/
│   │       │   │   │             #   cid(跨平台共享cid)/active_care(晚安意图)/reply_policy(被动回复)/
│   │       │   │   │             #   prefetch(RAG预取)/connection(断开检测)/streaming(流式)/messages(规范化)/
│   │       │   │   │             #   facade(编排门面)；chat_handlers.py 仅为兼容转发入口
│   │       │   ├── streaming.py  # 流式处理器
│   │       │   ├── adapter.py    # 适配器主类
│   │       │   ├── demo.py       # 演示处理器
│   │       │   └── utils.py      # 工具
│   │       ├── fastapi_websocket_adapter.py
│   │       └── websocket_manager.py
│   ├── resource/                 # 资源管理模块（2026-05-29 重构）
│   │   ├── config.py             # 配置管理（ResourceConfig）
│   │   ├── monitor.py            # 资源监控+GPU 缓存（0.5 秒 TTL）
│   │   ├── model_manager.py      # 模型生命周期管理
│   │   ├── cleanup.py            # 清理策略（策略模式，动态冷却）
│   │   ├── gpu.py                # GPU 显存管理
│   │   └── manager.py            # 主管理器
│   ├── resource_manager.py       # 资源管理器（兼容层，从 resource/ 导入）
│   ├── resource_components.py    # 基础组件（ResourceMonitor, ModelResource）
│   ├── utils/                    # 统一工具函数
│   │   ├── timestamp_utils.py    # 时间戳处理（safe_timestamp, format_elapsed_seconds）
│   │   ├── client_utils.py       # 客户端探测
│   │   ├── config_accessor.py    # 配置访问
│   │   ├── history_utils.py      # 历史记录处理
│   │   ├── logger.py             # 日志工具
│   │   ├── log_sanitizer.py      # 日志脱敏
│   │   ├── log_cleanup.py        # 日志清理
│   │   ├── json_utils.py         # JSON 工具
│   │   ├── text_processor.py     # 文本处理
│   │   ├── resource_lock.py      # 资源锁（GPU 背压门控）
│   │   ├── atomic_io.py          # 原子文件 I/O（safe_json_dump/load，同步+异步）
│   │   ├── data_paths.py         # 数据路径
│   │   ├── singleton.py          # 单例工具
│   │   ├── performance_tracker.py # 性能追踪
│   │   ├── saga_manager.py       # Saga 事务管理
│   │   ├── style_retriever.py    # 风格检索
│   │   ├── time_utils.py         # 时间工具
│   │   ├── debug_markers.py      # 调试标记
│   │   ├── error_handler.py      # 错误处理
│   │   ├── error_handlers.py     # 错误处理器
│   │   ├── common.py             # 通用工具
│   │   ├── conversation_labels.py # 对话标签
│   │   ├── demo_utils.py         # 演示工具
│   │   └── static_files.py       # 静态文件
│   ├── async_cache.py            # 异步缓存
│   ├── async_monitor.py          # 异步监控
│   ├── exceptions.py             # 异常定义
│   ├── log_config.py             # 日志配置（向后兼容）
│   └── vector_search.py          # 向量搜索
├── memory/                       # 记忆系统（详见 §5）
│   ├── core/                     # 核心操作模块（36 个文件）
│   │   ├── analysis_ops.py       # 分析操作（融合裁决，FusionConfig/FusionResult）
│   │   ├── async_persistence.py  # 异步持久化（aiofiles + to_thread 回退）
│   │   ├── batch_ops.py          # 批量操作（单次锁获取）
│   │   ├── cache_ops.py          # 缓存操作
│   │   ├── concurrency_optimized.py # 并发优化（ConcurrentCache, ThreadSafeCounter, ReadWriteLock）
│   │   ├── discourse.py          # 话语类型分析
│   │   ├── distillation.py       # 记忆蒸馏（分段 recency_factor）
│   │   ├── history_ops.py        # 历史操作
│   │   ├── io_ops.py             # IO 操作
│   │   ├── keyword_index.py      # 关键词索引
│   │   ├── keyword_ops.py        # 关键词索引辅助与偏好视图
│   │   ├── lifecycle_ops.py      # 加载/清理/迁移/保存生命周期
│   │   ├── lock_utils.py         # 共享锁工具（get_read_lock/get_write_lock，13 子模块统一）
│   │   ├── maintenance_ops.py    # 维护操作
│   │   ├── manager_init_ops.py   # 布局与管理器基础初始化
│   │   ├── mutation_ops.py       # 变更操作
│   │   ├── performance_monitor.py # 性能监控
│   │   ├── persistence.py        # 持久化
│   │   ├── preferences.py        # 偏好
│   │   ├── readable_ops.py       # readable/history 导出与回填
│   │   ├── recall_probability.py # 召回概率
│   │   ├── record_ops.py         # 记录规范化/去重/readable 视图
│   │   ├── retrieval_ops.py      # 检索操作（话题缓存 30 秒 TTL）
│   │   ├── retrieval_ops_optimized.py # 增量主题缓存（TopicWeightCache）
│   │   ├── runtime_ops.py        # auto-save/trim/运行时调度
│   │   ├── scoring_utils.py      # 统一评分函数（compute_hybrid_score_with_result）
│   │   ├── search.py             # 搜索核心
│   │   ├── state_ops.py          # 状态操作
│   │   ├── storage.py            # 存储操作（MemoryContext/MemoryInput dataclass）
│   │   ├── taxonomy.py           # 分类法
│   │   ├── text_segmenter.py     # 文本分词器（_UNIFIED_STOPWORDS）
│   │   ├── unified_cache_manager.py # 统一缓存管理器（嵌入/查询/记忆 L1-L2/主题）
│   │   ├── utils.py              # 工具（extract_keywords 限 30 个）
│   │   ├── vector_ops.py         # 向量操作
│   │   └── weights.py            # 权重计算
│   ├── weighted_memory_manager.py # 记忆管理器主类（融合版，模块级 _instances + 清理机制）
│   ├── embedding_generator.py    # 向量嵌入生成
│   ├── nightly/                  # 夜间处理（薄 TaskRunner + 蒸馏执行/Codec + Global 编排）
│   ├── nightly_processor.py      # 夜间处理门面（保留兼容接口）
│   ├── persistent_state.py       # 持久化状态
│   ├── keyword_index_mixin.py    # 关键词索引 Mixin
│   ├── persistence_mixin.py      # 持久化 Mixin
│   ├── save_scheduler_mixin.py   # 保存调度 Mixin
│   ├── search_mixin.py           # 搜索 Mixin
│   ├── shadow_analysis_mixin.py  # 影子分析 Mixin
│   └── README_VECTOR_SEARCH.md   # 向量搜索文档
├── multimodal/                   # 多模态（image_gen.py 已删除）
│   ├── stt_connector.py          # STT 连接器（VAD 管线）
│   └── tts_manager.py            # TTS 缓存管理器（TTSCacheManager）
├── routers/                      # 路由层（2026-06-15 重构为 v1/+admin/）
│   ├── v1/                       # 业务路由（统一前缀 /api/v1/）
│   │   ├── chat.py               # 聊天 API（/chat/message, /chat/persona, /chat/greeting, /chat/regenerate）
│   │   ├── sessions.py           # 会话管理
│   │   ├── health.py             # 健康检查（聚合 services/lifecycle/resources/gpu_gate/tasks）
│   │   ├── user.py               # 用户状态
│   │   ├── personas.py           # 人设管理
│   │   ├── models.py             # 模型管理
│   │   ├── plugins.py            # 插件管理（敏感模式开关）
│   │   ├── peer_chat.py          # 双角色对话
│   │   ├── food.py               # 食物系统
│   │   ├── vision.py             # 视觉理解
│   │   ├── life.py               # 生命状态
│   │   ├── system.py             # 系统状态/主动关怀/联网搜索
│   │   ├── memories.py           # 记忆管理
│   │   ├── context.py            # 上下文同步/每日记录/意图识别
│   │   ├── media.py              # 多媒体（STT/TTS/upload）
│   │   ├── vocab.py              # 词汇与学习工具集
│   │   ├── tutor.py              # 教学域
│   │   ├── diary.py              # 日记
│   │   ├── tasks.py              # 每日任务
│   │   └── workspace.py          # Study 工作区联动
│   ├── admin/                    # 运维路由（规范前缀 /api/v1/admin/，memory_watchdog 兼容旧 /api/v1/memory/）
│   │   ├── auto_heal.py          # 自愈系统
│   │   ├── data_ops.py           # 数据运维
│   │   ├── remote_ops.py         # 远程操作
│   │   └── memory_watchdog.py    # 内存监控（规范 /api/v1/admin/memory/，兼容 /api/v1/memory/）
│   ├── openai_compat.py          # OpenAI 兼容 API（/v1/chat/completions，独立挂载）
│   ├── websocket.py              # WebSocket 路由（/api/v1/ws）
│   ├── demo.py                   # 演示路由
│   └── __init__.py               # 路由聚合（api_v1_router 唯一前缀声明点）
├── cpp_modules/                  # C++ 加速模块集合
│   ├── cpp_scheduler/            # C++ 调度引擎（三队列隔离：LLM/TTS/图像）
│   ├── cpp_memory_index/         # 高性能向量索引（SIMD 余弦，OpenMP 并行）
│   ├── cpp_fast_tokenizer/       # 轻量 Token 计数（UTF-8 字符类型估算）
│   ├── cpp_audio_processor/      # 音频预处理 + VAD（RMS 能量阈值）
│   └── cpp_bert_engine/          # BERT 推理引擎（ONNX Runtime）
├── config/                       # 配置管理（单一数据源）
│   ├── integrated_config.py      # 配置主入口（Settings + get_settings）
│   ├── yaml_loader.py            # YAML 解析/环境变量展开/配置映射
│   ├── model_detector.py         # 本地模型自动探测
│   ├── model_config.py           # 模型配置（resolve_active_care_model_path）
│   ├── cache_manager.py          # 启动缓存管理
│   ├── debug_config.py           # Debug 日志集中配置（24 个开关）
│   ├── task_scheduler_config.py  # 任务调度配置
│   ├── settings_server.py        # 服务器配置子模块
│   ├── settings_model.py         # 模型配置子模块
│   ├── settings_chat.py          # 聊天配置子模块
│   ├── settings_life.py          # 生命模拟配置子模块
│   ├── settings_infra.py         # 基础设施配置子模块
│   ├── settings_core.py          # 核心配置子模块
│   ├── _base.py                  # 基础配置类
│   └── yaml/                     # YAML 配置文件
│       ├── app.yaml              # 主配置文件
│       └── env.yaml              # 环境配置
├── tests/                        # 测试系统
│   ├── unit/                     # 单元测试
│   ├── integration/              # 集成测试
│   ├── diagnostics/              # 诊断工具（100+ 文件）
│   ├── stress/                   # 压力测试
│   ├── benchmark/                # 基准测试
│   ├── scheduler/                # 调度器测试
│   ├── self_improvement/         # 自我改进测试
│   ├── experiments/              # 实验脚本
│   ├── prototypes/               # 原型演示
│   ├── scripts/                  # 测试脚本（含 git_watchdog.ps1）
│   ├── auto_heal/                # 自愈测试
│   ├── verification/             # 验证脚本（新增）
│   └── conftest.py               # pytest 配置
├── maintenance/                  # 维护工具
│   ├── diagnose_backend.py       # 后端诊断
│   ├── check_imports.py          # 导入检查
│   ├── find_large_files.py       # 大文件查找
│   ├── code_semantic_index.py    # 代码语义索引
│   ├── hybrid_memory_analysis_playbook.md # 记忆分析手册
│   └── backend_tidy_backlog_2026-03-06.md # 待办清单
├── scripts/                      # 脚本工具
│   ├── build_cpp_modules.py      # C++ 模块构建
│   ├── verify_optimization.py    # 优化验证
│   ├── optimize_memory.py        # 记忆优化
│   └── ...
├── start_scripts/                # 启动脚本
│   ├── start_qq_bot.bat          # 单 QQ 启动
│   ├── start_multi_qq_bot.bat    # 多 QQ 启动
│   ├── start_web.bat             # Web 启动
│   ├── start_services.bat        # 服务启动
│   └── start_frp.bat/ps1         # FRP 启动
├── main.py                       # 主入口
├── server_run.py                 # 服务器启动
├── launcher.py                   # 启动器
├── desktop_app.py                # 桌面应用
├── build_exe.py                  # EXE 构建
├── pyproject.toml                # 项目配置
├── Dockerfile                    # Docker 配置
├── docker-compose.yml            # Docker Compose
└── start.bat                     # Windows 启动
```

## 2. 核心引擎层技术详解

### 2.x 状态契约统一（避免漂移）

项目中“资源状态、模型状态、服务健康、任务状态”曾在多个模块各自定义/各自输出，长期会导致 API 字段漂移、监控/调试困难。

现在统一收敛为：

- 统一枚举：`core/contracts/states.py`
- `/health` 聚合端点会同时输出：
  - `resources`（系统资源快照，来自 `core/services/monitoring/resource_monitor.py::to_contract_dict()`）
  - `resource_manager`（模型/显存调度快照，来自 `core/resource_manager.py::get_resource_stats()`，包含 `snapshot`）
  - `gpu_gate`（全局 GPU 背压门控状态，来自 `core/utils/resource_lock.py`）
  - `tasks`（活跃任务列表，来自 `core/services/scheduler/task_scheduler.py`）
  - `lifecycle`（服务初始化状态，来自 `core/core_engine/lifecycle_manager.py`）

其中：

- `TaskStatus` 对齐 `pending/running/completed/failed/cancelled`
- 模块初始化态使用 `ModuleInitState`（例如 LLM/调度器适配器会在 `get_status()/get_stats()` 中增加 `init_state` 字段）
- 模型运行态与初始化态分离：`ModelRuntimeState`（loaded/offloaded/unloaded）不等同于 `ModuleInitState`

建议：新模块对外输出状态时优先复用契约枚举值，避免再引入 `queued/processing` 等不一致的字符串。

### 2.1 CoreEngine 类（已删除）

> **已删除 (2026-06-17)**：`core/core_engine/engine.py` 已作为死代码删除。该文件头部明确标注"已废弃，已被 ServiceLifecycle + EventBus 完全覆盖"。全项目搜索确认生产代码无任何 import 引用。
>
> 当前核心引擎层的职责由以下组件承担：
> - **EventBus** (`event_bus.py`)：事件总线
> - **LifecycleManager** (`lifecycle_manager.py`)：生命周期管理（`ServiceLifecycle` 类）
> - **ServiceRegistry** (`service_registry.py`)：默认服务注册逻辑
> - **ServiceSingletons** (`service_singletons.py`)：业务单例管理（Aveline/Vision/ActiveCare）
> - **ModelManager** (`model_manager.py`)：模型管理
> - **ConfigManager** (`config_manager.py`)：配置管理

启动流程改为：

```
main.py → core/lifecycle/lifespan.py → lifecycle_manager.initialize_default_services()
                                      → lifecycle_manager.initialize_all()
```

### 2.2 LifecycleManager 类

**文件**: `core/core_engine/lifecycle_manager.py`

**职责**: 服务注册、并行初始化、优雅关闭、自动重启

**启动流程**:

```
main.py → lifespan.py → lifecycle_manager.initialize_default_services()
                        → lifecycle_manager.initialize_all()
```

**服务优先级分组**（同优先级并行初始化，跨优先级串行）:

| 优先级 | 服务 | 说明 |
|--------|------|------|
| 1 | resource_manager, log_sanitizer, cpu_processor | 基础资源层，互不依赖 |
| 2 | config_manager, search_cache_manager, cache_system, system_memory_manager | 配置与缓存层 |
| 3 | image_manager, cpp_scheduler_engine | 调度器层（依赖 resource_manager） |
| 4 | task_scheduler, monitoring_system | 任务与监控层 |
| 5 | immune_system, websocket_adapter | 安全与通信层 |
| 6 | aveline_service, active_care_service | 业务服务层，互不依赖 |
| 7 | auto_heal_service | 自愈服务（依赖 aveline_service 进行 LLM 分析） |

**关键优化**:
- 延迟导入：所有服务注册使用函数级延迟导入，避免启动时加载重模块
- 预加载机制：并行初始化前先串行预加载 `preload_modules` 中的模块
- `asyncio.gather()` 实现同优先级服务的并行初始化

### 2.3 EventBus 类

**文件**: `core/core_engine/event_bus.py`

**职责**: 模块间通信、事件发布订阅

**关键方法**:

```python
class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._event_queue: asyncio.Queue = asyncio.Queue()
    
    def subscribe(self, event_type: str, handler: Callable) -> None:
        """订阅事件"""
    
    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """取消订阅"""
    
    async def publish(self, event_type: str, data: Any) -> None:
        """发布事件"""
    
    async def _process_events(self) -> None:
        """事件处理循环"""
```

**事件类型**:

| 事件类型              | 说明     | 数据结构                     |
| ----------------- | ------ | ------------------------ |
| `system.startup`  | 系统启动   | `{}`                     |
| `system.shutdown` | 系统关闭   | `{}`                     |
| `model.loaded`    | 模型加载完成 | `{model_id, model_type}` |
| `model.unloaded`  | 模型卸载完成 | `{model_id}`             |
| `memory.updated`  | 记忆更新   | `{memory_id, weight}`    |
| `emotion.changed` | 情绪变化   | `{emotion, intensity}`   |

### 2.3 ResourceManager 类

**目录**: `core/resource/`（主模块）, `core/resource_manager.py`（兼容层）

**职责**: 统一管理系统资源（内存、CPU、GPU、磁盘），并将基础资源组件与主调度逻辑解耦

**模块结构**（2026-05-29重构）:

现在采用模块化结构：

- `core/resource/config.py` — 配置管理（ResourceConfig数据类）
- `core/resource/monitor.py` — 资源监控 + GPU缓存优化（0.5秒TTL）
- `core/resource/model_manager.py` — 模型生命周期管理
- `core/resource/cleanup.py` — 清理策略（策略模式，支持动态冷却时间）
- `core/resource/gpu.py` — GPU显存管理和模型卸载/加载
- `core/resource/manager.py` — 主管理器，整合所有子模块
- `core/resource_components.py` — 基础组件（ResourceMonitor, ModelResource等）
- `core/resource_manager.py` — 兼容层，从新模块导入

**关键方法**:

ResourceManager类提供以下核心功能：
- 模型注册/卸载管理
- 重负载任务资源准备
- 三级清理策略（常规/临界/紧急）
- GPU模型自动回迁
- 资源状态监控和统计

**资源优先级**:

| 优先级 | 模型类型      | 说明    |
| --- | --------- | ----- |
| 10  | LLM       | 最高优先级 |
| 8   | Vision    | 视觉模型  |
| 6   | TTS       | 语音合成  |
| 4   | Image Gen | 图像生成  |
| 2   | STT       | 语音识别  |

***

## 3. 服务层技术详解

### 3.1 AvelineService

**文件**: `core/services/aveline/service.py`

**职责**: 对话主编排服务

**关键方法**:

```python
class AvelineService:
    def __init__(self):
        self.chat_agent: ChatAgent = None
        self.memory_manager: WeightedMemoryManager = None
        self.emotion_manager: EmotionManager = None
        self._ling_social_state: OrderedDict[str, Dict[str, Any]] = OrderedDict()  # LRU缓存，最大128条
        self._ling_social_state_max_size = 128

    async def _prepare_conversation_context(
        self, *, user_input, conversation_id, system_prompt,
        length_preference, persona_filename, is_stream=True
    ) -> Tuple[Dict, Dict, Optional[str]]:
        """公共上下文准备：角色配置加载、双角色运行时解析、社交状态更新、
        系统提示词构建（动态上下文+双角色+仿生状态+身份守卫）"""

    async def chat(self, message: str, context: Dict) -> AsyncGenerator:
        """处理对话消息"""
        # 1. _prepare_conversation_context（公共上下文准备）
        # 2. 意图识别
        # 3. 记忆检索
        # 4. 情绪更新
        # 5. LLM调用
        # 6. 记忆写入
        # 7. 流式返回

    async def stream_chat(self, message: str, context: Dict) -> AsyncGenerator:
        """流式对话"""
```

**子模块架构**:

| 文件 | 职责 |
|------|------|
| `service.py` | 主服务类，对话生成、主动消息分发、视觉分析 |
| `stream_orchestrator.py` | 流式对话事件编排、缓存、去重、TTFT追踪 |
| `command_handler.py` | 系统命令处理（/clear, /mode, /care 等） |
| `control_intent.py` | 自然语言控制意图识别（BERT + 关键词） |
| `mode_control.py` | 模式切换（隐私、学习、普通） |
| `prompt_policy.py` | 系统提示词构建策略 |
| `response_postprocess.py` | 响应后处理链（情绪→重写→媒体→日计划） |
| `response_media.py` | 自动媒体富化（图片生成、TTS） |
| `dual_role/` | 双角色协调子系统 |

**真流式响应事件时序**:

对话流式回复采用「真流式」逐块推送，事件时序如下：

```
普通文本阶段  → token 逐字符推送（立即到达前端）
AI 调用工具   → response_reset（前端清空当前临时消息，历史不动）
                + discard_turn() 丢弃中间轮次缓冲
工具执行完成  → 最终回答 token 逐字符继续推送
全部完成      → response_done（前端标记完成；后端此刻才把完整结果写入数据库）
```

**关键规则**:
- 普通文本立即逐块发送，不等待整轮结束。
- `response_reset` 只在工具调用轮次出现；Android 收到后只清空当前正在生成的那条消息（`ChatFlushManager.onResponseReset()`）。
- 落库（`_save_conversation_history`）严格推迟到 `response_done` 之后调度。
- 事件产出：`core/agents/chat_agent_components/streaming.py` + `streaming_pipeline/tag_stream_parser.py`（token 实时队列 `rt_emits`）；SSE 映射：`stream_orchestrator.py`。

**依赖服务**:

- ChatAgent: 聊天代理
- WeightedMemoryManager: 记忆管理
- EmotionManager: 情绪管理
- SchedulerService: 任务调度
- ActiveCareStorage: 主动关怀状态（通过 `get_last_thought()` 异步 API 或 `get_last_thought_sync()` 同步 API）

### 3.2 ActiveCareService

**文件**: `core/services/active_care/core/service.py`

**职责**: 主动关怀服务

**模块化架构**:

```python
class ActiveCareService:
    def __init__(self):
        self.storage = ActiveCareStorage()
        self.context = ActiveCareContext(self.storage)
        self.scheduler_logic = ActiveCareSchedulerLogic()
        self.decision = ActiveCareDecision(self.storage)
        self.executor = ActiveCareExecutor(self.context, self.storage)
        self.vocab = ActiveCareVocabulary(self.storage)
        self.mode_state = ActiveCareModeState()
        self.checker = ProactiveChecker(...)
```

**子模块架构**（2026-04-28 代码审查优化后，2026-06-19 阶段 A 八轨道拆分，2026-06-19 目录整理为子目录）:

| 模块                 | 文件                     | 职责                                     |
| ------------------ | ---------------------- | -------------------------------------- |
| constants          | `shared/constants.py`  | 统一状态键、关键词常量、私密模式常量、**睡眠状态描述构建**、**build_sleep_status_description**、**build_reduced_mode_clear_updates**、**build_goodnight_clear_updates**、**extract_json_block** |
| prompt\_builder    | `prompt/prompt_builder.py` | Prompt 组装（19个 section）；上下文构建已拆分到 `prompt/prompt_context_builders.py`，话题多样性已拆分到 `prompt/topic_diversity.py`，保留转发方法 |
| prompt\_context\_builders | `prompt/prompt_context_builders.py` | Prompt 上下文构建（设备/生物/健康/食物/学习上下文，人设风格加载） |
| topic\_diversity   | `prompt/topic_diversity.py` | 话题多样性控制（detect_topic_category，check_topic_cooldown，build_topic_diversity_constraint） |
| persona\_resolver  | `core/persona_resolver.py` | 人设文件名解析、prompt 加载、语气参考构建、sensitive模式检测 |
| postprocessor      | `postprocess/postprocessor.py` | 后处理管线；睡眠净化已拆分到 `postprocess/sleep_sanitizer.py`，去重已拆分到 `postprocess/deduplicator.py`，泄露检测已拆分到 `postprocess/leak_detector.py`，保留转发方法 |
| sleep\_sanitizer   | `postprocess/sleep_sanitizer.py` | 睡眠净化器（SleepSanitizer，晚安/睡眠状态消息过滤） |
| deduplicator       | `postprocess/deduplicator.py` | 去重器（Deduplicator，发送历史相似度检测） |
| leak\_detector     | `postprocess/leak_detector.py` | 泄露检测器（LeakDetector，提示词泄漏检测与拦截） |
| state\_persistence | `storage/state_persistence.py` | 状态持久化（事件记录、发送历史）                       |
| executor           | `core/executor.py`     | 核心编排器薄壳门面（协调上述模块）；QQ 连接解析已拆分到 `core/qq_connection_resolver.py`，LLM 生成已拆分到 `core/response_generator.py`，硬件意图已拆分到 `core/hardware_intent.py`，历史解析已拆分到 `core/history_processor.py`，LLM 输入构建已拆分到 `core/input_builder.py`，上下文组装已拆分到 `core/context_builder.py`，会话路由已拆分到 `core/conversation_router.py`，消息分发已拆分到 `core/message_dispatcher.py`，提醒处理已拆分到 `core/reminder_handler.py`，保留 trigger_message 核心调度 + 12 兼容入口 + 8 委托方法 + get_active_care_executor 工厂函数 |
| history\_processor | `core/history_processor.py` | 历史消息纯解析（HistoryProcessor，emoji 剥离/最近历史文本/助手消息提取/时间戳解析） |
| input\_builder     | `core/input_builder.py` | LLM 输入构建（ModelInputBuilder，沉默区间策略/自问自答防护/晚安守卫/主动触发输入） |
| context\_builder   | `core/context_builder.py` | 上下文组装+Prompt（TriggerContextBuilder，历史缓存/触发上下文/睡眠状态/模式状态/Prompt 构建） |
| conversation\_router | `core/conversation_router.py` | 会话路由（ConversationRouter，目标会话解析/QQ persona conversation_id 构建） |
| message\_dispatcher | `core/message_dispatcher.py` | 消息分发+回调（MessageDispatcher，消息分发/状态保存/日记写入/非响应计数/主动消息持久化） |
| reminder\_handler  | `core/reminder_handler.py` | 提醒处理（ReminderHandler，到期提醒检查/完成/格式化） |
| decision\_executor | `decision/decision_executor.py` | 决策执行器；动作构建已拆分到 `decision/action_builder.py`，上下文采集已拆分到 `decision/context_gatherer.py`，保留转发方法 |
| action\_builder    | `decision/action_builder.py` | 动作构建器（build_available_actions，apply_action_overrides，should_force_send） |
| context\_gatherer  | `decision/context_gatherer.py` | 上下文采集器（get_workspace_snapshot，get_recent_history，get_user_signal_and_intent，build_urgent_needs） |
| decision           | `decision/decision.py` | LLM 决策 + Bandit 动作选择；输出解析已拆分到 `decision/decision_output_parser.py`，指令构建已拆分到 `decision/decision_instruction_builder.py`，保留转发方法 |
| decision\_output\_parser | `decision/decision_output_parser.py` | 决策输出解析（_parse_decision_output，JSON 修复，regex fallback，peer chat 输出解析） |
| decision\_instruction\_builder | `decision/decision_instruction_builder.py` | 决策指令构建（_build_daily_routine_probe_instruction，_build_specific_instruction） |
| proactive\_checker | `core/proactive_checker.py` | 薄壳门面 + 核心协调器（保留 perform_check/_run_decision_core）；睡眠会话状态机已拆分到 `core/sleep_session_manager.py`，初始化/状态恢复已拆分到 `checker/checker_init_state.py`，客户端门控已拆分到 `checker/checker_client_gate.py`，节流调度已拆分到 `checker/checker_throttle.py`，状态检测已拆分到 `checker/checker_state_detector.py`，事件检测已拆分到 `checker/checker_event_handler.py`，动作流程已拆分到 `checker/checker_action_flow.py`，时间检测已拆分到 `checker/checker_time_gate.py`，睡眠会话兼容垫片已拆分到 `checker/sleep_session_compat.py`（mixin 继承），本类保留转发方法向后兼容 |
| checker\_init\_state | `checker/checker_init_state.py` | 检查器初始化与状态恢复（CheckerInitState）：决策时间戳管理、per-persona 独立决策时间、从持久化存储恢复状态 |
| checker\_client\_gate | `checker/checker_client_gate.py` | 检查器客户端门控（CheckerClientGate）：活跃客户端检测、用户进程活动检测、私密/敏感模式检测、客户端类型探测 |
| checker\_throttle | `checker/checker_throttle.py` | 检查器节流与时间调度（CheckerThrottle）：间隔抖动计算（apply_interval_jitter）、非响应退避乘数计算 |
| checker\_state\_detector | `checker/checker_state_detector.py` | 状态检测（CheckerStateDetector，从 proactive_checker.py 拆分）：`execute_decision_flow`（决策流程准备）、`build_unified_decision_ctx`（统一决策上下文）、`inject_peer_chat_info`（双角色互聊注入）、`check_daily_record_auto_wakeup`（起床自动退出睡眠）、`execute_peer_chat_check`（已废弃兼容）。构造器接收 `checker=self`，方法内通过 `checker.xxx` 访问原 self 属性 |
| checker\_event\_handler | `checker/checker_event_handler.py` | 事件检测（CheckerEventHandler，从 proactive_checker.py 拆分）：`handle_due_reminder`（到期提醒处理，含重试策略、间隔保护、起床提醒跳过）。构造器接收 `checker=self` |
| checker\_action\_flow | `checker/checker_action_flow.py` | 动作流程（CheckerActionFlow，从 proactive_checker.py 拆分）：`build_priority_and_select_action`（优先级构建+动作选择+LLM决策）、`execute_send_or_skip`（发送/跳过执行，含交互保护、硬性间隔、退避）。构造器接收 `checker=self` |
| checker\_time\_gate | `checker/checker_time_gate.py` | 时间检测（CheckerTimeGate，从 proactive_checker.py 拆分）：`apply_silence_overrides`（长沉默和无发送超时覆盖逻辑，委托 DecisionExecutor.should_force_send）。构造器接收 `checker=self` |
| sleep\_session\_compat | `checker/sleep_session_compat.py` | 睡眠会话兼容 mixin（SleepSessionCompatMixin，从 proactive_checker.py 拆分）：10 个委托给 `self._sleep_session_manager` 的兼容垫片方法。ProactiveChecker 通过继承此 mixin 保持向后兼容 |
| sleep\_session\_manager | `core/sleep_session_manager.py` | 晚安低打扰状态机；即时入口按 `reason/label` 严格区分学习专注与晚安，`WAKEUP_NOW` 必须由明确的当前起床陈述确认；清醒信号只退出低打扰，不再把推断时刻同步为正式睡眠/起床事实。通过 weakref 持有 checker 引用以支持 `_get_config_value` 的运行时 mock |
| intent\_detector   | `detection/intent_detector.py` | 意图检测（**BERT语义先行+关键词兜底**，新增 `_detect_bert_state_event()` 通用BERT状态事件检测）                 |
| activity\_detector | `detection/activity_detector.py` | 活动检测；活动映射已拆分到 `detection/activity_maps.py`，保留转发方法 |
| activity\_maps     | `detection/activity_maps.py` | 活动映射表（is_system_process，classify_by_process_name，classify_by_window_title，extract_relevant_keyword） |
| priority\_analyzer | `decision/priority_analyzer.py` | 优先级分析；每日推送已拆分到 `decision/daily_push_priority.py`，画像关键词已合并到 `decision/portrait_keyword_map.py`，保留转发方法 |
| daily\_push\_priority | `decision/daily_push_priority.py` | 每日推送优先级（build_daily_push_priority_candidates，analyze_daily_push_priority，persist_daily_push_priority_analysis） |
| portrait\_keyword\_map | `decision/portrait_keyword_map.py` | 画像关键词映射（check_portrait_keyword_coverage，detect_user_already_covered，**统一了 decision.py 和 priority_analyzer.py 的重复映射**） |
| schedule\_adapter  | `scheduling/schedule_adapter.py` | 作息学习适配器（从每日记录学习作息规律，动态调整推断睡眠时间窗口和沉默阈值，自适应白天判定，30分钟缓存） |
| schedule\_config\_loader | `scheduling/schedule_config_loader.py` | 作息调度配置加载（load_schedule_configs，build_default_push_schedule，build_default_quiet_hours，cleanup_legacy_schedule_files） |
| gate\_scorer       | `detection/gate_scorer.py` | 软评分门控系统（7层门控从硬拦截改为评分制0.0-1.0，硬门控仍为硬拦截，软门控加权几何平均，概率决策） |
| scheduler\_logic   | `scheduling/scheduler_logic.py` | 智能心跳间隔计算（随机因子 0.85~1.15，边界 max(active,quiet)*2） |
| storage            | `storage/storage.py`    | 持久化（JSON + 延迟写入缓冲）+ **get_last_thought 异步方法**；共享低打扰状态与带来源的 Samsung Health 睡眠区间统一写入用户级 `user_sleep_state.json` |
| context            | `core/context.py`       | 上下文管理；会话解析已拆分到 `core/conversation_resolver.py`，作息配置已拆分到 `scheduling/schedule_config_loader.py`，保留转发方法 |
| conversation\_resolver | `core/conversation_resolver.py` | 会话 ID 解析与候选排序（resolve_primary_conversation_id，缓存，persona token 匹配） |
| peer\_script\_generator | `peer_chat/peer_script_generator.py` | 剧本生成；分发已拆分到 `peer_chat/peer_script_dispatch.py`，后处理钩子已拆分到 `peer_chat/peer_script_hooks.py`，保留转发方法 |
| peer\_script\_dispatch | `peer_chat/peer_script_dispatch.py` | 剧本分发（dispatch_script，逐条 WebSocket 广播） |
| peer\_script\_hooks | `peer_chat/peer_script_hooks.py` | 剧本后处理钩子（run_peer_post_hooks，日记/社交事件/巡逻触发） |

**统一工具函数**（2026-04-26 DRY优化新增）:

| 工具函数 | 位置 | 用途 |
| --- | --- | --- |
| `resolve_active_care_model_path()` | `config/model_config.py` | 统一模型路径解析（优先级：hint→config→settings→LLM→provider） |
| `should_force_send()` | `decision/action_builder.py` | 统一长沉默/无发送超时覆盖判断（从 decision_executor.py 迁移） |
| `build_sleep_status_description()` | `shared/constants.py` | 统一睡眠状态描述文本构建 |
| `build_reduced_mode_clear_updates()` | `shared/constants.py` | 统一构建 reduced_mode 清理状态字典（5字段重置） |
| `build_goodnight_clear_updates()` | `shared/constants.py` | 统一构建 goodnight+reduced_mode 清理状态字典（7字段重置） |
| `_get_scheduler_engine()` | `decision/decision.py` | CPPSchedulerEngine 模块级单例缓存 |
| `safe_timestamp()` | `core/utils/timestamp_utils.py` | 统一时间戳解析（毫秒→秒自动转换） |

**决策算法**: 题材感知 MDP（马尔可夫决策过程）+ Contextual Bandit 兜底

```python
# 题材感知 MDP（新增，决策主路径）
# decision/mdp.py：状态 S = (tod_slot, last_topic_sub, last_reply)
#   - tod_slot: 时段槽位（day/night/late_night）
#   - last_topic_sub: 上一条主动消息的题材子类型（sleep/food/study/care/vehicle/greeting）
#   - last_reply: 上一轮用户是否回复（replied/ignored/none，用时间戳比较派生）
# Q 表：active_care_mdp.json，键 "<state>::<action>"，增量 Q-learning（学习率 0.15 随样本衰减）
# 接入：decision_executor.select_action → MDP 优先；Q 表为空/异常回退 bandit

# 题材分类（新增）
# decision/topic_classifier.py：intent 主类 + topic_diversity.detect_topic_category 子类型
#   → 标签 "share_thought:food"，发送时经 persist_proactive_message 记录 last_sent_topic

# 自发做事排除：activity_transition / activity_return 告别消息传 self_activity=True，
# 不记录题材、不进 MDP/bandit 学习闭环

# Contextual Bandit（保留，作为 MDP 冷启动兜底）
class ActiveCareDecision:
    async def select_action_bandit(self, ctx: Dict, actions: List[str]) -> str:
        """使用Contextual Bandit选择动作"""
        # 1. 计算每个动作的期望奖励
        # 2. 应用探索/利用策略
        # 3. 返回最优动作
    
    async def update_policy_reward(self, action: str, reward: float):
        """更新动作奖励值"""
```

**动作类型**:

| 动作       | 触发条件      | 说明   |
| -------- | --------- | ---- |
| greeting | 静默时间 > 阈值 | 问候   |
| reminder | 有未完成提醒    | 提醒   |
| weather  | 天气变化      | 天气提醒 |
| health   | 能量低/饥饿    | 健康关怀 |
| emotion  | 情绪低落      | 情绪关怀 |
| study    | 学习时间      | 学习提醒 |
| random   | 随机触发      | 随机闲聊 |

### 3.3 WorkspaceService

**文件**: `core/services/workspace/service.py`

**职责**: 工作空间统一记录执行层

用户自动学习计划的唯一生成真源是 Journal `plan.json`。`WorkspaceDailyTaskService.generate_daily_tasks_from_progress()` 只把主计划映射为 `source=journal_plan_snapshot` 的 MDP 快照，不再调用 Tutor/学习摘要生成第二套任务，也不为自动镜像项创建硬提醒。Workspace 手动任务和用户明确修改的定时项仍保留原提醒语义。

**存储路径**:

| 数据类型   | 存储路径                                                                          |
| ------ | ----------------------------------------------------------------------------- |
| 用户状态   | `companion_data/user_data/status/user_status.json`                            |
| 日记     | `companion_data/user_data/daily/YYYY/MM/DD/diary/*.json`                      |
| 明日计划   | `companion_data/user_data/daily/YYYY/MM/DD/plan.json`                         |
| 每日画像   | `companion_data/user_data/daily_records/YYYY/M/D/daily_record.json`           |
| 提醒     | `companion_data/user_data/reminders.json`                                     |
| 角色仿生档案 | `companion_data/aveline_data/aveline_life/YYYY/M/D/bionic_delay_profile.json` |
| 角色进食记录 | `companion_data/aveline_data/life_records/YYYY/M/D/daily_record.json`         |

**关键方法**:

```python
class WorkspaceService:
    async def get_daily_workspace_snapshot(self, date: str) -> Dict:
        """获取每日工作空间快照"""
        return {
            "status": await self.status_manager.get_status(),
            "journal": await self.journal_service.get_entries(date),
            "reminders": await self.reminder_manager.get_reminders(date),
            "daily_record": await self.daily_manager.get_record(date),
        }
```

### 3.4 SchedulerService

**文件**: `core/services/scheduler/task_scheduler.py`

**职责**: 全局任务调度

**任务优先级**:

```python
class TaskPriority(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3
```

**任务类型**:

```python
class TaskType(Enum):
    DEFAULT = "default"      # IO密集型
    CPU_BOUND = "cpu_bound"  # CPU密集型
    GPU_BOUND = "gpu_bound"  # GPU密集型
```

**关键方法**:

```python
class GlobalTaskScheduler:
    async def submit_task(
        self,
        name: str,
        coro: Callable,
        priority: TaskPriority = TaskPriority.MEDIUM,
        task_type: TaskType = TaskType.DEFAULT,
    ) -> str:
        """提交任务"""
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
    
    async def get_task_status(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务状态"""
```

***

### 3.5 MetaIntentService（元认知服务）— ⚠️ 待定模块

**文件**: `core/services/metacognition/service.py`

**当前状态**: 此模块的功能已被现有系统覆盖，暂不接入主流程。

**覆盖情况**:

| 元认知功能 | 已被覆盖的系统 |
|-----------|-------------|
| 意图追踪 | PersistentStateTracker + BERT 意图检测 |
| 主动提醒 | Active Care（reminder / health_reminder / wake_up_greeting） |
| 历史检索 | RAG search_memory（语义级检索） |
| 行为记录 | 日记系统（Journal）+ tomorrow_tone 回注 + 明日学习生活计划（Plan） |
| 计划执行 | 明日计划（PlanItem TODO 勾选）+ Priority 系统联动主动推送 |
| 去重/防重复 | Active Care 三层去重 + 二次改写 |

**潜在方向（待讨论）**:
- AI 回复风格的量化追踪与自适应
- 对话节奏感知（用户回复间隔变化趋势）
- 跨人设行为一致性校验

**相关 Bug 修复**: Active Care 话题冷却从只覆盖 sleep 扩展到覆盖所有已定义话题类别（greeting/care），见 `prompt_builder.py` 的 `check_topic_cooldown`

### 3.6 ImmuneSystemService（免疫系统服务）

**文件**: `core/services/immune/service.py`

**职责**: 系统自愈与资源保护，模拟生物免疫系统的自动检测、自动响应、自动修复机制

**核心架构**:

```python
class ImmuneSystemService:
    def __init__(self, *, settings, lifecycle, health_checker, performance_monitor):
        self._thresholds = _ThresholdConfig()   # 配置缓存
        self._stats = _ImmuneStats()            # 运行指标
        self._last_downgrade_level: int = 0     # 当前降级级别
        self._errors: Deque                      # 错误记录（最多5000条）

    async def _loop(self):                       # 每10秒自检循环
        await self._tick()

    async def _tick(self):                       # 每次循环执行两大策略
        await self._apply_resource_response()    # 资源应急响应
        await self._apply_service_self_heal()    # 服务自愈重启
```

**两大核心能力**:

| 能力 | 方法 | 说明 |
|------|------|------|
| 资源应急响应 | `_apply_resource_response()` | 监控 CPU/内存，双阈值策略（medium/emergency），智能避让活跃任务 |
| 服务自愈重启 | `_apply_service_self_heal()` | 检测不健康/未初始化服务，自动重启，限频保护 |

**配置项** (`ImmuneSettings`):

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| enabled | True | 是否启用 |
| interval | 10.0s | 自检间隔 |
| restart_window_seconds | 600s | 重启统计窗口 |
| max_restarts_per_window | 2 | 窗口内最大重启次数 |
| min_restart_interval_seconds | 30.0s | 两次重启最小间隔 |
| memory_medium_threshold | 90.0% | 内存中负载阈值 |
| memory_emergency_threshold | 96.0% | 内存紧急阈值 |
| cpu_medium_threshold | 95.0% | CPU中负载阈值 |
| cpu_emergency_threshold | 99.0% | CPU紧急阈值 |

**优化特性** (2026-04-27):

- **配置缓存**: `_ThresholdConfig` dataclass 在 `initialize()` 时一次性读取，消除每次 tick 重复 getattr
- **运行指标**: `_ImmuneStats` 追踪 tick 数、降级次数、重启次数等，通过 `get_stats()` 暴露
- **降级恢复**: 资源恢复后自动调用 `perform_downgrade(level=0)` 解除降级
- **错误暴增检测**: `_check_error_burst()` 检测短时间错误暴增，执行预防性清理
- **线程安全单例**: `get_immune_system_service()` 使用 `threading.Lock` 保护

**依赖关系**:

```
ImmuneSystemService
├── PerformanceMonitor  → 获取 CPU/内存指标
├── ResourceMonitor     → 执行降级和资源清理
├── HealthChecker       → 检测不健康服务
├── LifecycleManager    → 重启服务
├── TaskScheduler       → 检查系统是否繁忙
└── ErrorReporter       → 接收全局错误回调
```

### 3.7 AutoHealService（自愈服务）

**文件**: `core/services/auto_heal/`

**职责**: 运行时日志驱动的自动 bug 检测与修复。灵感来自 OpenAI Symphony，但更注重运行时真实信号（日志 error、业务指标异常）而非静态代码扫描。

**核心架构**:

```
日志 Error
  → 错误回调 → AnomalyDetector（聚类/去重/指纹计算）
  → 规则匹配（5种规则）→ AnomalyEvent
  → RootCauseAnalyzer（traceback → 源码定位 → LLM 分析）
  → PatchGenerator（LLM 生成修复代码 + unified diff）
  → PatchSandbox（语法检查 + import 验证 + ruff 检查）
  → 人工审批 / 自动应用
  → Workspace.write_source_file()（安全沙箱写入 + 自动备份）
  → 可一键回滚
```

**子模块**:

| 模块 | 文件 | 职责 |
|------|------|------|
| 数据模型 | `models.py` | AnomalyEvent、ErrorFingerprint、Patch、RootCauseReport、5种默认异常规则 |
| 异常检测 | `anomaly_detector.py` | 错误聚类/去重/指纹计算，5种规则匹配 |
| 根因分析 | `root_cause_analyzer.py` | traceback 解析 → 源码定位 → LLM 分析 |
| 补丁生成 | `patch_generator.py` | LLM 生成修复代码 + unified diff |
| 补丁验证 | `patch_sandbox.py` | 语法检查 + import 验证 + ruff 检查 |
| 补丁管理 | `patch_manager.py` | 补丁的生成、验证、应用和回滚 |
| 报告生成 | `report_generator.py` | 生成、保存和管理自愈报告 |
| 自愈服务 | `heal_service.py` | 编排完整流程 + 7层安全机制 |

**7层安全机制**:

| 层级 | 机制 | 说明 |
|------|------|------|
| 1 | 受保护文件黑名单 | `main.py`、`lifecycle_manager.py`、`auto_heal/*`、`logger.py`、`integrated_config.py` 等核心文件永不修改 |
| 2 | 目录白名单 | 只能修改 `core/`、`config/`、`routers/`、`memory/` |
| 3 | 扩展名白名单 | 只能修改 `.py`、`.yaml`、`.yml`、`.json`、`.toml` |
| 4 | 每日补丁上限 | 每天最多 10 个补丁，每个文件每天最多 3 次 |
| 5 | 补丁体积限制 | 单个补丁最大 512KB |
| 6 | 三重备份+回滚 | 内存备份 + 文件备份 + 备份验证 + 失败自动恢复 + 一键回滚 API |
| 7 | 人工审批（默认） | 默认 `auto_apply=False`，补丁需人工审批才写入 |

**异常检测规则**:

| 规则名 | 类型 | 条件 | 自动修复 |
|--------|------|------|---------|
| `error_burst` | 错误暴增 | 5分钟内 >15 次错误 | ❌ |
| `repeated_same_error` | 重复异常 | 10分钟内同一错误 >5 次 | ✅ |
| `active_care_flood` | 业务指标异常 | 一天主动关怀 >50 条 | ✅ |
| `llm_timeout_cluster` | 错误聚集 | 10分钟内 LLM 超时 >5 次 | ✅ |
| `service_unhealthy` | 服务降级 | 有服务不健康 | ❌ |

**API 接口** (`/api/v1/auto-heal/`):

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/stats` | 获取统计信息 |
| GET | `/patches` | 获取所有补丁 |
| GET | `/patches/pending` | 获取待审批补丁 |
| GET | `/patches/{id}` | 获取补丁详情（含 diff） |
| POST | `/patches/{id}/apply` | 应用补丁 |
| POST | `/patches/{id}/rollback` | 回滚补丁 |
| POST | `/patches/{id}/reject` | 拒绝补丁 |
| POST | `/check` | 手动触发异常检查 |

**依赖关系**:

```
AutoHealService
├── AnomalyDetector     → 异常检测（订阅 log_sanitizer 错误回调）
├── RootCauseAnalyzer   → 根因分析（调用 AvelineService LLM）
├── PatchGenerator      → 补丁生成（调用 AvelineService LLM）
├── PatchSandbox        → 补丁验证（语法/import/ruff）
├── WorkspaceService    → 源码文件读写（安全沙箱）
├── EventBus            → 发布补丁就绪事件
└── LifecycleManager    → 服务生命周期（priority=7）
```

**与免疫系统的区别**:

| 维度 | 免疫系统 | 自愈服务 |
|------|---------|---------|
| 修复方式 | 重启服务、资源降级 | 修改源代码 |
| 触发信号 | 资源指标、健康检查 | 日志错误、业务指标 |
| 修复范围 | 运行时行为 | 代码层面 |
| 风险等级 | 低（可逆） | 中（需审批+备份） |
| 优先级 | 5 | 7 |

### 3.8 SelfImprovementService（自我改进系统）

**文件**: `core/services/self_improvement/`

**职责**: 结构化学习、纠正追踪、核心记忆管理。整合 SKILL.md (self-improvement) + SKILL1.md (memory-manager) + 现有系统的优点，构建统一的自我改进能力。

**核心架构**:

```
用户纠正/错误/学习
  → CorrectionTracker（6种信号检测）→ 记录到 .learnings/corrections.md
  → LearningLogger（结构化日志）→ .learnings/LEARNINGS.md | ERRORS.md | FEATURE_REQUESTS.md
  → CoreMemory（轻量核心记忆）→ MEMORY.md（≤5KB，6分区）
  → LearningPromoter（模式检测）→ 重复≥3次/2条相似纠正 → 晋升为永久规则
  → DailyLogger（每日日志）→ memory/YYYY-MM-DD.md
  → DriftGuard（漂移防护）→ 验证记忆准确性
```

**子模块**:

| 模块 | 文件 | 职责 |
|------|------|------|
| 主服务 | `service.py` | 统一入口，协调所有子模块 |
| 学习日志 | `learning_logger.py` | 结构化学习/错误/功能请求日志（.learnings/，ID 追踪，模式去重） |
| 纠正追踪 | `correction_tracker.py` | 6种纠正信号检测 + 纠正晋升（2条相似→永久规则） |
| 核心记忆 | `core_memory.py` | MEMORY.md 管理（6分区，自动瘦身，NOT-to-save，归档） |
| 学习晋升 | `learning_promoter.py` | 重复模式检测 + 纠正晋升 → project_rules.md |
| 每日日志 | `daily_logger.py` | memory/YYYY-MM-DD.md 格式日志 + 自动归档 |
| 漂移防护 | `drift_guard.py` | 验证文件路径/函数名/配置值准确性 |
| 数据模型 | `models.py` | LearningEntry/ErrorEntry/FeatureRequestEntry/CorrectionEntry |

**MEMORY.md 分区结构**:

| 分区 | 图标 | 保留策略 | 上限 |
|------|------|---------|------|
| 用户偏好 | 🔒 | 永久保留 | 无限制 |
| 角色定位 | 💼 | 永久保留 | 无限制 |
| 业务经验 | 📝 | 长期保留 | ≤15条 |
| 活跃任务 | 📋 | 完成后删 | 10条 |
| 纠正记录 | 🔄 | 晋升后删 | ≤10条 |
| 对话摘要 | 💬 | 7天精简 | 20条 |

**纠正信号检测**:

| 信号 | 示例 | 优先级 |
|------|------|--------|
| 放弃 | "算了我来" | 最高 |
| 直接否定 | "不对"、"错了" | 高 |
| 不同答案 | "应该是"、"其实是" | 中高 |
| 质疑 | "你确定？" | 中 |
| 温和引导 | "换个角度" | 低 |
| 示范 | 直接展示正确做法 | 最低 |

**晋升规则**:

| 条件 | 晋升目标 |
|------|---------|
| 学习条目重复≥3次 | project_rules.md |
| 2条相似纠正 | project_rules.md |
| 最佳实践类学习 | prompt 组件 |
| 知识缺口类学习 | MEMORY.md 永久区 |

**配置项** (`SelfImprovementSettings`):

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `enabled` | True | 是否启用 |
| `correction_detection` | True | 通用纠正检测 |
| `learning_log` | True | 结构化学习日志 |
| `core_memory` | True | MEMORY.md 管理 |
| `auto_slim` | True | 自动瘦身 |
| `drift_guard` | True | 漂移防护 |
| `daily_log` | True | 每日日志 |
| `promotion` | True | 学习晋升 |
| `memory_max_size_kb` | 5 | MEMORY.md 最大 KB |
| `prompt_injection` | True | prompt 注入 |

**与现有系统的关系**:

| 关联系统 | 集成方式 |
|---------|---------|
| WeightedMemoryManager | MEMORY.md 是轻量摘要，底层仍用加权记忆 |
| AutoHealService | 自愈补丁应用后通知自我改进系统记录学习 |
| correction.py | 生活类纠正保留，通用纠正扩展到 CorrectionTracker |
| JournalService | 每日日志与日记系统联动 |
| PromptAssembler | 自我改进指令注入到 prompt |

**依赖关系**:

```
SelfImprovementService
├── LearningLogger      → 结构化学习/错误/功能请求日志
├── CorrectionTracker   → 通用纠正检测与记录
├── CoreMemory          → MEMORY.md 核心记忆管理
├── LearningPromoter    → 学习晋升与模式检测
├── DailyLogger         → 每日日志生成
├── DriftGuard          → 记忆漂移防护
└── PromptAssembler     → 自我改进指令注入
```

### 3.9 其他服务模块（2026-06 新增汇总）

以下服务模块为近期新增，体量较小，统一说明：

| 服务 | 文件 | 职责 |
|------|------|------|
| **CommandHandler** | `core/services/command/handler.py` | 命令处理系统。用字典映射处理斜杠命令（`/clear` `/save` `/load` `/memory` `/setmemory` `/system` `/help`），内部持有轻量级 `WeightedMemoryManager` 与默认 chat agent |
| **MessageComposer** | `core/services/communication/composer.py` | 消息组装器（静态工具类）。统一构造 `UnifiedMessage`：文本/图片/语音消息，以及流式响应 chunk 字典 |
| **UDPBeaconService** | `core/services/discovery/udp_beacon.py` | UDP 服务发现信标。向局域网广播 `AVELINE_SERVER|http://<ip>:<port>`（端口 28899，默认 5 秒间隔），供安卓客户端零配置发现后端 |
| **IntentService** | `core/services/intent/service.py` | 意图识别服务。BERT 模型为主 + 高频正则规则第一层拦截的混合方案。导出 `rule_classify_intent`/`classify_intent`/`normalize_slots`，覆盖切换/列表/清空记忆/帮助/模型/语音/人设/延迟/系统状态/赞美等意图 |
| **MemorySync** | `core/services/maintenance/memory_sync.py` | 维护服务。`sync_recent_memories_to_status()`：扫描最近 24h 加权记忆中遗漏的生活事件（Wakeup/Meals），同步到 `user_status.json` |
| **ReactionManager** | `core/services/reaction/reaction_manager.py` | 自发反应管理器。基于系统状态/环境/上次交互时间触发角色自发反应；带冷却时间（默认 5 分钟，演示模式 10 秒），依赖 `AvelineCharacter` 的反射（reflexes） |
| **RemoteOpsService** | `core/services/remote_ops/service.py` | 远程操作服务（单例）。封装 workspace 的文件动作（list/read/write/append/mkdir/exists），带 `max_chars`/`limit` 限制。配套 `approval.py` → `ApprovalService`（审批流，`ApprovalRequest` 含 `action_type/description/payload/expires_at`，状态走 `core.contracts.ApprovalStatus`） |
| **UserPhysiologyService** | `core/services/user_physiology/service.py` | 用户生理状态服务。按 user_id 维护最新生理指标，原子写 JSON（`runtime/user_physiology.json`），线程锁保护 |
| **VTubeStudioService** | `core/services/vtube/service.py` | VTube Studio 集成服务。基于 `pyvts` 控制 VTube Studio 模型，按情绪触发 hotkey/表情；后台 `_connect_loop` 异步连接，配置走 `settings.vtube` |

**API 契约层**（`core/api/`，新增）:
- `contract.py` — `success_response(data, message)` 与 `error_response(error_code, message, request_id, details)` 统一封装；`validate_internal_token` 校验 `X-Internal-Token`
- `error_response.py` — `ErrorCode` 枚举覆盖系统/请求/认证/资源/LLM/任务调度/速率限制/业务领域错误码

**业务管理器**（`core/managers/`，新增）:
- `notification_manager.py` — `NotificationManager`（单例）：按 user_id 维护 `deque(maxlen=50)` 通知队列，`has_active_connections`（60 秒窗口）
- `preference_manager.py` — `PreferenceManager`（单例）：持久化到 `runtime/user_preferences.json`，偏好含 mode/active_care_enabled/response_length/conversation_style/sensitivity/debug_visible
- `session_manager.py` — `SessionManager`：多会话管理器，按 scope（aveline/ling）+ legacy 三处文件聚合加载

**虚拟环境间通信**（`core/env/`，新增）:
- `env_communication_manager.py` — 环境通信管理器（`Message` dataclass，`MessageQueue` 进程间队列按 topic 订阅通知）
- `websocket_client.py` — WebSocket 客户端（`WebSocketMessage` dataclass，处理 `ConnectionClosedOK/Error`）

**应用生命周期**（`core/lifecycle/`，新增）:
- `lifespan.py` — FastAPI 应用生命周期管理。`_force_kill_self` 强杀进程树（psutil）；`_install_windows_console_close_handler` 处理 Windows 控制台关闭事件；集成 `lifecycle_manager`/`service_registry`/`EventBus`/`performance_monitor`/`discovery.udp_beacon` 的启停

### 3.10 CharacterDailyService（角色日常服务）

**文件**: `core/services/character_daily/`

**职责**: 角色日常活动管理，为全部已配置模板角色提供独立的日常生活节奏。每个角色每天生成活动计划（学习、做饭、看书、散步等），按计划推进自己的生活。Peer Chat 从固定定时器变为自然触发，但其 persona/账号配对边界独立于计划角色发现。

角色计划与 Journal 用户计划共用 `core/services/planning/engine.py`。YAML `fixed` 活动转换为固定候选，`pool` 活动展开为多个候选实例，周末角色特有候选由 `rest_day_extras.<period>` 配置；引擎按模板权重、优先级、昨日重复次数、时长惩罚和 `date + owner + candidate key` 稳定哈希评分，再做固定项优先、冲突检查和贪心容量排程。`DailyPlanGenerator.role_ids` 和 `CharacterDailyEngine.managed_role_ids` 直接来自已加载模板键；新增模板角色重启后会自动生成，当天状态缺失时也会补齐，不依赖 `KNOWN_ROLES`。`CharacterDailyEngine` 不再导入 `LLMPlanGenerator`，旧配置即使误开 `llm_plan.enabled` 也只记录警告。

**活动解析补充**:
- `current_activity` 优先取当前命中的 `slot.activity`
- 睡觉结束后的短空档仅保留几分钟 `waking_up`
- 其他无 slot 的时间空档回落到 `idle`，避免角色在计划空白段长时间卡在上一项活动，误伤 `peer chat` 和被动回复判定
- 当 `current_activity` 发生变化时同步保存 `daily_state.json`，避免磁盘里长期残留过时的瞬时态

**模块架构**:

```python
class CharacterDailyEngine:
    def __init__(self):
        self._generator: DailyPlanGenerator  # 每日计划生成器
        self._state: DailyStateStore         # 状态持久化
        self._gate: PeerChatGate             # Peer Chat 门控
        self._running: bool = False

    async def start(self) -> None:
        """启动主循环（独立 async loop）"""

    async def stop(self) -> None:
        """停止主循环"""

    async def _tick(self) -> None:
        """每 2 分钟 ±20% jitter 执行一次"""
        # 1. 新的一天？生成今日计划
        # 2. 更新每个角色的当前活动
        # 3. 检查是否触发 peer chat

    def get_current_activity(self, role_id: str) -> ActivityType:
        """获取角色当前活动"""

    def get_activity_context_text(self, role_id: str) -> str:
        """获取自然语言描述（如 'Ling现在在发呆'）"""

    def get_peer_chat_summary(self) -> str:
        """获取今日 peer chat 摘要"""
```

**子模块架构**:

| 模块 | 文件 | 职责 |
|------|------|------|
| 活动模型 | `activity_model.py` | ActivityType 枚举（15种）、ActivitySlot、DailyPlan 数据类 |
| 共享计划引擎 | `../planning/engine.py` | 稳定哈希评分、固定项优先、冲突检查和贪心容量排程 |
| 每日计划 | `daily_plan.py` | YAML fixed/pool 候选适配，读取昨日同角色计划做重复惩罚 |
| 历史 LLM 模块 | `llm_plan_generator.py` | 仅保留兼容；运行时引擎不导入、不实例化 |
| 被动回复策略 | `reply_policy.py` | 用户发消息时根据角色活动/睡眠状态 + 回复窗口期决定延后处理/强制唤醒/强制打断 |
| 回复提示模板 | `reply_hints.py` | 集中管理所有"被吵醒/被打断/起床后/忙完后"提示模板和 builder（从 reply_policy.py 拆出，避免超 500 行） |
| ReplyPolicy 辅助函数 | `reply_policy_support.py` | 手动打断窗口读取、回归决策提示、窗口延长、轻活动延迟分档 |
| 活动配置 | `config.py` | 加载 `character_daily.yaml` + `app.yaml` 配置 |
| 计划展示 | `plan_view.py` | 角色计划摘要/完整时间线格式化，供工具调用 |
| Peer Chat 门控 | `peer_chat_gate.py` | 5 层门控 + 异步聊天 + 紧急打断路径 |
| 手动打断窗口 | `interrupt_window.py` | `/打断` 后的临时聊天窗口管理（激活/延长/跳过/过期） |
| 统一回归消息 | `activity_return/` | `/打断` 后回去做事 + 半夜睡回去的告别消息，事件驱动调度（含 instruction/state/scheduler/core） |
| 状态持久化 | `state.py` | JSON + 原子写入 + 节流保存 |

**活动类型**:

| 类型 | 说明 | 是否忙碌 |
|------|------|----------|
| SLEEPING | 睡觉 | 忙碌 |
| COOKING | 做饭 | 忙碌 |
| STUDYING | 学习/做题 | 忙碌 |
| NAPPING | 午休 | 忙碌 |
| READING | 看书/看番 | 空闲 |
| HOUSEWORK | 做家务 | 空闲 |
| WALKING | 散步 | 空闲 |
| PHONE_SCROLLING | 刷手机 | 空闲 |
| GARDENING | 浇花 | 空闲 |
| IDLE | 发呆/休息 | 空闲 |

**Peer Chat 门控**:

| 层级 | 条件 | 默认值 |
|------|------|--------|
| 1 | 全局最小间隔 | 5400s（1.5小时） |
| 2 | 今日总次数 | 软上限 4，硬上限 6 |
| 3 | 时间范围 | 9:00-22:00 |
| 4 | 双方活动都适合聊天 | CHAT_ELIGIBLE_ACTIVITIES |
| 5 | 概率判定 | 基础 0.04，多因素修正 |

**Peer Chat 紧急打断路径**（异步聊天模式）:

当一方空闲、另一方忙碌（异步聊天）时，按概率（默认 15%）走"紧急打断"路径：
- `should_use_urgent_interrupt()` 决定模式
- `build_situation_context(interrupt_mode=True)` 生成情境：提示 LLM"有急事要找她，会被打断，可能有点不情愿但会放下手头的事回应"
- 非打断路径：异步聊天，忙碌方可能不回/简短回（如"忙着呢等下说"）

**被动回复策略（Reply Policy）**:

用户发消息时，根据角色当前活动 + Active Care 睡眠会话 + 回复窗口期决定回复方式：

| 状态 | 行为 | 配置 |
|------|------|------|
| 回复窗口期内（上次 BUSY 回复后 ≤ 120s） | **正常回复**：趁热打铁延续对话，不走延后处理。仅对"忙碌但非 DND"的活动（studying/cooking）有效 | `reply_policy.reply_window_seconds` (默认 120) |
| 主动回接窗口内（同 persona 最近主动发消息后 ≤ 300s） | **正常回复**：即使当前活动仍投影为 `sleep_recovery`，也直接接话，避免出现“她先来找你，你回她却被静默累积”的割裂体验。按 `persona_filename` 解析 scope，只放行当前 persona | `reply_policy.proactive_reply_window_seconds` (默认 300) |
| 计划即将切换（下一个槽位 ≤ 300s） | **正常回复 + 动态提示**：给当前回复注入“下一个安排快到了”的提示，让模型自然选择是把安排稍微顺延几分钟继续聊，还是礼貌收尾去做下一项；不硬切对话 | `reply_policy.plan_transition_notice_seconds` (默认 300) |
| 轻活动（按类型分档） | **静默后回复**：不再直接吞消息，而是按活动类型延迟不同秒数后再自然回复。`idle/phone_scrolling/reading/gaming` 走 `quick(8~18s)`，`self_care/shopping/walking/creative_hobby` 等走 `normal(18~35s)`，`cooking/housework/exercising/正餐` 走 `slow(28~55s)`，`sleep_recovery` 单独走 `recovery(20~40s)` | `reply_policy.soft_delay_quick_*` / `normal_*` / `slow_*` / `recovery_*` |
| 硬忙碌（studying） | **延后处理**：继续静默累积，留到做完后统一处理 | `HARD_BUSY_ACTIVITIES` + `reply_policy.busy` |
| 不可打扰（sleeping/napping/waking_up 或 active_care 睡眠会话） | **延后处理**：第 1 条起即静默累积（不发占位消息），should_reply=False（消息留到起床后处理） | `reply_policy.do_not_disturb` |
| 不可打扰 + 连续消息 | **递增概率强制唤醒**：基础概率仍是第 2 条 8%、第 3 条 25%、第 4 条 55%、第 5 条 85%，达到硬上限（默认 6 条）100% 醒；但如果角色是“刚睡下”的 `sleeping`，会额外叠加 `fresh_sleep_bonus`，让首条消息也可能把她叫醒。唤醒时缩短延迟，把前几条没回的消息一起发给 LLM，persona_hint 说明"被用户连续发了 N 条消息吵醒" | `reply_policy.force_reply_threshold` + `reply_policy_support.resolve_dnd_wake_profile()` |
| 角色起床后下次发消息 | 检查 `_DND_PENDING` 累积消息，注入 `build_morning_after_hint`（提示 LLM"刚才在睡觉，看到用户在你睡觉时发的 N 条消息，要逐条回应"） | — |
| 夜间被叫醒后静默结束 | **主动补发消息**：如果角色决定 `return_to_sleep` 或 `sleep_later`，会主动补一句“我先继续睡会儿/我等会儿再去睡”，避免聊天突然无声消失；同时同步更新 Active Care 的最近主动发消息时间 | `chat_reply_runtime._notify_sleep_resume_message()` |
| 忙碌（studying/cooking）第 1 条 | **延后处理**：静默累积（不发占位消息，should_reply=False），消息留到做完后处理 | `reply_policy.busy` |
| 忙碌 + 连续消息 | **递增概率强制打断**（与 DND 共用概率表）：唤醒时注入 `build_busy_interrupt_hint`（带活动动词，如"你正在学习，被用户连续发了 N 条消息打断"） | `reply_policy.force_reply_threshold` |
| 角色做完后下次发消息 | 检查累积消息，注入 `build_busy_done_hint`（提示 LLM"刚才在学习，现在做完了，看到用户在你做事时发的消息"） | — |
| 手动打断窗口期内（`/打断` 后） | **正常回复 + 动态提示**：`build_manual_interrupt_window_hint()` 告知 LLM 当前处于临时聊天窗口，还剩多久；窗口快结束时（≤60s）提示 LLM 自然提及要回去继续做事 | `reply_policy.manual_interrupt_window_seconds` |
| 回归消息等待期内 | **正常回复 + 决策提示**：AI 已发送回归消息后 90s 内用户再次回复，`build_activity_return_reply_hint()` 让 LLM 根据回复内容选择继续聊还是真的回去做事/睡回去；work 场景会自动延长窗口并重新调度回归消息 | `activity_return._DEFAULT_GRACE_SECONDS` |
| 空闲 | 正常回复 | — |

设计变更（2026-06-27）：
- 去掉占位消息（zZz.../专注中...），DND/BUSY 第 1 条起即静默累积（`skip_message=""`），更接近"消息没回"的真实体验
- BUSY 不再延迟回复分支（不再 30%/70% 概率分流），统一延后处理
- 新增回复窗口期机制：BUSY 回复后窗口期内继续聊正常回复，DND 强制唤醒后不享受窗口期

累积消息状态由 `handlers/chat_reply_runtime.py` 的 `_DND_PENDING` 字典管理（per-conversation），含 `messages` + `last_ts` + `activity` 字段（记录累积时的活动类型，用于决定活动结束后注入哪个 hint），超时（默认 10 分钟）自动重置。`_build_after_activity_done_hint()`（在 `handlers/chat/reply_policy.py` 中）按累积时的活动类型选择 hint 模板（DND→morning_after / BUSY→busy_done）。

回复窗口期状态由 `handlers/chat_reply_runtime.py` 的 `_LAST_REPLY_STATE` 字典管理（per-conversation），含 `last_reply_ts` + `activity` 字段，`evaluate_reply_state` 接收 `last_reply_ts` / `last_reply_activity` 参数，在 DND/BUSY 判断前先检查窗口期。should_reply=True 时由 `_record_successful_reply()` 记录状态。

**与 Active Care 集成**:

1. **决策上下文注入**: `CheckerStateDetector._get_character_daily_context()` 在每次 Active Care 决策时注入角色活动状态
2. **主程序工具调用**: `get_character_daily_plan` 允许主对话 LLM 查看自己、同伴或双方的当日角色计划
3. **动态约束注入**: `ActiveCareDecision.decide_proactive_content()` 根据角色活动生成 LLM 动态约束（忙碌→should_send=false，空闲→适合发消息）
4. **统一回归消息**: `activity_return.send_activity_return_message()` 复用 Active Care executor 发送 `/打断` 后回去做事与半夜睡回去的告别消息；通过 `reply_policy_support.build_activity_return_reply_hint()` 把用户回复时的决策提示注入被动回复 prompt

**配置**:

```yaml
# config/yaml/character_daily.yaml
aveline:
  wake_time: "07:00"
  sleep_time: "23:00"
  time_blocks:
    - period: "morning_routine"
      start: "07:00"
      end: "08:30"
      fixed:
        - { activity: "waking_up", duration: [15, 30] }
      pool:
        - { activity: "cooking",   duration: [20, 35], weight: 3 }
        - { activity: "breakfast", duration: [15, 25], weight: 5 }
```

**预期效果**:

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 角色生活 | 无，只有生理状态 | 完整的每日活动计划 |
| Peer chat 频率 | 固定 30min 定时器 | 全局 60min + 概率自然波动 |
| 活动感知 | 无 | 知道角色在干嘛，只在空闲时聊 |
| Active Care 联动 | 无 | 角色忙碌时抑制主动消息 |

**详细文档**: `core/services/character_daily/README.md`

---

### 3.11 DigitalWellbeingService（数字健康服务）

**文件**: `core/services/digital_wellbeing/service.py` | 路由: `routers/v1/context_device.py`

**定位**: 应用使用时长限额管理与复盘。Android 端通过 DataSyncWorker 上报当日应用前台时长，后端落盘 `app_usage.jsonl`，支持限额设定/超限判断/active care 关怀/nightly 自动复盘。

**核心功能**:
- **限额存取**: `get_limits()` / `save_limits()` / `set_single_limit()` — 按日期落盘 `digital_wellbeing/limits_{date}.json`，支持 user/auto 两种来源（auto=nightly 自动生成）
- **会话限额**: `set_session_cap()` / `session_cap_ms` — 一次性 cap，从设定时刻起累计，超限即强退，说"恢复"可解除
- **超限判断**: `get_exceeded_apps()` — 对比当日限额与实时用量，返回超限列表（含 ratio 进度比）
- **Nightly 复盘**: `build_limit_suggestion()` — 基于昨日用量（>2h 的应用取 80% 向上取整到 15min）生成明日限额建议
- **Active Care 关怀**: `maybe_notify_exceeded_via_active_care()` — 超限时通过 active care 发提醒，带 6h 冷却 + 30min 最近活跃窗口

**数据流**:
```
Android UsageStatsManager (当日累计前台时长)
  ├→ UsageEvents 区间累加 → WellbeingScreen 本地实时进度
  ├→ AvelineAccessibilityService (受限应用进入前台时即时检查)
  │   └→ 超额后返回桌面，再用 Shizuku / 后台进程结束作为执行通道
  └→ DataSyncWorker (每 15 分钟, getAppUsageSince(midnight))
      → POST /api/v1/context/sync → app_usage.jsonl
        ├→ read_today_app_usage (按 server_timestamp 最新聚合)
        │   └→ GET /wellbeing/app-limits → WellbeingScreen
        └→ maybe_notify_exceeded_via_active_care (带 last_used 活跃检查)
            └→ Active Care 关怀消息
```

**关键修复 (2026-08-10)**:
- DataSyncWorker 从 `getAppUsage(hours=24)` 改为 `getAppUsageSince(todayMidnight)`，切断昨天数据污染
- `read_today_app_usage` 聚合从最大值改为最新时间戳
- `maybe_notify_exceeded` 增加最近活跃窗口，last_used >30min 跳过
- UsageLimitMonitor 会话 cap 从全局起点改为各自独立

**前端执行修复 (2026-08-17)**:
- Wellbeing 页面拉取/保存限额后立即写入本地缓存，不再等待下一轮 DataSyncWorker 才生效
- 使用 UsageEvents 累加精确裁切任意起点，避免会话限额混入设置前的 daily bucket
- 无障碍服务监听受限应用进入前台，超额时立即返回桌面；周期 Worker 继续作为无障碍未启用时的兜底
- 页面显示“使用情况访问 / 即时限制”是否就绪，并提供直达系统授权入口

**无障碍宿主保活 (2026-08-18)**:
- `AvelineAccessibilityService` 连接后无条件拉起 `AvelineForegroundServiceV2`，由前台进程降低无障碍宿主被系统回收的概率
- `AvelineForegroundServiceV2` 是不超过 300 行的生命周期薄壳；`services/foreground/` 分别承载通知与 Intent 协议、WebSocket 指令、上下文同步、Samsung Health 同步、无障碍监测和 WakeLock，避免 Service God Class
- 守护通知保持 `ongoing`，并通过 `deleteIntent` 在被划除后立即重新提交；已授权通知读取时，`AvelineNotificationService.onNotificationRemoved` 提供厂商系统兜底
- 恢复前必须确认无障碍仍在系统启用列表或常驻模式仍开启；用户主动关闭两者后不再拉起
- 通知自恢复不能绕过 Android 的无障碍授权：若系统关闭授权，只能提示用户回设置页重新开启

**相关文件**:
- 后端: `core/services/digital_wellbeing/service.py`, `core/tools/device/set_app_limit.py`
- 路由: `routers/v1/context_device.py` (`/context/sync`, `/wellbeing/app-limits`, `/wellbeing/app-limit`)
- 安卓: `UsageLimitMonitor.kt`, `DataSyncWorker.kt`, `AvelineAccessibilityService.kt`, `AvelineForegroundServiceV2.kt`, `services/foreground/`, `ContextRepositoryImpl.kt`, `WellbeingViewModel.kt`, `WellbeingScreen.kt`

**配置常量**:
- `_DEFAULT_SOFT_THRESHOLD_MS = 2h` — nightly 自动设限的最低用量阈值
- `_ENFORCE_GRACE_RATIO = 1.0` — 超限触发倍数
- `_CARE_COOLDOWN_SECONDS = 6h` — 同应用关怀消息冷却
- `_RECENT_ACTIVE_MINUTES = 30` — 最近活跃窗口
- `_EXCLUDED_PREFIXES` — 自动排除 com.aveline.ai 等系统/自身包

***

### 3.12 学习工具 - 背单词模块（Study Tools - Vocabulary）

**文件**: `core/tools/study/english/` | Facade: `vocabulary_manager.py` | 详细文档: `core/tools/study/english/README.md`

**定位**: 面向单一用户的背单词系统，对外统一走 `get_vocabulary_manager()` 单例门面。后端服务层 `core/services/study/service.py` 透传，安卓端 `StudyVocabReviewManager` 驱动复习会话。

**模块结构（2026-08 解耦自原 VocabularyManager God Class）**:
- `loader.py` — `VocabDataStore`：路径解析、词典/例句/进度懒加载与落盘、查询、导入/切换
- `fsrs_scheduler.py` — FSRS(`Scheduler`/`Card`)间隔调度 + SM-2 回退 + quality→Rating 映射 + daily/unfamiliar 同步
- `quiz.py` — `get_daily_words`（昨天 daily 生词 + FSRS 到期词）、测验生成与判分
- `stats.py` — 统计、错词/弱词、App 错题与 unfamiliar 计数合并、记忆曲线、`get_review_overview`、streak
- `daily_word_log.py` — 每日生词日志 `daily/YYYY/MM/DD.txt`（单例）
- `vocab_review_reminder.py` — 复习定时提醒（APScheduler，通道留接口）

**词书来源（2026-08 从考纲压缩版换为 ECDICT；2026-08-25 恢复可复现生成与释义分层）**:
- 由 `scripts/study/vocabulary/build_wordbooks.py` 基于 **ECDICT**（`external/ECDICT-master/ecdict.csv`）重建，筛选 8 个考纲标签（zk/gk/cet4/cet6/ky/toefl/ielts/gre）并保留进度、daily、unfamiliar 手动补词；默认只生成报告，`--write` 才原子替换并备份现有词书。
- `CET-全量.json`：全量释义总表约 1.5 万词，每条带 `tags` 标注所属级别；仅作复习释义兜底查询，不显示在词书选择列表。
- 分级词书：`CET4-顺序.json`（四级基础，默认词书）/ `CET6-顺序.json` / `考研-顺序.json` / `托福-顺序.json` / `雅思-顺序.json` / `GRE-顺序.json`，词书选择页按级别切换，背新词按当前词书取词。
- 构建器保留 `vt/vi`，清除字面量换行残片，把 `[经][机][医][化]` 等领域义写入 `extended_translations`；Sentence 文件仅提供例句、短语与音标，附带释义不会进入 Words。
- `config/study/vocabulary_sense_overrides.json` 维护少量人工核对的 `primary_translations`。Android 仅对 `primary=true` 加粗，并将专业义及来源补充义默认折叠；未核对词不自动加粗第一条。
- 进度文件：`output/user_data/vocab_progress.json`（FSRS 状态以 `fsrs_` 前缀存储，due/last_review 为 UTC 时间戳）。

**复习调度要点（2026-08 修复）**:
- `get_daily_words(limit=0)`：第一阶段取昨天 `daily/YYYY/MM/DD.txt` 生词（词书查不到也保留），第二阶段补 FSRS 到期且「今天未 last_review」的词（避免刚 Again 的词立刻重排成"一直学到会为止"）。
- AI `word_quiz` 默认读取昨天的 daily 日志；可显式读取 `unfamiliar`，或用 `source=both` 获取严格分区的两套结果。结果携带 `source/scope/dates_with_words`，防止模型把空 daily 结果复述成上一轮 unfamiliar 结果。
- AI 的 unfamiliar 抽词池即时合并既有 App 历史错题与长期文件计数，无需迁移或改写原文件；Android 提交评分后，`quality<=2` 同步增加 unfamiliar 难词计数，`quality>=3` 递减（最低 0）。`GET /api/v1/vocab/mistakes` 同样返回合并视图，`error_count=max(progress_error_count, unfamiliar_count)` 避免同一错误重复计数。
- 安卓复习：Again 本轮最多重排 2 次（含首次共出现 3 次）；结算页按单词去重统计会/不会。
- Android 使用 `study_vocab_session` 私有 SharedPreferences 保存未完成会话的动态队列、卡片索引、Again 次数和本轮结果。冷启动先恢复有效快照，再决定是否拉取远端列表；完整结算后清理快照。该快照只负责本轮强化，长期 FSRS 与 daily 错词仍由后端持久化。

**安卓复习 UI 关键文件**:
- `StudyVocabReviewManager.kt` — 评分提交、Again 重排、结果去重（`dedupeResults`）
- `StudyVocabSessionStore.kt` — 未完成复习/背新词会话的本地快照与版本校验
- `StudyVocabReview.kt` — 翻卡会话 + 结算页（`VocabSessionSummary` 展示会/不会明细 + 例句区）

***

### 3.13 学习服务 - 专注番茄钟模块（Study - Focus Pomodoro）

**文件**: `core/services/study/focus_session_service.py` | 模型: `focus_session_models.py` | 策略: `focus_monitor_policy.py` | 配置: `config/focus_monitor_config.py` | 路由: `routers/v1/study_focus.py` | AI 工具: `core/tools/focus_session_tool.py` | 模块指南: `.trae/skills/xiaoyou-study-focus/SKILL.md`

**定位**: 后端权威的专注会话 + 摄像头状态监控（人在/离开/疑似分心）+ 温柔探班 + 严格模式低频视觉复核 + 跨端（Web/Android）同步 + AI 只读聚合查询。

**核心机制**:
- **后端权威计时**: `FocusSessionService` 维护会话状态机（idle→active→paused→finished），接收端侧 MediaPipe FaceDetector 产出的结构化观察（presence/activity/confidence/signals），按 `sequence` 幂等处理（乱序/重复忽略），心跳超时自动暂停，结束总结并同步 `DailyTracker`。
- **监控策略**: `focus_monitor_policy.py` 根据 `config/focus_monitor_config.py` 阈值决定温柔探班时机；严格模式下在持续分心、已授权摄像头、冷却结束、专注时长足够时，建议低频视觉复核。
- **落盘**: `companion_data/user_data/focus_sessions/YYYY/MM/DD.txt`（filelock + 原子写）。

**隐私红线（强制）**:
- 后端存储与返回均不含 base64 / 图像 / 音频 / 视频；观察 payload 含图像字段会被 `_validate_observation` 丢弃。
- 视觉复核帧（`POST /vision-review`）仅在单次请求内临时送视觉模型，只把结论文本写入 `vision_review_events`，不落盘任何图像。

**跨端**:
- Web 端侧 MediaPipe 检测，Android 经 `AvelineApiService` / `StudyRepository` / `StudyFocusViewModel` 复用同一后端会话，实现跨端共享一个专注会话。

**AI 只读工具**:
- `get_current_focus_session` / `get_focus_session_summary`：返回聚合专注数据（focus_rate/remaining_seconds/nudge_count 等），裁剪所有图像字段，无法开启监控或读取画面。

***

## 4. 模块层技术详解

### 4.1 LLM模块

**文件**: `core/modules/llm/module.py`

**模块职责拆分**:

| 模块          | 文件                                 | 职责                            |
| ----------- | ---------------------------------- | ----------------------------- |
| OpenAI兼容客户端 | `openai_compat/client.py`          | 核心HTTP通信、会话管理、重试逻辑            |
| Aveline客户端  | `openai_compat/aveline_client.py`  | Aveline专用配置                   |
| DeepSeek客户端 | `openai_compat/deepseek_client.py` | DeepSeek专用配置                  |
| MiniMax客户端  | `openai_compat/minimax_client.py`  | MiniMax专用配置                   |
| Ark客户端      | `openai_compat/ark_client.py`      | 火山方舟专用配置                      |
| 智谱AI客户端    | `openai_compat/zhipu_client.py`    | 智谱AI专用配置(思考模式/联网搜索/视觉模型)     |
| API监控       | `openai_compat/api_monitor.py`     | API调用计数、调用栈追踪、日志记录            |
| 消息工具        | `openai_compat/message_utils.py`   | 消息规范化、角色映射、Payload构建          |
| 错误处理        | `openai_compat/error_handling.py`  | 网络错误分类、瞬时错误判断                 |
| 流式解析器       | `openai_compat/stream_parser.py`   | SSE流式响应解析、content/reasoning提取 |

**双模式架构**:

```python
class LLMModule:
    def __init__(self, config: Dict):
        self.backend = config.get("backend", "gguf")
        self.model = None
        self.device = config.get("device", "cuda")
    
    async def load_model(self) -> None:
        """加载模型"""
        if self.backend == "gguf":
            from .gguf_backend import GGUFBackend
            self.model = GGUFBackend(self.config)
        elif self.backend == "transformers":
            from .transformers_backend import TransformersBackend
            self.model = TransformersBackend(self.config)
        elif self.backend == "cloud":
            from .cloud_backends import CloudBackend
            self.model = CloudBackend(self.config)
    
    async def generate(self, prompt: str, **kwargs) -> str:
        """同步生成"""
    
    async def stream_generate(self, prompt: str, **kwargs) -> AsyncGenerator:
        """流式生成"""
```

**GGUF后端配置**:

```python
GGUFConfig = {
    "model_path": "models/qwen-7b.gguf",
    "n_gpu_layers": 35,
    "n_ctx": 4096,
    "n_batch": 512,
    "f16_kv": True,
}
```

**云端后端配置**:

```python
CloudConfig = {
    "provider": "siliconflow",  # openai, dashscope, deepseek
    "api_key": "xxx",
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "base_url": "https://api.siliconflow.cn/v1",
}
```

### 4.2 视觉模块

**文件**: `core/modules/vision/module.py`

**支持模型**:

| 模型          | 类型 | 说明               |
| ----------- | -- | ---------------- |
| Qwen-VL     | 本地 | 通义视觉语言模型         |
| Qwen2-VL    | 本地 | 通义视觉语言模型v2       |
| SiliconFlow | 云端 | SiliconFlow视觉API |

**关键方法**:

```python
class VisionModule:
    async def describe_image(self, image_path: str, prompt: str) -> str:
        """图像描述"""
    
    async def analyze_image(self, image_path: str, questions: List[str]) -> Dict:
        """图像分析"""
    
    async def ocr(self, image_path: str) -> str:
        """文字识别"""
```

### 4.3 语音模块

**文件**: `core/voice/tts_engine.py`、`core/voice/cloud_tts_helpers.py`

**TTS引擎路由**:

```python
class TTSEngine:
    def __init__(self, config: Dict):
        self.engines = {
            "qwen3_tts": Qwen3TTS(config),
            "gpt_sovits": GPTSoVITS(config),
            "cloud": CloudTTS(config),
        }
        self.current_engine = config.get("engine", "qwen3_tts")
    
    async def synthesize(self, text: str, **kwargs) -> bytes:
        """语音合成"""
        engine = self.engines[self.current_engine]
        try:
            return await engine.synthesize(text, **kwargs)
        except Exception:
            # 回退到下一个引擎
            for name, engine in self.engines.items():
                if name != self.current_engine:
                    return await engine.synthesize(text, **kwargs)
```

**TTS配置**:

```python
TTSConfig = {
    "engine": "qwen3_tts",
    "sample_rate": 24000,
    "reference_audio": "reference.wav",
    "speed": 1.0,
    "pitch": 1.0,
}
```

**当前职责拆分**:

- `tts_engine.py`
  - 引擎路由
  - GPT-SoVITS / Qwen3TTS / CloudTTS 总入口
  - 设备迁移与资源管理对接
- `cloud_tts_helpers.py`
  - Cloud TTS 会话复用
  - HTTP 请求构造与发送
  - Cloud TTS 关闭清理
- `multimodal/tts_manager.py`（TTSCacheManager）
  - LRU 缓存层 + 请求去重
  - 同步/异步双 API（`text_to_speech` / `async_text_to_speech`）
  - 线程安全后台事件循环（`_init_lock` 独立锁）
  - Future 超时机制（`_wait_for_inflight_async`）
  - 磁盘空间监控与配额驱逐
  - 文本规范化提升缓存命中率
  - 结构化异常（`TTSError` → `TTSInitializationError` / `TTSSynthesisError` / `TTSTimeoutError` / `TTSDiskSpaceError`）
  - `TTSCacheConfig` 可配置参数（7项）
  - `health_check()` 健康检查端点
  - `shutdown()` 优雅关闭

### 4.4 文本模型适配模块

**文件**: `core/text_model_adapter.py`、`core/text_adapter_request_utils.py`、`core/text_adapter_remote_backends.py`

**当前职责拆分**:

- `text_model_adapter.py`
  - 本地 Transformers / llama\_cpp 路径
  - 统一 `stream_chat()` / `chat()` / `generate()` 外部接口
  - 重试、OOM 缩容、健康检查总入口
- `text_adapter_request_utils.py`
  - `messages/prompt` 归一化
  - 默认 `max_tokens` 规范化
- `text_adapter_remote_backends.py`
  - ollama / vllm / dashscope / infer service 的远端调用
  - 远端后端健康检查

### 4.5 图像生成模块

**文件**: `core/image/image_manager.py`、`core/image/forge_runtime.py`

**多后端支持**:

```python
class ImageManager:
    def __init__(self, config: Dict):
        self.backends = {
            "forge": ForgeClient(config),
            "siliconflow": SiliconFlowClient(config),
            "comfy": ComfyClient(config),
        }
        self.current_backend = config.get("backend", "forge")
    
    async def generate(self, prompt: str, **kwargs) -> str:
        """生成图像"""
    
    async def img2img(self, image: str, prompt: str, **kwargs) -> str:
        """图像到图像"""
    
    async def get_available_models(self) -> List[str]:
        """获取可用模型"""
```

**当前职责拆分**:

- `image_manager.py`
  - provider 路由
  - 图像任务前后的资源协调
  - Forge / ComfyUI / SiliconFlow 统一业务入口
- `forge_runtime.py`
  - Forge 进程拉起
  - 就绪检查
  - 预热
  - 进程终止与回收

***

## 5. 记忆系统技术详解

### 5.1 WeightedMemoryManager

**文件**: `memory/weighted_memory_manager.py`

**核心数据结构**:

```python
memory_record = {
    "id": str,
    "content": str,
    "memory_type": str,
    "category": str,
    "topics": List[str],
    "display_tags": List[str],
    "status": str,
    "weight": float,
    "source_ref": Dict[str, Any],
    "readable_title": str,
    "readable_summary": str,
    "last_hit_time": float,
    "metadata": Dict[str, Any],
}
```

**关键方法**:

```python
class WeightedMemoryManager:
    def __init__(self):
        self.weighted_memories: Dict[str, Memory] = {}
        self.keyword_index: Dict[str, Set[str]] = {}
        self.category_index: Dict[str, List[str]] = {}
        self.content_dedupe_index: Dict[str, str] = {}
        self.lock = threading.RLock()
    
    async def add_memory(
        self,
        content: str,
        category: str = "general",
        weight: float = 1.0,
        metadata: Optional[Dict] = None,
    ) -> str:
        """添加记忆"""
    
    async def search_memories(
        self,
        query: str,
        limit: int = 10,
        category: Optional[str] = None,
    ) -> List[Dict]:
        """搜索记忆"""
    
    async def update_weight(self, memory_id: str, delta: float) -> bool:
        """更新权重"""
    
    async def apply_decay(self) -> None:
        """应用权重衰减"""
```

### 5.2 权重计算

**文件**: `memory/core/weights.py`

**权重因子**:

| 因子   | 权重   | 计算方式                                          |
| ---- | ---- | --------------------------------------------- |
| 时间衰减 | 0.30 | `exp(-elapsed_seconds / half_life)`           |
| 访问频率 | 0.20 | `log(access_count + 1) / log(max_access + 1)` |
| 情感强度 | 0.20 | `abs(emotion_score)`                          |
| 用户反馈 | 0.15 | `user_rating / max_rating`                    |
| 关联度  | 0.15 | `related_memories / max_related`              |

**衰减公式**:

```
weight(t) = weight(0) * exp(-λ * t)
```

其中 `λ = ln(2) / half_life`

### 5.3 检索操作

**文件**: `memory/core/retrieval_ops.py`

**混合检索**:

```python
def hybrid_search_memories(
    manager: Any,
    query: str,
    limit: int = 10,
    keyword_weight: float = 0.4,
    vector_weight: float = 0.6,
) -> List[Dict]:
    """混合检索（关键词 + 向量）"""
    # 1. 关键词检索
    keyword_results = search_by_keywords(manager, query, limit * 2)
    
    # 2. 向量检索
    query_embedding = generate_embedding(query)
    vector_results = search_by_similarity(manager, query_embedding, limit * 2)
    
    # 3. 融合排序
    combined_scores = {}
    for i, result in enumerate(keyword_results):
        combined_scores[result["id"]] = keyword_weight * (1 / (i + 1))
    for i, result in enumerate(vector_results):
        combined_scores[result["id"]] = combined_scores.get(result["id"], 0) + vector_weight * result["similarity"]
    
    # 4. 返回Top-K
    sorted_results = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:limit]
```

### 5.4 记忆存储与数据类

**文件**: `memory/core/storage.py`

**数据类架构**（v2.1.0 新增）：

```python
@dataclass
class MemoryContext:
    """管理器上下文，封装 add_memory_locked 所需的全部管理器状态和回调"""
    weighted_memories: Dict[str, Dict[str, Any]]
    short_term_memory: List[Dict[str, Any]]
    category_index: Dict[str, List[str]]
    important_prompts: List[Dict[str, Any]]
    sensitive_memories: List[Dict[str, Any]]
    topic_weights: Dict[str, float]
    emotion_memory_map: Dict[str, List[Dict[str, Any]]]
    weight_calculator: Any
    detect_topics_fn: Callable
    detect_emotion_fn: Callable
    # ... 其他回调和配置

@dataclass
class MemoryInput:
    """记忆输入参数，封装单条记忆的内容和元数据"""
    content: str = ""
    topics: Optional[List[str]] = None
    emotions: Optional[List[str]] = None
    is_important: bool = False
    source: str = "chat"
    category: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    scopes: Optional[List[str]] = None
    user_id: str = "default"
    is_sensitive_mode: bool = False
```

**辅助函数**（v2.1.0 从 add_memory_locked 提取）：

| 函数 | 职责 |
|------|------|
| `_filter_system_injection` | 过滤系统提示词注入 |
| `_resolve_legacy_kwargs` | 兼容旧版关键字参数 |
| `_add_memory_core` | 核心添加逻辑（使用 MemoryContext + MemoryInput） |
| `_normalize_for_dedupe` | 内容标准化用于去重 |
| `_is_low_value_for_weighted` | 判断是否为低价值记忆 |
| `_build_dedupe_key` | 构建去重索引 key |
| `_build_memory_record` | 构建记忆字典记录 |
| `_check_duplicate` | 去重检测（支持 content_dedupe_index 和 O(N) 回退） |
| `_handle_duplicate` | 处理重复记忆的合并更新 |
| `_extract_preferences_for_user` | 用户偏好提取 |
| `_index_new_memory` | 新记忆索引（分类、话题、情绪、重要提示词晋升） |

### 5.5 融合裁决评分体系

**文件**: `memory/core/analysis_ops.py`

**评分配置**（v2.2.0 重构为 FusionConfig dataclass）：

```python
@dataclass(frozen=True)
class FusionConfig:
    """融合裁决配置，替代硬编码字典"""
    s_rule: float = 0.40
    s_ai: float = 0.20
    s_consistency: float = 0.30
    s_stability: float = 0.10

    consistency_topic: float = 0.55
    consistency_category: float = 0.20
    consistency_discourse: float = 0.25

    trigger_rule_signal: float = 0.40
    trigger_ai_signal: float = 0.35
    trigger_state_consistency: float = 0.15
    trigger_consistency: float = 0.10

    rule_topic_strength: float = 0.6
    rule_category_strength: float = 0.4

    trigger_allow_threshold: float = 0.72
```

**融合结果**（v2.2.0 重构为 FusionResult dataclass）：

```python
@dataclass
class FusionResult:
    """融合裁决结果，替代 _write_fusion_metadata 的 20+ 参数"""
    action: str = "reject"
    final_confidence: float = 0.0
    s_rule: float = 0.0
    s_ai: float = 0.0
    s_consistency: float = 0.0
    s_stability: float = 0.0
    trigger_final_confidence: float = 0.0
    trigger_decision: str = "deny"
    # ... 其他字段
```

**话语类型权重惩罚**：

| 话语类型 | 权重惩罚 |
|---------|---------|
| INSTRUCTION/QUESTION/REPORTED_SPEECH | -0.4 |
| HYPOTHETICAL/FUTURE_PLAN | -0.25 |
| RETROSPECTIVE_SELF_REPORT | -0.1 |
| `BLOCKED_DISCOURSE_LABELS` | 阻断触发的话语标签 | frozenset: RETROSPECTIVE_SELF_REPORT, FUTURE_PLAN 等 |
| `RISK_CATEGORIES` | 高风险分类 | frozenset: preference, sensitive, state |
| `RISK_MEMORY_TYPES` | 高风险记忆类型 | frozenset: preference, sensitive, state, profile |

**评分流程**:
```
1. _compute_rule_score → 规则评分（话题强度 + 分类强度）
2. _compute_consistency_score → 一致性评分（话题/分类/话语 Jaccard 相似度）
3. _compute_stability_score → 稳定性评分（历史分析结果一致性）
4. _compute_final_confidence → 加权融合（FUSION_WEIGHTS）
5. _compute_trigger_decision → 触发决策（阈值 0.72）
6. _assess_risk_level → 风险评估（调整 override/supplement 阈值）
7. _apply_fusion_action → 执行裁决（override/supplement/reject/rollback）
```

### 5.5 性能优化特性

| 特性 | 文件 | 说明 |
|------|------|------|
| 话题缓存 | `retrieval_ops.py` | `get_top_topics` 30秒 TTL 缓存，实例级缓存（`manager._top_topics_cache`），写操作自动失效；`_cleanup_top_topics_cache` 防止内存泄漏（上限64条） |
| 查询嵌入缓存 | `retrieval_ops.py` | 使用 `hashlib.sha256` 确定性哈希做缓存 key（跨进程一致） |
| 关键词数量限制 | `utils.py` | `extract_keywords` 限制最多30个关键词，仅生成 2-gram |
| 统一评分函数 | `scoring_utils.py` | `compute_hybrid_score_with_result` 统一所有模块的评分逻辑（v2.2.0） |
| 统一锁策略 | `mutation_ops.py`, `retrieval_ops.py`, `vector_ops.py`, `cache_ops.py` | `_get_read_lock()` / `_get_write_lock()` 辅助函数，优先使用读写锁，回退到互斥锁（v2.2.0） |
| 读写锁写者优先 | `concurrency_optimized.py` | `ReadWriteLock` 新增 `_waiting_writers` 计数器，防止写者饥饿（v2.2.0） |
| 增量主题缓存 | `retrieval_ops_optimized.py` | `TopicWeightCache` 增量更新 + `needs_rebuild()` 定期重建保证时间衰减一致性（v2.2.0） |
| 蒸馏时间衰减 | `distillation.py` | 分段 recency_factor：≤1h→3.0, 1h~1d→1.5, >1d→0.5 |
| 人物档案蒸馏门控 | `nightly/distillation_service.py`, `core/character/people/signal_gate.py` | scope 蒸馏落盘人物/角色演化线索，global 每晚汇总一次；仅候选原始批次调用详细提取，无线索为 0 次 LLM |
| Nightly/人物档案职责拆分 | `nightly/task_runner.py`, `core/character/people/extractor.py` | 两个入口均为薄门面；蒸馏 Codec、全局任务、对话源、门控、外部人物和角色演化各由兄弟模块承担 |
| 统一停用词 | `utils.py` | `_UNIFIED_STOPWORDS` 合并 `text_segmenter.STOPWORDS` 和额外停用词，消除重复定义 |
| 线程安全单例 | `weighted_memory_manager.py` | 模块级 `_instances` + `_instances_lock`，消除函数属性竞态 |
| 安全快照 | `retrieval_ops.py` | `search_memories` 锁内 `.copy()` 快照，消除 TOCTOU 竞态 |
| 权重持久化 | `io_ops.py` | 加载时保留原始权重，时间衰减仅在查询时动态计算，避免重启累积衰减 |
| 并发安全缓存 | `concurrency_optimized.py` | `ConcurrentCache`（原 `LockFreeCache`），读无锁 + 写加锁（v2.2.0 重命名） |
| 线程安全计数器 | `concurrency_optimized.py` | `ThreadSafeCounter`（原 `AtomicCounter`），加锁计数器（v2.2.0 重命名） |
| 共享锁工具 | `lock_utils.py` | `get_read_lock()` / `get_write_lock()` 上下文管理器，13个子模块统一使用（v2.3.0） |
| 统一缓存管理器 | `unified_cache_manager.py` | `UnifiedCacheManager` 整合嵌入/查询/记忆L1-L2/主题缓存，统一统计和清理接口（v2.3.0） |
| 异步持久化 | `async_persistence.py` | `async_safe_json_dump` / `async_safe_json_load`，aiofiles + 回退到 asyncio.to_thread（v2.3.0） |
| 批量操作 | `batch_ops.py` | `batch_delete_memories` / `batch_update_weights` / `batch_search_memories`，单次锁获取（v2.3.0） |

### 5.6 模块依赖关系

```
storage.py ──imports──→ record_ops.py (merge_tags)
mutation_ops.py ──imports──→ retrieval_ops.py (invalidate_top_topics_cache)
weighted_memory_manager.py ──delegates──→ storage/retrieval/distillation/mutation/search/core modules
```

## 6. 调度系统技术详解

### 6.1 C++调度器架构

**目录**: `cpp_scheduler/`

**核心组件**:

| 组件                         | 文件                          | 职责         |
| -------------------------- | --------------------------- | ---------- |
| ResourceIsolationScheduler | `core/scheduler.hpp`        | 资源隔离调度器    |
| GPULLMWorker               | `workers/gpu_worker.hpp`    | GPU LLM工作器 |
| CPUWorker                  | `workers/cpu_worker.hpp`    | CPU工作器     |
| PriorityQueue              | `queue/priority_queue.hpp`  | 优先级队列      |
| BiologicalState            | `core/biological_state.hpp` | 生物学状态      |

**Python绑定**:

```python
# core/services/scheduler/cpp_scheduler_engine.py
class CPPSchedulerEngine:
    def __init__(self):
        self._scheduler = None  # C++调度器实例

    async def initialize(self) -> None:
        """初始化调度器"""
        self._scheduler = create_scheduler(self.config)

    async def submit_llm_task(
        self,
        prompt: str,
        model_config: LLMModelConfig,
        priority: int = 1,
    ) -> AsyncGenerator:
        """提交LLM任务"""
```

**增强功能 (2026-04-03 更新)**:

| 功能                  | 说明                              | 配置项                                                                                                                          |
| ------------------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **Circuit Breaker** | C++后端连续失败3次后自动熔断，降级到Python后端    | `XIAOYOU_CPP_BREAKER_THRESHOLD` (默认3)`XIAOYOU_CPP_BREAKER_MIN_COOLDOWN_S` (默认5s)`XIAOYOU_CPP_BREAKER_MAX_COOLDOWN_S` (默认60s) |
| **OOM自动重试**         | Python后端OOM时自动卸载并重试             | `XIAOYOU_LLM_OOM_MAX_RETRIES` (默认1)                                                                                          |
| **C++→Python降级**    | C++后端失败时自动切换到Python后端执行         | 自动触发                                                                                                                         |
| **KV Cache保存/恢复**   | 紧急卸载时先保存KV Cache，后台加载CPU实例后恢复   | 自动启用                                                                                                                         |
| **NVIDIA SMI监控**    | 使用nvidia-smi获取显存使用量（不依赖PyTorch） | 自动启用                                                                                                                         |
| **推理统计信息**          | 记录token生成数量、推理耗时等性能指标           | 通过 `get_last_llm_stats()` 查询                                                                                                 |

**当前模块拆分（2026-06 重构为子目录结构）**:

调度服务已从扁平结构重构为子目录组织，按职责清晰分层：

**顶层文件**:
- `cpp_scheduler_engine.py` — `CPPSchedulerEngine`（单例）主引擎，协调各子模块，提供统一调度接口
- `scheduler_wrapper.py` — C++ 扩展绑定层（`_import_scheduler_py` 查找并导入 C++ scheduler 扩展，处理 Windows DLL 搜索路径）

**`bio/` 生物系统**:
- `bio_state.py` — `build_biological_status(bio_system)`：从 C++ bio_system 抽取神经递质/energy/sleep_debt/circadian_phase/cognitive_delay
- `bio_system_manager.py` — `BioSystemManager`：`get_biological_system` / `apply_bio_before_infer`（推理前应用认知延迟/能量消耗）

**`client/` C++ 调度器 HTTP 客户端**:
- `cpp_client.py` — `CPPSchedulerClient`（httpx.AsyncClient，30s 超时，`connect`/`submit_llm_task`/`submit_tts_task`）
- `cpp_config_builder.py` — `CPPConfigBuilder`：dict 配置映射到 C++ `LLMModelConfig`（驼峰/下划线双写属性）

**`inference/` 推理执行**:
- `inference_executor.py` — `InferenceExecutor`：推理任务执行器（架构明确为"Python 路由层 → C++ 执行层，不存在 Python 后端降级"）
- `cpp_llm_handler.py` — C++ 后端 LLM 推理路径（`on_token` 回调 + `asyncio.Queue` + `call_soon_threadsafe` 桥接异步流）
- `python_llm_handler.py` — Python 后端 LLM 推理路径（`llama_cpp`，.gguf 模型热切换，`_llm_setup_lock` 串行化加载）
- `inference_stats.py` — `record_llm_inference_stats` / `get_last_llm_stats`
- `inference_utils.py` — `messages_to_text`/`clamp_messages`/`clamp_text`/token 估算（尝试加载 C++ 加速分词器）

**`lifecycle/` 调度器生命周期**:
- `scheduler_lifecycle.py` — `SchedulerLifecycle`：`start(worker_count, gpu_config, preload_llm)` 初始化并启动 C++ ResourceIsolationScheduler
- `health_monitor.py` — `HealthMonitor`：`health_check_gpu_worker` 提交简单推理测试验证 GPU worker 健康

**`model/` 模型与 GPU 资源**:
- `llm_model_manager.py` — `LLMModelManager`：LLM 模型生命周期管理（加载/卸载/切换，`_patch_llama_cpp_internals` 防崩溃，`ThreadPoolExecutor` 加载）
- `gpu_resource_manager.py` — GPU 资源管理（`_cleanup_gpu_instance` 清理旧 LLM 实例并释放显存，`_update_resource_manager_state` 同步状态）

**C++ Llama Worker 实现**:
- `llama_model_impl.cpp` — tokenization 与生成循环
- `llama_model_cache.cpp` — 会话 sequence、KV Cache、KV Swap 与清理
- `llama_model_lifecycle.cpp` — 模型/context 初始化、关闭和状态查询
- `llama_model_runtime.cpp` — decode 超时、batch、采样和 UTF-8 辅助

**`task/` 任务调度**:
- `task_scheduler.py` — `GlobalTaskScheduler`：统一全局任务调度器（`TaskPriority`/`TaskType`/`TaskInfo`，状态对齐 `core.contracts.TaskStatus`）
- `task_scheduler_adapter.py` — `TaskSchedulerAdapter`：适配器，封装 `GlobalTaskScheduler`，支持无缝切换到 C++ 资源隔离调度器
- `async_task_wrapper.py` — 异步任务包装器（扩展 `TaskType`：CPU/GPU/IO/TTS/STT/IMAGE/LLM，`EnhancedTaskInfo`）

**`utils/` 工具函数**:
- `circuit_breaker.py` — 断路器机制（`BreakerState`/`BreakerRegistry`，指数退避倍增 cooldown，兼容旧 dict 接口）
- `error_utils.py` — 错误检测与友好转换（`is_oom_error`/`is_cuda_backend_error`/`friendly_llm_error`）
- `kv_cache_manager.py` — KV Cache 紧急保存/恢复（`save_llm_state_emergency`/`restore_llm_state_emergency`，失败非致命）
- `nvidia_smi_monitor.py` — nvidia-smi 显存读取（优先 pynvml，回退子进程，2 秒 TTL 缓存）
- `resource_utils.py` — 资源管理公共工具（`MemoryPressureResult`/`check_memory_pressure`/`offload_tts_services`/`read_kv_swap_config`/`set_llm_config_attr`/`get_cuda_free_mb`）
- `startup_config.py` — 启动配置（`resolve_llm_backend` 按 gpu_config + 环境变量 + settings 决定 cpp/python，`apply_biological_config` 写入 C++ `BiologicalConfig`）

**断路器状态查询示例**:

```python
engine = get_scheduler_engine()

# 查询断路器状态
breaker_status = engine.get_breaker_status()
# 返回: {"llm": {"is_open": False, "failures": 0, ...}, "image": {...}}

# 查询最近一次推理统计
stats = engine.get_last_llm_stats()
# 返回: {"backend": "cpp", "generated_tokens": 150, "inference_time_s": 2.35, ...}
```

### 6.2 生物学状态驱动

**文件**: `core/services/scheduler/bio/bio_state.py`（已迁移到 `bio/` 子目录）

**神经递质模型**:

```python
@dataclass
class Neurotransmitters:
    dopamine: float = 0.5      # 多巴胺：奖励/动机
    serotonin: float = 0.5     # 血清素：情绪稳定
    norepinephrine: float = 0.5 # 去甲肾上腺素：注意力
    oxytocin: float = 0.5      # 催产素：社交连接
    cortisol: float = 0.3      # 皮质醇：压力水平
```

**认知延迟计算**:

```python
def calculate_cognitive_delay(bio_state: BiologicalState) -> float:
    """计算认知延迟（秒）"""
    base_delay = 0.5
    
    # 能量影响
    energy_factor = 1.0 + (1.0 - bio_state.energy) * 0.5
    
    # 睡眠债务影响
    sleep_factor = 1.0 + bio_state.sleep_debt * 0.3
    
    # 皮质醇影响
    stress_factor = 1.0 + bio_state.neurotransmitters.cortisol * 0.2
    
    return base_delay * energy_factor * sleep_factor * stress_factor
```

***

## 7. 接口层技术详解

### 7.1 HTTP API规范

**基础URL**: `http://localhost:8000/api/v1`

**请求格式**:

```json
{
    "message": "用户消息",
    "conversation_id": "conv_123",
    "user_id": "user_456",
    "context": {}
}
```

**响应格式**:

```json
{
    "status": "success",
    "data": {},
    "timestamp": "2026-03-12T10:00:00Z"
}
```

**错误响应**:

```json
{
    "status": "error",
    "error": {
        "code": "INTERNAL_ERROR",
        "message": "错误描述",
        "details": {}
    },
    "timestamp": "2026-03-12T10:00:00Z"
}
```

**安全基线（公网部署）**:

- 受保护路径：`/api/**`、`/v1/**`、`/demo**`
- HTTP 认证方式：`Authorization: Bearer <token>`（兼容 `X-Internal-Token` / `X-Access-Token`）
- 密钥来源：`XIAOYOU_SECURITY_WEB_ACCESS_TOKEN`
- 未配置密钥时，受保护路径返回 `503`（拒绝访问，防止裸奔）
- WebSocket `/api/v1/ws` 在握手前执行同一 Token 校验（支持 `token` 查询参数），失败返回 `1008`
- 请求治理：按 `server.max_content_length` 做请求体大小限制，按 `max_requests_per_minute` 与 `max_ip_requests_per_minute` 做 60 秒窗口限流

### 7.2 WebSocket协议

**连接URL**: `ws://localhost:8000/api/v1/ws?token=xxx&user_id=xxx`

**消息类型**:

| 类型             | 方向            | 说明     |
| -------------- | ------------- | ------ |
| `ping`         | Server→Client | 心跳检测   |
| `pong`         | Client→Server | 心跳响应   |
| `chat`         | 双向            | 聊天消息   |
| `stream`       | Server→Client | 流式响应   |
| `notification` | Server→Client | 主动关怀通知 |
| `status`       | Server→Client | 状态更新   |

**双 QQ 主动消息可靠投递**:
- 逻辑会话使用 `shared__persona__{role}`，WebSocket 广播与离线队列必须使用真实主人传输 ID（`private_{master_qq_id}`），不得使用 `shared__scope__*`。
- 同一主人下的多角色连接用 `client_id=qq_{role_id}_{session_id}` 区分；实时广播和离线重放都只交给目标角色连接，发送失败的离线消息保留到下次重连。
- 协议心跳为 30 秒间隔、60 秒超时；Windows `WinError 121` 作为可恢复断连记录，不输出误导性的完整错误堆栈。

**消息格式**:

```json
{
    "type": "chat",
    "data": {
        "content": "消息内容",
        "emotion": "happy",
        "is_streaming": false
    },
    "timestamp": 1710230400000
}
```

### 7.3 OpenAI兼容API

**路径**: `/v1/chat/completions`, `/v1/models`, `/v1/embeddings`

**请求格式**:

```json
{
    "model": "qwen-7b",
    "messages": [
        {"role": "user", "content": "你好"}
    ],
    "stream": true,
    "temperature": 0.7,
    "max_tokens": 2048
}
```

***

## 8. 客户端层技术详解

### 8.1 QQ机器人适配器

**文件**: `clients/bots/qq/main.py` / `clients/bots/qq/config.py`

**多QQ独立角色架构**:

```
QQ用户 <--> NapCatQQ #1 (端口3001) <--> QQAdapter(Aveline)  <--> Xiaoyou Core
QQ用户 <--> NapCatQQ #2 (端口3002) <--> QQAdapter(Ling)    <--> Xiaoyou Core
QQ用户 <--> NapCatQQ #3 (端口3003) <--> QQAdapter(Frost)    <--> Xiaoyou Core
QQ用户 <--> NapCatQQ #4 (端口3004) <--> QQAdapter(Coco)    <--> Xiaoyou Core
```

- 单进程多实例：`multi_qq_adapter.py` 在同一进程内运行多个 `QQAdapter`，各自连接不同 NapCatQQ
- 配置对象化：`QQAdapterConfig` 封装所有per-instance配置（66个字段），`QQAdapter` 和 `XiaoyouSession` 从 `self.cfg` / `self._cfg` 读取，不再依赖全局变量
- 日志前缀：`_PrefixLogAdapter` 自动添加 `[七濑澪]` / `[Ling]` 等前缀区分角色
- 向后兼容：原有 `qq_adapter.py` 单QQ入口不受影响

**启动方式**:
- 单QQ: `start_scripts\start_qq_bot.bat` → `qq_adapter.py`
- 多QQ: `start_scripts\start_multi_qq_bot.bat` → `multi_qq_adapter.py`

**配置文件**:
- 单QQ: `clients/bots/config.json`
- 多QQ: `clients/bots/multi_qq_config.json`（定义 aveline/ling/rushuang/yeye 多个角色的独立配置）

**消息处理流水线**:

```
1. Preprocess (预处理)
   ├── 表情提取 (FaceInjector.extract)
   ├── 引用消息展开 (process_reply_in_message)
   ├── 图片理解 (Vision, process_images_in_message)
   └── 语音转写 (STT, process_audio_in_message)

2. Command (命令路由)
   └── CommandRouter.dispatch() -> Handler

3. Intent (意图路由) [可选]
   ├── Fast Path: 本地正则匹配
   └── Slow Path: LLM意图分类

4. Chat (对话处理)
   └── XiaoyouSession -> WebSocket -> Xiaoyou Core
```

**Handler架构**:

```python
class BaseHandler:
    def __init__(self, adapter):
        self.adapter = adapter
        self.logger = adapter.logger
    
    async def api_request(self, method, path, json_body=None, params=None):
        """委托给适配器的API请求方法"""
    
    async def send_text(self, session_id, content):
        """委托给适配器的发送方法"""

class CommandRouter:
    def _build_routes(self) -> List[CommandRoute]:
        return [
            CommandRoute({"状态", "status"}, False, self._status),
            CommandRoute({"切模型"}, True, self._switch_model),
            # ...
        ]
```

### 8.1.1 Telegram 主程序托管适配器

**文件**: `clients/bots/telegram/adapter.py`、`clients/bots/telegram/session.py`、`core/lifecycle/lifespan.py`

- **启动模型**：`main.py` 的 FastAPI lifespan 根据 `config/yaml/app.yaml` 的 `telegram.enabled` 在主事件循环中托管，无需另开 Adapter 终端；QQ 的独立进程模式不变。
- **配置边界**：开关、语音/视觉能力、后端地址和超时位于 `app.yaml`；Bot Token、Master 用户 ID、代理等本机值来自 `.env`。遗留 `TELEGRAM_ENABLED` 不覆盖 `app.yaml`。
- **就绪语义**：只有 Telegram polling 已成功启动后才设置 ready 并输出“Telegram 轮询已启动，正在监听消息”，托管任务提交不等于启动成功。
- **可靠性**：监督循环对异常退出退避重启；WebSocket 未确认发送在重连后重试；空闲会话按 `session_timeout_minutes` 回收；退出时统一关闭 polling、会话和 HTTP 客户端。
- **路由顺序**：图片、语音 handler 先于文本 handler，命令文本也进入统一消息入口，避免媒体被宽泛过滤器截获。
- **独立脚本**：`clients/bots/scripts/start_telegram.ps1` 仅用于调试，不得与主程序托管的 polling 同时运行。

### 8.2 Web前端

**文件**: `clients/frontend/aveline-web/`

**状态管理**:

```typescript
interface AvelineState {
    messages: Message[];
    lifeStatus: any;
    persona: any;
    emotion: EmotionType;
    emotionMix: Record<string, number>;
    stats: Stats;
    isTyping: boolean;
    studyMode: boolean;
    autoTtsEnabled: boolean;
    replyDisplayMode: 'text_and_tts' | 'tts_only';
}
```

**WebSocket连接管理**:

```typescript
export function useWebSocket(options: UseWebSocketOptions = {}) {
    const connect = useCallback(() => {
        const wsUrl = `${wsBaseUrl}/api/v1/ws?token=${token}&user_id=${userId}`;
        const ws = new WebSocket(wsUrl);
        
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'ping') {
                ws.send(JSON.stringify({ type: 'pong', timestamp: data.timestamp }));
                return;
            }
            onMessage(data);
        };
    }, []);
    
    // 自动重连（指数退避 + 抖动）
    const scheduleReconnect = useCallback(() => {
        const delay = Math.min(30000, base * Math.pow(1.5, attempt) + jitter);
        setTimeout(connect, delay);
    }, []);
}
```

***

### 8.3 Android 客户端 (Jetpack Compose)

**文件**: `clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/`

**技术栈**: Jetpack Compose + Material3 + Kotlin 1.9.22 + Hilt 2.51.1 + Room 2.6.1 + Retrofit2 + Navigation Compose

**架构**: MVVM + Clean Architecture (di/domain/data/presentation/services/utils)

**6单元主导航架构** (统一风格,职责清晰):

| 单元 | 职责 | 关键文件 |
|------|------|---------|
| Chat | 聊天对话(WebSocket流式) | ChatScreen + ChatViewModel(307行,薄壳协调者) + 子模块(ChatSessionController/ChatSessionObserver/ChatSendController/ChatIncomingMessageHandler/ChatFlushManager/ChatUploadHelper/ChatTtsController/ChatVoiceInputController/ChatPeerChatHandler/ChatTextProcessor) |

Android 聊天消息由 Room v4 持久化为树结构：`parentId` 指向当前版本的父消息，`variantIndex` 标识同级版本顺序，`isActiveVariant` 保存当前选择。`ChatRepositoryImpl.selectActiveConversationPath()` 将树投影成 UI 线性列表；编辑用户请求或重新生成 AI 回复只新增同级节点，不删除旧分支。`MessageRequest.history_override` 将当前激活路径传入 `/api/v1/chat/message`，后端一路透传到 `build_conversation_history()`，在生成该分支时覆盖默认线性历史。
| Companion | 已合并到 Chat 内的伙伴详情面板(状态/人设/记忆),不再占用侧边栏单元 | CompanionScreen(3-tab: Status/Persona/Memory) |
| Study | 学习管理 + Daily文件夹适配 | StudyScreenV2(6-tab) + StudyViewModel + StudyDailyViewModel(195行) |
| Life | 日常生活(健康/饮食/日程/饮水) | LifeScreen(4-tab) |
| Food | 食物商店(购买/食用) | FoodScreen |
| Wellbeing | 数字健康(使用统计/每日限额/会话限额/执行状态) | WellbeingScreen + WellbeingViewModel + UsageLimitMonitor |
| Settings | 应用设置(5-tab: 常规/权限/隐私/数据/高级) | SettingsScreenV2 + 5个Tab文件 |

侧边栏运动由 Compose Foundation `AnchoredDraggableState` 统一驱动：主页直接拖拽和 Pager 第一页无法消费的边界拖拽，通过 `NestedScrollConnection` 写入同一实时偏移，侧栏位移与遮罩透明度随手指连续变化。主页不是固定距离触发，而是慢拖使用 12% 位置阈值、轻甩使用 125dp/s 速度阈值；Route 接力仅在抽屉已产生实际位移时于 `onPreFling` 保存原始速度并执行吸附，防止内层详情退出的同一 fling 串联打开侧栏。其他 Pager 页面仍正常翻页。关闭态遮罩仅绘制、不创建点击节点，Drawer 可见时才组合点击关闭层，避免阻断 NavHost 内容命中。`MainActivity` 已移除全屏 `pointerInput`、`PointerEventPass.Initial` 和透明边缘窗口。圈子前端 Route 及后端旧圈子服务均已移除，旧 `aveline://circle` 链接兼容重定向到消息主页。

聊天页的伴侣详情也使用同一模式：`PullableDismissPanel` 包住完整详情 `Surface`，第一个 Companion Tab 的 Pager 边界剩余右滑通过 `NestedScrollConnection` 实时驱动整体 `translationX`；接力后支持反向拖回，松手按 12% 短距离阈值或速度吸附。`CompanionScreen` 不再包含全屏 `pointerInput`、`Animatable + Channel` 或动态禁用 Pager 的旧实现。

Android 模型选择以后端 `/api/v1/models.selected_model_id` 为权威状态，通过每个模型的 `path` 对齐 `cloud:provider[:alias]:model` 路由；本地 SharedPreferences 只在接口未返回当前模型时兜底，无法匹配时不再选择列表第一项。移动端切换消息使用后端协议字段 `model` 并发送实际路由。

Android 商城的缓存位于 `@Singleton ShopRepositoryImpl`，以类目为键保存分页商品、余额与更新时间组成的 `ShopCacheSnapshot`。`ShopViewModel` 初始化和切换类目时先同步恢复快照，10 分钟新鲜期内不请求网络；过期刷新与用户手动刷新使用 stale-while-revalidate，保留现有列表。类目切换会取消上一轮首屏和翻页 Job，并在响应写入 UI 前再次核对类目，防止快速滑动时旧响应覆盖新页面。

**统一组件**:
- `ModuleHeader` - 统一页头(标题+副标题+操作按钮容器),副标题用TextSecondary
- `ModuleHeaderActionContainer` - 统一操作按钮背景(14dp圆角+半透明黑)
- `SectionCard` - 统一分区卡片(16dp圆角+CardBackground+CardBorder+可折叠+图标+副标题)
- `MetricRow` - 统一指标行(标签:值对齐)

**Study/Daily API适配** (后端→客户端全链路):
- 后端: `routers/v1/study_daily.py` (5个GET端点: calendar/date/notes/note/latest-progress)
- API层: `StudyDailyApiService` 接口(从AvelineApiService拆出,AvelineApiService继承之)
- Model层: `StudyDailyModels.kt` (CalendarDay/DailyContent/DailyNote/DailyNoteContent/LatestProgress/PlanItem)
- Repository层: `StudyRepository` + `StudyRepositoryImpl` (snake_case→camelCase映射)
- ViewModel层: `StudyDailyViewModel` (独立文件,init自动加载当月日历和最新进度)
- View层: 4个Tab(Plan/Diary/Notes/Overview)优先使用后端数据,placeholder保留为后备

**API服务拆分** (避免单文件超500行):
- `AvelineApiService` (468行) - 主API接口,继承StudyDailyApiService
- `StudyDailyApiService` (53行) - Study/Daily专用接口

***

### 8.4 多QQ独立角色架构 (Multi-QQ Independent Roles)

角色从"同账号前台/后台切换"升级为"多QQ独立运行"：
在 `stream_generate_response` 中：

1. Aveline、Ling、Frost、Coco分别运行在独立的 QQ 号上，各自直接对用户对话，不再需要前台/后台切换。
2. 后台建议注入已移除（原 `DualRoleCoordinator` 的建议注入从未实际接入主链路）。
3. 旧后台圈子已删除；角色间自动互聊统一由 Peer Chat 调度，不再重复写入圈子存储或生成社交事件（关系热度功能已移除）。
4. 多QQ适配器（`multi_qq_adapter.py`）在单进程内运行多个 `QQAdapter` 实例，各自连接不同 NapCatQQ（端口 3001-3004）。
5. 配置对象化：`QQAdapterConfig` 封装所有 per-instance 配置，`QQAdapter` 和 `XiaoyouSession` 从 `self.cfg` / `self._cfg` 读取。
6. 仿生系统仍采用单引擎多角色状态池：`LifeSimulationService`（门面）→ `LifeOrchestrator`（协调）维护 `actor_life_states/actor_relationships`。
7. QQ 人设上下文隔离：消息链路透传 `persona_filename`，按 `{session_id}__persona__{persona}` 构造 `conversation_id`。
8. 多角色关系评估保留：`dual_role/social_events.py` 按 `dual_role` 配置计算关系状态。
9. 数据隔离：persona JSON 的 `meta.scope` 是角色持久化的唯一标识，统一存放在 `companion_data/{scope}_data/`。`core/utils/data/scope_registry.py` 自动扫描配置并把中文文件名、显示名、英文名和历史别名映射到同一 scope；`data_paths.py` 与旧兼容入口均委托该注册表。新增角色只需声明英文 snake_case `meta.scope`，无需修改 Python 白名单；历史别名目录可用 `scripts/migrate/merge_persona_scope_dirs.py` 安全合并，冲突文件不会被覆盖。
10. Peer Chat 成功后只写普通日记摘要和 `peer_{role_id}` 原始会话记录；不再产生圈子专属日记副本或逐句社交事件。
11. `SocialEventEngine` 统计用户自述与 Samsung Health 产生的可共享生活事件；事件保存 `source`、`learned_by`、`certainty`，历史 `background_circle` 仍不参与关系和证据计算。
12. 历史圈子数据保留在磁盘作为归档，运行时代码不再读取或继续生成。
13. Active Care 支持按会话人设路由，主动关怀运行状态存储到 `companion_data/active_care/{persona_scope}` 实现角色隔离。
14. 历史分层规则收敛：`history/` 作为原始记忆层，`companion_data/` 作为可读业务层。

### 8.5 双角色互聊 Peer Script 架构

双角色互聊（Peer Chat）允许两个角色（如七濑澪和Ling）自动生成对话剧本并分发到各自的QQ。

调度协同规则：CharacterDaily 接管 Peer Chat 后依次尝试提醒分工与主动关怀时段分工。协商缺失或失败时，每个时段仍只有一个稳定兜底主导，另一个角色只能超时接管。剧本生成同时聚合两个角色与主人的真实近期对话以及上次互聊内容，有合适素材时优先使用具体互动，不回退到空泛日常寒暄。

生活事件只是 Peer Chat 的可选题材，不是事件一到就强制聊天。Aveline、Ling作为同住室友可以自然共享睡醒、饮食等近况；如果事件最先由某一角色从用户或 Samsung Health 得知，另一角色引用时必须保留转告来源。聊天中的“我起来了”只表示恢复正常打扰，正式主睡眠起床时间仍以 Samsung Health 为准，午睡单独记为 `nap_wake`。

#### 消息标识
Peer Script 消息通过 `extra_payload` 元数据标识，不使用内容前缀：
```python
extra_payload = {
    "target_qq_id": "目标QQ号",       # 消息发送到哪个QQ
    "is_peer_script": True,            # 兼容标记
    "message_type": "peer_script"      # 统一消息类型标识
}
```

#### 分发流程
```
Active Care ProactiveChecker 决策触发
    │
    ▼
executor.generate_peer_script()
    ├── 读取 multi_qq_config.json（一次读取，复用配置）
    ├── 获取主人聊天记录 + 历史互聊记录
    ├── LLM 生成剧本 JSON（DeepSeek）
    ├── 解析剧本（PeerChatManager.parse_script）
    └── 逐条分发（通过 WebSocket 广播）
         ├── Aveline说的话 → target_cid=role_cid, target_qq=peer_role_qq_id
         ├── Ling说的话   → target_cid=peer_cid, target_qq=role_qq_id
         └── 提及主人     → target_cid=role_cid, target_qq=master_qq_id
              │
              ▼
         QQ Adapter Session 收到 proactive_message
              ├── 检测 is_peer_script / message_type == "peer_script"
              ├── 直接 adapter.send_to_napcat(peer_{target_qq_id}, content)
              └── continue 跳过（不触发AI回复）
```

#### 关键文件
| 文件 | 职责 |
|------|------|
| `core/services/active_care/core/executor.py` | 剧本生成与分发 |
| `core/services/active_care/core/proactive_checker.py` | Peer Chat 触发决策 |
| `clients/bots/qq/peer_chat.py` | PeerChatManager 角色配置、解析、延迟 |
| `clients/bots/qq/session/session.py` | 剧本消息接收与转发 |
| `core/agents/chat_agent_components/persona_system/prompt/qq_peer_context.py` | 剧本生成prompt |

#### 角色配置
角色配置在 `PeerChatManager.PEER_PROFILES` 中，包含性格、说话风格、关系描述。`multi_qq_config.json` 配置QQ号、persona_filename 等运行时参数。

## 9. 数据流与调用链路

### 9.1 对话主链路

```
用户消息
    │
    ▼
routers/api_v1/chat.py::chat()
    │
    ▼
core/services/aveline/service.py::AvelineService.chat()
    │
    ├──▶ core/services/aveline/chat_agent.py::ChatAgent.process()
    │        │
    │        ├──▶ 意图识别
    │        ├──▶ 记忆检索 (memory/weighted_memory_manager.py)
    │        ├──▶ 情绪更新 (core/emotion/manager.py)
    │        └──▶ LLM调用
    │
    ├──▶ core/services/scheduler/task_scheduler.py::submit_task()
    │        │
    │        └──▶ cpp_scheduler/ (C++调度引擎)
    │
    ├──▶ 记忆写入 (memory/weighted_memory_manager.py)
    │
    └──▶ WebSocket/HTTP返回
```

### 9.2 主动关怀链路

```
lifecycle_manager.initialize_active_care_service()
    │  读取 active_care_enabled 配置 → enable_proactive_checker
    ▼
core/services/active_care/core/service.py::ActiveCareService._proactive_loop()
    │
    ├──▶ if checker: ProactiveChecker.perform_check()
    │        │
    │        ├──▶ 客户端检测 / 私密模式检测
    │        ├──▶ 睡眠会话状态处理
    │        ├──▶ Focus reduced policy 检查
    │        ├──▶ Sleep probe policy 检查
    │        ├──▶ PriorityAnalyzer 优先级分析
    │        ├──▶ DecisionExecutor 动作选择 + LLM 决策
    │        └──▶ Executor.trigger_message() 消息生成和发送
    │
    └──▶ else: _fallback_proactive_check()  # 保底触发（checker 未启用时）
             │
             └──▶ Executor.trigger_message(sys_prompt_type="share_thought")

关键配置项（config/yaml/app.yaml）:
- active_care_enabled: true/false  → 控制 ProactiveChecker 是否启用
- active_care_require_active_client: true/false  → 是否要求有活跃客户端
- active_care_min_gap_seconds: 600  → 最小消息间隔
- active_care_default_next_check_seconds: 300  → 默认检查间隔
- active_care_daily_limit: 30  → 每日消息上限

关键阈值（core/services/active_care/shared/constants.py）:
- SILENCE_BREAKER_SECONDS: 1800  → 沉默打破阈值
- LONG_SILENCE_THRESHOLD_SECONDS: 600  → 长沉默判定阈值
- BACKOFF_BASE: 1.4, BACKOFF_CAP: 6.0  → 统一退避算法基数和上限
- JITTER_LOW_RATIO: 0.9, JITTER_HIGH_RATIO: 1.1  → 对称抖动因子
- EMOTION_INTERVAL_MULTIPLIERS  → 情绪-间隔乘数映射（配置化）
- AUTO_WAKE_MAX_HOURS: 14  → 自动退出晚安模式最大小时数
- GOODNIGHT_SIGNAL_GAP_SECONDS: 300  → 晚安后信号判定间隔
- INTERVAL_MIN_SECONDS: 30  → 最小检查间隔

决策上下文阈值（core/services/active_care/decision/decision_context.py）:
- long_silence_seconds: 3600（当 min_gap≤1200）或 min_gap*3（当 min_gap>1200）
- no_send_for_too_long: min_gap*2  → 无发送超时判定
```

### 9.2.1 今日计划落盘与提醒链路

Journal 自动日计划与 Workspace 硬提醒的边界：算法自动生成的时间块只进入 `daily_push_priority` / MDP 决策上下文，不再逐项创建硬提醒；只有用户明确新增或修改的定时项才以 `metadata.delivery_mode=hard` 注册。历史未带该标记的 `daily_task` 待发项由 Active Care 静默完成并交回 MDP，以保留未回复退避。

```
StudyService.get_review_overview()
WeaknessTracker.get_due_reviews(target_date)
StudyService.get_daily_study_summary_data(yesterday_date)
昨日 plan.json 的 pending / in_progress / sleep-skipped
    │
    ▼
journal/plan_candidate_builder.py
    │  业务事实 → PlanCandidate
    ▼
planning/engine.py
    │  稳定评分 + 固定项优先 + 冲突/容量约束
    ▼
journal plan.json（真源，source=algorithm_generated/algorithm_adjusted）
    ├──▶ Study Daily plan.md
    ├──▶ Active Care daily_push_priority / MDP
    └──▶ Workspace daily_tasks（journal_plan_snapshot，不建自动硬提醒）
```

工作日默认 `6 项 / 240 分钟`，周末 `5 项 / 180 分钟`，已配置节假日 `4 项 / 150 分钟`；时间窗与滚动上限在 `config/yaml/app.yaml::journal_plan.planning`。中午/傍晚检查点把 `pending/in_progress` 再转换成同一批候选并压缩剩余窗口，保持 completed/skipped/in_progress 语义，不调用 scheduler 或 LLM。睡眠结算继续将未完成项标记为 `skipped`，同时写 `settlement_reason=sleep`，第二天按 `carryover_count` 上限滚动。

下面的对话指令捕获链路属于“用户明确要求生成/替换 Workspace 计划”，不属于夜间/自动主计划生成；其显式定时项可保留硬提醒：

```
用户消息（如“帮我计划一下今天干什么”）
    │
    ▼
core/services/aveline/service.py::generate_response()
    │
    ├──▶ 通过 BERT 意图识别 `GENERATE_DAILY_PLAN`
    ├──▶ 追加 Plan Instruction，强制模型输出 HH:MM-HH:MM 时间块
    │
    ▼
core/services/aveline/response_postprocess.py::maybe_capture_daily_plan()
    │
    ├──▶ 解析回复中的时间计划
    ├──▶ 必要时用 LLM 做 JSON 提取兜底
    │
    ▼
core/services/workspace/service.py::replace_daily_plan()
    │
    ▼
core/services/workspace/daily_task_service.py::replace_daily_plan()
    │
    ├──▶ 替换旧的 planner_ai / study_progress pending 任务
    ├──▶ 保留 manual 与已完成任务
    ├──▶ 为 timed task 重新创建 reminder
    │
    ▼
core/services/active_care/core/service.py::notify_workspace_plan_updated()
    │
    ├──▶ 提前调整 checker.next_decision_ts
    └──▶ 唤醒 Active Care loop，等待最近一个计划提醒点
```

### 9.3 记录落盘链路

```
core/services/workspace/service.py::WorkspaceService
    │
    ├──▶ core/services/journal/storage.py (日记)
    │        │
    │        └──▶ companion_data/user_data/daily/YYYY/MM/DD/diary/*.json
    │
    ├──▶ core/services/daily/manager.py (画像)
    │        │
    │        └──▶ companion_data/user_data/daily_records/YYYY/M/D/daily_record.json
    │
    ├──▶ status_manager.py (状态)
    │        │
    │        └──▶ companion_data/user_data/status/user_status.json
    │
    ├──▶ journal/storage.py (用户主计划真源)
    │        │
    │        └──▶ companion_data/user_data/daily/YYYY/MM/DD/plan.json
    │
    ├──▶ daily_task_service.py (Journal 主计划的 Workspace/MDP 快照)
    │        │
    │        └──▶ companion_data/user_data/daily_records/YYYY/M/D/daily_record.json
    │
    ├──▶ core/food/manager.py (角色自主进食)
    │        │
    │        └──▶ companion_data/aveline_data/life_records/YYYY/M/D/daily_record.json
    │
    └──▶ 本地JSON存储
```

***

## 10. 配置系统详解

### 10.1 配置文件结构

```
config/
├── integrated_config.py         # 配置主入口（Settings + get_settings）
├── yaml_loader.py               # YAML解析、环境变量展开、配置映射
├── model_detector.py            # 模型目录解析与自动探测
├── cache_manager.py             # 启动缓存读写、签名校验、失效重建
├── task_scheduler_config.py     # 任务调度配置
└── yaml/
    └── app.yaml                 # 主配置文件
```

### 10.2 当前配置职责划分

- `integrated_config.py`
  - 定义 `AppSettings` 与各子配置类
  - 提供 `get_settings()` / `reset_settings_cache()` / 兼容 `Config`
- `yaml_loader.py`
  - 负责 `app.yaml` 解析、环境变量展开与 YAML → Settings 覆盖映射
- `model_detector.py`
  - 负责本地 LLM / 图像 / 视觉 / Whisper / GPT-SoVITS 自动探测
- `cache_manager.py`
  - 负责启动缓存文件、版本号、路径签名与缓存读写

### 10.3 主配置文件

```yaml
# config/yaml/app.yaml

# LLM配置
llm:
  backend: "cpp"                 # cpp | python | cloud
  model_path: "models/qwen-7b.gguf"
  n_gpu_layers: 35
  n_ctx: 4096
  temperature: 0.7
  max_tokens: 2048

# 云端LLM配置
cloud_llm:
  provider: "siliconflow"
  api_key: "${SILICONFLOW_API_KEY}"
  model: "Qwen/Qwen2.5-7B-Instruct"

# TTS配置
tts:
  engine: "qwen3_tts"
  sample_rate: 24000
  speed: 1.0
  pitch: 1.0

# VTube Studio配置
vtube:
  enabled: true
  host: "127.0.0.1"
  port: 8001

# 免疫系统配置
immune_system:
  enabled: true
  check_interval: 60
  cpu_threshold: 90.0
  memory_threshold: 90.0

# 主动关怀配置
active_care:
  enabled: true
  base_interval: 1800
  silence_threshold: 2700
  max_interval: 7200
  min_interval: 600

# 记忆配置
memory:
  short_term_max: 100
  decay_rate: 0.1
  min_weight: 0.1
  similarity_threshold: 0.7
```

### 10.4 配置类

```python
# config/integrated_config.py

from pydantic import BaseSettings

class LLMSettings(BaseSettings):
    backend: str = "cpp"
    model_path: str = "models/qwen-7b.gguf"
    n_gpu_layers: int = 35
    n_ctx: int = 4096
    temperature: float = 0.7
    max_tokens: int = 2048

class TTSSettings(BaseSettings):
    engine: str = "qwen3_tts"
    sample_rate: int = 24000
    speed: float = 1.0
    pitch: float = 1.0

class ActiveCareSettings(BaseSettings):
    enabled: bool = True
    base_interval: int = 1800
    silence_threshold: int = 2700
    max_interval: int = 7200
    min_interval: int = 600

class Settings(BaseSettings):
    llm: LLMSettings = LLMSettings()
    tts: TTSSettings = TTSSettings()
    active_care: ActiveCareSettings = ActiveCareSettings()
    
    class Config:
        env_file = ".env"
        env_nested_delimiter = "__"
```

***

## 11. 错误处理与日志系统

### 11.1 异常定义

**文件**: `core/exceptions.py`

```python
class XiaoyouError(Exception):
    """基础异常类"""
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)

class ModelNotFoundError(XiaoyouError):
    """模型未找到"""
    def __init__(self, model_id: str):
        super().__init__(f"Model not found: {model_id}", "MODEL_NOT_FOUND")

class ResourceExhaustedError(XiaoyouError):
    """资源耗尽"""
    def __init__(self, resource: str, required: int, available: int):
        super().__init__(
            f"Resource exhausted: {resource} (required: {required}, available: {available})",
            "RESOURCE_EXHAUSTED"
        )

class OOMError(XiaoyouError):
    """内存不足"""
    def __init__(self, details: str):
        super().__init__(f"Out of memory: {details}", "OOM_ERROR")
```

### 11.2 日志系统

**文件**: `core/utils/logger.py`（主日志系统）, `core/log_config.py`（向后兼容）

```python
# 推荐使用方式
from core.utils.logger import get_logger

logger = get_logger(__name__)
logger.info("消息内容")

# 带上下文的日志
logger.info("操作完成", extra={"context": {"user_id": "123", "action": "login"}})
```

**日志系统特性**:
- 异步日志支持（QueueHandler + QueueListener）
- colorama 颜色支持（Windows 兼容）
- 日志脱敏（log_sanitizer）
- AutoHeal 集成（ERROR+ 级别自动转发给异常检测器）
- 模块级日志文件
- 按日期自动分目录

**当日日志导航与板块分流**:

- `logs/YYYY/M/D/README.md`：查看顺序和板块说明。
- `important.log`：仅保留 WARNING+ 以及收发消息、健康起床、服务启停等关键事件。
- `sections/01_active_care.log` ~ `sections/07_other.log`：每条日志按 logger
  名称只进入一个功能板块。
- `xiaoyou_main.log`：保留完整聚合流，用于跨板块时序追踪，不作为日常首要排查入口。

**独立 debug 调试日志（统一归口 `logs/` 目录，受 `config/debug_config.py` 开关控制，全部默认关闭）**:

| 日志文件 | 开关 | 用途 |
|---------|------|------|
| `logs/active_care_debug.log` | `active_care_ws` | WebSocket 实时晚安/唤醒意图检测过程 |
| `logs/ws_handshake_debug.log` | `websocket_handshake` | WebSocket 握手诊断（403/连接失败定位，5MB 轮转） |
| `logs/api_calls_simple.log` | `api_call_log` | LLM API 调用记录 |
| `logs/server_debug.log` | `server_debug` | 桌面端 FastAPI server 进程调试（pywebview） |

> 约定：`debug_config.py` 集中管理所有独立 debug 日志开关，开启方式为 YAML（`config/yaml/app.yaml` 的 `debug:` 段）或环境变量 `XIAOYOU_DEBUG__<开关名>=true`。关闭时对应日志零写入，避免根目录/无控落盘堆积。

### 11.3 原子文件 I/O

**文件**: `core/utils/atomic_io.py`

```python
# 同步版本
from core.utils.atomic_io import safe_json_dump, safe_json_load

safe_json_dump(data, "path/to/file.json")
data = safe_json_load("path/to/file.json", default={})

# 异步版本
from core.utils.atomic_io import async_safe_json_dump, async_safe_json_load

await async_safe_json_dump(data, "path/to/file.json")
data = await async_safe_json_load("path/to/file.json", default={})

# 启用 fsync 保证数据持久化
safe_json_dump(data, "path/to/file.json", use_fsync=True)
```

**原子写入特性**:
- 线程+进程安全的临时文件命名（追加 uuid 保证协程间唯一）
- 指数退避重试（覆盖 Windows 杀毒软件/索引器锁）
- 可选 fsync 支持
- Windows 错误码检测（winerror 5/32）
- 同步/异步双版本
- **陈旧临时文件自动清理**：每次写入前清理同前缀、修改时间超过 5 分钟的 `.tmp_*` 残留（防止进程崩溃时临时文件泄漏，v2.x.x）

***

## 12. 性能优化指南

### 12.1 GPU显存优化

| 优化项  | 方法                | 效果      |
| ---- | ----------------- | ------- |
| 模型量化 | 使用GGUF Q4\_K\_M量化 | 显存减少50% |
| 动态卸载 | 低优先级模型自动卸载        | 避免OOM   |
| 批处理  | 合并推理请求            | 提高吞吐量   |
| KV缓存 | 启用KV缓存            | 加速生成    |

### 12.2 内存优化

| 优化项  | 方法        | 效果     |
| ---- | --------- | ------ |
| 异步缓存 | L1/L2多级缓存 | 减少重复计算 |
| 记忆蒸馏 | 压缩历史记忆    | 减少存储空间 |
| 延迟加载 | 按需加载模块    | 减少启动内存 |

### 12.3 响应延迟优化

| 优化项       | 方法              | 效果         |
| --------- | --------------- | ---------- |
| 流式输出      | SSE/WebSocket流式 | 首token延迟降低 |
| Fast Path | 本地正则匹配          | 毫秒级响应      |
| 预加载       | 预加载常用模型         | 减少加载延迟     |

***

## 相关文档索引

| 文档      | 路径                                    | 说明         |
| ------- | ------------------------------------- | ---------- |
| 主README | `readme.md`                           | 项目概述       |
| 核心技术亮点  | `TECHNICAL_HIGHLIGHTS.md`             | 12个核心技术亮点  |
| 更新日志    | `UPDATES.md`                          | 最新更新记录     |
| 客户端层文档  | `clients/README.md`                   | 客户端层详细文档   |
| QQ机器人文档 | `clients/bots/README.md`              | QQ机器人详细文档  |
| Web前端文档 | `clients/frontend/README.md`          | Web前端详细文档  |
| 核心层文档   | `core/README.md`                      | 核心层详细文档    |
| 服务层文档   | `core/services/README.md`             | 服务层详细文档    |
| 调度服务文档  | `core/services/scheduler/README.md`   | 调度服务详细文档   |
| 大文件阅读索引 | `BIGFILE_README.md`                   | 大文件入口与拆分边界 |
| 主动关怀文档  | `core/services/active_care/README.md` | 主动关怀详细文档   |
| 记忆系统文档  | `memory/README.md`                    | 记忆系统详细文档   |
| 路由层文档   | `routers/README.md`                   | 路由层详细文档    |
| 测试系统文档  | `tests/README.md`                     | 测试系统详细文档   |
| 维护工具文档  | `maintenance/README.md`               | 维护工具详细文档   |
| 学习工具文档  | `core/tools/study/README.md`          | 学习工具详细文档   |
| 资源管理层文档 | `core/资源管理层README.md`                | 资源管理模块详解   |
| 工具与辅助系统 | `core/工具与辅助系统README.md`              | 工具/Utils/Managers/Emotion/Voice/Image |
| 自愈服务文档  | `core/services/auto_heal/README.md`   | 自愈服务安全机制   |
| 远程操作规范  | `core/services/remote_ops/RemoteOps-Spec.md` | 远程操作规范文档 |
| C++调度器  | `cpp_modules/cpp_scheduler/README.md` | C++资源隔离调度器 |
| 向量索引    | `cpp_modules/cpp_memory_index/README.md` | 高性能向量索引   |
| Token计数 | `cpp_modules/cpp_fast_tokenizer/README.md` | 轻量Token计数 |
| 音频处理    | `cpp_modules/cpp_audio_processor/README.md` | 音频预处理+VAD |
| BERT引擎  | `cpp_modules/cpp_bert_engine/README.md` | BERT推理引擎  |

***

**文档版本**: 3.3.0
**最后更新**: 2026-06-19
**维护者**: Xiaoyou Core Team
