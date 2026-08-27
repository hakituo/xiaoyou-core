# TTS / STT / 语音

本分类共 15 条记录。按时间倒序（最新在前）排列。

---

### 问题 3: WebSocketHandler TTS manager 初始化在事件循环运行时返回 None (2026-06-17)


*   **问题描述**: `core/server/handler.py` 的 `WebSocketHandler._get_tts_manager` 在 `__init__` 中同步调用，当事件循环正在运行时（`loop.is_running()` 为 True），直接返回 None 作为"占位符"。但后续 `_synthesize_tts` 方法直接调用 `self.tts_manager.synthesize_and_play`，因 `self.tts_manager` 是 None 而抛出 `AttributeError: 'NoneType' object has no attribute 'synthesize_and_play'`。
*   **复现步骤**:
    1. 在事件循环运行时实例化 `WebSocketHandler`（`__init__` 调用 `_get_tts_manager`）
    2. `loop.is_running()` 返回 True，`_get_tts_manager` 返回 None
    3. `self.tts_manager` 被设为 None
    4. 调用 `_synthesize_tts`，执行到 `self.tts_manager.synthesize_and_play`
    5. 抛出 `AttributeError`
*   **预期行为**: TTS manager 应能正确初始化，或在无法同步初始化时延迟到首次使用的 async 上下文中获取。
*   **实际行为**: `self.tts_manager` 为 None，TTS 功能完全失效并抛异常。
*   **修复方案**: 
    - `__init__` 改为 `self.tts_manager = None`（不立即初始化）
    - 新增 async `_ensure_tts_manager()` 方法：首次使用时在 async 上下文中 `await get_tts_manager()` 获取，失败时兜底尝试同步导入路径
    - `_synthesize_tts` 在使用前调用 `await self._ensure_tts_manager()`，返回 None 时优雅返回并记录错误日志
*   **验证**: `WebSocketHandler` 导入成功，`_ensure_tts_manager` 方法存在，`_get_tts_manager` 已移除，ruff 通过。注：2 个相关测试因 `stream_forwarder.py:65` 的预存 `get_settings` 未定义 bug 而失败（与本次修复无关，修改前已失败）。

### 10.126 Qwen3-TTS create_causal_mask() 参数不兼容（第二轮：cache_position） (2026-06-13)

*   **问题描述**: 修复 `input_embeds` → `inputs_embeds` 后，TTS 仍然报错 `create_causal_mask() got an unexpected keyword argument 'cache_position'`
*   **根本原因**: `qwen_tts` 包是为旧版 `transformers` 写的，新版 `transformers` 的 `create_causal_mask()` 和 `create_sliding_window_causal_mask()` 签名已移除 `cache_position` 参数（文档标注 "Deprecated and unused"）
*   **修复方法**: 从3处调用中删除 `cache_position` 参数：
    - `modeling_qwen3_tts.py` mask_kwargs 中删除 `"cache_position": cache_position`
    - `modeling_qwen3_tts.py` 直接传参中删除 `cache_position=cache_position`
    - `modeling_qwen3_tts_tokenizer_v2.py` mask_kwargs 中删除 `"cache_position": cache_position`
*   **注意**: 这是 `qwen_tts` 与新版 `transformers` 的系统性不兼容问题，可能还有其他参数差异，需逐个排查

### 10.124 Qwen3-TTS 生成失败：create_causal_mask() 参数名不兼容 (2026-06-13)

*   **问题描述**: Qwen3-TTS 模型加载正常，但生成语音时报错 `create_causal_mask() got an unexpected keyword argument 'input_embeds'`，导致 TTS 生成结果为空
*   **复现步骤**:
    1. 启动项目，加载 Qwen3-TTS 模型
    2. 调用 TTS 接口生成语音
    3. 观察日志出现 `create_causal_mask() got an unexpected keyword argument 'input_embeds'` 错误
*   **预期行为**: TTS 正常生成语音
*   **实际行为**: 生成失败，返回空结果
*   **根本原因**: `qwen_tts` 包代码中调用 `create_causal_mask()` 时传的参数名是 `input_embeds`，但新版 `transformers` 的 `create_causal_mask()` 函数签名为 `inputs_embeds`（多了个 `s`），参数名不匹配
*   **修复方法**: 将 `qwen_tts` 包中 3 处 `input_embeds` 改为 `inputs_embeds`：
    - `modeling_qwen3_tts.py` 第1099行（mask_kwargs）
    - `modeling_qwen3_tts.py` 第1513行（直接传参）
    - `modeling_qwen3_tts_tokenizer_v2.py` 第539行（mask_kwargs）

### 10.121 TTS不可用：qwen_tts未安装 + transformers 5.x兼容性问题 (2026-06-03)

*   **问题描述**: TTS功能报错 `No module named 'qwen_tts'`，安装后又报 `TypeError: check_model_inputs() missing 1 required positional argument: 'func'`
*   **复现步骤**:
    1. 启动项目，尝试TTS合成
    2. 日志报错 `No module named 'qwen_tts'`
    3. 在venv_core中安装 qwen-tts==0.1.1 后，导入报 TypeError
*   **预期行为**: TTS正常工作
*   **实际行为**: qwen_tts 未安装在 venv_core 中（只装在系统Python里）；安装后因 transformers 5.x 的 `check_model_inputs` 签名变更导致 TypeError
*   **根本原因**:
    1. `qwen-tts` 包未安装在项目的 `venv_core` 虚拟环境中
    2. `transformers 5.x` 将 `check_model_inputs` 从装饰器工厂改为普通装饰器，而 `qwen_tts` 代码使用 `@check_model_inputs()` 带括号调用，导致多传了一个参数
*   **修复方案**:
    1. 在 venv_core 中安装 `qwen-tts==0.1.1 --no-deps`
    2. 修补 `qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py` 第499行：`@check_model_inputs()` → `@check_model_inputs`

### 10.115 AutoHealService反复报TTS_ENGINE错误聚集但无法定位根因(2026-05-29)

*   **问题描述**: AutoHealService每30秒检测到`错误聚集: TTS_ENGINE x5`，但`无法定位根因`，导致auto_heal_history.jsonl被重复记录膨胀到1450条。
*   **复现步骤**:
    1. 配置TTS provider为qwen3，但VoiceSettings默认值仍为gpt_sovits
    2. GPT-SoVITS服务未启动，初始化失败产生ERROR日志
    3. AutoHealErrorHandler捕获ERROR日志转发给AnomalyDetector
    4. AnomalyDetector触发ERROR_CLUSTER规则（600秒内≥3次）
    5. RootCauseAnalyzer无法定位根因（traceback为空→指纹file_path为空→_locate_error_by_type搜索"raise TTS_ENGINE"找不到）
    6. _save_history用append模式每次追加50条，导致重复膨胀
*   **预期行为**: AutoHealService能正确定位TTS错误来源文件，且历史记录不重复
*   **实际行为**: 每次都报"无法定位根因"，历史文件重复膨胀
*   **根本原因**:
    1. VoiceSettings默认值仍为`gpt_sovits`，与实际使用的`qwen3`不一致（历史遗留）
    2. AutoHealErrorHandler未传递record的源文件位置信息（pathname/lineno/funcName）
    3. AnomalyDetector._compute_fingerprint在traceback为空时无法计算有效指纹
    4. RootCauseAnalyzer._locate_error_by_type只搜索`raise ErrorType`，不支持通过logger名称定位
    5. _save_history用append模式导致重复写入
*   **修复**:
    1. VoiceSettings默认值从`gpt_sovits`改为`qwen3`
    2. AutoHealErrorHandler添加source_file/source_line/source_func到error_report
    3. AnomalyDetector新增_extract_from_source_info方法，利用record位置信息计算指纹
    4. RootCauseAnalyzer新增_find_by_logger_name方法，通过`get_logger("TTS_ENGINE")`定位源文件
    5. TTSManager回退逻辑从GPT-SoVITS改为Qwen3-TTS优先
    6. _save_history改为覆盖写入+dirty标记，去重历史文件

### 10.32 Qwen3-TTS SoX 依赖缺失与回退机制 (2026-02-08)

*   **问题描述**:
    *   运行 Qwen3-TTS 试跑脚本或初始化时，Windows 系统报错 `SoX could not be found!`，即使安装了 SoX 且配置了 PATH，`qwen_tts` 库仍可能检测失败或抛出警告；
    *   用户请求保留 GPT-SoVITS 作为备用方案，以防 Qwen3-TTS 不可用。
*   **原因分析**:
    *   `qwen_tts` 库（及其内部引用的 `speech_vq` 模块）在代码层面硬编码了 `import sox` 和 `sox.Transformer` 调用，这是一个基于 Linux/MacOS 环境的遗留设计；
    *   Windows 环境下 `sox` Python 包装器对二进制文件的查找机制不够健壮，导致即使 PATH 正确也可能报错。
*   **解决方案**:
    *   **自动回退**: 在 `core/voice/tts_engine.py` 中实现初始化回退逻辑，当 Qwen3-TTS 加载失败时，自动降级为 GPT-SoVITS 引擎；
    *   **Mock 替代**: 在 `tts_engine.py` 和测试脚本中注入 `MockTransformer` 类来模拟 `sox` 模块的行为（使用 NumPy 实现音频归一化），彻底移除了对外部 SoX 二进制文件的依赖。
*   **验证结果**:
    *   `tests/diagnostics/verify_qwen3_tts.py` 不再报错 SoX 缺失，音频生成正常；
    *   系统不再强制要求用户安装 SoX 工具。
    *   在 TTS 服务关闭的情况下，LLM 对话依然流畅，无卡顿。

### 10.37 GPT-SoVITS TTS 首句慢与“静音”复测记录（2025-12-27）


*   **问题描述**:
    *   用户反馈 TTS 单句生成约 10 秒，且曾出现“生成静音”。
*   **复现步骤**:
    *   启动后端；未启动或刚启动 GPT-SoVITS 服务时，调用 `/api/v1/tts` 或触发自动 TTS。
*   **预期行为**:
    *   稳态 TTS 在几秒内返回可播放音频；服务不可用时应快速失败并返回结构化错误。
*   **实际行为**:
    *   首句明显慢于稳态（冷启动）；服务不可用时存在“调用链阻塞/噪音日志/返回空或近似静音”的体验问题。
*   **原因分析**:
    *   冷启动包含：TTSManager 初始化、权重设置、设备切换、服务端首次推理。
    *   控制接口与合成接口若缺少连接复用与短超时，会放大“服务离线/重启”阶段的阻塞与噪音。
*   **修复与改动**:
    *   为 GPTSoVITSEngine 引入持久 `aiohttp.ClientSession`（减少连接开销）。
    *   控制接口增加短超时与 15 秒退避窗口，避免服务离线时反复重试拖慢主链路。

### 10.31 模型双重加载与TTS阻塞修复 (2025-12-17)

*   **问题描述**: 
    *   主程序启动后 LLM 响应极慢（首字超时 3 分钟以上），但独立测试脚本 `test_llm_standalone.py` 响应迅速（<1s）。
    *   TTS 服务未启动时，系统尝试卸载模型会卡死。
    *   日志显示系统同时加载了两次 LLM 模型。
*   **原因分析**:
    *   **双重加载**: `cpu_processor` 服务启动了 `GlobalTaskScheduler`，其默认配置会加载一份 GPU 模型用于 C++ 加速。同时，业务层的 `ChatAgent` 通过 `LLMModule` 也加载了一份 GPU 模型。两份 7B/8B 模型挤在显存中，导致显存溢出到系统内存，性能雪崩。
    *   **TTS 阻塞**: `tts_engine.py` 和 `resource_manager.py` 中的网络请求缺乏短超时控制。当本地 TTS 服务 (gpt-sovits) 未启动时，卸载/迁移请求会挂起直到 TCP 超时，阻塞了主事件循环。
*   **解决方案**:
    *   **消除双重加载**: 修改 `core/services/scheduler/task_scheduler.py`，在启动 C++ 调度器时强制 `gpu_config=None`，禁止调度器加载 GPU 模型，仅保留 `ChatAgent` 的模型加载权。
    *   **非阻塞 TTS**: 在 `tts_engine.py` 的 `move_to_cpu` 等控制方法中增加 `timeout=2.0s` 限制；在 `resource_manager.py` 中增加 `asyncio.wait_for` 保护，确保 TTS 服务离线时不影响主流程。
    *   **服务恢复**: 在修复上述资源冲突后，完全恢复了 `lifecycle_manager.py` 中之前为了排查问题而禁用的 `cpu_processor`、`cache_system` 等核心服务，确保系统功能完整。
*   **验证结果**:
    *   主程序启动时间正常，模型仅加载一次。
    *   LLM 首字响应恢复至 <1s。

### 10.29 TTS 初始化死锁与同步调用警告修复 (2025-12-16)



*   **问题描述**:
    *   用户反馈主程序启动后无法响应请求，且日志中偶现 `Running sync text_to_speech inside async loop` 警告；
    *   `TTSManager` 在初始化或调用时可能导致整个服务卡死（Deadlock）。
*   **原因分析**:
    *   **初始化死锁**: `TTSManager._initialize` 内部直接调用 `asyncio.run(self.new_engine.initialize())`。当该方法在 FastAPI 的 `lifespan`（异步上下文）中被调用时，由于当前线程已有运行中的事件循环，`asyncio.run` 会抛出错误或导致不可预期的行为（取决于 Python 版本），在某些情况下表现为死锁或静默失败，导致服务未能正确启动；
    *   **同步调用死锁风险**: `TTSManager.text_to_speech` 为同步方法，内部尝试通过 `asyncio.run_coroutine_threadsafe(...).result()` 跨线程调用异步引擎。但当该方法被直接在主线程的事件循环中调用（例如由 `TextToSpeechTool._run` 直接触发）时，`result()` 会阻塞主线程等待结果，而主线程正是执行异步任务的线程，导致**死锁**（主线程等待任务完成，任务等待主线程调度）。
*   **修复方案**:
    *   **安全初始化**: 修改 `TTSManager._initialize`，增加对 `asyncio.get_running_loop()` 的检测。若检测到当前线程已有事件循环，则通过 `threading.Thread` 启动一个独立线程来执行初始化逻辑，彻底隔离上下文，避免冲突；
    *   **异步能力扩展**: 在 `TTSManager` 中新增 `async_text_to_speech` 方法，提供原生的异步调用路径；
    *   **死锁防护**: 在同步的 `text_to_speech` 方法中增加检测，若发现正在异步循环中被调用，直接抛出明确的 `RuntimeError`（或日志报错），禁止这种必然导致死锁的用法；
    *   **工具层升级**: 更新 `core/tools/study_tools.py` 中的 `TextToSpeechTool`，实现 `_arun` 异步接口。优先调用 `async_text_to_speech`，若不可用则通过 `loop.run_in_executor` 将同步调用卸载到线程池，确保 Agent 工具执行不会阻塞主事件循环。
*   **验证结果**:
    *   修复后，系统通过 `lifespan` 启动时不再卡死，TTS 引擎能正确初始化；
    *   Agent 调用 TTS 工具时，优先走异步路径，不再触发“同步调用警告”或死锁，提升了系统在高并发下的稳定性。

---

### 10.23 对话与TTS任务超时后的后台协程泄漏防护 (2025-12-16)


*   **问题描述**: 在 HTTP `/api/v1/message` 与 `/api/v1/tts` 接口中，长时间推理或语音合成可能触发超时，但旧逻辑中仅在 `asyncio.wait_for` 抛出 `TimeoutError` 后直接返回错误/友好文案，没有显式处理已创建的后台任务对象。虽然 `wait_for` 会对内部任务注入取消信号，但在高并发场景下，未显式 `await` 取消完成可能导致任务短时间内仍占用资源，增加显存与CPU压力。
*   **复现步骤**:
    *   将本地 GGUF 大模型与 TTS 同时开启，在默认 `limits.message_timeout=60`、`limits.tts_timeout=120` 配置下，使用前端反复发送长文本或包含图像/语音触发的复杂请求；
    *   人为制造模型加载缓慢或显存紧张（如同时跑图像生成），观察在接口返回“思考时间过长”或“语音合成超时”等提示后，后台仍有 LLM/TTS 相关协程短时间持续占用 GPU/CPU；
    *   通过日志可以看到任务在超时后仍有少量残余输出或清理逻辑延迟执行。
*   **原因分析**:
    *   `/api/v1/message` 中创建了 `process_message_with_async` 的任务并通过 `asyncio.wait_for` 加超时，但在捕获 `TimeoutError` 后仅构造了友好回复返回前端，没有对任务对象执行二次取消与 `await`，依赖 `wait_for` 的内部取消机制；
    *   `/api/v1/tts` 中同样对 `_generate_tts_with_async` 使用了 `asyncio.wait_for` 包裹，`except asyncio.TimeoutError` 分支只返回错误 JSON，而未对任务进行显式取消与回收；
    *   在高并发或调度器压力较大时，单纯依赖 `wait_for` 内部取消可能导致少量任务在事件循环中以“已取消但未收尾”的状态短暂存活，增加资源抖动。
*   **修复方案**:
    *   在 `/api/v1/message` 的超时分支中，补充对后台任务的显式取消与等待：`task.cancel()` 后包裹 `await task` 并捕获 `CancelledError`，然后再返回友好中文提示，避免前端看到 HTTP 层面的 504 错误 (`routers/api_router.py:808-830`)；
    *   在 `/api/v1/tts` 的 `except asyncio.TimeoutError` 分支中同样引入 `task.cancel()` 与 `await task` 的回收逻辑，即便取消过程中抛出异常也统一吞掉，只保留标准化的 `TTS_TIMEOUT` 错误响应 (`routers/api_router.py:1278-1299`)；
    *   保持对话与 TTS 超时的用户可见行为不变：对话接口继续返回“抱歉，我思考的时间有点久，请稍后再试或换个话题。”一类温和提示，TTS 接口则返回结构化 JSON，前端统一按照 `error_code` 做错误展示。
*   **验证结果**:
    *   通过重复压测 `/api/v1/message` 与 `/api/v1/tts`，在强制缩短超时时间的情况下观察任务生命周期，确认超时后相关协程会在短时间内完全回收，不再出现残留日志或 GPU/CPU 突增；
    *   结合 `tests/test_empty_responses.py` 与前端长文本对话手工测试，确认对话超时时用户体验保持一致，未引入新的空回复或异常文案；
    *   在语音合成超时时，前端能够稳定收到 `TTS_TIMEOUT` 错误码并展示中文错误提示，不会出现接口长时间挂起或无响应的情况。
*   **经验总结**:
    *   使用 `asyncio.wait_for` 包装长耗时任务时，除了依赖其内部取消机制外，在捕获 `TimeoutError` 后显式 `task.cancel()` 并 `await` 完成本轮取消，是一种更稳健的清理策略；
    *   对于 LLM 推理与多媒体生成这类重型任务，接口层要同时关注“用户可见超时文案的一致性”和“后台协程及时回收”，避免因为实现细节差异导致某些接口在超时后仍消耗大量资源。

### 10.22 TTS GPU/CPU 动态切换与显存占用控制 (2025-12-16)


*   **问题描述**: 即使将 TTS 配置为在 CPU 上运行，关闭前端终端窗口后，核显显存仍然长期被占用，表现为 GPT-SoVITS 相关进程在 GPU 显存紧张时依旧常驻 GPU，影响 LLM/图像等其他任务。
*   **原因分析**:
    *   旧实现中，`TTSManager` 只是在重型任务前通过 `move_to_cpu()` 将 TTS 服务迁移到 CPU，但缺少统一的设备状态管理和基于 GPU 剩余显存的动态决策；
    *   TTS 合成链路始终直接调用远端 GPT-SoVITS 服务，客户端虽然支持 `/set_device` 接口，但未在每次合成前根据当前 GPU 状态自动选择合适设备；
    *   C++ 调度器中的 `CPUTTSWorker` 仅实现了纯 CPU 的 Mock TTS，用于压力测试和资源隔离验证，不参与实际 GPT-SoVITS 推理，因此无法替代 GPU/CPU 之间的真实设备切换。
*   **改动方案**:
    *   在 `core/voice/tts_engine.py:346-422` 中为 `TTSManager` 引入 `current_device` 字段和 `_device_lock`，统一记录当前语音服务所在设备；
    *   新增 `_ensure_optimal_device()` 协程（`core/voice/tts_engine.py:386-414`），在每次 `synthesize` 前根据当前 GPU 剩余显存自动选择设备：
        *   若未安装 `torch` 或 `torch.cuda.is_available()` 为 `False`，则强制迁移到 CPU；
        *   通过 `torch.cuda.get_device_properties(0)` 获取总显存，结合 `memory_allocated`/`memory_reserved` 估算已用显存，计算剩余显存 `free_gb`；
        *   当 `free_gb >= 2.0` 时优先将 TTS 放到 GPU (`move_to_gpu()`)，否则迁移到 CPU (`move_to_cpu()`)；
        *   使用异步锁保证多路 TTS 并发请求下的设备切换不会发生竞态。
    *   更新 `TTSManager.move_to_cpu` / `move_to_gpu`，在成功调用底层引擎的迁移接口后，同步维护 `current_device`（`core/voice/tts_engine.py:378-385`），确保手动迁移与自动迁移逻辑一致。
    *   在 `TTSManager.synthesize` 中先调用 `_ensure_optimal_device()`，再执行实际的 `engine.synthesize` 调用（`core/voice/tts_engine.py:432-438`），使所有 TTS 调用天然具备 GPU/CPU 动态切换能力。
*   **效果**:
    *   当 GPU 显存充裕时，TTS 默认跑在 GPU 上，保证推理速度；
    *   当 GPU 显存紧张或不可用时，TTS 会自动迁移并锁定在 CPU 上，给 LLM/图像等重任务腾出显存；
    *   结合现有的 `ResourceManager.prepare_for_heavy_task` 中对语音服务的 `move_to_cpu` 调用，可以显著降低在多模态高负载场景下核显显存被语音服务长时间占满的风险。
        *   后续 STT 使用 HF Whisper `whisper-small` 在 GPU 上完成转写，闭环验证通过。
*   **经验总结**:
    *   在类体内部书写 `import` 会将模块绑定为类属性，方法中直接使用未加前缀的名字会触发 `NameError`，应统一将依赖导入放在模块顶层；
    *   涉及 `sys.frozen` / `sys._MEIPASS` 的路径适配逻辑要同时兼容打包与源码运行两种模式，特别是 Windows 环境下的 TTS/多媒体资产路径解析。

### 10.21 TTS 在源码运行模式下未导入 sys 导致合成失败 (2025-12-16)


*   **问题描述**: 在源码模式（非打包 EXE）下使用桌宠或 HTTP `/api/v1/tts` 进行语音合成时，后端日志连续报错 `NameError: name 'sys' is not defined`，堆栈指向 `core/voice/tts_engine.py` 中的 `GPTSoVITSEngine.synthesize`，前端表现为 TTS 无法播放语音。
*   **复现步骤**:
    *   通过桌面宠或 `/api/v1/message` 发送文本消息并开启 TTS 播放；
    *   或直接调用 `/api/v1/tts` 接口让后端进行语音合成；
    *   观察后端日志，出现类似：
        *   `TTS生成过程中出错: name 'sys' is not defined`
        *   `NameError: name 'sys' is not defined. Did you forget to import 'sys'`
*   **原因分析**:
    *   `GPTSoVITSEngine.synthesize` 中为了区分打包 EXE (`sys.frozen`) 和源码运行模式，在多处使用了 `getattr(sys, 'frozen', False)` 和 `sys.executable`、`sys._MEIPASS` 来定位参考音频 `ref_audio` 的路径；
    *   但 `sys` 的 `import` 被错误地写在类体内部 (`class GPTSoVITSEngine` 中的 `import sys`)，Python 会将其视为类属性，而不是模块级全局变量；
    *   在方法体内访问未在局部或全局定义的 `sys` 时，解释器抛出 `NameError`，导致整个 TTS 合成流程直接失败。
*   **修复方案**:
    *   将 `sys` 的导入提升到模块顶层，与其他标准库一起声明，使之成为真正的全局变量：
        *   从 `class GPTSoVITSEngine` 中移除 `import sys`；
        *   在文件头部 `import logging, asyncio, io, os, uuid, aiohttp` 之后增加 `import sys` (`core/voice/tts_engine.py:6-13`)；
    *   其他逻辑保持不变，继续沿用 `sys.frozen`/`sys._MEIPASS` 区分打包模式与源码模式。
*   **验证结果**:
    *   运行 `python tests/test_full_system.py`，观察日志：
        *   TTS Manager 成功初始化 GPT-SoVITS 引擎并加载权重；
        *   `GPT-SoVITS` 成功返回音频数据（约 100k 采样点），无再出现 `NameError`。

### 10.17 STT/TTS 链路全面修复与升级 (2025-12-15)

*   **STT 升级**:
    *   **模型迁移**: 从 `Faster-Whisper` 迁移至 `HuggingFace Transformers` 原生加载的 `whisper-small` 模型 (下载至 `models/whisper-small`)。
    *   **原因**: 增强对 Transformers 生态的兼容性，为后续微调做准备。
    *   **实现**: 新增 `HuggingFaceSTTEngine` 类，`STTManager` 自动检测本地模型路径并优先加载。
*   **TTS 修复**:
    *   **混合精度错误**: 修复了 `GPT-SoVITS` 在 FP16 模式下 BERT 特征 (FP32) 与模型权重 (FP16) 类型不匹配导致的 `RuntimeError`。
    *   **修复代码**: 在 `t2s_model.py` 中增加了自动类型转换逻辑。
*   **闭环验证**:
    *   建立了 `TTS -> Audio -> STT` 的自动化测试链路 (`tests/test_full_system.py`)，验证了语音交互的完整性。

### 10.15 语音服务设备迁移 (Device Migration) (2025-12-15)

*   **功能**: 为 `FasterWhisperSTTEngine` 和 `GPTSoVITSEngine` (通过 API) 实现了动态设备切换。
*   **接口**:
    *   `move_to_cpu()`: 将模型权重转移到 RAM，释放 VRAM。
    *   `move_to_gpu()`: 将模型权重转移回 VRAM，恢复高性能推理。
*   **集成**: 集成至 `ResourceManager`，在 LLM/Image 生成期间自动触发 `move_to_cpu`。

### 10.8 TTS 引擎方法名不匹配修复 (2025-12-14)

*   **问题描述**: 调用语音合成时报错 `AttributeError: 'TTSManager' object has no attribute 'text_to_speech'`。
*   **解决方案**: 修正调用代码为 `synthesize`。

### VOICE-FULLWIDTH-001 VOICE 标签全角括号不识别导致语音消息直接以文本发出 (2026-07-18)
*   **问题描述**: LLM 输出 ［VOICE］ 全角括号标签时，三处匹配代码只识别半角 [VOICE]，导致标签未被剥离，语音消息以文本形式直接发送
*   **复现步骤**:
    1. LLM 生成包含 ［VOICE］ 的回复
    2. extract_voice_tag 无法匹配全角括号
    3. 标签作为文本直接发出
*   **预期行为**:
    1. 全角/半角括号的 VOICE 标签都应被识别并转为语音发送
*   **实际行为**:
    1. 全角括号标签被忽略，直接作为文本发送
*   **根因**:
    1. 三处正则只匹配半角方括号
*   **修复方案**:
    1. 修改三处正则同时匹配半角 [ 和全角 ［ 括号
*   **验证**:
    1. `python 测试全角/半角 VOICE 标签匹配和剥离均正确`
