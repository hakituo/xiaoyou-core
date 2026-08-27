# LLM 与模型调用

本分类共 15 条记录。按时间倒序（最新在前）排列。

---

### 11.33 OpenAI 兼容层把裸模型名污染成 `cloud:custom:*`（2026-06-29）

*   **问题描述**: 通过 `/v1/chat/completions` 调用 DeepSeek 时，供应商返回 400：`The supported API model names are deepseek-v4-pro or deepseek-v4-flash, but you passed cloud:custom:deepseek-v4-flash.`
*   **复现步骤**:
    1. 保持 `config/yaml/sections/modeling.yaml` 中 `model.llm.provider: "deepseek"`
    2. 让第三方客户端通过 OpenAI 兼容层请求 `POST /v1/chat/completions`，请求体 `model` 传 `deepseek-v4-flash`
    3. 观察 `openai_client` 日志，出现 `API Error (400)`，下游收到的模型名带上了 `cloud:custom:` 前缀
*   **预期行为**: OpenAI 兼容层应把裸模型名映射到当前真实 provider 的内部 `model_path`，最终发给下游供应商的 `model` 必须仍是裸模型名 `deepseek-v4-flash`
*   **实际行为**:
    1. `routers/openai_compat.py` 把所有请求硬编码成 `model_path=cloud:custom:{model}`
    2. `core/llm/hybrid_module.py` 用字符串包含判断 provider，`cloud:custom:deepseek-v4-flash` 因包含 `deepseek` 被错误覆盖成完整脏模型名
*   **根因**: OpenAI 兼容层内部模型路径映射缺失，加上 Hybrid 路由层的 provider 解析实现过于粗糙，导致 `model_path` 反向污染了真实 `model`
*   **修复**:
    1. `routers/openai_compat.py` 新增 `_resolve_openai_compat_model_path()`，按当前 provider 与已注册模型列表回填真实 `model_path`
    2. `core/llm/hybrid_module.py` 改为按 `cloud:provider[:key_alias]:model` 结构解析，只在 `model` 为空或本身已带 `cloud:` 前缀时才纠正
    3. 新增 `tests/verification/verify_openai_compat_model_path_fix.py`，验证路由层与 Hybrid 路由层修复点

### 10.130 auto-eat LLM 选食模型质量与上下文不足 (2026-06-18)

*   **问题描述**: Qwen2.5-7B-Instruct 在 SiliconFlow 上流式输出不稳定，截断和畸形 JSON 导致 LLM 选食始终 fallback 到随机；prompt 仅含 hunger/thirst，缺乏人格上下文
*   **复现步骤**:
    1. 运行 auto-eat，观察日志中 LLM 原始返回
    2. 发现 raw_out 为畸形 JSON（缺冒号、food_id 截断、缺引号等）
    3. 即使 max_tokens=512 也无法稳定输出
*   **预期行为**: LLM 应返回完整 JSON 并根据角色上下文做有意义的饮食决策
*   **实际行为**: 所有选食都 fallback 到随机，理由固定为“随机选的”
*   **根因**: (1) Qwen2.5-7B-Instruct 在 SiliconFlow 上流式输出质量差；(2) prompt 缺少心情、活动、同伴状态等上下文，LLM 无法做有“人格”的决策
*   **修复方案**:
    1. 模型升级为 DeepSeek-V3.2（与 decision/priority_analysis 统一）
    2. 增强 prompt 注入：心情、活动、消化队列、上一餐、同伴状态
    3. 新增 LLM 决策字段：share_with_ling、chat_while_eating
    4. 边吃边聊时异步触发 PeerChatScheduler
*   **状态**: ✅ 已修复并验证（诊断脚本两场景均通过）

### 10.121 /模型 只显示图像模型不显示LLM模型 (2026-06-02)

*   **问题描述**: QQ adapter的 `/模型` 命令只能看到图像模型，看不到LLM模型
*   **复现步骤**:
    1. 发送 `/模型` 命令
    2. 只看到图像模型列表，没有LLM模型
*   **预期行为**: 应该同时显示LLM模型和图像模型
*   **实际行为**: 只显示图像模型
*   **根本原因**: API 响应返回的是 `data` 字段，但代码期望的是 `available` 字段。
*   **修复**: 修改 `show_models` 方法，支持两种字段名：`available`（旧格式）和 `data`（新格式）
*   **状态**: ✅ 已修复

### 10.63 MiniMax-M2.5 content字段仍含推理语言导致泄露 (2026-04-30)

*   **问题描述**: 启用 `reasoning_split=True` 后，MiniMax-M2.5 的 `content` 字段仍包含推理语言（如`但规则说"优先顺着你上一`），而非自然对话内容。LeakDetector 因阈值和关键词不足未能拦截
*   **复现步骤**:
    1. Active Care 触发主动消息生成
    2. MiniMax-M2.5 返回 `content="但规则说\"优先顺着你上一"` + `reasoning_details=[...]`
    3. `reasoning_split=True` 确实分离了推理到 `reasoning_details`，但 `content` 本身也是推理语言
    4. 代码因 `content` 不为空直接返回，LeakDetector 因文本仅12字符且无匹配关键词而跳过
*   **预期行为**: 推理语言应被检测，触发 fallback 模型重试
*   **实际行为**: 推理语言直接发送到 QQ
*   **根因**:
    1. **MiniMax-M2.5 作为推理模型，倾向于把推理过程当作回复输出**：即使 `reasoning_split=True` 分离了主要推理，`content` 字段仍可能包含推理语言
    2. **LeakDetector 阈值过高**：40字符阈值导致12字符的短文本泄露被跳过
    3. **LeakDetector 缺少推理语言模式**：没有"规则说"、"优先顺着"等推理语言关键词
    4. **OpenAI 客户端缺少 content 推理检测**：当 `content` 不为空但有 `reasoning_details` 时，没有检查 content 是否也是推理语言
*   **修复**:
    1. `client.py`：添加 `_looks_like_reasoning_leak()` 函数，当 `content` 不为空但有 `reasoning_details` 且 content 含推理语言标记时，标记为 `reasoning_only`
    2. `postprocessor.py`：LeakDetector 添加 `reasoning_language_markers` 列表（规则说/指令说/按照规则/优先顺着等），命中即判定泄露（无长度限制）；阈值从 40 降到 20

### 10.36 MiniMax 模型 (MiniMax-M2.5) 在主程序中无回复 (2026-04-15)

*   **问题描述**: 用户在主程序中配置使用 MiniMax 官方模型（如 `MiniMax-M2.5` 和 `M2-her`）时，系统一直无法收到回复，但在官方文档的示例调用中却可以正常使用。
*   **问题描述**: 用户更正睡觉时间为 21:30 后，Active Care 仍说"睡了将近12小时"（实际应为8小时28分）。
    *   在配置文件或 `.env` 中设置 `MINIMAX_API_KEY`，并在使用模型时选择 `cloud:minimax:MiniMax-M2.5`。
    *   在主程序中发送对话请求，系统日志无明显异常但前端未收到任何文本回复。
*   **预期行为**: MiniMax 模型能够像其他 OpenAI 兼容模型一样正常流式/非流式回复用户。
*   **实际行为**: `MiniMax-M2.5` 模型使用主程序的 `chatcompletion_v2` 接口且按 OpenAI 格式发送请求时，API 返回了 HTTP 200，但响应体中的 `choices` 字段为 `null`，导致内部解析报错“Error: No response content”或流式卡死。
*   **原因分析**: 
    *   `core/llm/openai_compat/minimax_client.py` 中默认的 `MINIMAX_BASE_URL` 配置为了 MiniMax 自定义的 V2 接口 (`https://api.minimax.chat/v1/text/chatcompletion_v2`)。
    *   该 V2 接口对 OpenAI 的请求格式兼容性不佳（特别是对于 `MiniMax-M2.5`，会在 `stream=False` 时直接返回 `choices: null`）。
    *   而 MiniMax 官方推荐的 OpenAI 兼容接口端点应该是 `https://api.minimax.chat/v1/chat/completions`。
*   **解决方案**:
    *   将 `minimax_client.py` 中的 `MINIMAX_BASE_URL` 修改为标准的 OpenAI 兼容端点：`https://api.minimax.chat/v1/chat/completions`。
    *   修改后，`MiniMax-M2.5` 和 `M2-her` 均能完美适配 `OpenAIClient` 的流式和非流式解析逻辑。

### 10.38.1 启动阶段本地 LLM 预加载阻塞导致卡顿（2026-01-14）

*   **问题描述**: `provider=local` 且开启 `llm_preload_on_startup` 时，启动阶段会同步等待本地模型加载，表现为日志长时间停在“初始化/加载”附近（常见 1-3 分钟）。
*   **预期行为**: 后端应快速完成启动；本地模型预加载不应阻塞启动主流程。
*   **解决方案**:
    *   将本地 LLM 预加载改为后台任务调度，启动流程仅触发 preload，不再等待加载完成（`core/llm/__init__.py`）。
    *   在 `ChatAgent.initialize()` 增加 LLM 初始化阶段耗时日志，便于快速定位卡点（`core/agents/chat_agent.py`）。
    *   本地预加载超时从配置 `model_load_timeout` 读取，并输出实际耗时，避免“无日志卡死”的错觉（`core/llm/__init__.py`）。

### 10.26 本地推理上下文预算在中文场景下的校准 (2026-01-03)


*   **问题描述**: 在本地 GGUF 推理中，即使已对 prompt 做了字符级截断，仍会间歇触发 `exceed context window`，并出现“内容有点长了”的友好提示；该问题在中文长对话/大量状态注入（system prompt 很长）场景更容易复现。
*   **复现步骤**:
    *   使用本地 GGUF 模型进行多轮聊天，持续输入较长中文内容；
    *   或让 system prompt 注入较多状态（记忆、体感、元认知线索等）后，再追加一段较长用户输入；
    *   观察 `CPPSchedulerEngine.submit_llm_task` 的 Python 推理路径或 C++ 调度器路径出现 `exceed context window`。
*   **预期行为**:
    *   在接近 `n_ctx` 上限时应自动裁剪对话历史/过长消息，确保推理请求不超出上下文窗口；
    *   当可用预算很小（例如不足 16 token）时，应按实际预算收缩生成长度，而不是强行请求 16 token。
*   **实际行为**:
    *   之前采用 `max_chars = n_ctx * 3` 这类规则对字符串 prompt 截断：在中文占比高（字符/Token 比更低）时，字符级截断仍可能对应远超 `n_ctx` 的 token 数；
    *   推理前对剩余预算 `available` 采用 `max(16, available)` 的写法会在 `available` 小于 16 时仍请求 16 个新 token，反而把请求推到上下文窗口外。
*   **解决方案**:
    *   Python llama-cpp 路径：增加基于 `llm.tokenize` 的消息裁剪，必要时对 system prompt 和最后一条超长消息按 token 预算截断；当 tokenize 不可用时回退到粗略估算；
    *   C++ 调度器路径：在将消息列表扁平化为字符串前，先按上下文 token 预算做字符级截断（保留 system 头与最近对话），并在 prompt 仍过长时逐步收紧预算；
    *   统一修正 `available < 16` 时的 `max_tokens` 收缩策略，按实际剩余预算取值，避免请求再次超窗。
*   **相关文件**:
    *   `core/services/scheduler/cpp_scheduler_engine.py`

### 10.26.1 本地 GGUF 首 token 偏慢：仿生延迟开关 + flash_attn/offload_kqv 透传 (2026-01-01)


*   **问题描述**:
    *   用户反馈在 GPU 环境下，本地 GGUF 推理首 token 仍可能达到 ~7 秒；
    *   单独运行 `llama_cpp` 探针/测试时 TTFT 明显更低，说明“模型本身能快”，但“服务链路”存在额外开销或误配置。
*   **原因分析**:
    *   `CPPSchedulerEngine.submit_llm_task` 在进入推理前会调用 BioSystem 的认知延迟逻辑，虽然最大值只有 1.8s，但在 TTFT 敏感场景下属于不必要的额外等待；
    *   `LLMModule` 的 GGUF 加载逻辑默认只从 `config` 读取 `flash_attn/offload_kqv`，导致全局配置中即使开启也不会生效；
    *   `GlobalTaskScheduler.start` 构造 `gpu_config` 时，Python 后端会把 `max_batch_size` 强制压到 256，GPU 模式下会放大 prompt eval 的耗时。
*   **修复方案**:
    *   增加 `scheduler.bio_enable_cognitive_delay`（默认关闭），仅在明确需要时才施加认知延迟；
    *   `LLMModule` 优先读 `config`，否则回退读取全局 `settings.model.flash_attn/offload_kqv`；
    *   `TaskScheduler` 构造 `gpu_config` 时透传 `flash_attn/offload_kqv`，并仅在 CPU 模式才把 `max_batch_size` 限制到 256。
    *   **新增指令支持**: 为方便用户根据场景（如演示 vs 实用）动态调整，增加了多端切换指令：
        *   **Web/WebSocket**: `/latency on/off` (由 `AvelineService` 处理)；
        *   **QQ/NapCat**: `/仿生延迟 on/off` 或 `/latency on/off` (由 `QQAdapter` 处理)；
*   **验证结果**:
    *   `pytest -m gpu tests/test_llm_gpu.py` 可确认 llama-cpp-python 的 CUDA 后端正常工作；
    *   `pytest -m gpu tests/test_llm_long_context.py` 可用于测量长提示词场景下的 TTFT。
*   **涉及文件**:
    *   `config/integrated_config.py`
    *   `core/services/scheduler/cpp_scheduler_engine.py`
    *   `core/modules/llm/module.py`
    *   `core/services/scheduler/task_scheduler.py`

### 10.25 本地 GGUF 上下文超限时流式错误误判为成功 (2025-12-26)


*   **问题描述**: 在本地 GGUF 模型触发 `Requested tokens (...) exceed context window of ...` 时，后端会对用户输出“这次对话的内容有点长了...”的友好提示，但上层仍记录了 `First token received` / `Stream generation completed`，看起来像“正常生成过回复”，并且 WebSocket 链路只发了 `response_chunk/response_done` 而没有 `error` 帧。
*   **复现步骤**:
    *   使用本地 GGUF 模型多轮聊天，持续输入较长内容，直到日志出现 `Requested tokens (...) exceed context window of ...`；
    *   观察同一轮对话日志：仍会出现 `Turn N: First token received ...`、`LocalLLMAdapter.stream_chat finished`；
    *   前端收到一段友好提示文本，表面像是模型“回复了”，但实际上本轮推理失败。
*   **预期行为**:
    *   上下文超限应被视为失败：向前端推送 `type=error` 帧，随后结束本轮流式；
    *   `First token received` 不应在错误场景被触发，避免误导排障。
*   **实际行为**:
    *   `CPPSchedulerEngine` 将友好提示作为普通字符串 token 返回，导致 `ChatAgent` 把它当成“首 token”，并按成功路径走完整个流式流程；
    *   `AvelineService.stream_conversation` 先看到 `done=True` 就发送了 `response_done`，错误信息没有按 `error` 事件透传。
*   **原因分析**:
    *   流式协议层缺少“错误 chunk”的统一语义：底层把错误包装成字符串，导致上层无法区分“生成内容”与“错误文案”；
    *   C++ 调度器任务失败（`TaskStatus.FAILED`）也仅返回 `errorMessage` 字符串，没有统一转成 error chunk。
*   **解决方案**:
    *   统一错误语义：在 `CPPSchedulerEngine.submit_llm_task` 遇到上下文超限/显存/未知异常时，将队列元素改为 `{"error": 友好文案, "done": True}`，并让 C++ 调度器 `FAILED` 分支也走同样的 error chunk；
    *   透传 error chunk：在 `LLMModule.stream_chat` 的 C++ 调度器分支中，如果拿到的是 `dict` chunk，则原样向上 `yield`，确保 `ChatAgent` 能在 `"error" in chunk` 时立即中断；
    *   WebSocket 收尾一致性：在 `AvelineService.stream_conversation` 收到 error chunk 后先推送 `type=error`，再补一条 `response_done`，避免前端一直处于“正在输入”；
    *   自适应截断：
        *   Python 侧（llama_cpp）推理前使用 `llm.tokenize` 估算 prompt token，并在 `n_ctx` 内裁剪 `messages`，同时把 `max_tokens` 动态压到可用上限；
        *   C++ 调度器推理前对 `prompt` 做字符级裁剪，并基于中英文混合的粗略 token 估算动态压 `maxTokens`，降低再次触发 context window 的概率。
*   **相关文件**:
    *   `core/services/scheduler/cpp_scheduler_engine.py`
    *   `core/modules/llm/module.py`
    *   `core/services/aveline/service.py`

### 10.68 本地 GGUF 流式偶发 `UnboundLocalError: prompt`（2025-12-21）

*   **问题描述**:
    *   后端在本地 GGUF 推理的流式路径中，偶发出现报错：`UnboundLocalError: cannot access local variable 'prompt' where it is not associated with a value`，随后 producer 线程结束并向上游透出 stream error，前端表现为“有时不回，但继续发消息又能回”。
*   **复现步骤**:
    *   使用本地 GGUF 模型（如 `Qwen2___5-7B-Instruct-Q4_K_M.gguf`）走 `core/modules/llm/module.py` 的 Python 侧 GGUF 流式路径（非 C++ 调度器路径）；
    *   调用 `LLMModule.stream_chat(prompt=[{"role": "user", "content": "hi"}])`；
    *   观察日志出现 `UnboundLocalError`，并在队列消费侧打印 `Stream error in queue: ...`。
*   **预期行为**: 无论是否启用 C++ 调度器，本地 GGUF 流式推理都应稳定输出 token；异常应为明确的模型/输入错误，而不是 Python 作用域错误。
*   **实际行为**: 在 Python 侧 GGUF 流式实现中，producer 线程会在第一次访问 `prompt` 时直接抛 `UnboundLocalError`，导致本次流式会话提前结束。
*   **原因分析**:
    *   `LLMModule.stream_chat` 内部定义的 `_producer()` 使用了 `prompt = ...` 的赋值语句（用于 clamp 文本/消息），这会让 Python 在编译期将 `prompt` 判定为 `_producer` 的局部变量；
    *   由于 `_producer` 内又在赋值之前调用了 `isinstance(prompt, ...)` 等读取逻辑，最终触发 `UnboundLocalError`；
    *   该问题之所以“看起来偶发”，通常是因为有时请求被 `use_cpp_scheduler` 分支短路（走 C++ 调度器，不触发 Python GGUF fallback），而当回落到 Python GGUF 路径时必现。
*   **解决方案**:
    *   在 `_producer` 内引入独立变量 `prompt_value`，仅对 `prompt_value` 做 clamp/转换，避免对外层 `prompt` 赋值触发作用域错误（`core/modules/llm/module.py:389-494`）。
    *   增加轻量回归测试，使用 Fake llama 模型验证 `prompt` 为 list 的场景能够正常产出 token（`tests/test_llm_module_prompt_scope.py:1-39`）。
*   **验证结果**:
    *   `python -m pytest -q tests/test_llm_module_prompt_scope.py` 通过；
    *   `python -m ruff check core/modules/llm/module.py tests/test_llm_module_prompt_scope.py` 通过；
    *   `python -m mypy core/modules/llm/module.py` 通过。

### 10.66 主动推送改为本地 LLM 决策驱动 + 日程文件体系（2025-12-21）

*   **问题描述**: 现有主动推送逻辑更偏固定策略（沉默时长阈值/简单阶段），缺少可长期维护的“时间表/免打扰/日记与计划”文件空间，导致体验偏“定时器”而不够拟人。
*   **改动要点**:
    *   引入 `Aveline_daily_data` 作为 Aveline 的个人数据根目录，承载时间表、免打扰规则与按日期归档的内容。
    *   主动推送决策改为“本地 LLM 先决定是否打扰 + 下次检查间隔 + 意图”，再进入原有的文本生成阶段。
    *   主动推送增加“免打扰时段/时间窗口”门控：不在窗口内则不打扰，并把下次检查时间推迟到下一窗口开始。
    *   主动推送增加状态落盘：记录最近一次主动推送时间、意图与内容摘要，用于最小打扰间隔与调度稳定性。
*   **涉及文件**:
    *   目标评估文档：`AVELINE_ACTIVE_FILE_SYSTEM_TARGET.md`
    *   数据目录与默认配置：`Aveline_daily_data/index.json`、`Aveline_daily_data/schedule/push_schedule.json`、`Aveline_daily_data/schedule/quiet_hours.json`
    *   受限文件工具：`core/tools/aveline_daily_data_tool.py`（仅允许在 `Aveline_daily_data` 内部读写/列出/建目录）
    *   工具注册：`core/agents/chat_agent.py`
    *   主动推送改造：`core/services/active_care/service.py`
*   **预期行为**:
    *   主动推送不再只依赖固定阈值，而是结合时间窗口/免打扰/最近互动/今日频控等综合决策，更像真人“挑合适的时机找你说话”。

### 10.63 本地 LLM `chat()` 不支持 `model_path` 导致生成脚本失败（2025-12-20）


*   **问题描述**: 使用 `scripts/generate_dialogue_examples.py` 跑 NSFW 且指定本地 GGUF（如 L3 Stheno）时，报错 `LLMModule.chat() got an unexpected keyword argument 'model_path'`，导致生成中断。
*   **复现步骤**:
    *   配置 `app.yaml` 的 LLM provider 为 `local`；
    *   执行 `python .\\scripts\\generate_dialogue_examples.py --mode nsfw --count 1 --turns 2 --model "<gguf 路径>"`；
    *   观察报错与生成中断。
*   **预期行为**: 生成脚本能通过 `model_path` 驱动本地模块切换到指定 GGUF 并正常推理。
*   **实际行为**: 本地 `core.modules.llm.module.LLMModule.chat()` 的签名不包含 `model_path`，而上层 `HybridLLMModule/LocalLLMAdapter` 会透传 `model_path`，最终触发 `TypeError`。
*   **解决方案**:
    *   为 `core/modules/llm/module.py` 的 `LLMModule.chat()` 补齐 `model_path` 参数，并与 `stream_chat()` 对齐：当 `model_path` 与当前模型不一致时执行安全卸载与切换；禁止在本地模块中接收 `cloud:` 路径。
    *   在 `core/llm/__init__.py` 的 `LocalLLMAdapter.chat()/stream_chat()` 中仅透传本地实现支持的参数（`max_tokens`/`temperature`/`model_path`/`first_token_timeout`），避免无效 kwargs 破坏接口兼容性。
    *   生成脚本压测/批量场景可用 `--no-vector-db` 跳过向量库写入（避免 ChromaDB/Embedding/TTS 初始化开销），只落盘 JSONL。
*   **验证结果**:
    *   `python -m ruff check .` 通过；
    *   `python -m mypy .` 通过；
    *   NSFW 生成可正常运行，并持续写入 `generated_data/*.jsonl`。

### 10.30 Cloud API 迁移与本地模型停用 (2025-12-16)


*   **变更背景**:
    *   本地 GGUF 模型 (Qwen2.5-7B) 在开发环境中出现首个 Token 生成超时 (First Token Timeout) 且占用大量内存 (90%+)，导致其他服务 (TTS/WebUI) 运行不稳定。
*   **变更内容**:
    *   **停用本地模型**: 在 `app.yaml` 中将 `model.path` 设置为 `null`，禁用本地 LLM 加载。
    *   **启用云端 API**:
        *   将 `model.llm.provider` 设置为 `"dashscope"`。
        *   **模型指定**:
            *   DashScope (Primary): 强制使用 `"qwen3-max-2025-09-23"`。
            *   SiliconFlow (Backup): 强制使用 `"deepseek-ai/DeepSeek-V3.2"`。
        *   配置 `model.llm.api_key` 设置为 `null`，强制从环境变量读取（避免 `${}` 字符串替换问题）。
    *   **文档更新**: 更新 `README.md` 声明维护模式及云端 API 依赖。
*   **后续计划**:
    *   待 `cpp_scheduler` 优化完成后，再重新评估本地模型的启用条件。
    *   验证 `qwen3-max` 在当前业务场景下的表现（记忆检索、情感响应等）。
    *   注:此问题已解决，详见下一条日志即10.31，在此仅做记录。

### 10.27 本地 L3-8B-Stheno GGUF 模型 invalid vector subscript 与首 token 早返回行为 (2025-12-16)


*   **问题描述**:
    *   在将本地默认 LLM 从 `Qwen2___5-7B-Instruct-Q4_K_M.gguf` 切换为 `L3-8B-Stheno-v3.2-Q5_K_M.gguf` 时，用户端日志多次出现 `llama_model_load: error loading model: invalid vector subscript`，模型加载失败但 HTTP 层仍然只在全局 `limits.message_timeout`（如 60/300 秒）到达后才给出“超时”提示；
    *   由于 `invalid vector subscript` 属于 llama.cpp 内部对 GGUF 权重结构的断言错误，通常意味着模型文件损坏或与当前 `llama-cpp-python` 版本不兼容，无法通过简单配置修复；
    *   旧逻辑在本地 LLM 加载失败时往往只在后台日志中记录异常，而对前端表现为长时间无响应、最终触发 HTTP 超时，用户直观感受是“设多少秒就会硬跑满多少秒，然后才告诉你超时”，难以分辨“模型本身坏了”与“单次请求真的很慢”。
*   **原因分析**:
    *   `LLMModule._load_model_sync` 对 GGUF 路径始终直接调用 `Llama(model_path=..., n_ctx=..., n_gpu_layers=..., n_batch=...)`，外围只做了一个泛化的 `except Exception as e`，将所有错误统一记录为“加载文本模型失败”，没有识别特定错误类型；
    *   `CPPSchedulerEngine._setup_python_llm` 作为 C++ 调度器的 Python 侧回退同样简单地包裹了 `Llama(...)` 调用，一旦抛出 `invalid vector subscript`，只是在日志中写入一行 `Failed to load Python Llama model`，不会对上层作进一步区分；
    *   `/api/v1/message` 的外层仅基于 `limits.message_timeout` 做超时控制，缺乏“首 token 层级”的早期反馈机制：当模型在加载阶段或首 token 前就已经失败时，调用链依然要等到 HTTP 超时点才结束。
*   **改动方案**:
    *   在本地 LLM 模块中对 `invalid vector subscript` 做专门识别与日志标注：
        *   `LLMModule._load_model_sync` 内对 GGUF 加载增加细粒度异常捕获，当 `str(e).lower()` 中包含 `"invalid vector subscript"` 时，输出明确日志：提示 GGUF 文件可能损坏或与当前 `llama-cpp-python` 不兼容，并返回 `False`，避免继续使用一个半初始化模型 (`core/modules/llm/module.py:116-128, 154-156`)；
        *   通用异常分支中同样增加对 `"invalid vector subscript"` 的匹配，将其作为单独类别记录，便于后续排查 (`core/modules/llm/module.py:154-156`)；
        *   `CPPSchedulerEngine._setup_python_llm` 中对 `Llama(...)` 调用加入特判逻辑，遇到该错误时写入更详细的中文说明，并将 `self.llm` 置为 `None`，阻止后续提交任务到一个无效实例 (`core/services/scheduler/cpp_scheduler_engine.py:135-149`)。
    *   保持 `/api/v1/message` 侧的“首 token 早返回”行为，用于区分“模型完全不产出”与“仍在正常推理中”:
        *   在 `CPPSchedulerEngine.submit_llm_task` 与 `LLMModule.stream_chat` 中，通过 `asyncio.wait_for(queue.get(), timeout=first_token_timeout)` 实现首 token 超时，默认 10 秒，在超时时立即返回友好中文文案“本地模型在较长时间内没有产生任何输出，请尝试重启模型或缩短输入。”，而不是继续等到 `message_timeout`；
        *   配套的 `tests/test_empty_responses.py` 确保该类文案不会被误归类为“空回复”或“技术细节泄露”，同时通过 `simple_message_client.py` 进行端到端验证，确认在模型长时间无输出时 HTTP 层能在十几秒内返回而非跑满 60/300 秒 (`simple_message_client.py:8-34`)。
*   **验证与现状**:
    *   在当前环境中，通过 `tests/test_llm_gpu.py` 验证 `Qwen2___5-7B-Instruct-Q4_K_M.gguf` 能在 ~1 秒内加载并正常推理，说明 llama.cpp 与 GPU 环境工作正常 (`tests/test_llm_gpu.py:14-47`)；
    *   对于用户提供的 `L3-8B-Stheno-v3.2-Q5_K_M.gguf`，一旦底层 llama.cpp 抛出 `invalid vector subscript`，系统现在会：
        *   在日志中给出明确错误类别（模型文件/版本兼容问题）；
        *   在本地模块加载失败时直接返回“模型加载失败”错误，而不是继续走推理链路；
        *   在已加载模型但长时间无首 token 输出时，通过首 token 超时逻辑给出早期反馈，避免用户等待完整 HTTP 超时时间。
*   **经验总结**:
    *   对于本地 GGUF 模型，`invalid vector subscript` 这类错误基本不可能通过调整 `n_ctx`/`n_gpu_layers` 等参数解决，应直接视为“模型文件或版本问题”，通过日志清晰提示用户重新下载或更换模型，而不是尝试自动修复；
*   在用户感知上，区分“模型不可用”（加载阶段失败）与“模型很慢”（推理阶段首 token 超时）非常重要：前者应尽量在初始化阶段就被暴露出来，后者则通过首 token 超时机制在 10 秒量级内给出说明，而不依赖长达数分钟的 HTTP 超时。

### 10.5 LLM模块死锁与超时修复 (2025-12-13)

*   **问题描述**: 用户反馈切换模型（尤其是使用 cloud 参数）时，请求会卡住直到 10 秒超时。
*   **原因分析**: `LLMModule` 中的 `stream_chat` 方法在持有异步锁 `async with self._lock` 的情况下调用了 `unload_model` 方法。而 `unload_model` 方法内部又尝试获取同一个异步锁。由于 `asyncio.Lock` 不支持重入（non-reentrant），导致死锁。
*   **解决方案**:
    *   将 `unload_model` 重构为 `_unload_model_unsafe`（无锁版本）和 `unload_model`（加锁版本）。
    *   在 `stream_chat` 中（已持有锁的上下文中）调用 `_unload_model_unsafe`。

### QR-2026-07-30-01 DeepSeek API 402 余额不足时上层无脑重试刷屏日志 (2026-07-30)
*   **问题描述**: DeepSeek 账户余额耗尽后，服务端返回 HTTP 402 Insufficient Balance，但项目代码缺少不可重试错误识别，导致 PeopleProfileExtractor 等上层调用方对 402 错误也执行 2 次重试，2 分钟内累计 70+ 条 ERROR 日志。
*   **复现步骤**:
    1. DeepSeek 账户余额耗尽
    2. PeopleProfileExtractor 触发批量人物画像提取，并发提交多个 LLM 任务
    3. 每个 LLM 任务收到 402 错误，client.py 记录 ERROR 并返回 error chunk
    4. task_scheduler 透传时只取 content，吞掉 error 字段
    5. extractor.py 看到 full_response 为空，无脑重试 2 次
    6. 单个任务实际触发 3 次 402 调用，日志放大 3 倍
*   **预期行为**:
    1. 401/402/403 这类认证计费类错误应快速失败，不重试
    2. 上层调用方应能识别 non_retryable 标识并立即返回
    3. 日志只记录 1 条 ERROR，不刷屏
*   **实际行为**:
    1. client.py 对所有非 200 错误统一记 ERROR 后返回，无 non_retryable 标识
    2. task_scheduler 吞掉 error 字段，上层收不到错误信号
    3. extractor.py 无脑重试 2 次，2 分钟内 70+ 条 ERROR 日志
*   **根因**:
    1. client.py 未区分可重试与不可重试错误
    2. task_scheduler 透传逻辑只取 content/text，丢弃 error 字段
    3. extractor.py 重试逻辑只看 full_response 是否为空，不识别错误类型
*   **修复方案**:
    1. client.py: 识别 401/402/403，返回带 non_retryable 标识的 error chunk，日志截断 200 字符
    2. task_scheduler.py: 透传带 error 字段的 dict chunk
    3. extractor.py: 检测 non_retryable 标识立即返回空串，跳过重试
*   **验证**:
    1. `venv_core\Scripts\ruff.exe check core\llm\openai_compat\client.py core\services\scheduler\task\task_scheduler.py core\character\people\extractor.py`

### QR-LLM-030 云端 LLM 启动时白白加载 LocalLLMAdapter 浪费 30 秒 (2026-07-30)
*   **问题描述**: provider=deepseek（云端 LLM）+ CPU venv 启动时，ChatAgent 初始化耗时 32.340s，AvelineService 后台初始化耗时 42.681s
*   **复现步骤**:
    1. 使用 CPU venv 启动服务（provider=deepseek，C++ 调度器接管 LLM）
    2. 观察启动日志，发现 LLM 模块初始化耗时 30.471s
    3. 日志显示 LocalLLMAdapter created (lazy) 后紧接着 Skipping local preload (C++ scheduler LLM enabled)
*   **预期行为**:
    1. provider 为云端时不应加载本地 LLM 相关模块，LLM 模块初始化应在 1s 内完成
*   **实际行为**:
    1. provider=deepseek 时仍同步创建 LocalLLMAdapter，触发 torch/llama_cpp 冷导入 ~30s
    2. 创建后 initialize() 检测到 C++ 调度器接管 LLM 直接 return，adapter 未被使用
*   **根因**:
    1. factory.py 构造 HybridLLMModule 时无条件传入 lazy_local_factory
    2. HybridLLMModule.initialize() 在 preload_local=False 时走 else 分支同步创建 LocalLLMAdapter
    3. LocalLLMAdapter() 构造触发 import torch + llama_cpp 等重模块冷导入
*   **修复方案**:
    1. factory.py 新增 needs_local_adapter = (provider == 'local')，provider 为云端时不传 lazy_local_factory
    2. provider=local 时保持原有行为，不影响本地 LLM 模式
*   **验证**:
    1. `venv_cpu\Scripts\python.exe tests\scripts\verify_cloud_provider_skip_local_llm.py`
    2. `4 项验证全部通过`

### QR-20260816-02 人物档案提取 LLM 调用失败但日志无异常细节 (2026-08-16)
*   **问题描述**: errors_20260816.json 两条 "LLM 调用失败，已重试 2 次"，traceback 为空，无法定位真实失败原因（回查日志实为 DeepSeek deepseek-v4-pro 流式返回空）。
*   **复现步骤**:
    1. 夜间任务触发 PeopleProfileExtractor._call_llm_with_prompt
    2. LLM 多次返回空内容或上游 error chunk
    3. 重试耗尽后记录汇总错误
*   **预期行为**:
    1. 错
    2. 误
    3. 日
    4. 志
    5. 携
    6. 带
    7. 真
    8. 实
    9. 异
    10. 常
    11. 栈
    12. 与
    13. 上
    14. 游
    15. 错
    16. 误
    17. 信
    18. 息
    19. ，
    20. 便
    21. 于
    22. 定
    23. 位
    24. 是
    25. A
    26. P
    27. I
    28. 空
    29. 响
    30. 应
    31. /
    32. 断
    33. 路
    34. 器
    35. /
    36. 配
    37. 置
    38. 问
    39. 题
*   **实际行为**:
    1. e
    2. x
    3. c
    4. e
    5. p
    6. t
    7. 分
    8. 支
    9. l
    10. o
    11. g
    12. g
    13. e
    14. r
    15. .
    16. e
    17. r
    18. r
    19. o
    20. r
    21. 未
    22. 带
    23. e
    24. x
    25. c
    26. _
    27. i
    28. n
    29. f
    30. o
    31. =
    32. T
    33. r
    34. u
    35. e
    36. ，
    37. e
    38. r
    39. r
    40. o
    41. r
    42. _
    43. c
    44. o
    45. l
    46. l
    47. e
    48. c
    49. t
    50. o
    51. r
    52. 只
    53. 能
    54. 合
    55. 成
    56. R
    57. u
    58. n
    59. t
    60. i
    61. m
    62. e
    63. E
    64. r
    65. r
    66. o
    67. r
    68. (
    69. r
    70. e
    71. c
    72. o
    73. r
    74. d
    75. .
    76. g
    77. e
    78. t
    79. M
    80. e
    81. s
    82. s
    83. a
    84. g
    85. e
    86. (
    87. )
    88. )
    89. ，
    90. t
    91. r
    92. a
    93. c
    94. e
    95. b
    96. a
    97. c
    98. k
    99. 为
    100. 空
*   **根因**:
    1. except 分支未传 exc_info=True
    2. 上游 error chunk（error 字段）未被记录，返回空原因不可见
*   **修复方案**:
    1. extractor.py 的 except 分支 logger.error 带 exc_info=True
    2. 新增 last_upstream_error 记录上游 error chunk，"返回空"警告与最终失败日志携带上游错误与最后一次异常
*   **验证**:
    1. `venv_core tests/scripts/websocket_errors/verify_debug_20260815_20260816.py 断言 exc_info=True 与上游错误字段存在`

### QR-20260817-01 LLM流式请求统计漏记：DeepSeek v4 流式默认不返回 usage (2026-08-17)
*   **问题描述**: Prompt 缓存命中率统计（log_prompt_cache_usage 埋点于 OpenAIClient.stream_chat）上线后，本地统计与 DeepSeek 开放平台数据严重不符：官网 159 次请求 30多万 tokens，本地日志仅 21 条且全为 sync 模式，流式请求零记录。
*   **复现步骤**:
    1. 在 logs/prompt_cache_stats.log 观察记录数与 mode 字段
    2. 对照 DeepSeek 开放平台控制台当日请求量与 token 用量
    3. 排查 task_scheduler.submit_llm_task 的 cloud 分支与 C++ 分支（provider=local 才走 C++）
    4. 检查 DeepSeekClient → OpenAIClient._build_payload → build_payload 的请求体字段
*   **预期行为**:
    1. 流式请求结束后统计日志记录一条 mode=stream 的 usage（含 prompt_cache_hit_tokens/miss_tokens）
    2. 本地统计请求数与开放平台控制台一致
*   **实际行为**:
    1. 流式请求全部无记录，仅非流式 chat() 路径有 sync 记录
    2. build_payload 生成的请求体无 stream_options 字段，服务端流式响应不携带 usage 块
*   **根因**:
    1. DeepSeek v4 流式 API 与 OpenAI 规范对齐：默认不返回 usage，需显式设置 stream_options.include_usage=true
    2. 自研 aiohttp 客户端 build_payload 未设置该字段（openai SDK 时代也常踩此坑）
*   **修复方案**:
    1. DeepSeekClient._build_payload 在 stream=True 时注入 stream_options={'include_usage': True}（setdefault）
*   **验证**:
    1. `verify_prompt_cache_optimization.py 新增用例 test_deepseek_stream_options_injected 通过（12/13，剩余 1 例为已知 mock 脚手架问题）`

### QR-20260817-LLM-EMPTY-RESPONSE 人物档案提取 LLM 重试后持续空响应 (2026-08-17)
*   **问题描述**: PeopleProfileExtractor._call_llm_with_prompt 连续 5 次记录重试后空响应；日志显示最后一次异常为 None、上游错误为无，且没有 traceback，无法判断是调度器、模型服务还是流式响应丢失。
*   **复现步骤**:
    1. 运行夜间人物档案提取流程。
    2. 观察 PeopleProfileExtractor._call_llm_with_prompt 的重试日志和 errors_*.json。
*   **预期行为**:
    1. LLM 返回可解析内容，或记录可定位的异常与上游错误。
*   **实际行为**:
    1. 重试 2 次后仍为空，异常与上游错误字段均无有效诊断信息。
*   **根因**:
    1. 当前错误记录缺少足够诊断信息，暂无法安全归因。
*   **修复方案**:
    1. 本次未修改 LLM 调用策略，等待补充上游响应或调度器诊断信息。
*   **验证**:
    1. `已核对 errors_20260817.json 中 5 条同类记录，均无 traceback。`

### Q-20260818-01 流式请求 Prompt Cache 命中率日志缺失（仅有 mode=sync 无 mode=stream） (2026-08-18)
*   **问题描述**: 日常聊天使用云端模型时，logs/prompt_cache_stats.log 只记录 mode=sync 的非流式调用（nightly 蒸馏等），完全没有 mode=stream 的缓存命中率记录，无法评估用户日常聊天场景下的真实缓存命中率。
*   **复现步骤**:
    1. 重启后端服务，使用 QQ 或客户端触发日常聊天对话（流式返回）。
    2. 打开 DeepSeek 官网控制台，确认流式请求已发送并产生 token 消耗。
    3. 检查 logs/prompt_cache_stats.log，逐行查看 mode 字段。
*   **预期行为**:
    1. 每次流式聊天结束后，prompt_cache_stats.log 应新增一条 mode=stream 的记录，hit_tokens/miss_tokens 取值于 usage.prompt_cache_hit_tokens 与 prompt_cache_miss_tokens。
*   **实际行为**:
    1. prompt_cache_stats.log 所有条目均为 mode=sync，无任何 mode=stream 记录；缓存统计仅覆盖非流式任务，严重偏离真实使用场景。
*   **根因**:
    1. stream_parser._extract_sse_content 的 usage 提取条件错误：仅当 choices 为空时才检查 usage。但真实 DeepSeek API 返回的最后 SSE chunk 同时包含 choices[0].finish_reason=stop 与 usage 对象，条件完全无法满足，usage 被当作 finish 块 yield 后直接丢弃，未触发 log_prompt_cache_usage。
    2. 附带：SSE 首包仅有 delta.role=assistant（content/reasoning 均为 null），_extract_sse_content 原实现会返回 None，导致被放入 pending_json，下一条正常 chunk 触发损坏告警。
*   **修复方案**:
    1. 修改 stream_parser._extract_sse_content 返回结构为 (parsed_items 列表, reasoning_mode)：usage 提取前置于 choices 判断，保证无论 choices 是否为空都能提取；finish_reason 与 usage 可并存于同一 chunk，两者都会 yield。
    2. 修改 parse_sse_stream：遍历 parsed_items 列表逐个 yield 对应事件；只要 data JSON 可正常解析就不放入 pending_json，仅解析异常才走 pending 分支。
    3. 类型收紧：_extract_sse_content 签名从 Optional[tuple] 改为 tuple，异常时统一返回 ([], reasoning_mode)。
*   **验证**:
    1. `运行 tests/scripts/prompt_cache/_debug_real_deepseek_stream.py 观察最后一段 [4] 日志列表，应出现 [D] mode=stream hit=0 miss=100 model=deepseek-v4-flash。`
    2. `同一次调试输出中不应再有 [WARNING] Discarding corrupted pending_json 告警。`
    3. `用真实对话多次触发后，prompt_cache_stats.log 中统计：`grep mode=stream` 条目数与流式对话次数大致匹配。`

### QR-20260818-LOCAL-LAUNCHER 云端启动后切换本地 GGUF 无回复 (2026-08-18)
*   **问题描述**: 通过 start_venv_core.bat 启动后，移动端选择本地 GGUF，日志停在 HybridLLMModule.stream_chat，未进入 LocalLLMAdapter。
*   **复现步骤**:
    1. 以 YAML 中的云端 provider 启动主程序。
    2. 移动端切换到本地 GGUF 并发送消息。
    3. 观察日志只有 HybridLLMModule.stream_chat，没有本地适配器或 llama.cpp 加载日志。
*   **预期行为**:
    1. 通过 start_venv_core.bat 启动时默认 provider 为 local，并创建可用的本地适配器。
*   **实际行为**:
    1. 运行时路由显示 local，但本地适配器不存在，请求无法进入实际推理。
*   **根因**:
    1. 云端快速启动优化只在初始 provider=local 时保存本地适配器工厂，运行时 reload 只更新路由偏好。
    2. 普通环境变量在配置加载顺序中被 YAML provider 覆盖。
*   **修复方案**:
    1. 为 venv_core 启动器设置专用本地启动标记。
    2. 在 YAML 应用完成后将专用启动器的 provider 覆盖为 local。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\llm\verify_start_venv_core_local_provider.py`

### QR-20260824-UIE-LOCAL-MODEL UIE 项目模型目录为空且运行依赖用户缓存 (2026-08-24)
*   **问题描述**: models/UIE/uie-mini 为空，但 UIE 代码仍能运行，模型来源和实际效果不透明。
*   **复现步骤**:
    1. 检查项目 models/UIE/uie-mini 的文件数量
    2. 检查用户目录 PaddleNLP 缓存和 venv_core 的 Paddle 依赖
    3. 运行 UIE 验证脚本并记录实际后端、加载路径和失败案例
*   **预期行为**:
    1. 正式运行优先使用项目 models 目录中的模型，不依赖单个 Windows 用户的缓存
    2. 中文抽取结果不包含 tokenizer 注入的逐字空格
    3. 验证结果区分后端可用与字段抽取质量
*   **实际行为**:
    1. 项目目录 0 个文件，Paddle 后端从 C 盘用户缓存加载约 215 MB 模型
    2. 基础字段抽取成功 8/11，但活动、情绪、餐次失败，复合时间句存在错选
    3. 中文 span 被解码为逐字带空格的文本
*   **根因**:
    1. 本地 Paddle 模型目录没有加入后端候选路径
    2. 设置脚本没有在 ONNX 不可用时复制完整 Paddle 静态模型
    3. 解码逻辑未清理中文 token 间空格
    4. UIE-mini 对开放式活动、隐含情绪和多事件指代的零样本能力有限
*   **修复方案**:
    1. 复制模型到项目目录并设置项目内 Paddle 后端优先
    2. 修正设置脚本和路径解析
    3. 清理中文 span 空格并增加本地模型验证脚本
*   **验证**:
    1. `本地目录包含 7 个文件，共 215358385 字节`
    2. `验证日志确认加载 D:/AI/xiaoyou-core/models/UIE/uie-mini/static/inference.json`
    3. `基础抽取返回今天早上7点，不再包含逐字空格`

### QR-20260824-UIE-ACCURACY UIE 非空验证虚高且多类字段实际准确率为零 (2026-08-24)
*   **问题描述**: 既有 UIE 验证把字段非空视为成功，无法识别首 span 错选、部分实体截断和关键类别完全漏抽。
*   **复现步骤**:
    1. 构造八类字段各四个固定样本
    2. 调用当前 Paddle UIE-mini 后端并保留全部 span
    3. 按照生产 _uie_first_text 只检查第一个 span 是否包含期望文本
    4. 分别汇总每类和总体准确率
*   **预期行为**:
    1. 验证口径与正式记录路径一致
    2. 错误 span、部分实体和空结果均不能计为正确
    3. 结果能够支持是否继续保留 UIE 的工程判断
*   **实际行为**:
    1. 总体准确率 13/32（40.6%）
    2. 餐次、活动和情绪均为 0/4
    3. 复合睡眠句的起床字段首 span 错选晚上10点，食物字段把番茄炒蛋截断为番茄
*   **根因**:
    1. UIE-mini 对开放式活动、情绪及餐次 schema 的零样本泛化不足
    2. 生产逻辑只取第一个 span，模型返回多个候选时没有结合 intent 或语义排序
    3. 旧验证脚本只检查非空，没有判断文本正确性
*   **修复方案**:
    1. 新增严格准确率基准并固化首 span 评分规则
    2. 保留分字段结果，为后续缩减 UIE 使用范围或移除模型提供证据
*   **验证**:
    1. `benchmark_uie_accuracy.py 完成 32 个样本并返回退出码 0`
    2. `本地模型验证在删除 C 盘缓存后仍返回退出码 0`

### QR-20260824-MODEL-MANAGER-DEBUG-SECRET 模型管理器伪 Debug 日志刷屏并明文记录 API Key (2026-08-24)
*   **问题描述**: 后端启动时持续显示 [INFO] ... [DEBUG] 模型已存在/注册完成等日志，且完整的多 API Key 配置对象被写入日志。
*   **复现步骤**:
    1. 在 app.yaml 保持 logging.console_level=INFO 且 debug 开关全关闭
    2. 启动后端并观察 core.core_engine.model_manager 输出
    3. 检查当日 xiaoyou_main.log 中的多 API Key 配置日志
*   **预期行为**:
    1. 模型注册详细日志仅在 debug.model_manager=true 时输出
    2. 任何日志模式都不记录 API Key 值
    3. 同名模型在注册前去重，不用普通 INFO 日志反复报告跳过
*   **实际行为**:
    1. 源码使用 logger.info 输出手写 [DEBUG] 前缀，所以 INFO 级别下仍可见
    2. 旧日志确认 CloudProviderKeyConfig.api_key 以明文落盘
    3. 兼容路径和多 Key 路径各自追加候选，产生重复模型
*   **根因**:
    1. 调试文案与 logging 实际级别混用
    2. 模型管理器没有接入 config.debug_config 的统一开关
    3. CloudProviderKeyConfig.api_key 是普通字符串，对整个对象进行格式化会直接暴露值
*   **修复方案**:
    1. 新增 debug.model_manager 默认关闭开关并包裹全部注册细节日志
    2. 仅构建不含 api_key/base_url 的脱敏配置摘要
    3. 候选入队时用模型显示名统一去重
    4. 增加独立验证脚本覆盖开关两种状态、去重和密钥泄露回归
*   **验证**:
    1. `verify_model_manager_debug_logging.py 确认开关关闭时 INFO 调试调用为 0，模型仍完整注册`
    2. `开启时确认脱敏摘要和候选去重日志存在，模拟密钥值和 api_key= 均不存在于日志调用参数`
    3. `Ruff 和 py_compile 通过`
