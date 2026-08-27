"""Question_Reviewer 分类共享模块。

提供类别定义与基于标题关键词的自动归类逻辑，供：
- `split_question_reviewer.py` 一次性拆分旧 `Question_Reviewer.md`
- `update_project_records.py` 后续按类别追加新记录

新增/调整类别时只需修改本文件。
"""

from __future__ import annotations


# 分类定义：顺序即优先级（先匹配先归类）
# (类别文件名, 类别中文名, 关键词列表)
# 注意：关键词应尽量短且具特征性，避免被通用类目（LLM / build_test_env）抢走
CATEGORIES: list[tuple[str, str, list[str]]] = [
    # Active Care 必须放在 LLM / 通用关键词之前，避免被通用类目抢走
    (
        "01_active_care",
        "Active Care 主动关怀",
        [
            "Active Care", "active_care", "ActiveCare", "主动关怀",
            "proactive", "Proactive", "主动消息", "PeerChat", "peer chat", "peer_chat",
            "sleep_recovery", "conversation_incomplete", "conversation_stalled",
            "manual_delay", "reduced_mode", "Goodnight", "GoodnightMode",
            "wakeup", "waking_up", "NightlyProcessor", "nightly_processor",
            "ReminderInjection", "reminder", "Reminder", "提醒注入",
            "stale persona", "stale_persona",
            "ReplyPolicy", "reply_policy",
            "submit_llm_task", "SubmitLLMTask",
            "sleep_state_store", "睡眠状态", "睡眠窗口", "睡眠会话",
            "probable_sleep", "perform_check", "probe_gap", "探针",
            "backoff", "退避", "延时惩罚", "间隔保护", "overlap_guard",
            "优先级分析", "priority_focus", "PriorityFocus",
            "low_touch", "低打扰",
            "Daily Routine", "每日任务",
            "时间解析", "extract_time", "record_sleep", "record_wakeup",
            "daily_record", "作息时间", "睡眠/起床",
            "继续聊", "PeerChatScheduler",
            "ProactiveChecker", "proactive_checker",
            "AC-", "AC_", "AC:",  # ID 形如 QR-20260630-AC-CONFLICT
            "due_reminder",
            "dual_role",
        ],
    ),
    # Phase-Aware 调度器：在 LLM 之前
    (
        "14_scheduler_phase_aware",
        "Phase-Aware 调度器",
        [
            "Phase-Aware", "PhaseAware", "phase_aware",
            "RESIDENT_MIGRATABLE", "backfill_hidden_time",
            "LLMState", "PhaseScheduler",
        ],
    ),
    # C++ 调度器：在 LLM 之前
    (
        "03_cpp_scheduler",
        "C++ 调度器与 GPU",
        [
            "C++ 调度器", "C++ Scheduler", "C++ scheduler", "cpp_scheduler",
            "scheduler_py", "C++ Worker", "C++ LLM", "C++ GPU",
            "GPU LLM Worker", "BUILD_TESTING",
            "gpu推理卡死", "GPU推理卡死", "GPU利用率",
            "显存溢出", "显存优化", "显存深度", "显存争抢", "显存压力",
            "ConnectionResetError", "Access Violation",
            "Forge 生图", "Forge生图", "Forge",
        ],
    ),
    # TTS / STT / 语音：在 LLM 之前
    (
        "05_tts_stt_voice",
        "TTS / STT / 语音",
        [
            "TTS", "STT", "Qwen3-TTS", "GPT-SoVITS", "SoX",
            "语音服务", "语音合成", "语音识别", "Device Migration",
            "transformers 5.x", "transformers 5",
            "create_causal_mask", "cache_position",
            "TTS_ENGINE", "TTS 不可用", "TTS初始化",
            "WebSocketHandler", "_get_tts_manager", "synthesize_and_play",
            "_synthesize_tts", "_ensure_tts_manager",
        ],
    ),
    # 图片生成与视觉：在 LLM 之前
    (
        "13_image_vision",
        "图片生成与视觉",
        [
            "ComfyUI", "KSampler", "latent=None",
            "图片生成", "画图", "画了个画", "边画图边聊天",
            "MVP Core", "image_status", "image_task",
            "CQ码图片", "NapCat无法识别",
            "Vision描述", "Vision Module", "视觉模型",
            "图片状态机", "图片任务", "image 任务",
            "图片生成误触发", "图片异步", "生图",
        ],
    ),
    # 文件 IO / 数据存储：在 WinError 通用之前
    (
        "10_file_io_storage",
        "文件 IO 与数据存储",
        [
            "atomic_io", "async_safe_json_dump",
            "Active Care Storage", "ActiveCareStorage",
            "proactive_state.json", "sleep_states.json",
            "Bad file descriptor", "FileNotFoundError",
            "atomic_write", "atomic dump",
            "storage scope", "scope 并发", "scope 并发状态",
        ],
    ),
    # Android / 前端：在 QQ 之前
    (
        "02_android_frontend",
        "Android / 前端",
        [
            "Android", "前端", "移动端",
            "Compose", "Compose BOM", "DrawerContent",
            "HorizontalPager", "ModalNavigationDrawer",
            "LeftEdgeDrawer", "LeftEdgeDrawerGesture",
            "Capacitor", "WebView", "Mixed Content",
            "键盘白屏", "断句不生效", "ChatFlushManager",
            "ChatViewModel", "Hilt", "kotlinx-coroutines",
            "Room Flow", "uiState",
            "Switch", "onCheckedChange", "press ripple",
            "SectionCard", "DrawerLayout",
            "BackHandler", "全面屏返回",
            "insets 驱动", "insets", "WindowInsets",
            "Next.js", "app/layout.js", "app/page.js",
            "Tk GUI", "呼吸灯",
            "消息气泡", "消息重复显示",
            "原生安卓",
        ],
    ),
    # QQ 适配器 / 消息断句：在通用关键词之前
    (
        "06_qq_message_split",
        "QQ 适配器与消息断句",
        [
            "QQ Adapter", "QQ adapter", "QQ适配器", "QQ 适配器",
            "QQ消息", "QQ Bot", "QQ 动作", "QQ emoji",
            "QQ连接", "QQ账号", "双QQ", "双角色私聊",
            "断句", "消息chunk", "消息 chunk",
            "CQ码", "NapCat", "base64 乱码",
            "颜文字", "emoji 过滤",
            "续接词", "续接合并",
            "消息气泡类型", "消息发送",
        ],
    ),
    # WebSocket / 网络：在通用关键词之前
    (
        "08_websocket_network",
        "WebSocket 与网络",
        [
            "WebSocket", "websocket", "WebSocketManager",
            "心跳", "keepalive", "ping timeout",
            "ping/pong", "handle_heartbeat", "handle_pong",
            "连接泄漏", "WebSocket 路由",
            "断连", "断开异常", "1006", "no close frame",
            "Unclosed connector", "aiohttp",
            "TransferEncodingError", "Transfer Encoding",
        ],
    ),
    # 记忆系统：在 LLM 之前
    (
        "07_memory_system",
        "记忆系统",
        [
            "记忆系统", "短期记忆", "长期记忆", "记忆管理", "记忆权重", "记忆蒸馏", "记忆分类",
            "WeightedMemory", "WeightedMemoryManager",
            "VectorSearch", "chromadb", "ChromaDB",
            "memory_manager",
            "save_memory", "save_conversation_history",
            "向量搜索",
            "ReadwriteLock", "ReadWriteLock",
            "写锁", "自锁死锁", "self-deadlock",
            "asyncio.Lock",
            "get_recent_history", "get_write_lock", "get_read_lock",
            "history_ops",
        ],
    ),
    # Persona / 角色：在 LLM 之前
    (
        "11_persona_character",
        "Persona / 角色系统",
        [
            "persona", "Persona", "persona_filename",
            "人设", "角色", "双角色",
            "Ling", "Aveline", "澪姐", "主人",
            "CharacterDaily", "character_daily",
            "人设混乱", "人设切换", "人设列表",
            "stale persona", "stale_persona",
        ],
    ),
    # 日记 / 每日总结：在 LLM 之前
    (
        "12_diary_journal",
        "日记与每日总结",
        [
            "日记", "Diary", "diary",
            "Journal", "journal_service", "JournalSummary",
            "每日总结", "DailySummary", "daily_summary",
            "月总结", "monthly_summary",
            "后台圈子", "日记每日总结",
            "summary_parse_support",
        ],
    ),
    # 生命模拟 / 自动进食：在 LLM 之前
    (
        "16_life_simulation",
        "生命模拟与自动进食",
        [
            "FoodSystem", "food_system", "tick_digestion",
            "auto_eat", "AUTO_EAT", "自动喂食", "自动进食",
            "hunger", "Hunger", "饥饿",
            "生命模拟", "life_simulation", "LifeSimulation",
            "life_stats", "life_stats_state",
            "energy", "精力", "低精力",
            "sleep_manager", "SleepManager",
            "nightmare_level", "impact_level",
            "sleep_inertia", "sleep_debt",
            "新陈代谢", "digestion",
            "ActorManager", "actor_life_state", "actor_states",
            "心情", "mood", "mood_score", "EmotionManager", "EmotionResponder",
        ],
    ),
    # Chat Agent：在通用 LLM 之前
    (
        "15_chat_agent",
        "主对话 Agent",
        [
            "ChatAgent", "chat_agent", "ChatAgent.py",
            "stream_generate_response", "stream_chat",
            "流式输出", "流式回复", "流式对话",
            "tool-calling", "tool_calls", "ToolDispatcher",
            "意图识别", "学习模式", "学习工具",
            "BERT", "bert_analyzer", "get_bert_analyzer",
            "图片生成误触发", "图片触发",
            "context_overflow", "上下文窗口",
            "上下文丢失", "上下文隔离",
            "thinking", "Thinking Process",
            "DSML token", "DSML",
            "reasoning_content", "reasoning_split",
            "deepseek", "DeepSeek",
            "submit_llm_task",
            "study_tool", "study_service", "StudyService",
            "vocabulary_manager", "VocabularyManager",
            "Pydantic", "default_factory",
            "WorkspaceService", "workspace 最近历史", "workspace",
            "schedule_message", "handler.py", "EmotionResponder",
            "AI 回复", "强行截断", "消息超时", "路由与异常",
            "对话生成", "对话样本", "SFW", "NSFW",
            "JSON 解析", "落盘条数",
            "model_manager", "list_models",
            "动态对话示例", "generated_data",
            "manual_selected", "语气注入", "手动验证",
        ],
    ),
    # LLM / 模型调用：通用兜底
    (
        "04_llm_model",
        "LLM 与模型调用",
        [
            "MiniMax", "MiniMax-M2.5",
            "Qwen3", "Qwen", "qwen_tts",
            "LLM", "llm",
            "推理模型", "reasoning",
            "本地模型", "本地 GGUF", "GGUF", "本地推理",
            "Cloud API", "云端", "SiliconFlow", "OpenAI", "兼容层", "cloud:custom",
            "API 400", "API 404",
            "DeepSeek v4", "DeepSeek V4",
            "DSML", "thinking 模式", "思考模式",
            "invalid vector subscript",
            "首 token", "首包",
            "模型名传None", "model_path",
            "模型切换", "模型双重加载",
            "上下文预算", "上下文窗口",
        ],
    ),
    # 构建 / 测试 / 环境
    (
        "09_build_test_env",
        "构建 / 测试 / 环境",
        [
            "Pytest", "pytest", "PyInstaller", "Pyinstaller",
            "Ruff", "ruff", "Flake8", "flake8",
            "Linux", "WSL", "WSL2",
            "Windows", "WinError", "WinError 1920",
            "Tk GUI", "PowerShell", "PSReadLine",
            "LaTeX", "lstlisting",
            "Pywin32", "pywin32", "pyreadline3",
            "依赖失败", "依赖收敛", "开发依赖",
            "编译失败", "编译错误", "编译与路径",
            "编译避坑", "编译exe", "Android 编译",
            "venv_core", "venv",
            "环境", "环境变量",
            "Diagnostic", "诊断脚本",
            "verify_", "验证脚本",
            "压力测试", "stress test",
            "测试清理", "清理重复",
            "代码规范", "F841", "F401",
            "DeprecationWarning", "FutureWarning",
            "NameError", "SyntaxError",
            "UnboundLocalError",
            "ABI 不匹配", "ABI",
            "Python 3.10", "Python 3.11",
            "Tk GUI",
            "幽灵进程", "内存泄漏",
            "文档漂移", "技术参考拆分",
            "接口返回格式",
            "优雅关闭", "生命周期超时",
            "信号增强", "SetConsoleCtrlHandler",
            "ERROR 日志", "logs/errors", "ErrorReporter", "error_collector",
            ".git", "Git 历史", "Git 历史丢失",
            "安全改造", "崩溃恢复", "性能报告", "指标数字",
            "YAML", "AppSettings", "debug 字段",
            "异步恢复", "断言使用", "固定 sleep",
            "单文件脚本", "项目根路径",
        ],
    ),
    # 兜底
    (
        "17_misc",
        "其他",
        [],
    ),
]


# 合法的类别文件名集合（不含 .md 后缀），用于校验 entry.category 字段
VALID_CATEGORY_FILES: set[str] = {file_name for file_name, _, _ in CATEGORIES}


def categorize(title: str) -> tuple[str, str]:
    """根据标题关键词判定类别，返回 (类别文件名, 类别中文名)。"""
    for file_name, display_name, keywords in CATEGORIES:
        if not keywords:
            continue
        for kw in keywords:
            if kw in title:
                return file_name, display_name
    return "17_misc", "其他"


def resolve_category(title: str, explicit: str | None = None) -> tuple[str, str]:
    """解析类别：优先用 explicit，否则按标题自动归类。

    explicit 可以是文件名（如 `01_active_care`）或带后缀（如 `01_active_care.md`）。
    """
    if explicit:
        normalized = explicit.removesuffix(".md").strip()
        if normalized in VALID_CATEGORY_FILES:
            for file_name, display_name, _ in CATEGORIES:
                if file_name == normalized:
                    return file_name, display_name
        # 显式指定但不在合法列表里：报错而不是默默兜底，避免拼错写到 misc
        raise ValueError(
            f"非法 category: {explicit!r}，合法值见 question_categories.CATEGORIES"
        )
    return categorize(title)
