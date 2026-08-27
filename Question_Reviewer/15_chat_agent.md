# 主对话 Agent

本分类共 32 条记录。按时间倒序（最新在前）排列。

---

### 10.141 `chat_agent.py` 顶层硬导入 `core.tools.study` 导致主对话直接崩溃（2026-06-28）

*   **问题描述**: Aveline 主对话在 `stream_generate_response` 内导入 `core.agents.chat_agent` 时，直接抛出 `ModuleNotFoundError: No module named 'core.tools.study'`，导致流式回复完全失败。
*   **复现步骤**:
    1. 当前仓库中不存在 `core/tools/study/` 目录
    2. 触发任意需要 `AvelineService` 走 `stream_generate_response` 的对话请求
    3. 执行到 `from core.agents.chat_agent import get_default_chat_agent`
    4. `chat_agent.py` 顶层执行 `from core.tools.study.english.vocabulary_manager import VocabularyManager`
    5. 立即抛出 `ModuleNotFoundError`
*   **预期行为**: 词汇学习模块缺失时，主对话应降级运行，只关闭相关词汇能力，而不是整条对话链中断。
*   **实际行为**: 因为顶层硬导入发生在模块加载阶段，`ChatAgent` 甚至还没开始初始化，主对话已直接失败。
*   **根因**: 学习词汇模块已经不在当前仓库中，但 `chat_agent.py` 仍保留旧的顶层硬依赖；模块级导入没有任何降级保护，导致可选功能变成了启动前置条件。
*   **修复**:
    1. 新增 `core/agents/chat_agent_components/vocab_compat.py`，统一做惰性导入和降级
    2. `chat_agent.py` 移除顶层 `VocabularyManager` 硬导入，改为构造时调用兼容辅助
    3. 缺失模块时仅记录 warning，并将 `vocab_manager` 设为 `None`
    4. 新增 `tests/diagnostics/verify_chat_agent_vocab_import_guard.py` 验证回归
*   **验证**: `venv_core\Scripts\python.exe tests\diagnostics\verify_chat_agent_vocab_import_guard.py`

### 问题 2: model_manager list_models 日志刷屏 (2026-06-27)


*   **问题描述**: `core/core_engine/model_manager.py` 的 `list_models` 方法用 `logger.info` 输出 `[DEBUG]` 级别内容，每次调用都打印全部模型列表（30+ 个模型名），日志刷屏。
*   **复现步骤**:
    1. 后端运行，任何调用 `list_models(model_type="llm")` 的场景
    2. 日志输出 `[INFO] [core.core_engine.model_manager] [DEBUG] 所有注册的模型: ['L3-8B-...', 'qwen2.5-...', ...]`（约 30 个模型名）
*   **预期行为**: 这类调试信息应在 debug 级别输出，默认 info 级别不显示。
*   **实际行为**: 三行 `logger.info` 每次调用都输出，刷屏。
*   **修复方案**: `logger.info` → `logger.debug`，去掉 `[DEBUG]` 前缀。

### 10.135 `WorkspaceService.schedule_message()` 参数名不匹配（2026-06-20）

*   **问题描述**: `JournalService._sync_plan_to_reminders` 调用 `ws.schedule_message(message_type="text")` 时报 `got an unexpected keyword argument 'message_type'`。
*   **复现步骤**:
    *   调用 `WorkspaceService.schedule_message(message=..., trigger_ts=..., message_type="text", metadata=...)`；
    *   观察到 TypeError。
*   **预期行为**: `WorkspaceService.schedule_message()` 应接受 `message_type` 参数。
*   **实际行为**: `WorkspaceService.schedule_message()` 的参数名为 `type`（不是 `message_type`），内部再转发给 `ReminderService.schedule_message(message_type=type)`。
*   **原因分析**:
    *   `WorkspaceService.schedule_message()` 签名为 `(message, trigger_ts, type="text", metadata=None)`，参数名是 `type`；
    *   底层 `ReminderService.schedule_message()` 签名为 `(message, trigger_ts, message_type="text", metadata=None)`，参数名是 `message_type`；
    *   两层 API 参数名不一致，调用方误用了底层参数名。
*   **解决方案**: 将 `JournalService` 中三处 `schedule_message` 调用的 `message_type="text"` 改为 `type="text"`（`core/services/journal/service.py`）。

### 10.133 Pydantic 类字段名遮蔽模块名导致 `default_factory=time.time` 报错（2026-06-20）

*   **问题描述**: `core/services/journal/models.py` 的 `PlanItem` 类中，`created_at: float = Field(default_factory=time.time)` 抛出 `AttributeError: 'FieldInfo' object has no attribute 'time'`。
*   **复现步骤**:
    *   在同一个 Pydantic BaseModel 子类中，先定义一个名为 `time` 的字段（如 `time: Optional[str] = Field(default=None)`）；
    *   随后在同一个类中用 `Field(default_factory=time.time)` 引用标准库 `time` 模块的 `time.time` 函数；
    *   类定义时即抛出 `AttributeError`。
*   **预期行为**: `default_factory=time.time` 应正确引用 `time` 模块的 `time()` 函数。
*   **实际行为**: `time` 被解析为前一行定义的 FieldInfo 对象（`PlanItem.time` 字段），而非模块级 `time`，导致 `time.time` 访问失败。
*   **原因分析**:
    *   Pydantic 在类定义时，`time: Optional[str] = Field(...)` 会在类作用域创建一个名为 `time` 的类变量（值为 FieldInfo）；
    *   `default_factory=time.time` 在类体中即时求值，此时 `time` 指向类作用域中的 FieldInfo 对象，遮蔽了模块级 `import time`；
    *   注意：同一文件中 `JournalEntry` / `DailySummary` 等类没有 `time` 字段，所以它们的 `default_factory=time.time` 不受影响。
*   **解决方案**: 在文件顶部增加别名导入 `import time as _time`，在 `PlanItem` 中使用 `default_factory=_time.time`（`core/services/journal/models.py:5,86-87`）。

### 10.123 workspace 最近历史 limit 绑定验证失败 (2026-06-14)

*   **问题描述**: 复查 Active Care 衔接时顺手运行 `tests/diagnostics/verify_history_limit_keyword_binding.py`，workspace 分支断言失败。
*   **复现步骤**:
    1. 在项目根目录运行 `venv_core\Scripts\python.exe tests\diagnostics\verify_history_limit_keyword_binding.py`
    2. 观察 workspace service 的 fake memory manager 调用参数。
*   **预期行为**: `WorkspaceService._get_recent_conversation_history("default_user", history_limit=12)` 调用记忆管理器时 `limit == 12`。
*   **实际行为**: 脚本输出 `FAIL: workspace get_history limit binding wrong: {'scope': None, 'raw': False, 'exclude_categories': None, 'limit': 13}`。
*   **备注**: 该失败与本次 Active Care 主动关怀/主对话衔接改动无关，暂未混入本次修复范围。

---

## 2026-06-17 P0 问题修复记录

### 10.125 流式输出 tool-calling 循环中间轮次内容泄露 (2026-06-13)

*   **问题描述**: 用户问一个问题时，LLM 对同一个问题回复了三段内容。日志显示 LLM 被调用了3次（API Call #14319, #14320, #14321），每次调用都通过 `_emit_visible_text` 直接 yield 内容给前端，导致用户看到多段重复回复
*   **复现步骤**:
    1. 用户发送需要调用工具的消息（如食物相关）
    2. LLM 第1轮：输出文本 + 调用 `show_inventory`/`get_aveline_meals` 工具
    3. LLM 第2轮：输出文本 + 调用 `feed_food` 工具
    4. LLM 第3轮：输出最终文本（无工具调用）
    5. 用户收到3段文本，每段都是对同一问题的回复
*   **预期行为**: 用户只看到最终轮次的回复，中间工具调用轮次的文本不应显示
*   **实际行为**: 每轮 LLM 调用的内容都通过 `_emit_visible_text` 直接流式输出给用户
*   **根本原因**: `streaming.py` 的 `stream_chat_impl` 中，tool-calling 循环（`while current_turn < max_turns`）的每一轮都通过 `_emit_visible_text`（async generator）直接 yield token 事件给前端。Native Tool 路径和 `[tool_use:]` 路径都没有抑制中间轮次的文本输出。Native Tool 路径甚至没有重置 `current_response_content`，导致多轮文本累积
*   **修复方法**:
    1. 将 `_emit_visible_text`（async generator）替换为 `_buffer_visible_text`（普通函数），将事件缓存到 `turn_event_buffer` 而非直接 yield
    2. 将 try 块内所有直接 yield 语句（thought_chain、image_trigger 等）改为 `turn_event_buffer.append()`
    3. 中间轮次（`tool_executed_this_turn == True`）结束时：丢弃 buffer，重置 `current_response_content = content_at_turn_start`
    4. 最终轮次（无工具调用）结束时：输出所有缓存的事件 `for evt in turn_event_buffer: yield evt`

### 10.70 模型名传None导致DeepSeek API 400错误（2026-05-29）

*   **问题描述**: DeepSeek API 返回 400 错误：`"The supported API model names are deepseek-v4-pro or deepseek-v4-flash, but you passed None."`
*   **复现步骤**:
    1. app.yaml 的 `model.llm` 节只设置 `provider: "deepseek"`，不设置 `model` 字段
    2. 启动服务，发送任意消息
    3. 观察日志：`[ERROR] [openai_client] API Error (400): ...you passed None.`
*   **预期行为**: 应使用 `model_routing.default_chat_model` 中配置的模型名
*   **实际行为**: `settings.model.llm.model` 为 None，构造出 `"cloud:deepseek:None"`，API 收到字符串 `"None"`
*   **根因**: `chat_handlers.py:_sync_with_global_config()` 直接使用 `settings.model.llm.model` 拼接模型路径，当该字段为 None 时未做回退处理
*   **修复**:
    1. 优先从 `get_default_chat_model()` 获取完整路径
    2. 回退时增加 None 保护，使用默认模型名 `deepseek-v4-pro`
    3. 同步修复 `api_v1/chat.py`、`core/llm/__init__.py` 中的相同问题

### 10.107 DeepSeek thinking 模式 reasoning_content 未回传导致 400 错误 (2026-05-13)

*   **问题描述**: DeepSeek thinking 模式下，LLM 返回 tool_calls 后执行工具并重试时，API 返回 400 错误：`The reasoning_content in the thinking mode must be passed back to the API.`
*   **复现步骤**:
    1. 用户发送消息触发 DeepSeek thinking 模式
    2. LLM 返回 `reasoning_content` + `tool_calls`（空 response）
    3. ChatAgent 进入 retry 路径，执行 tool
    4. 构建 assistant 消息时**未包含 `reasoning_content`**
    5. 第二次 LLM 调用 → DeepSeek API 返回 400 错误
*   **预期行为**: assistant 消息应包含 `reasoning_content`，DeepSeek API 正常接受请求
*   **实际行为**: `reasoning_content` 被丢弃，API 拒绝请求返回 400
*   **根因**: 三处代码丢失 `reasoning_content`：
    1. `streaming.py` 第 1076-1087 行：retry 路径构建 tool_call 的 assistant 消息时未包含 `reasoning_content`（对比原生 tool_call 路径第 577-578 行是有的）
    2. `client.py` 第 267-271 行：原生 `finish_reason == "tool_calls"` 返回时未包含 `reasoning_content`
    3. `client.py` 第 331-332 行：content 为空但 reasoning 非空时，将 reasoning 当作 content 返回，`reasoning_content` 字段丢失
*   **修复方案**:
    1. `streaming.py` retry 路径：构建 assistant 消息时，若 `retry_reasoning` 非空则添加 `reasoning_content` 字段
    2. `client.py` 原生 tool_calls 返回：补上 `reasoning_content` 字段
    3. `client.py` content 为空时：改为返回 `reasoning_only: True` + `reasoning_content` 字段，不再将 reasoning 当作 content
*   **涉及文件**: `core/agents/chat_agent_components/streaming.py`、`core/llm/openai_compat/client.py`

### 10.94 DeepSeek 思考模式 reasoning_content 未回传 API 导致 400 错误 (2026-05-09)

*   **问题描述**: DeepSeek 思考模式启用后，多轮对话中 API 返回 400 错误："The `reasoning_content` in the thinking mode must be passed back to the API."
*   **复现步骤**:
    1. 启用 DeepSeek 思考模式（thinking_enabled=True）
    2. 进行多轮对话，第一轮模型返回 reasoning_content
    3. 第二轮请求时，历史消息中 assistant 消息缺少 reasoning_content 字段
    4. DeepSeek API 返回 400 错误
*   **预期行为**: 后续 API 请求中 assistant 消息应包含 reasoning_content 字段，DeepSeek API 正常接受
*   **实际行为**: reasoning_content 在历史恢复链路中丢失，导致 API 拒绝请求
*   **根因**（3层丢失）:
    1. `save_conversation_history()` 将 thought_text 保存为独立的 system 消息（category="thinking"），而非 assistant 消息的 reasoning_content 字段
    2. `WeightedMemoryManager.get_history()` 只返回 `{role, content, timestamp}`，丢弃了 reasoning_content、tool_calls、tool_call_id 等扩展字段
    3. `fetch_history_for_scope()` 中 category="thinking" 被 exclude_categories 排除，思考内容不会出现在历史消息中
*   **修复方案**:
    1. `history.py`: 将 reasoning_content 保存到 assistant 消息的 metadata 中
    2. `weighted_memory_manager.py`: get_history() 从 metadata 提取 reasoning_content、tool_calls、tool_call_id 并返回
    3. `context_budget.py`: _sanitize_history_messages() 不再跳过含 reasoning_content 或 tool_calls 的空 content 消息
    4. `client.py`: _parse_non_stream_response() 和 chat() 返回 reasoning_content 字段
*   **涉及文件**: `core/agents/chat_agent_components/history.py`、`memory/weighted_memory_manager.py`、`core/agents/chat_agent_components/context_budget.py`、`core/llm/openai_compat/client.py`

### 10.91 retry 逻辑未处理 tool_calls 返回值，用户收到空回复 (2026-05-08)

*   **问题描述**: LLM 多轮 tool call 后只返回思考内容无可见文本，触发 retry 逻辑，但 retry 返回了 tool_calls 而非文本，用户收到空回复
*   **复现步骤**:
    1. 用户发消息，LLM 调用 get_daily_summary、search_memory、aveline_daily_data 等工具
    2. 多轮 tool call 后，LLM 只返回 thought_content，无可见文本
    3. 触发 retry 逻辑（"visible response empty, retrying once without think output"）
    4. retry 使用非流式 chat() 调用，未传 tools 参数
    5. DeepSeek v4 仍通过 DSML 格式在 content 中输出 tool call
    6. DSML 兜底解析将 content 清空，提取 tool_calls
    7. retry 代码只取 response/content 字段，忽略 tool_calls
    8. retry_text 为空，current_response_content 为空，用户收到空回复
*   **预期行为**: retry 应处理 tool_calls 返回值，执行工具后再生成文本回复
*   **实际行为**: retry 忽略 tool_calls，直接返回空内容
*   **根因**: retry 代码假设非流式 chat() 不会返回 tool_calls，但 DeepSeek v4 的 DSML 格式可以在无 tools 参数时仍输出工具调用
*   **修复方案**: retry 返回值新增 tool_calls 处理分支，执行工具后再次调用 LLM 生成文本；retry 生成的文本逐字 yield 给前端保证打字效果

### 10.88 学习模式下 bot 看不到自己发的题目，用户回复时上下文丢失 (2026-05-07)

*   **问题描述**: bot 发历史题后，用户回复答案，bot 完全看不到自己发的题目，反复要求用户重复内容（"看不到你发的题目图片"）
*   **复现步骤**:
    1. bot 发送学习题目（如历史4道选择题），保存为 `category="learning"`
    2. 用户回复答案（如 "B，A的话应该是英国..."），答案不含学习模式触发词
    3. `is_study_mode()` 对用户答案返回 False
    4. `fetch_history_for_scope(is_study_mode=False)` 排除 `learning` 类别消息
    5. bot 看不到自己发的题目，上下文断裂
*   **预期行为**: bot 应能看到自己之前发的学习题目，在用户回复答案时保持上下文连贯
*   **实际行为**: bot 对自己发的学习题目完全失忆，反复要求用户重复
*   **根因**: 学习模式消息隔离机制过于激进——`fetch_history_for_scope()` 在非学习模式下一刀切排除所有 `learning` 类别消息，没有考虑"用户正在回答学习问题"的场景。`is_study_mode()` 的触发词和关键词列表不够覆盖用户的答案格式（如 "B，A的话应该是英国..."）
*   **修复方案**: `context_budget.py` 新增 `_check_recent_learning_context()` 函数，当非学习模式下获取历史时，先检查最近 10 条消息中是否有 `learning` 类别的 assistant 消息（bot 出的题），如果有则自动包含 learning 上下文，确保用户回答学习问题时 bot 能看到自己发的题目

### 10.72 "Thinking Process:" 解析正则过于严格，无法识别 Qwen 的推理输出格式 (2026-05-03)

*   **问题描述**: Qwen3.5-27B 作为 Active Care Checker 决策模型时，输出 "Thinking Process:\n\n1. **Analyze the Request:**..." 推理文本，但 `_extract_json_block()` 和 `strip_reasoning_segments()` 中的正则只匹配 `> **Thinking Process:**` 格式（有 `> ` 前缀和 `**` 加粗标记），导致推理文本无法被剥离
*   **复现步骤**: 配置 Active Care Checker 使用 `Qwen/Qwen3.5-27B` 模型，触发决策，观察日志中 LLM 返回的 raw response 包含 "Thinking Process:" 推理文本
*   **预期行为**: 推理文本应被正确定位并剥离，只保留纯 JSON 部分进行解析
*   **实际行为**: 推理文本未被剥离，`constants.extract_json_block()` 的 `{.*?}` 非贪心正则可能匹配到推理文本中的花括号，或 `rfind("}")` 兜底把推理文本和 JSON 一起返回，导致 `json.loads()` 失败，最终走正则兜底解析
*   **根因**: 现有正则 `> \*\*Thinking Process:\*\*.*?` 要求 `> ` 前缀和 `**` 加粗标记都必须存在。Qwen 输出的是裸 `Thinking Process:` 格式，完全不匹配
*   **修复方案**:
    1. `decision.py:_extract_json_block()` 正则改为 `(?:>\s*\*\*)?(?:Thinking Process|思考过程)\s*:?(?:\*\*)?.*?` — 使前缀和加粗标记可选
    2. `postprocessor.py:strip_reasoning_segments()` 同步修改相同正则
    3. 同时支持中文 "思考过程：" 格式
*   **关键文件**: `core/services/active_care/decision.py:154`, `core/services/active_care/postprocessor.py:482-487`

### 10.70 DeepSeek V4 DSML token 泄漏：工具调用以原始文本形式输出 (2026-05-03)

*   **问题描述**: DeepSeek V4 Pro 模型在调用工具时，API 有时不解析内部 `<｜｜DSML｜｜>` 特殊 token，导致原始 DSML 格式文本（如 `<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="aveline_daily_data">...`）泄漏到 `content`/`response` 字段，前端直接显示给用户
*   **复现步骤**: 使用 DeepSeek V4 Pro 模型（`cloud:deepseek:deepseek-v4-pro`）进行对话，触发工具调用（如 aveline_daily_data），观察日志 `HybridLLM cloud result type=dict preview={'response': '<｜｜DSML｜｜tool_calls>...'}`
*   **预期行为**: API 应将 DSML token 解析为结构化 `tool_calls` JSON 字段，前端不应看到任何 DSML 文本
*   **实际行为**: DSML token 作为原始文本出现在 `content` 字段，前端显示乱码般的 DSML 标签
*   **根因**: DeepSeek V4 内部使用 `<｜｜DSML｜｜>` 特殊 token 表示工具调用。正常情况下 API 服务端解析这些 token 为结构化 `tool_calls`，但某些情况下（API bug、模型版本、tools 参数未正确传递）API 不解析，token 泄漏为文本
*   **修复方案**:
    1. 新增 `dsml_parser.py`：支持 V4/V3.2/Plain 三种 DSML 格式的检测和解析
    2. 非流式路径：`_parse_non_stream_response()` 中添加 DSML 兜底解析
    3. 流式路径：`OpenAIClient._process_stream_chunk()` 在 LLM 客户端层拦截 DSML token，缓冲完整块后解析为 `tool_calls`
    4. streaming.py 添加 DSML 残留清理（安全网）
*   **关键文件**: `core/llm/openai_compat/dsml_parser.py`, `core/llm/openai_compat/client.py`, `core/agents/chat_agent_components/streaming.py`

### 10.68 意图识别误触发：普通聊天被错误识别为系统指令 (2026-05-02)

*   **问题描述**: 用户发送普通聊天消息时，系统错误地触发了意图识别指令，返回了不相关的系统回复
    - "我之后就一直在修你" → "系统：已收到，Active Care 将在约 30 分钟后再提醒你"（ACTIVE_CARE_SNOOZE 误触发）
    - "四对炸鸡翅根" → "这些功能建议使用网页端的设置/面板入口操作"（LIST_MODELS/SHOW_STATUS 误触发）
    - "其实我有点累了想睡觉了" → "请告诉我你要切换到哪个模型"（SWITCH_MODEL 误触发）
    - "想睡又不是会睡，而且你干嘛老是回这么多" → "系统：已收到，Active Care 将在约 30 分钟后再提醒你"（ACTIVE_CARE_SNOOZE 误触发）
*   **复现步骤**: 在私聊中发送上述普通聊天消息，系统返回意图识别相关的系统回复而非正常聊天回复
*   **预期行为**: 系统应正常聊天回复，不应触发任何系统指令
*   **实际行为**: 系统将普通聊天误判为系统指令，返回了不相关的系统回复
*   **根因**:
    1. `_RULE_ACTIVE_CARE_DELAY_RE` 正则包含 "之后"、"以后" 等极常见中文词，任何含这些词的句子都会被规则层直接判定为 ACTIVE_CARE_SNOOZE（confidence 0.92），无需额外上下文
    2. BERT 安全守卫只覆盖了 `TOGGLE_LATENCY`、`SHOW_STATUS`、`TOGGLE_REPLY_MODE` 三个意图，`SWITCH_MODEL`、`SWITCH_MODEL_HINT`、`ACTIVE_CARE_SNOOZE`、`LIST_MODELS`、`LIST_VOICES` 等意图没有守卫，BERT 误判直接通过
    3. `_RULE_NARRATIVE_PREFIX_RE` 叙事性前缀列表太短（只有13个词），大量普通对话无法在规则层被拦截为 NONE，落入 BERT 分类后被误判
*   **修复方案**:
    1. 将 "之后/以后" 从 `_RULE_ACTIVE_CARE_DELAY_RE` 移除，新增 `_RULE_ACTIVE_CARE_DELAY_CONTEXT_RE`（匹配之后/以后）和 `_RULE_ACTIVE_CARE_SNOOZE_VERB_RE`（匹配提醒/叫/找/通知/打扰/烦），规则层要求 "之后/以后" 必须搭配提醒动词才触发 SNOOZE
    2. 扩展 BERT 安全守卫：新增 `SWITCH_MODEL`、`SWITCH_MODEL_HINT`、`LIST_MODELS`、`LIST_VOICES` 的命令语气校验（`_has_explicit_command_tone`），以及 `ACTIVE_CARE_SNOOZE` 的专用 snooze 语气校验（`_has_explicit_snooze_tone`）
    3. 扩展 `_RULE_NARRATIVE_PREFIX_RE` 至 50+ 个词（新增 "其实/感觉/觉得/想/要/会/能/但是/所以/因为" 等），在规则层 NONE 拦截中增加叙事前缀检测和代词开头检测

### 10.64 MiniMax-M2.5 reasoning_split 实测验证 (2026-04-30)

*   **问题描述**: 之前 Active Care 发送的 QQ 消息是推理泄露内容（如"但规则说"优先顺着你上一"），需要验证 `reasoning_split=True` 修复是否生效
*   **实测结果**:
    - **无 reasoning_split**：`content` 字段包含 `<think...>` 标签的推理+实际回复混合内容（460字符），`reasoning_content` 为空
    - **有 reasoning_split=True**：`content` 字段只包含干净的实际回复（如"哎呀又被发现了！我这就来，别吃独食等我呀~"），推理被分离到 `reasoning_details` 字段
    - **MiniMaxClient 封装调用**：返回 `{"response": "啊呀，被你说中了！刚忙着打字完全忘了饿！马上来蹭你的夜宵～", "reasoning_only": False}`
    - **Active Care 完整场景**：返回 `{"response": "哈哈又被你发现了，马上吃！", "reasoning_only": False}`，LeakDetector 判定无泄露
*   **结论**: `reasoning_split=True` 修复有效，MiniMax-M2.5 在该模式下能正确返回干净的实际回复。之前的泄露是因为没有 `reasoning_split=True`，推理内容混入了 `content` 字段

### 10.48 流式对话上下文完全丢失 - asyncio.create_task 在 yield done 之后导致保存代码永远不执行 (2026-04-29)

*   **问题描述**: AI 完全看不到上下文，每发一条消息就像开了新对话一样。`get_history()` 始终返回空列表
*   **复现步骤**:
    1. 启动 Xiaoyou Core 后端
    2. 通过 WebSocket 或 HTTP streaming 发送消息
    3. AI 正常回复
    4. 再发一条消息，AI 完全不记得上一条说了什么
*   **预期行为**: AI 能看到之前的对话历史，保持上下文连续
*   **实际行为**: 每条消息都是全新对话，AI 看不到任何历史
*   **根因**: 4/28 的优化（10.47）将 `asyncio.create_task(save_conversation_history)` 放在 `yield {"done": True}` 之后。但消费端 `stream_conversation_events` 收到 done 后执行 `break` 退出 `async for` 循环，Python 自动调用 `aclose()` 关闭生成器。生成器被关闭后，`yield` 之后的代码（包括 `asyncio.create_task`）**永远不执行**，对话历史从不保存到 `short_term_memory`
*   **修复**:
    1. 将 `asyncio.create_task(save_conversation_history)` 移到 `yield {"done": True}` **之前**，确保保存任务在生成器被关闭前已调度
    2. 附加修复：`perform_context_summary` 和 `command/handler.py` 中使用 `memory_manager.lock`（旧锁）而非 `_rw_lock`（新读写锁），与 `add_memory`/`get_history` 存在数据竞争，统一改为读写锁
*   **调用链**: `stream_chat_impl` → `yield {"done": True}` → 消费端 `break` → `aclose()` → 生成器关闭 → 保存代码不执行
*   **教训**: Python 异步生成器中，`yield` 之后的代码不保证执行。如果消费端 `break` 退出循环，生成器会被 `aclose()` 关闭，`yield` 之后的代码被跳过。需要确保关键逻辑（如保存数据）在 `yield` 之前完成调度，或使用 `try/finally` 保证执行

### 10.46 get_bert_analyzer() 死锁导致消息不处理 (2026-04-28)

*   **问题描述**: 用户发送消息后，系统日志显示 `stream_generate_response` 启动但之后无任何输出，消息完全不被处理。日志最后停留在"为用户启动异步保存线程"
*   **复现步骤**:
    1. 启动 Xiaoyou Core 后端
    2. 通过 WebSocket 发送一条消息（如"小澪？"）
    3. 观察日志：`stream_generate_response` 启动后无后续日志，无响应返回
*   **预期行为**: 消息正常处理，LLM 流式返回响应
*   **实际行为**: 消息处理卡死，无任何响应
*   **根因**: `get_bert_analyzer()` 使用 `threading.Lock()`（不可重入锁）作为 `_SINGLETON_LOCK`，在锁内调用 `BertAnalyzer()`，而 `BertAnalyzer.__new__` 也尝试获取同一个 `_SINGLETON_LOCK`。同一线程重复获取不可重入锁导致永久死锁。调用链：`stream_generate_response` → `classify_intent` → `get_bert_analyzer()`（同步调用）→ 死锁 → 事件循环被阻塞
*   **修复**:
    1. 将 `_SINGLETON_LOCK` 从 `threading.Lock()` 改为 `threading.RLock()`（可重入锁）
    2. 将 `classify_intent` 中的 `get_bert_analyzer()` 改为 `await asyncio.to_thread(get_bert_analyzer)` 避免阻塞事件循环
    3. 给 BERT 分析添加 `asyncio.wait_for(timeout=10.0)` 超时保护
    4. 将 handlers.py 中同步 `_get_memory_manager` 改为异步 `get_memory_manager_async`

### 10.42 DeepSeek v4-pro 思考模式下 content 被 <think 标签吞掉 (2026-04-27)

*   **问题描述**: DeepSeek v4-pro 思考模式下，每次对话都触发 `StreamChat: visible response empty, retrying once without think output`，导致每次对话产生 2 次 API 调用
*   **复现步骤**:
    1. 启动服务，使用 `cloud:deepseek:deepseek-v4-pro` 模型
    2. 发送任意消息
    3. 观察日志：`[WARNING] [ChatAgent] StreamChat: visible response empty, retrying once without think output`
*   **预期行为**: DeepSeek v4-pro 的 `content` 字段包含完整回答，不应触发 retry
*   **实际行为**: `current_response_content` 为空，触发二次 API 调用
*   **根因**: DeepSeek v4-pro 思考模式下，`content` 字段中会冗余包含 `<think/>...</think/>` 标签。`streaming.py` 的 `pending_text` 缓冲逻辑遇到 `<think` 就进入 `in_think=True` 状态，导致所有后续 content 被当作 `thought_content` 吞掉
*   **修复**: 
    1. 在 content chunk 进入 `pending_text` 前，用正则清理冗余的 `<think/>` 和 `</think/>` 标签
    2. `pending_text` 中的 `<think` 标签处理逻辑增加判断——如果已有 `thought_content`，则直接跳过冗余标签块
*   **关键发现**: DeepSeek API 的 `reasoning_content` 和 `content` 字段都可能包含 `<think/>` 标签，前者是真正的思考内容，后者是冗余标签。代码需要区分处理

### 10.33 手动验证语气注入时实际流式推理因 `NoneType` 报错中断 (2026-04-08)

*   **问题描述**: 为验证 `manual_selected.txt` 注入后的实际说话语气，直接运行 `ChatAgent.stream_chat` 进行一次真实回复测试时，流式推理阶段报错 `argument of type 'NoneType' is not iterable`，导致无法基于真实模型输出判断“像不像人工样例”。
*   **复现步骤**:
    *   初始化 `ChatAgent`
    *   调用 `stream_chat(user_id="manual_selected_probe", message="你下班了吗", save_history=False)`
    *   Prompt 构建完成后进入 LLM streaming
    *   日志报错：`[ChatAgent] LLM streaming error: argument of type 'NoneType' is not iterable`
*   **预期行为**: 能正常返回一条真实模型回复，用于对比 `manual_selected.txt` 的语气风格。
*   **实际行为**: Prompt 已成功构建，但实际流式推理失败，无法完成“生成结果像不像”的端到端验证。
*   **当前结论**:
    *   `manual_selected.txt` 已确认被读取并稳定注入到 prompt 前缀
    *   风格相似度的真实生成验证被当前 LLM 流式报错阻断，需要单独排查模型流式链路里的 `None` 来源

### 10.31 BERT 误分类"我被鸟吵醒的"为SLEEP_NOW导致睡觉时间被覆盖 (2026-04-08)

*   **问题描述**: Active Care 说"昨晚只睡了26分钟"，实际原因是 daily_record.json 中 sleep 被错误记录为 06:01（应为 22:01）。
*   **复现步骤**:
    *   用户在 22:01 说"晚安" → 正确记录 sleep=22:01
    *   次日早上用户说"我被鸟吵醒的，太吵了"
    *   BERT zero-shot 分类器将此文本错误分类为 SLEEP_NOW（置信度 0.978）
    *   extractor 的 `_apply_bert_record` 执行 `record_sleep(05:59)`，熬夜逻辑归到前一天
    *   **sleep=22:01 被 06:01 覆盖**，且 `record_sleep` 无幂等保护
    *   Active Care 基于错误的 sleep=06:01 + wakeup=06:31 计算，得出"只睡了26分钟"
*   **预期行为**: "我被鸟吵醒的"应被识别为 WAKEUP_NOW（起床），不应触发 record_sleep
*   **实际行为**:
    *   BERT 将"我起来了"、"我被鸟吵醒的"、"（捏你）"全部误分类
    *   `_looks_like_wakeup` 规则层因 token 列表不完整（缺少"被吵醒"/"醒来"等）+ 无"醒"字兜底，防护完全失效
    *   `record_sleep` 无幂等保护，后调用的错误值直接覆盖正确值
*   **解决方案**:
    *   **从根源上修复**：扩展 `STATE_EVENT_DEFINITIONS` 中 WAKEUP_NOW（3→17个例子）和 SLEEP_NOW（3→9个例子）的定义，BERT 现在正确分类"我被鸟吵醒的"为 WAKEUP_NOW
    *   **规则层兜底**：扩展 `_looks_like_wakeup` token 列表（新增11个变体），添加"醒"字兜底检测
    *   **数据层保护**：`record_sleep` 添加幂等保护，已有晚间值时拒绝凌晨覆盖值
    *   同时增强了 Active Care 睡眠幻觉拦截和"不用回我"多样性

### 10.34 Emotion 相关单测暴露 DummyChatAgent 契约过期 (2026-04-02)

*   **问题描述**: 运行情绪相关单测时，`tests/unit/test_server_handler_emotion_fields.py` 失败，无法进入最终消息断言。
*   **复现步骤**:
    *   在项目根目录执行 `.\venv_core\Scripts\python.exe -m pytest tests\unit\test_emotion_influence.py tests\unit\test_emotion_stream_metadata.py tests\unit\test_server_handler_emotion_fields.py -q`。
*   **预期行为**: WebSocket Handler 能正常走完整个流式转发链路，并在最终消息中携带 `emotion` / `emotion_internal` 字段。
*   **实际行为**:
    *   `forward_chat_stream` 读取 `handler.chat_agent.config.system_prompt` 时抛出 `AttributeError: '_DummyChatAgent' object has no attribute 'config'`。
    *   由于异常提前返回，测试里收不到最终 `message` 包，断言 `final` 为空。
*   **原因分析**: `test_server_handler_emotion_fields.py` 中的 `_DummyChatAgent` 仍沿用旧契约，未补齐当前 `forward_chat_stream` 所需的 `config.system_prompt` 属性。
*   **解决方案**:
    *   更新该测试桩，补齐最小 `config` 对象与 `system_prompt` 字段。
    *   如果后续继续扩展 Handler 依赖，优先集中封装一个可复用的 ChatAgent 测试桩，避免多处 Dummy 再次过期。

### 10.69.1 动态对话示例未参考 `generated_data`（2026-01-01）

*   **问题描述**: 你在 `generated_data/*.jsonl` 里准备了"参考对话语气"，但运行时动态 system prompt 注入的示例对话并未稳定命中这些参考样本，导致回复更像"助手腔"，与参考对话不一致。
*   **复现步骤**:
    *   直接启动服

### 10.9 彻底解决 AI 回复强行截断问题 (2025-12-28)

*   **问题描述**: 用户反馈 AI 说话经常说一半就没了，表现为强硬截断。这在之前的 10.8 修复中虽然通过恢复 `reply_char_limit` 解决了“短回复”需求，但牺牲了长回复的完整性。
*   **原因分析**: 代码层面使用 `reply_hard_stop` 配合字数上限直接 `break` 了生成流，导致模型没有机会生成自然结尾（如标点或语气词）。
*   **解决方案**:
    *   **重构截断逻辑**: 彻底移除 `reply_hard_stop` 硬截断判断，将 `reply_char_limit` 改为 `soft_reply_char_limit`。
    *   **柔性引导**: 不再在代码中强行中断，而是将长度预期作为指令注入 `system_prompt`（例如：“回复请尽量保持在 X 字以内，保持自然，不要刻意截断”）。
    *   **结果**: AI 能够根据指令自主控制长度，同时保证了每一句话都有完整的逻辑结尾，彻底解决了“说话断一半”的糟糕体验。
*   **后续原则**: 优先使用 Prompt 引导模型行为，非必要不使用硬编码逻辑干预模型生成过程。

### 10.6 学习模式提示词优化 (2025-12-21)

*   **文件化提示词**: 将学习模式的 System Prompt 从代码硬编码 (`get_aveline_cloud_persona_prompt_sfw`) 迁移至独立配置文件 `core/character/configs/Aveline_Cloud_Study.txt`。
*   **DeepSeek 优化**: 针对 DeepSeek 模型特性重写提示词，增加结构化 JSON 输出要求与思维链 (Chain of Thought) 引导。
*   **动态加载**: 修改 `persona.py` 实现运行时动态加载，支持热更新提示词而无需重启服务。
*   **SFW 强制**: 在配置文件中明确 Safe For Work (SFW) 协议，确保云端模型输出安全。

### 10.62 SFW 对话样本输出文件被覆盖（固定文件名 + 意外清空）（2025-12-20）

*   **问题描述**:
    *   使用 `scripts/generate_dialogue_examples.py` 多次生成 SFW 日常闲聊样本，并指定 `--tag` 或 `--output` 时，输出文件名固定，导致重复运行时容易覆盖旧样本。
    *   在一次修复中曾引入“启动时以 `w` 模式初始化文件”的逻辑，导致旧 JSONL 被清空，表现为“之前跑过的 100 轮找不到了”。
*   **复现步骤**:
    *   运行：`python .\\scripts\\generate_dialogue_examples.py --mode sfw-daily --count 100 --turns 2 --tag cloud-local-persona`
    *   再次运行同样命令（或显式指定同一 `--output`），观察输出 JSONL 是否被覆盖/清空。
*   **预期行为**:
    *   默认每次运行生成独立的 JSONL 文件，不覆盖既有数据。
    *   仅当用户显式要求追加（`--append`）或明确覆盖时才写入到同一文件。
*   **实际行为**:
    *   输出文件名固定时，多次运行会写到同一文件；若存在清空逻辑则会直接丢失旧样本。
*   **解决方案**:
    *   `--append` 未开启时，输出文件名强制带时间戳，保证每次运行落到独立文件。
    *   当显式 `--output` 指定目标文件且已存在、同时未开启 `--append` 时，自动生成带时间戳的新文件名，避免覆盖旧文件。文件：`scripts/generate_dialogue_examples.py`
    *   数据恢复：利用 ChromaDB 持久化向量库 `aveline_dialogue_sfw_daily` 中的历史文档重新导出 JSONL，按 `id` 尾号连续序列选出完整的 0..99 共 100 条样本重建本地文件。

### 10.61 NSFW 对话样本未落盘（脚本禁用/目录混淆/云端回落风险）（2025-12-20）

*   **问题描述**:
    *   使用 `scripts/generate_dialogue_examples.py` 生成 NSFW 对话样本时，`generated_data`/`generate_data` 目录下未出现对应 JSONL 文件，向量库 `aveline_dialogue_nsfw` 也未写入新文档。
*   **复现步骤**:
    *   执行：`python .\\scripts\\generate_dialogue_examples.py --nsfw --count 5 --turns 4`
    *   或执行：`python .\\scripts\\generate_dialogue_examples.py --mode nsfw --count 5 --turns 4`
    *   检查项目根目录下 `generated_data/` 或 `generate_data/` 的输出文件是否生成。
*   **预期行为**:
    *   NSFW 模式能正常生成样本并写入向量库 `aveline_dialogue_nsfw`，同时把 JSONL 输出到 `generated_data/`（或显式 `--output-dir` 指定目录）。
    *   NSFW 样本不应走云端模型，避免把成人内容发送到云端供应商。
*   **实际行为**:
    *   旧逻辑中 `--nsfw` 会直接抛错导致流程终止；即使进入生成流程，在仅云端配置且未指定 `model_path` 的情况下，Hybrid 路由可能回落到云端模型。
    *   目录命名上同时存在 `generated_data` 与历史兼容的 `generate_data`，如果误看了另一个目录，会造成“没落盘”的错觉。
*   **解决方案**:
    *   `generate_dialogue_examples.py` 增加 `nsfw` 模式：支持 `--mode nsfw` 与 `--nsfw` 别名，collection 使用 `aveline_dialogue_nsfw`，metadata 标记 `is_nsfw=true`，并按 JSONL 逐行落盘。
    *   强制 NSFW 仅使用本地模型：无本地 LLM 模块时直接报错；禁止 `model_path` 以 `cloud:` 开头，避免回落到云端。
    *   输出目录解析保持兼容：默认优先 `generated_data/`，同时兼容历史 `generate_data/`；实际写入路径以日志 `Saving examples to:` 为准。
*   **验证**:
    *   运行：`python -m ruff check .`、`python -m mypy .`、`python -m pytest` 通过。
    *   运行脚本时日志会打印 `Saving examples to:` 的实际 JSONL 路径；在本地模型可用时应可看到 NSFW JSONL 文件新增行，并且 `aveline_dialogue_nsfw` collection 有新增文档。

### 10.60 对话生成返回非严格 JSON 导致解析失败与落盘条数不足（2025-12-20）

*   **问题描述**:
    *   运行 `scripts/generate_dialogue_examples.py` 生成对话样本时，模型偶尔返回被 ```json 代码块包裹、或包含结尾多余逗号等“非严格 JSON”，导致脚本 `json.loads` 解析失败。
    *   解析失败会触发 `Failed to parse response` 警告，样本既不会写入向量库也不会写入 JSONL 文件；如果按“迭代次数”计数，还会出现“跑了 N 次但落盘不足 N 条”的错觉。
*   **复现步骤**:
    *   执行：`python .\\scripts\\generate_dialogue_examples.py --mode sfw-daily --count 100 --turns 4`
    *   观察日志出现 `Failed to parse response. Raw: ```json { ... }`，或 JSON 末尾出现 `,}` / `,]` 等结构。
    *   检查输出 JSONL 行数明显少于 `--count` 期望值。
*   **预期行为**:
    *   脚本在遇到轻微格式瑕疵（代码块包裹、尾逗号）时仍能成功解析并落盘。
    *   生成条数以“成功落盘条数”为准，最终落盘条数应达到 `--count`（在合理重试次数内）。
*   **实际行为**:
    *   严格解析失败导致样本丢弃；并且当脚本按“循环次数”推进时，最终落盘条数可能不足。
*   **解决方案**:
    *   增加容错 JSON 解析：去除代码块包裹、清理 BOM/零宽字符、移除 `,}`/`,]` 尾逗号后再解析。
    *   生成循环改为按“成功条数”计数，并增加最大尝试次数上限，避免解析失败导致条数不足或无限循环。
*   **验证**:
    *   运行同样命令后，解析失败显著减少；即使偶发失败，也能在最大尝试次数内达到目标落盘条数。

### 10.41 本地/云端上下文隔离、NSFW 仅本地与清空记忆接口统一（2025-12-18）

*   **目标**:
    *   本地模型与云端模型的对话上下文严格隔离，避免跨域“串话”；
    *   私密（NSFW/Private）内容只保留在本地记忆与本地模型上下文中；
    *   每日学习/计划只注入云端上下文；
    *   提供一键清空记忆能力，并具备可回归的测试覆盖。
*   **实现要点**:
    *   **按 scope 拉取历史**: `build_conversation_history` 通过 `model_hint`/当前模型名判定 `is_cloud`，并用 `scope="cloud"|"local"` 调用 `memory_manager.get_history(scope=scope)`，从源头隔离历史可见性（`core/agents/chat_agent_components/context.py`、`memory/weighted_memory_manager.py`）。
    *   **NSFW 独立存储与仅本地注入**:
    *   `save_conversation_history` 识别 `/nsfw` `/private` 或 `[nsfw]/[private]` 标记，强制 `scopes=["local"]` 且 `category="nsfw"`（`core/agents/chat_agent_components/history.py`）；
    *   `WeightedMemoryManager.add_memory` 对 `category == "nsfw"` 的记忆写入 `nsfw_memories` 并固定 `scopes=["local"]`，落盘到 `history/nsfw/{user}_nsfw.json`（`memory/weighted_memory_manager.py`）；
    *   **动态隔离验证**: 仅在本地模型构建上下文时，读取 `get_nsfw_memories()` 并以 system message 注入；当处于敏感模式时，系统会强制将全局 `scope` 锁定为 `local`，彻底杜绝敏感信息流向云端（`core/agents/chat_agent_components/context.py`）。
    *   **SFW 隔离机制**: Aveline 角色管理类（`aveline.py`）仅在云端模式且非敏感状态下注入 SFW 提示词；本地模式下自动加载 `sensitive_examples` 范例。
    *   **每日学习总结仅云端注入**: 流式对话中只在 `is_cloud` 且非私密对话时调用 `_check_daily_routine` 并插入 `daily_summary`（`core/agents/chat_agent_components/streaming.py`）。
    *   **清空记忆接口统一**:
        *   `POST /api/v1/memory/clear` 与 `DELETE /api/v1/memory/clear` 统一走 `ChatAgent.clear_history(mode=all|short)`；
        *   对 `short_term/short-term` 等别名归一化为 `short`，避免前端/脚本传参不一致（`routers/api_router.py`）。
*   **验证与回归**:
    *   新增/补齐用例覆盖：NSFW 仅本地注入、私密消息强制本地打标、每日任务仅云端注入、清空记忆接口透传 `mode`（`tests/test_context_overflow.py`）。
    *   `pytest` 回归通过：`python -m pytest`。

*   **问题记录：`import routers.api_router as api` 得到的是 `APIRouter` 不是模块**:
    *   **问题描述**: 在测试里写 `import routers.api_router as api`，随后访问 `api.clear_memory_endpoint` 报错：`AttributeError: 'APIRouter' object has no attribute ...`。
    *   **复现步骤**:
        1. `routers/__init__.py` 中存在 `from .api_router import router as api_router`；
        2. 在任意代码中执行 `import routers.api_router as api`；
        3. `type(api)` 变为 `fastapi.routing.APIRouter`，而非 `routers/api_router.py` 模块对象。
    *   **预期行为**: `api` 应是子模块（可访问 `clear_memory_endpoint`、`ClearMemoryRequest` 等符号）。
    *   **实际行为**: `api` 被解析为包属性 `routers.api_router`（即 `APIRouter` 实例），导致测试/调用方无法访问模块级函数。
*   **解决方案**: 在测试/动态导入场景使用 `importlib.import_module("routers.api_router")` 强制导入子模块对象，避免与包导出属性同名时的歧义。

### 10.25 ChatAgent 组件化与调度测试清理 (2025-12-16)

*   **组件化重构**: 将 `ChatAgent` 拆分为 `core/agents/chat_agent_components/` 目录下的多个子模块（上下文、触发器、流式输出、人设、学习模式、历史记录等），显著降低单文件复杂度。
*   **薄壳模式**: `core/agents/chat_agent.py` 仅保留对外方法与少量编排逻辑，大部分实现下沉到组件中，方便独立演进与单元测试。
*   **测试清理**: 删除 `tests/test_cpp_scheduler_binding.py`，避免依赖硬编码本地模型路径的临时脚本，仅保留 `tests/test_scheduler_binding.py` 作为 C++ 调度绑定的主测试入口。

### 10.20 本地 GGUF 模型上下文窗口超限与用户可见错误文案优化 (2025-12-16)


*   **问题描述**: 使用本地 GGUF 模型（通过 `llama_cpp` Python 端集成）时，在长对话或单次输入过长场景下，`llama_cpp` 抛出 `Requested tokens (24136) exceed context window of 2048` 等异常，`CPPSchedulerEngine` 之前直接将异常文本包装为 `"抱歉，本地模型出错：{e}"` 作为流式最后一个 token 返回，导致前端用户能看到带有英文堆栈信息和 “context window” 等技术细节的错误提示，体验较差。
*   **复现步骤**:
    *   在默认本地 GGUF 模型开启的情况下，连续进行多轮长文本聊天，或一次性粘贴非常长的中文段落；
    *   通过桌面宠或 `/api/v1/message` 发送上述内容，观察当上下文长度逼近 `n_ctx=2048` 时的表现；
    *   在问题修复前，前端会收到形如 “抱歉，本地模型出错：Requested tokens (24136) exceed context window of 2048” 的回复。
*   **原因分析**:
    *   `CPPSchedulerEngine.submit_llm_task` 在使用 Python 侧 `Llama.create_chat_completion(stream=True)` 时，将整个推理过程包裹在 `try/except` 中；
    *   一旦发生异常（包括上下文窗口超限、显存不足、CUDA 错误等），旧逻辑会直接将异常字符串插入到返回给前端的文本中，缺乏针对不同错误类型的友好文案；
    *   虽然 `ChatAgent._build_conversation_history` 已增加了本地模型的字符级切片（`max_chars=1800`），但极端情况下（如单条用户输入特别长或外部配置的 `n_ctx` 较小）仍可能触发 `llama_cpp` 的上下文窗口异常；
    *   早期版本中，通过字符串包含 `"qwen"`/`"deepseek"` 判断云端模型，导致本地 Qwen GGUF 路径（如 `models/llm/Qwen2___5-7B-Instruct-Q4_K_M.gguf`）被误判为云端模型，跳过了本地历史截断逻辑，实际仍向 `llama_cpp` 投喂了超长上下文，因此在前端看起来是“普通多轮对话突然报 context window 错误”，本质是模型类型判定策略过于粗糙 (`core/agents/chat_agent.py:1296-1301`)。
*   **修复方案**:
    *   保留异常的详细信息在日志中，仅使用友好的中文提示对用户展示：
        *   对包含 `"exceed context window" / "context window of" / "maximum context length"` 的异常，返回文案：引导用户减少单次输入长度或拆分问题，而不再暴露英文错误信息；
        *   对包含 `"out of memory" / "CUDA error" / "OOM"` 的异常，返回文案：提示系统资源紧张，建议稍后重试或简化问题；
        *   其他未知异常，统一使用温和的恢复性文案，提示“刚刚有点没反应过来”，避免制造紧张感；
    *   新逻辑仍然通过流式队列返回单条友好文本，并立即结束本次会话，不再附带原始异常字符串 (`core/services/scheduler/cpp_scheduler_engine.py:280-320`)；
    *   将本地/云端模型的判定规则统一改为基于显式前缀 `cloud:`，在 `_build_conversation_history` 中仅当 `model_hint` 或当前模型名包含 `cloud:` 时才视为云端模型，从而保证所有 GGUF 本地模型（包括 Qwen/L3 等）都会经过统一的字符级历史截断，最大程度避免再次触发 `Requested tokens exceed context window` 这一类错误 (`core/agents/chat_agent_components/context.py:195-253`)；
    *   在 `CPPSchedulerEngine.submit_llm_task` 中引入基于 `max_context_size` 的安全上限：对传入的 `max_tokens` 做半窗口限制（`<= n_ctx * 0.5`，且不小于 128），并对纯字符串 `prompt` 按字符长度进行尾部截断（上限约为 `n_ctx * 4` 个字符），避免由于配置层将 `max_new_tokens` 设得过大或外部模块直接投喂超长文本导致再次触发 `Requested tokens (...) exceed context window of ...` 这一类错误 (`core/services/scheduler/cpp_scheduler_engine.py:238-288`)。
    *   针对未通过 C++ 调度器而是直接走本地 `LLMModule` GGUF 推理路径的场景，在 `LLMModule.stream_chat` 与 `_chat_sync_gguf` 内同样引入基于实际 `n_ctx` 的 `max_tokens` 上限（同样为 `max(n_ctx * 0.5, 128)`），通过查询 `llama_model.n_ctx()` 或回退到配置/全局默认值，避免当全局 `max_new_tokens` 误配为数万级时再次向 `llama_cpp` 发送远超上下文窗口的生成长度请求 (`core/modules/llm/module.py:220-238, 479-488`)。
*   **验证与回归测试**:
    *   扩展了 `tests/test_empty_responses.py` 的检查逻辑，除了原本的 “回复非空且不包含‘无回复内容’” 之外，新增了对以下关键字的排除校验：`"本地模型出错"`, `"exceed context window"`, `"context window of"`；
    *   通过 `AvelineService.generate_response` 和 `/api/v1/message` 的回归调用，确认在极端长输入场景下，前端只会看到简洁的中文提示，不再泄露底层异常细节；
    *   同时配合 `ChatAgent._build_conversation_history` 的本地上下文切片逻辑（本地模型历史约束在 ~1800 字符内），显著降低了触发上下文窗口异常的概率，从源头缓解问题。
*   **经验总结**:
    *   面向终端用户的错误信息需要与内部异常解耦：日志中保留完整错误堆栈，用户端则只暴露必要且可行动的提示；
    *   本地大模型在 Windows + 消费级 GPU 场景下，`n_ctx`、历史长度和单次输入长度三者叠加容易触发 “context window” 类错误，应同时从 Prompt 构建（历史截断）和错误文案两个层面进行优化；
    *   自动化回归脚本（如 `test_empty_responses.py`）应同时检查 “空回复” 与 “技术细节泄露” 两类问题，避免只关注是否有内容而忽略内容本身对用户体验的影响。

### 10.19 云端 DeepSeek 无回复与 SiliconFlow 400 错误 (2025-12-16)



*   **问题描述**: 使用云端 DeepSeek 模型（通过 SiliconFlow）时，前端经常出现“（无回复内容）”，日志中可见 `Stream Error 400: {"code":20015,"message":"Input tag 'system_summary' found using 'role' does not match any of the expected tags: 'system', 'user', 'assistant', 'tool'"}`，但 `ChatAgent` 仍然记录了 “First token received” 和 “Stream generation completed”。
*   **复现步骤**:
    *   使用带有较长对话历史的会话聊天，触发上下文摘要逻辑 `_perform_context_summary`；
    *   选择云端 DeepSeek 模型（`deepseek-ai/DeepSeek-V3.2`），通过 `/api/v1/message` 或 WebSocket 发送消息；
    *   终端日志中出现上述 SiliconFlow 400 错误，同时前端显示“无回复内容”。
*   **原因分析**:
    *   上下文摘要会通过 `WeightedMemoryManager.add_memory` 以 `source="system_summary"` 保存摘要记忆，`add_memory` 会将 `role` 同步设置为 `source`；
    *   `ChatAgent._build_messages` 调用 `memory_manager.get_history()`，该方法直接将记忆中的 `role` 原样放入发往 LLM 的 `messages` 中，导致请求中包含 `{"role": "system_summary", ...}`；
    *   SiliconFlow 的 Chat API 严格限制 `role` 只能是 `system/user/assistant/tool`，因此返回 400 错误；
    *   `siliconflow_client.stream_chat` 在收到非 200 响应时仅以 `{"error": ...}` 的 chunk 形式返回错误，不抛出异常；
    *   `ChatAgent.stream_chat` 未识别到这个 `error` 字段，只是把 `content` 视为 `""`，继续流式循环并最终返回空字符串，`api_router.handle_message` 在汇总结果时发现 `response_text` 为空，就回退为“（无回复内容）”。
*   **修复方案**:
    *   在 `WeightedMemoryManager.get_history` 中对 `role` 进行规范化，将不在 `("system", "user", "assistant", "tool")` 集合内的值统一映射为 `"system"`，避免将 `system_summary` 等内部标签直接暴露给云端 LLM (`memory/weighted_memory_manager.py:858-870`)；
    *   在 `ChatAgent.stream_chat` 中增加对 `response_chunk` 的错误识别：如果 chunk 为 `dict` 且包含 `error` 字段，则直接记录日志并向上游 `yield {"error": 错误信息, "done": True}`，中断对话循环；同时过滤掉内容为空的 chunk，只有在收到非空 `content` 时才认为是“首个 token”，记录耗时日志 (`core/agents/chat_agent.py:911-945`)；
    *   由于 `AvelineService.generate_response` 会在聚合流式结果时检查 chunk 中的 `error` 字段，并把错误信息包装成用户可见的文案返回 (`core/services/aveline/service.py:364-377`)，上述修改后前端再遇到云端 400 错误时将收到明确的错误提示，而不会再看到“（无回复内容）”这种伪成功状态。
*   **经验总结**:
    *   向外部 LLM 提供的 `messages` 结构必须严格使用标准的 `role` 枚举，对内部使用的标签（如 `system_summary`）要在适配层进行转换；
    *   流式接口中不能只依赖异常来感知错误，还需要向上传递底层 client 返回的 `{"error": ...}` chunk，并在上层统一处理，否则前端很容易出现“看似成功但没有任何内容”的假成功状态。

### 10.3 消息超时、路由与异常修复 (2025-12-13)

*   **ChatAgent 锁粒度优化**: 将锁的作用域严格限制在 `initialize()` 阶段。消息流式生成阶段不再持有锁，允许高并发处理，解决消息超时问题。
*   **DeepSeek 云端路由修复**: 在 `stream_chat` 中增加显式映射逻辑，将包含 "deepseek" 的 hint 自动映射为 `cloud:siliconflow:` 前缀路径。
*   **HybridLLMModule 非阻塞初始化**: 优先同步初始化云端模块，将本地模块的加载放入 `asyncio.create_task` 后台执行。
*   **异常吞没修复**: 修改 `AvelineService.generate_response`，显式检查流式响应中的 `error` 字段，并在发现错误时立即中断并返回明确的错误信息给前端。
*   **混合模型路由修复**: 引入 `HybridLLMModule`，根据 `model_path` 前缀 (`cloud:`) 智能路由请求到对应的模块。

### 15.93 活动自然切换时角色不告别直接消失，聊天中到了睡觉时间只触发固定晚安消息 (2026-07-14)
*   **问题描述**: 用户跟角色聊天时，到了下一个计划时段（学习/做饭/睡觉），角色不会主动说告别话，直接消失或只触发固定晚安消息。聊得好好的他突然就睡了，很不合理。
*   **复现步骤**:
    1. 用户在休息时间跟角色聊天
    2. 到了下一个计划时段（如学习/做饭/睡觉），角色活动自然切换
    3. 角色不会主动发告别消息，用户下次发消息时发现角色已切换到忙碌/睡觉状态
    4. 睡觉场景只触发固定晚安消息，不考虑当前是否在聊天
*   **预期行为**:
    1. 角色从可聊天切到忙碌时，如果用户最近在聊天，应主动发告别消息（如'我要去学习了，先不聊了'）
    2. 角色从可聊天切到睡觉时，如果用户最近在聊天，应让 LLM 判断是顺延还是告别去睡
    3. 用户没在聊天时活动切换，不发告别消息（不打扰）
*   **实际行为**:
    1. 角色活动自然切换时不发任何告别消息，直接消失
    2. 睡觉场景只触发固定晚安消息（'我要去睡了，晚安'），不考虑当前是否在聊天
    3. build_plan_transition_persona_hint 只在用户发消息时注入提示，且只在 5 分钟窗口内生效
*   **根因**:
    1. build_plan_transition_persona_hint 只在用户发消息时注入提示，且只在 plan_transition_notice_seconds（300秒）窗口内生效
    2. engine._tick 的 sync_current_activities 只更新 plan.current_activity，不触发任何主动消息
    3. schedule_activity_return 只在 /打断 接口调用时才安排告别消息
    4. trigger_character_goodnight 用固定晚安模板，不考虑当前是否在聊天
*   **修复方案**:
    1. 新建 activity_transition.py 模块检测活动切换并发告别消息
    2. 修改 engine.py 的 _tick 检测活动切换
    3. 修改 goodnight_proactive.py 在用户聊天时用不同 instruction
    4. 新增 _ACTIVITY_START_FAREWELL_TEMPLATE 和 _SLEEP_DURING_CHAT_FAREWELL_TEMPLATE 模板
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\scripts\character_daily\verify_activity_transition.py -v`
    2. `venv_core\Scripts\python.exe -m pytest tests\scripts\character_daily\verify_activity_return.py -v`
    3. `venv_core\Scripts\python.exe -m pytest tests\scripts\active_care\verify_character_goodnight.py -v`

### 10.142 空回复兜底重试丢失 model_path 导致模型路由错误（deepseek-v4-flash 误调 SiliconFlow） (2026-08-04)
*   **问题描述**: 用户用 cloud:siliconflow:Pro/moonshotai/Kimi-K2.6 聊天，第一次流式请求失败后触发空回复兜底重试，重试却错误地用 deepseek-v4-flash 调用 SiliconFlow，报 400 错误 code=20012 Model does not exist。
*   **复现步骤**:
    1. 启动后端，配置主对话模型为 cloud:siliconflow:Pro/moonshotai/Kimi-K2.6
    2. 发送消息，触发首次流式请求失败（Stream Request Failed，TTFT≈61s）
    3. ChatAgent 检测到 visible response empty，进入 retry_visible_response
    4. 观察日志：HybridLLM routing to cloud. provider=siliconflow model=deepseek-v4-flash（模型已变）
    5. SiliconFlow 返回 400: Model does not exist
*   **预期行为**:
    1. 重试应继续使用原 model_path（cloud:siliconflow:Pro/moonshotai/Kimi-K2.6）调用 SiliconFlow
*   **实际行为**:
    1. 重试丢失 model_path，HybridLLMModule 用 default_model_name（deepseek-v4-flash）+ default_provider（siliconflow）路由
    2. SiliconFlow 不认识 deepseek-v4-flash（DeepSeek 自家模型名），报 20012
*   **根因**:
    1. empty_retry.py 用 inspect.signature(chat_fn).parameters 检查参数名，但 HybridLLMModule.chat(self, messages, **kwargs) 用 **kwargs 接收所有额外参数，model_path/max_tokens/conversation_id 都不在 parameters 里，全部被跳过
    2. 重试时 model_path 未传递，HybridLLMModule.chat 中 model_path 为空，_resolve_cloud_model_path 不执行，kwargs 回退到 self.default_model_name（=deepseek-v4-flash）
    3. default_provider=siliconflow，路由到 SiliconFlow 客户端，模型名 deepseek-v4-flash 在 SiliconFlow 不存在
*   **修复方案**:
    1. 在 empty_retry.py 中检测 chat_fn 是否含 VAR_KEYWORD（**kwargs）参数，若有则无条件传递 model_path/max_tokens/conversation_id
    2. 保留对旧式显式命名参数签名的兼容分支
*   **验证**:
    1. `重启后端，复现场景：首次流式失败时重试应继续用原 model_path`
    2. `日志应显示 HybridLLM routing to cloud. provider=siliconflow model=Pro/moonshotai/Kimi-K2.6（而非 deepseek-v4-flash）`

### AOS-0805-03 前台服务 / FCM 服务协程 scope 未用 SupervisorJob 且 onDestroy 未释放资源 (2026-08-05)
*   **问题描述**: AvelineForegroundServiceV2、AvelineFirebaseMessagingService 两处服务级 CoroutineScope 直接 Job()，子协程失败会级联取消其他兄弟协程；onDestroy 未 disconnect WebSocket / 未 cancel scope，容易内存泄漏与协程泄漏。
*   **复现步骤**:
    1. 前台服务挂起时触发 WebSocket 重连失败抛异常
    2. FCM onMessageReceived 中 Retrofit 失败
    3. 按 Home 退出或系统回收 onDestroy 被触发
*   **预期行为**:
    1. scope 使用 SupervisorJob()，单个子协程失败不影响其他
    2. onDestroy 先断开 WebSocket 再 cancel scope，不遗留连接/协程
*   **实际行为**:
    1. serviceScope = CoroutineScope(Dispatchers.Default + Job())，Job 级联取消；AvelineFirebaseMessagingService 无 onDestroy cancel scope；AvelineForegroundServiceV2 onDestroy 未先 disconnect WebSocket
*   **根因**:
    1. Service 级协程照搬模板代码，未关注生命周期和异常隔离
*   **修复方案**:
    1. 两处 serviceScope Job()→SupervisorJob()
    2. AvelineForegroundServiceV2.onCreate 显式调 notificationManager.createNotificationChannels(channelList)，避免 Android 12+ 偶现 No channel found 崩溃
    3. AvelineForegroundServiceV2.onDestroy：先 webSocketManager.disconnect() 再 serviceScope?.cancel()
    4. AvelineFirebaseMessagingService.onDestroy：加 serviceScope.cancel()
*   **验证**:
    1. `:app:compileDebugKotlin exit 0`
    2. `leakcanary 重复进入退出前台服务，无 Service/WebSocketManager 泄漏引用`

### AOS-0805-06 Chat 模块 DB 操作 fire-and-forget 无异常保护 & observeWebSocketMessages 冗余 withContext(Main) (2026-08-05)
*   **问题描述**: ChatViewModel 中 handleTextMessage 批量写入、handleImageResult 单条写入、deleteMessage、clearHistory 四个仓库操作均为无异常保护的 fire-and-forget launch{}；ChatFlushManager.onResponseDone 流式批量入库同样未 try/catch；observeWebSocketMessages 中 viewModelScope.launch 内再包一层 withContext(Dispatchers.Main)，viewModelScope 默认已是 Main。
*   **复现步骤**:
    1. 用户存储空间接近满时发送多条聊天消息，Room SQLite INSERT 返回 SQLITE_FULL
    2. 快速删除同一条消息两次或并发 clearHistory
    3. 查看调用栈 observeWebSocketMessages collect 内 when 的 dispatch 切换
*   **预期行为**:
    1. DB 操作失败至少有 Log.e，用户可感知的写入失败还要在 UI 上提示
    2. 调度器切换最小化，无冗余 dispatch
*   **实际行为**:
    1. DB 写入异常会直接被 scope 父级取消静默吞掉或 crash(无 try/catch)，且 deleteMessage/clearHistory 还在 Default 调度器不是 IO
    2. withContext(Dispatchers.Main) 冗余包在 collect 内部多一次 no-op 调度
*   **根因**:
    1. 写 Repository 调用时只看 happy path，未考虑 SQLite 常见异常
    2. 早期对 viewModelScope 默认调度器不了解，用 withContext 加强行切 Main 规避
*   **修复方案**:
    1. ChatViewModel：4 处 launch(Dispatchers.IO) + runCatching { chatRepository.xxx() }.onFailure { Log.e + _uiState.update { it.copy(error="xx失败: ${e.message}") } }
    2. ChatFlushManager.onResponseDone：scope.launch(Dispatchers.IO) 内 runCatching + Log.e 写后台批量入库失败(不打断用户 UI 流程)
    3. observeWebSocketMessages 里去掉冗余 withContext(Dispatchers.Main)，保留注释说明原因
*   **验证**:
    1. `:app:compileDebugKotlin exit 0`
    2. `注入 SQLiteDiskIOException 模拟错误，logcat 能看到 ChatViewModel/ChatFlushManager 错误堆栈且 SnackBar 级 error 字段更新`

### QR-20260813-VOCAB-TAG 词书释义被 [经][机][医][化] 学科标签污染词性 (2026-08-13)
*   **问题描述**: ECDICT 的 translation 行首含 [经][机][医][化][网络] 等学科/语域标签，被当成了词性 type 显示在安卓端。
*   **复现步骤**:
    1. 打开 CET4 词书某词（如 bank/medical）复习
    2. 答案面查看词性列
    3. 看到 [经] [医] 等方括号标签而非 n./v./adj.
*   **预期行为**:
    1. 只显示真正词性 n./v./adj./adv.，学科标签不显示
*   **实际行为**:
    1. type 显示为 [经] [机] [医] 等，UI 绿字标签内容错误
*   **根因**:
    1. build_cet4_wordbook.py 的 parse_translations 只识别英文词性，把方括号标签整块当 head 保留
*   **修复方案**:
    1. 重写 parse_translations：剥离方括号标签、只取 POS_PREFIX_RE 命中的真实词性
    2. 空词性翻译行按纯文本去重，避免冗余同义行
*   **验证**:
    1. `python build_cet4_wordbook.py 后扫描全表残留方括号 type = 0`
    2. `venv_core 运行 verify_vocab_optimization.py 通过`

### QR-20260813-VOCAB-DAILY 复习取词不按 daily 文件给、只给 16 个且词对不上 (2026-08-13)
*   **问题描述**: 昨天 daily/2026/08/12.txt 有 22 个生词，但复习列表只给 16 个且不少词不在该文件里。
*   **复现步骤**:
    1. 某天把 22 个生词写入 daily/2026/MM/DD.txt
    2. 次日进入复习模式
*   **预期行为**:
    1. 复习列表应包含昨天文件里的 22 个词，并补充 FSRS 到期旧词
*   **实际行为**:
    1. 列表主体是被 FSRS 阶段拉入的刚学词，文件词被去重/丢弃，总数偏少
*   **根因**:
    1. get_daily_words 第一阶段查不到词书就 continue 丢弃
    2. 第二阶段把所有 next_review<=now 的词拉入，挤占列表
*   **修复方案**:
    1. 第一阶段查不到词书也按文件原样加入（兜底释义）
    2. 第二阶段排除今天 last_review 过的词
*   **验证**:
    1. `verify_vocab_optimization.py 覆盖取词链路`

### QR-20260813-VOCAB-AGAIN Again 词背完又被安排复习，一直学到会为止 (2026-08-13)
*   **问题描述**: 点 Again（1m）的词本轮重排后，下一轮复习又立刻出现，体感『任何一个单词软件都不会让你一直学到会为止』。
*   **复现步骤**:
    1. 复习中把词点 Again
    2. 本轮结束后再次进入复习
*   **预期行为**:
    1. Again 词按 FSRS 间隔（通常隔更久）再出现，不在下一轮立刻冒出来
*   **实际行为**:
    1. Again 把 next_review 设为极短（~1 分钟），下一轮 get_daily_words 立即拉回
*   **根因**:
    1. FSRS Again 间隔过短 + get_daily_words 第二阶段未排除刚复习的词
*   **修复方案**:
    1. get_daily_words 第二阶段排除今天 last_review 的词
    2. 前端 Again 本轮最多重排 1 次（redoCount<2）
*   **验证**:
    1. `verify_vocab_optimization.py 覆盖取词逻辑`

### QR-20260815-VOCAB-LEVEL 词库未收录用户手动记的跨级别词（inhibit/payroll 等）导致复习无释义 (2026-08-15)
*   **问题描述**: 用户按纸质词书手动记词到 daily 文件后复习，约 39% 的词（58/150）显示"词库未收录，待补充"，无释义可复习。
*   **复现步骤**:
    1. 在 daily/2026/MM/DD.txt 手动加入 inhibit、payroll、overthrow、ozone、penalty 等词
    2. 次日进入复习模式查看这些词
    3. 看到释义为"词库未收录，待补充"
*   **预期行为**:
    1. 手动记的词无论属于哪个考纲级别，复习时都能显示释义
*   **实际行为**:
    1. 58 个词（属 cet6/考研/托福/雅思/GRE 标签或无标签）无释义
*   **根因**:
    1. 词书构建仅纳入 zk∪gk∪cet4 三个标签，ECDICT 中带其他考纲标签或无标签的词被排除
    2. get_word_info 只查当前选中词书，不跨级别兜底
*   **修复方案**:
    1. 词书构建扩到 8 个考纲标签并保留 daily/进度补词，重建全量释义总表
    2. loader.py 增加全量总表兜底：当前词书查不到时回退全量总表
    3. 拆出四级/六级/考研/托福/雅思/GRE 分级词书，词书选择页可按级别切换
*   **验证**:
    1. `venv_core 运行 tests/scripts/study/verify_vocab_optimization.py 通过（跨级别词兜底命中）`
    2. `冒烟：10 个缺失词全部能查到释义`

### QR-20260815-VOCAB-REVIEW-LOOP 复习"不会"词无限循环、复习完仍提示待复习、daily 日志不同步 (2026-08-15)
*   **问题描述**: 复习会话里标"不会"的词被无限重排直到标"会"；复习完重新拉取仍是同一批 34 个词；daily/2026/08/15.txt 为空，复习过的词未按日期记录。
*   **复现步骤**:
    1. 进入复习，对某词选 Again（不会）
    2. 该词不断回到队尾再次出现，直到选 Good 才不再出现，复习数越叠越多
    3. 复习完返回，重新拉取复习列表仍是刚才那一批词
    4. 查看 daily/2026/08/15.txt 为空
*   **预期行为**:
    1. Again 的词每轮最多重排 2 次，之后交给 FSRS 短间隔调度
    2. 复习过（会）的词从待复习列表移除，不再出现
    3. 标"不会"的词写入当天 daily 文件，明天复习时优先出现
*   **实际行为**:
    1. Again 词无限重排（上限失效），复习数从 45 叠到 100+
    2. 复习完仍返回同一批词（昨天 daily 文件的词从未被移除）
    3. daily 文件无任何写入（导入名错误导致同步静默失败）
*   **根因**:
    1. fsrs_scheduler.py 导入不存在的 get_daily_word_log_manager
    2. apply_progress 未在复习后移除 daily 旧记录，也缺少"会"词的 mark_known 流转
    3. 安卓端重排计数基于按词去重的 reviewResults，导致重排上限恒不触发
*   **修复方案**:
    1. 修正导入名并升级错误日志级别
    2. 复习后统一 remove 旧记录，quality<=2 额外写入当天文件
    3. 安卓端用独立 redoCounts 计数重排次数
*   **验证**:
    1. `verify_vocab_optimization.py check_daily_flow 通过（临时目录隔离验证流转）`

### QR-20260820-STREAM-SAVE 流式对话历史落库静默丢失（yield done 后 create_task） (2026-08-20)
*   **问题描述**: 08-18 真流式改造后，正常对话完全不写入短期记忆：保存任务的 create_task 被移到 `yield {"done": True}` 之后，消费者在收到 done 后 break 会关闭 async 生成器链，保存代码永远不执行。
*   **复现步骤**:
    1. 用户通过 WebSocket/Android 正常发一条对话消息
    2. stream_chat_impl 生成回复并在阶段7 yield `{"done": True}`
    3. stream_orchestrator 收到 done chunk 后 break（stream_orchestrator.py:190），WS 适配器收到 response_done 后 break（adapters/streaming.py:133）
    4. break 后 async 生成器引用被丢弃，asyncio asyncgen finalizer 调度 aclose()，GeneratorExit 抛在 yield done 处
    5. yield 之后的 asyncio.create_task(_save_conversation_history) 永不执行
*   **预期行为**:
    1. 回复完成后，用户消息与助手回复写入短期记忆（save_conversation_history）
    2. 无论消费者完整消费还是 break，落库都发生
*   **实际行为**:
    1. 正常对话的短期记忆从不落盘，表现为每条消息像新对话
    2. 主动消息（append_proactive_message 直接写库）不受影响
*   **根因**:
    1. streaming.py 把保存调度放在 yield done 之后：async 生成器在 yield 点暂停时被 aclose，GeneratorExit 直接跳过 yield 之后的代码
    2. 注释声称『必须在 yield done 之前调度』但代码相反，08-18 改造回归了 4/28 已修复的同一问题
*   **修复方案**:
    1. 将保存调度移入 yield done 的 try/finally，正常消费与 break/aclose 路径都会执行 finally，保证保存任务一定被调度
    2. 新增 tests/scripts/streaming_refactor/verify_history_save_not_lost.py 覆盖三种消费路径，防止再次回归
*   **验证**:
    1. `venv_core/Scripts/python.exe tests/scripts/streaming_refactor/verify_history_save_not_lost.py（3/3 通过）`

### QR-20260825-VOCAB-SENSE-LAYER 词书构建脚本缺失且 ECDICT 释义层级丢失 (2026-08-25)
*   **问题描述**: 默认词书可读取但无法按文档重建；vt/vi 被拆坏，领域义与普通义平铺，部分词头还存在缩写义碰撞。
*   **复现步骤**:
    1. 检查文档引用的 build_cet4_wordbook.py，工作区与 Git 全历史均不存在
    2. 查看 CET4-顺序.json 中 a、account、address、conduct、issue、abandon 等词
    3. 观察 t./i. 出现在释义正文，计算机义与普通义同级展示
*   **预期行为**:
    1. 词书可从明确输入稳定重建，例句库不参与释义覆盖
    2. 词性结构正确，专业义默认折叠，只有人工核对义项才突出显示
*   **实际行为**:
    1. 构建脚本缺失，成品 JSON 是不可复现快照
    2. 1958 个 CET4 词头存在 t./i. 正文残片，专业义被当普通义展示
*   **根因**:
    1. 旧构建脚本未被 Git 跟踪
    2. 旧解析逻辑丢失 vt/vi 与领域标签结构
    3. 词频字段只覆盖单词，无法提供义项级考试排序
*   **修复方案**:
    1. 恢复分层构建器与安全写入入口
    2. 普通义、扩展义、人工主释义三层分离
    3. Android 仅依据 primary 显式字段加粗并折叠扩展义
*   **验证**:
    1. `verify_vocab_wordbook_build.py、verify_vocab_optimization.py、verify_vocab_source_linkage.py 全部通过`
    2. `Ruff 与 py_compile 通过；Android Gradle 未在沙箱运行`
