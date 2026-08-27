# 记忆系统

本分类共 13 条记录。按时间倒序（最新在前）排列。

---

### 问题 1: get_recent_history NameError — get_write_lock 未定义 (2026-06-27)


*   **问题描述**: `routers/v1/sessions.py` 调用 `get_session_history` 时报 `NameError: name 'get_write_lock' is not defined`，导致会话历史获取失败。
*   **复现步骤**:
    1. 前端请求 `/api/v1/sessions/{id}/history`
    2. 后端 `sessions.py:78` 调用 `mm.get_recent_history()`
    3. `weighted_memory_manager.py:916` 转调 `memory/core/history_ops.py:15`
    4. 第 15 行 `with get_write_lock(manager):` 抛出 NameError
*   **预期行为**: 正常返回会话历史列表。
*   **实际行为**: 500 错误，`NameError: name 'get_write_lock' is not defined`。
*   **根因**: `history_ops.py` 第 4 行 import 的是 `get_read_lock`，但第 15 行用了 `get_write_lock`（函数名写错）。读取历史记录应使用读锁而非写锁。
*   **修复方案**: 第 15 行 `get_write_lock(manager)` → `get_read_lock(manager)`。

### 10.122 /清除短期记忆 没有清除效果 (2026-06-02)

*   **问题描述**: 发送 `/清除短期记忆` 后，对话历史没有被清除
*   **复现步骤**:
    1. 发送 `/清除短期记忆` 命令
    2. 收到"短期记忆已清除"的回复
    3. 但之前的对话上下文仍然存在
*   **预期行为**: 清除后，AI应该不记得之前的对话内容
*   **实际行为**: AI仍然记得之前的对话内容
*   **根本原因**: 记忆存储在 scope 级别（如 `private_10001__scope__ling`），但清除时使用的是 persona 级别（如 `private_10001__persona__ling_qq_master`）。`resolve_memory_user_id` 函数会将 persona 级别的 conversation_id 转换为 scope 级别的 user_id，实现同一角色下的不同 persona 共享记忆池。
*   **修复**: 修改 `_resolve_memory_target_ids` 方法，添加 scope 级别的 ID
*   **状态**: ✅ 已修复

### 10.117 chromadb 模块缺失 (2026-05-29)

*   **问题描述**: `core/vector_search.py` 导入 chromadb 时报错 `No module named 'chromadb'`
*   **复现步骤**:
    1. 运行项目
    2. VectorSearch 初始化时尝试导入 chromadb
*   **预期行为**: chromadb 正常导入，向量搜索功能可用
*   **实际行为**: 报错 `No module named 'chromadb'`
*   **根本原因**: chromadb 未安装，且未添加到 requirements.txt 依赖中
*   **修复**:
    1. 使用 `pip install chromadb` 安装（阿里云镜像）
    2. 将 `chromadb>=1.0.0` 添加到 `requirements/requirements.txt`

### 10.110 WeightedMemory 保存权重数据 WinError 5 拒绝访问 (2026-05-23)

*   **问题描述**: `save_weighted_data_locked` 保存权重数据时报错 `[WinError 5] 拒绝访问。: '...weighted.json.tmp_xxx' -> '...weighted.json'`
*   **复现步骤**:
    1. 系统运行时自动保存权重记忆数据
    2. `safe_json_dump` 先写入 `.tmp` 临时文件，再调用 `os.replace` 原子替换
    3. `os.replace` 抛出 `WinError 5`（拒绝访问），目标文件被其他进程占用
*   **预期行为**: `.tmp` 文件写入后应成功被 `os.replace` 替换为目标文件
*   **实际行为**: `os.replace` 因目标文件被占用而失败，6次重试（总等待约1.9秒）仍不够
*   **根因**:
    1. Windows 上杀毒软件（如 Windows Defender）或搜索索引器可能长时间锁定目标 `.json` 文件
    2. 原重试策略等待时间过短（总等待仅约1.9秒），不足以覆盖杀毒软件扫描周期
*   **修复方案**:
    1. 将重试次数从6次增加到10次，采用更长指数退避（总等待约25秒）
    2. 原子替换最终仍失败时，回退到直接写入目标文件（非原子但保证数据不丢失）
*   **涉及文件**: `memory/core/persistence.py`

### 10.83 短期记忆修剪60条时不蒸馏直接移除，信息丢失 (2026-05-06)

*   **问题描述**: 短期记忆达到60条（修剪阈值）时，系统直接修剪移除低分消息，没有先进行蒸馏总结。被移除的消息虽然保存到加权记忆，但蒸馏要等60秒后才触发，且蒸馏定时器可能因防抖机制被跳过
*   **复现步骤**:
    1. 正常聊天，短期记忆逐渐增长到61条
    2. 30秒后触发修剪，移除1条低分消息
    3. 日志显示"短期记忆已修剪，当前保留 60/60 条消息，移除 1 条"
    4. 蒸馏需等60秒后才触发，且如果修剪频繁，蒸馏定时器可能被跳过
*   **预期行为**: 修剪前先蒸馏即将被移除的消息，确保信息不丢失；修剪后立即蒸馏剩余未蒸馏的加权记忆
*   **实际行为**: 先修剪移除消息，蒸馏延迟60秒且可能被跳过
*   **根因**:
    1. **蒸馏在修剪之后**: `_schedule_post_trim_distillation` 在修剪后才调度，延迟60秒执行
    2. **蒸馏定时器防抖跳过**: 如果修剪频繁，`_distillation_timer.is_alive()` 为 True 时新蒸馏被跳过
    3. **流程设计缺陷**: 应该"先蒸馏再修剪"，确保被移除的消息在离开短期记忆前已完成总结
*   **修复方案**:
    1. 新增 `_distill_before_trim()`: 修剪前先识别候选移除消息，移到加权记忆后同步蒸馏
    2. 替换 `_schedule_post_trim_distillation()` 为 `_run_post_trim_distillation()`: 修剪后立即蒸馏（不再延迟60秒）
    3. 移除不再使用的 `_distillation_delay` 和 `_distillation_timer`
*   **关键文件**: `memory/core/runtime_ops.py`, `memory/core/manager_init_ops.py`

### 10.51 写锁内做磁盘I/O导致所有操作阻塞10+秒 (2026-04-29)

*   **问题描述**: 修复10.50（自锁死锁）后，第二条消息仍然卡住。日志显示 `writers=1, waiting_writers=1` 持续10+秒不释放
*   **复现步骤**:
    1. 启动 Xiaoyou Core 后端
    2. 发送第一条消息，AI正常回复
    3. 发送第二条消息，卡在 "Resolving scope and sensitive mode..." 不动
*   **预期行为**: 所有消息正常回复
*   **实际行为**: 第二条消息卡住10+秒，日志显示 `writers=1` 持续不释放
*   **根因**: `_process_save_queue` 在持有 `ReadWriteLock` 写锁的情况下调用 `_safe_save_all()`，后者执行大量磁盘I/O（JSON序列化+写多个文件），导致写锁被持有10+秒。在此期间，所有读/写操作（包括 `get_memories_by_topic`、`add_memory` 等）全部阻塞
*   **修复**: 将磁盘I/O操作移到写锁外面。`_process_save_queue` 在写锁内只做内存操作（清空保存队列、更新索引），释放锁后再执行 `_safe_save_all()`。同步修复 `sync_save_memory`、`_save_weighted_data`、`migrate_legacy_data` 中的同类问题
*   **教训**: **写锁绝不能覆盖磁盘I/O操作**。读写锁的设计目的是保护内存数据结构的一致性，磁盘I/O应该在没有锁的情况下执行。如果必须在保存时获取一致性快照，应该在锁内复制数据，释放锁后再写入磁盘

### 10.50 写锁内调用 save_memory() 自锁死锁全量修复 (2026-04-29)

*   **问题描述**: 修复10.49后，第二条消息仍然卡住。用户定位到 `mutation_ops.py:182` 的 `delete_message` 在持有写锁时调用 `manager.save_memory()`。但更关键的根因是 `add_memory`（最频繁调用的函数）在写锁内通过 `_add_memory_core` → `schedule_save_fn()` → `_schedule_save()` 间接触发了异步保存线程，异步保存线程在 `_process_save_queue` 中再次获取写锁，导致自锁
*   **复现步骤**:
    1. 启动 Xiaoyou Core 后端
    2. 发送第一条消息，AI正常回复
    3. 发送第二条消息，卡在 "Resolving scope and sensitive mode..." 不动
*   **预期行为**: 所有消息正常回复
*   **实际行为**: 第二条消息永久卡住，日志显示 `writers=1, waiting_writers=2`
*   **根因**: `add_memory` 持有写锁时，内部调用链 `_add_memory_core` → `schedule_save_fn()` → `_schedule_save()` → `schedule_save()` → 启动异步保存线程 → `_process_save_queue()` → `with get_write_lock(manager)` → 再次获取写锁 → 自锁死锁。`_add_memory_core` 是最频繁调用的路径，这是死锁的主要触发点
*   **修复**: 
    1. `_add_memory_core` 不再调用 `schedule_save_fn()`，改为返回 `(memory_id, need_save)` 元组
    2. `add_memory` 在写锁外面根据 `need_save` 调用 `_schedule_save()`
    3. `add_memory_locked` 传给 `_add_memory_core` 的 `schedule_save_fn` 改为 `lambda: None`（空操作）
    4. 同步修复其他7个在写锁内调用 save 的函数
*   **教训**: 在排查自锁死锁时，**必须追踪最频繁调用的路径**。`add_memory` 是每次对话都会调用的核心函数，它才是死锁的主要触发点，而不仅仅是 `delete_message` 这种低频操作

### 10.49 第二条消息卡住 - ReadWriteLock 不可重入导致 add_memory 自锁死锁 (2026-04-29)

*   **问题描述**: 修复10.48后，AI能看到上下文了，但只有启动后的第一条消息能正常回复，第二条消息卡在 "Resolving scope and sensitive mode..." 不动。日志显示 "About to save 3 memories" 但没有 "Saved memory 1/3"
*   **复现步骤**:
    1. 启动 Xiaoyou Core 后端
    2. 发送第一条消息，AI正常回复
    3. 发送第二条消息，日志显示 "Resolving scope and sensitive mode..." 后永久卡住
*   **预期行为**: 第二条消息正常回复，能看到之前的上下文
*   **实际行为**: 第二条消息永久卡住，无响应
*   **根因**: `add_memory` 持有 `ReadWriteLock` 写锁时，内部调用链 `_schedule_save` → `schedule_save` → `with get_write_lock(manager)` → 再次获取 `ReadWriteLock` 写锁。但 `ReadWriteLock` **不可重入**——`acquire_write` 检查 `self._writers > 0` 时会永远等待，导致同一线程**自锁死锁**
*   **自锁链路**:
    1. `add_memory` → `with self._rw_lock.write_lock()` → `_writers = 1`
    2. `add_memory_locked` → `_schedule_save` → `schedule_save` → `with get_write_lock(manager)` → `self._rw_lock.write_lock()` → `acquire_write()` → 检查 `_writers > 0` → **永远等待！**
*   **修复**:
    1. `schedule_save` 移除 `with get_write_lock(manager):`——它只是往 deque 追加时间戳并启动异步保存线程，都是线程安全操作，不需要写锁
    2. 附加修复：多个 async 函数中同步调用 `mm.get_memories_by_topic()`、`mm.get_history()`、`mm.add_memory()` 等方法改为 `asyncio.to_thread`，避免阻塞事件循环
*   **教训**: 自定义读写锁（`ReadWriteLock`）通常**不可重入**。如果持有写锁的代码内部再次获取写锁，会导致自锁死锁。在设计锁策略时，必须确保同一线程不会重复获取同一把不可重入锁，或者使用可重入锁（如 `threading.RLock`）

### 10.47 save_conversation_history 阻塞 done 信号导致消息不显示 (2026-04-28)

*   **问题描述**: 用户发送消息后，LLM 已生成响应（日志显示 Chunk #10/#20 received），但客户端收不到消息。日志显示 "About to save 3 memories" 后卡住，嵌入模型加载和 C++ VectorIndexer 初始化耗时约4秒
*   **复现步骤**:
    1. 启动 Xiaoyou Core 后端
    2. 通过 QQ 发送一条消息
    3. 观察日志：LLM 流式生成 chunk 正常，但 "About to save memories" 后卡住
    4. 客户端无响应
*   **预期行为**: LLM 生成内容后立即显示给用户，记忆保存在后台进行
*   **实际行为**: 记忆保存阻塞了 `done` 信号的发送，客户端等待 `response_done` 事件才显示消息
*   **根因**: `streaming.py` 中 `await agent._save_conversation_history(...)` 在 `yield {"done": True}` 之前执行。`save_conversation_history` 内部 `mm.add_memory()` 首次调用需要加载嵌入模型（0.18s）+ 初始化 C++ VectorIndexer（3s），总共约4秒阻塞。QQ 客户端需要 `response_done` 事件才显示消息
*   **修复**:
    1. 将 `yield {"done": True}` 移到 `save_conversation_history` 之前，确保客户端立即收到完成信号
    2. 将 `await agent._save_conversation_history(...)` 改为 `asyncio.create_task(agent._save_conversation_history(...))`，后台执行不阻塞
    3. C++ VectorIndexer 改为延迟初始化（后台线程），避免首次 `add_memory` 时阻塞3秒
    4. 嵌入模型在 `WeightedMemoryManager.__init__` 中后台预加载，避免首次使用时阻塞
*   **调用链**: `stream_chat_impl` → `await _save_conversation_history` → `save_conversation_history` → `asyncio.to_thread(_write_all)` → `mm.add_memory()` → `embedding_generator.ensure_model_loaded()` + `self.vector_indexer` 延迟初始化

### 10.69 VectorSearch 多实例初始化导致 `_chromadb_module` 缺失（2025-12-22）

*   **问题描述**: 在同一进程内创建多个 `core.vector_search.VectorSearch` 实例（尤其是持久化模式、不同 collection）时，第二个及后续实例可能在初始化/查询阶段报错：`AttributeError: 'VectorSearch' object has no attribute '_chromadb_module'`，导致示例对话库（SFW/NSFW）检索不稳定。
*   **复现步骤**:
    *   在仓库根目录运行 Python；
    *   顺序创建多个实例（不同 collection），并调用 `query()`：

### 10.34 Pytest 中 ChromaDB DeprecationWarning 噪音记录 (2025-12-17)

*   **问题描述**: 运行 `pytest` 时出现 `chromadb` 的 `DeprecationWarning`，提示 `legacy embedding function config`。
*   **复现步骤**:
    *   在项目根目录运行 `python -m pytest -q`；

### 10.24 对话历史过长时的自动短期记忆清理与上下文防护 (2025-12-16)


*   **问题描述**: 在长时间持续对话（数百轮）或频繁大段输入的场景下，即便为本地 GGUF 模型增加了字符级截断（`max_chars=1800`），记忆管理器内部的 `short_term_memory` 仍会持续累积旧消息。虽然这些旧消息在投喂 LLM 前会被切片丢弃，但在极端情况下（如未来调整 `max_chars` 或切片策略）仍存在再次触发上下文窗口超限的风险，且用户期望“历史太长时自动帮我清掉旧记录”。
*   **改动方案**:
    *   在 `ChatAgent._build_conversation_history` 中，在进行本地/云端上下文切片逻辑之前，先对当前历史消息做一次“粗粒度字符总量”检查：
        *   通过 `memory_manager.get_history()` 获取当前短期历史，并累加其中 `content` 字段的字符数；
        *   当累计字符数首次超过 `10000` 时，即认为“历史已经长到对当前对话帮助有限”，立即调用 `memory_manager.clear_memory(mode="short")` 清空短期记忆，仅保留长期画像与重要记忆 (`core/agents/chat_agent.py:1285-1299`)；
        *   当前这一次 `_build_conversation_history` 调用中，直接将 `history` 置为空列表，确保本轮请求只携带系统提示词、必要的 RAG 注入和当前用户消息。
    *   保留 `WeightedMemoryManager` 原有的加权修剪与长期记忆机制：`clear_memory(mode="short")` 只会清空 `short_term_memory` 及其对应的 `*_short.json` 文件，不会影响长周期统计数据、画像和重要提示语 (`memory/weighted_memory_manager.py:532-547`)。
*   **行为与用户体验**:
    *   从用户视角看，当对话历史累积到极大规模时（约万级字符），系统会在“感觉你记得很多东西”的同时，自动丢弃最旧的一批短期对话，将后续回复更多地基于当前轮及长期画像进行生成；
    *   若用户在桌宠或前端点击“清空历史”，仍然通过显式调用 `/api/v1/clear_memory` 或前端 `clearHistory` 来触发记忆清理，两者相互独立：显式操作优先用于“手动重置会话”，自动清理则是全局的安全阈值保护。
*   **验证与回归**:
    *   新增 `test_auto_clear_history_on_overflow`，构造字符总量远超 `10000` 的伪历史，通过注入自定义 `DummyMemoryManager` 验证：
        *   `ChatAgent._build_conversation_history` 会调用 `clear_memory(mode="short")`；
        *   返回给 LLM 的 `messages` 中不再包含任何旧的 `user/assistant` 历史，仅保留系统提示和当前输入 (`tests/test_context_overflow.py:47-110`)；
    *   结合此前的本地上下文截断逻辑（约束在 ~1800 字符内）和 C++ 调度器中的友好错误文案，本地对话在长时间使用后仍能保持稳定，不再出现“历史太长导致模型直接报 context window 错误”的体验。
*   **经验总结**:
    *   对话系统的“历史保留策略”需要同时考虑用户体验与模型约束：一方面要尽量记住关键信息并沉淀到长期记忆，另一方面需要在短期记忆达到一定规模后果断清理，避免无限累积；
    *   自动化的“粗粒度安全阈值”（如总字符数）可以与精细化的“按重要度/时间衰减修剪”共存：前者负责兜底防护，后者负责在安全范围内尽量保留有价值的上下文。

### 10.7 记忆管理系统全面重构与修复 (2025-12-14)

*   **问题描述**: 用户反馈记忆文件出现大量空白文件、普通闲聊（如"你好"）被错误归入长期记忆、长期/权重/短期记忆内容大量重复、以及前端删除功能不完善。
*   **原因分析**:
    *   **空白文件**: `add_memory` 未对空内容进行校验。
    *   **记忆泛滥**: 进入长期记忆和权重记忆的阈值过低。
    *   **重复存储**: 旧逻辑未严格区分短期缓存与长期归档，导致所有交互都被持久化。
    *   **前端缺失**: 前端删除按钮缺乏确认机制和模式选择。
*   **解决方案**:
    *   **严格阈值**: 大幅提升准入标准。长期记忆需 `is_important=True` 或 (`len > 50` 且 `weight > 6.0`)。
    *   **自动清理**: 在 `reclassify_all_memories` 中引入清理逻辑，系统启动时自动移除低质量记忆并去重。
    *   **分层存储**: 明确区分短期记忆（`short_term/`）、长期记忆（`long_term/`）、权重记忆（`weighted/`）和 NSFW 记忆（`nsfw/`）。
    *   **NSFW 隔离**: 新增 `nsfw` 类别，存储于独立目录，且仅允许本地 LLM 通过 `local` 提示词访问。
    *   **前端增强**: 实现了分级删除确认窗口。
*   **验证结果**: 记忆文件体积显著减小，内容质量提升，重复率降低，且隐私内容得到隔离。

### QR-20260718-MEM-CONCURRENCY WeightedMemoryManager 异步保存 dict 迭代崩溃且 ERROR 未进入 errors_*.json (2026-07-18)
*   **问题描述**: [21:16:42] [ERROR] [memory.weighted_memory_manager] 异步保存循环异常: dictionary changed size during iteration。该 ERROR 未出现在 errors_20260718.json 中。
*   **复现步骤**:
    1. 运行项目触发短期记忆修剪 → _preserve_removed_to_weighted 向 weighted_memories 写入
    2. 同时异步保存线程迭代 weighted_memories.values()
    3. 保存循环抛 RuntimeError
    4. 查看 errors_20260718.json 无该 ERROR
*   **预期行为**:
    1. 异步保存循环在并发写入下不抛 RuntimeError
    2. 所有 ERROR 都应被 ErrorCollectorHandler 收集并写入 errors_YYYYMMDD.json
*   **实际行为**:
    1. 并发写入触发 RuntimeError，保存循环进入 60 秒退避
    2. memory.weighted_memory_manager 的 ERROR 未进入 errors_*.json
*   **根因**:
    1. safe_save_all 在锁外调用 _save_weighted_data_locked 等带 _locked 后缀的方法
    2. 三个迭代点直接迭代 weighted_memories.values() 未做 list 快照
    3. runtime_ops.py:193 误用 manager.lock，与生产环境 _rw_lock 写锁互不相干
    4. weighted_memory_manager.py 用 logging.getLogger 而非项目 get_logger，未挂 SafeQueueHandler
*   **修复方案**:
    1. weighted_memory_manager.py 三处 logger 改用 get_logger(__name__)
    2. io_ops.py / readable_ops.py / record_ops.py 三个迭代点改用 list 快照
    3. runtime_ops.py:193 改用 get_read_lock(manager) 并补 list 快照
    4. runtime_ops.py 顶部 import 补齐 get_read_lock
*   **验证**:
    1. `ruff check 5 个修改文件全部通过`
    2. `verify_weighted_memory_concurrency_fix.py 5 项检查全部通过，并发 200 轮无 RuntimeError`

### QR-20260719-NIGHTLY-TIMEOUT 夜间异步任务 600s 超时误杀日记生成，error_collector 合成 RuntimeError 误报 (2026-07-19)
*   **问题描述**: errors_20260719.json 报告 memory/nightly/task_runner.py:62 抛出 RuntimeError，但 error_message 在冒号后为空、traceback 为 'NoneType: None\n'，无法定位真实异常。同时夜间任务在 02:41:51 报错后，日记生成、明日计划等后续步骤均未执行。
*   **复现步骤**:
    1. 服务正常运行至 02:31:51 触发夜间任务
    2. PeopleProfileExtractor 串行处理 28 批次人物档案提取，耗时 9 分 11 秒
    3. 02:41:51 future.result(timeout=600) 超时抛出 concurrent.futures.TimeoutError
    4. TimeoutError 落入通用 except Exception 分支，logger.error 未传 exc_info=True
    5. error_collector._schedule_report 因 record.exc_info 为 None，兜底执行 RuntimeError(record.getMessage()) 合成异常上报
*   **预期行为**:
    1. 夜间任务在消息量大时不应被 600s 超时误杀，应放宽到能覆盖最慢场景的阈值
    2. TimeoutError 应被单独捕获并明确标注为超时，与真实业务异常区分
    3. logger.error 必须带 exc_info=True，让 error_collector 拿到真实异常类型与栈
    4. errors_*.json 中的 error_code 应反映真实异常类型，traceback 不应为空
*   **实际行为**:
    1. future.result(timeout=600) 在人物档案提取慢时超时，后续日记生成步骤被误杀
    2. TimeoutError 落入通用 except Exception 分支，error_code 误报为 RuntimeError
    3. logger.error 未传 exc_info=True，traceback 显示 'NoneType: None\n'
    4. error_message 在冒号后为空（record.getMessage() 返回空字符串，因 f-string 已被 logger 拼接）
*   **根因**:
    1. NIGHTLY_TASK_TIMEOUT_SECONDS 缺失，硬编码 600s 不足以覆盖 250+ 条消息/28 批次人物档案提取场景
    2. Python 3.10.11 下 concurrent.futures.TimeoutError 与内置 TimeoutError 不是同一个类，未显式捕获其 TimeoutError 时会落入通用 except Exception 分支
    3. logger.error 调用未传 exc_info=True（违反 CODING_GUIDE.md 6.2 节规范）
    4. error_collector._schedule_report 的兜底逻辑 exc = record.exc_info[1] if record.exc_info and record.exc_info[1] else RuntimeError(record.getMessage()) 在 exc_info 缺失时合成 RuntimeError，导致 error_code 误报
*   **修复方案**:
    1. memory/nightly/task_runner.py 新增类常量 NIGHTLY_TASK_TIMEOUT_SECONDS=1800
    2. 显式 import concurrent.futures，新增 except concurrent.futures.TimeoutError as exc 分支并放在通用 except 之前
    3. 两个 except 分支的 logger.error 均带 exc_info=True，错误消息含 user_id、exc_type、exc 字段
    4. 超时后返回空 dict 且不调用 future.cancel()，避免半成品数据
*   **验证**:
    1. `venv_core/Scripts/python.exe -m ruff check memory/nightly/task_runner.py`
    2. `venv_core/Scripts/python.exe -m py_compile memory/nightly/task_runner.py`
    3. `venv_core/Scripts/python.exe tests/scripts/verify_nightly_task_timeout_fix.py`
    4. `检查 errors_*.json 不再出现空 traceback 的 RuntimeError 误报（需观察下次夜间任务）`

### QR-20260720-SHORT-TERM-MESS Aveline short_term 目录混乱：临时文件泄漏 + 多代命名格式并存 + 跨 scope 污染 (2026-07-20)
*   **问题描述**: companion_data/aveline_data/memories/short_term 目录严重混乱：24 个文件堆积（含 12 个 .tmp_* 临时文件约 24MB、4 代历史命名格式并存、跨 scope 文件污染、测试文件混入生产）。同时代码从 __persona__ 格式切换到 __scope__ 格式后，旧的 4382 条历史记录被'孤立'，新格式只有 60 条。今天还误删了 Aveline chat_history，需要从 short_term 恢复。
*   **复现步骤**:
    1. 运行 inspect_short_term.py 列出 short_term 目录文件清单
    2. 发现 12 个 .tmp_* 临时文件残留，时间跨度 2026-06-24 到 2026-07-19
    3. 发现 4 代命名格式并存：aveline_short.json（第1代）→ default_user_short.json（第2代）→ private_xxx_short.json（第3代）→ __persona__（第4代 4382 条）→ __scope__（第5代 60 条）
    4. 发现 ling_short.json 错位在 aveline_data 目录
    5. 发现 peer_*__scope__dual_role_short.json 错位在 aveline_data 目录
    6. 发现测试文件 mem_style_smoke_user_short.json 混入生产
    7. 从合并后的 short_term 提取今天的 14 条记录写回 chat_history JSONL
    8. 发现 ChatHistoryStore 把 core_ling 对话错误写到 aveline_data 而非 ling_data
*   **预期行为**:
    1. short_term 目录只有当前代码使用的 __scope__ 格式文件
    2. 跨 scope 文件归位到对应 scope 目录
    3. 测试文件不污染生产环境
    4. 今天的 chat_history 从 short_term 完整恢复
    5. core_ling 对话应该写到 ling_data 而不是 aveline_data
*   **实际行为**:
    1. 12 个 .tmp_* 临时文件堆积近 1 个月（约 24MB 垃圾）
    2. 4 代历史格式文件并存，老格式数据被孤立
    3. ling_short.json 和 peer_*__scope__dual_role_short.json 错位在 aveline_data 目录
    4. 测试文件 mem_style_smoke_user_short.json 残留在生产环境
    5. ChatHistoryStore 把 core_ling 对话错误写到 aveline_data/QQ对话/
*   **根因**:
    1. safe_json_dump 在 _retry_os_replace 抛非 PermissionError 异常时不清理临时文件
    2. 历史多次重构命名规则，但老文件从未迁移
    3. ChatHistoryStore 写入时缺少跨 scope 校验
    4. resolve_data_scope_from_conversation_id 对 core_ling 这种 persona slug 识别有 bug：只匹配 __persona__ling 不匹配 __persona__core_ling
    5. 测试脚本直接写生产目录，未做隔离
*   **修复方案**:
    1. 删除 12 个 .tmp_* 临时文件和 mem_style_smoke_user_short.json（共 23.89MB）
    2. ling_short.json 移到 ling_data/memories/short_term/
    3. peer_*__scope__dual_role_short.json 移到 dual_role/memories/short_term/
    4. 按 id 去重合并 5 个老格式文件到 __scope__aveline_short.json，记录数 60→4550
    5. 老格式文件备份到 short_term_legacy_backup/
    6. 从 short_term 恢复 14 条今天的记录到 chat_history JSONL（13 条成功写入，1 条 hidden thinking 跳过）
    7. 手动把 core_ling.jsonl 从 aveline_data 移到 ling_data/QQ对话/
    8. 重建 aveline_data 和 ling_data 的 index.json
*   **验证**:
    1. `运行 restore_today_chat_history.py 验证恢复结果`
    2. `最终目录结构：aveline_data/chat_history/2026/07/20/ 下 2 个 jsonl（5 行 + 1 行），ling_data/chat_history/2026/07/20/ 下 2 个 jsonl（7 行 + 2 行）`

### QR-20260720-DATA-PATHS-CORE-PERSONA data_paths.py resolve_data_scope_from_conversation_id 对 core_ling/core_aveline persona slug 识别 bug (2026-07-20)
*   **问题描述**: ChatHistoryStore 把 conversation_id='private_10001__persona__core_ling' 的对话错误写到 aveline_data 目录而不是 ling_data。原因是 resolve_data_scope_from_conversation_id 没识别 core_ling/core_aveline 这类 persona slug。
*   **复现步骤**:
    1. 运行 restore_today_chat_history.py 从 short_term 恢复今天的 chat_history
    2. 发现 core_ling 对话被错误写到 aveline_data/chat_history/2026/07/20/主线对话/
    3. 阅读 core/utils/data_paths.py:75-89 的 resolve_data_scope_from_conversation_id
    4. 第 75-82 行只匹配 __persona__ling 不匹配 __persona__core_ling
    5. 第 83-89 行只匹配 __persona__aveline 不匹配 __persona__core_aveline
    6. 导致 __persona__core_ling fallthrough 到第 94 行的通用 __persona__ 分支，调用 _resolve_scope_from_active_persona() 返回当前 persona 的 scope（aveline）
*   **预期行为**:
    1. private_10001__persona__core_ling → ling
    2. private_10001__persona__core_aveline → aveline
    3. peer_private_10001__persona__core_ling → dual_role
    4. peer_private_10001__persona__core_aveline → dual_role
*   **实际行为**:
    1. private_10001__persona__core_ling → aveline（错误）
    2. private_10001__persona__core_aveline → aveline（碰巧正确，但走错分支）
*   **根因**:
    1. 第 75-82 行匹配条件只写了 __persona__ling，没写 __persona__core_ling
    2. 第 83-89 行匹配条件只写了 __persona__aveline，没写 __persona__core_aveline
    3. core_ling 和 core_aveline 是 persona 文件名（core_ling.json、core_aveline.json），常作为 persona token 出现在 conversation_id 中
*   **修复方案**:
    1. 第 75-82 行新增 __persona__core_ling 和 __core_ling 两个匹配条件
    2. 第 83-89 行新增 __persona__core_aveline 和 __core_aveline 两个匹配条件
*   **验证**:
    1. `10 个测试用例全部 PASS，覆盖 core_ling/core_aveline/peer_*/__scope__ 等各种 conversation_id 格式`

### QR-20260720-02 Aveline 全量历史聊天记录恢复 (2026-07-20)
*   **问题描述**: 用户要求恢复 Aveline 的全部历史聊天记录，但第一版恢复脚本只恢复了当天 14 条消息，遗漏了从 2026-05-26 开始的全部历史对话；同时需要确保Ling目录不被恢复。
*   **复现步骤**:
    1. 前序会话误删了 Aveline 角色的全部历史聊天记录
    2. 用户提出从 short_term 全量恢复 Aveline 历史聊天
    3. 第一版脚本 restore_today_chat_history.py 只恢复当天 14 条
    4. 用户明确指出需要恢复全部 Aveline 历史，Ling不需要恢复
*   **预期行为**:
    1. 从 short_term 中提取所有 Aveline 角色相关的对话消息（含 QQ 对话和主线对话）
    2. 全部回写到 companion_data/aveline_data/chat_history/ 下，按日期/lane/conversation_id 组织
    3. 时间跨度应覆盖 2026-05-26 ~ 2026-07-20
    4. Ling companion_data/ling_data/chat_history 目录保持原样未被修改
*   **实际行为**:
    1. 第一版只恢复 14 条当天消息，遗漏近 2 个月历史
    2. 第二版 restore_all_aveline_chat_history.py 全量恢复 4404 条消息
    3. 验证显示 64 个 jsonl 文件、4400 条消息、时间跨度 2026-05-26 ~ 2026-07-20
    4. Ling目录未被修改（2 月份 13 个文件 + 7/20 的 2 个文件保持原样）
*   **根因**:
    1. 对用户意图理解偏差：把『全部历史』误解为『今天的对话』
    2. 恢复脚本未扫描全部 short_term 数据，只过滤了当天记录
*   **修复方案**:
    1. 新建 analyze_aveline_short_term_all.py 全量扫描 short_term 目录统计可恢复消息
    2. 新建 analyze_empty_cid.py 解决 cid 为空记录的反解（4381 条全部能从 message_id 反解）
    3. 新建 restore_all_aveline_chat_history.py：过滤 hidden/空 content/非对话 role；通过 conversation_id 或 message_id 反解 cid；排除 ling 相关对话
    4. 运行前备份 chat_history 到 chat_history_backup_before_full_restore/backup_20260720_183123/
    5. 新建 verify_aveline_restore.py 验证恢复结果
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\verify_aveline_restore.py`
    2. `venv_core\Scripts\python.exe -c "from pathlib import Path; files = list(Path('companion_data/ling_data/chat_history').rglob('*.jsonl')); print(len(files))"`

### QR-20260720-03 QQ Official 数据从 Aveline 隔离 (2026-07-20)
*   **问题描述**: companion_data/aveline_data/memories/short_term 下存在 private_B78B23BF9C7F51857AEB19891AE32C1D__scope__aveline_short.json 文件，里面存的是 QQ 官方机器人（Coco，qq_official_2）的对话，不属于 Aveline。同时 aveline_data/memories/weighted 下还有 8 个同用户的 weighted 文件（含子目录）和 25 个完全无关的测试/默认文件。
*   **复现步骤**:
    1. 用户发现 aveline_data 下有 B78B23BF 开头的 short_term 文件
    2. 查看内容发现 cid 是 private_B78B23BF9C7F51857AEB19891AE32C1D__persona__qq_official_2
    3. 追踪 resolve_data_scope_from_conversation_id：cid 含 __persona__ 但无 ling/aveline 关键字，fallthrough 到 _resolve_scope_from_active_persona()
    4. active persona 当时是 Aveline，所以 scope 被错判为 aveline
    5. 数据被写入 aveline_data/memories/ 下
*   **预期行为**:
    1. QQ Official 角色（小鹿、Coco）的数据应该独立存放，不混入 aveline_data
    2. 每个 QQ Official 角色有独立的数据目录（按 persona 名字命名）
    3. 代码层支持新 scope，以后 qq_official_* 这种 cid 不会再被错归到 aveline
    4. aveline_data 下不再保留 qq_group/mobile_user/default/测试 等无关文件
*   **实际行为**:
    1. B78B23BF 用户的 9 个文件（1 short_term + 8 weighted）被错放在 aveline_data 下
    2. aveline_data/memories/weighted 下还堆积 25 个无关文件
    3. resolve_data_scope_from_conversation_id 没有 qq_official 专门分支
    4. _VALID_SCOPES 只有 4 个固定值，没有为 QQ Official 角色预留 scope
*   **根因**:
    1. resolve_data_scope_from_conversation_id 的通用 __persona__ fallback 走 active_persona，对未知 persona slug 会落到当前 active persona 的 scope
    2. _VALID_SCOPES 没有为 QQ Official 角色预留 scope，未考虑 QQ 官方机器人独立数据隔离需求
    3. short_term 和 weighted 子目录历史遗留测试文件未定期清理
*   **修复方案**:
    1. persona 文件改名：QQ_Official_1.json → Xiaolu.json（小鹿）、QQ_Official_2.json → Yeye.json（Coco）
    2. 更新 config_official_bot1/bot2.json 的 persona_filename 引用
    3. 新建 companion_data/xiaolu_data/ 和 yeye_data/ 目录结构
    4. 迁移Coco 9 个文件到 yeye_data（文件名 __scope__aveline 改为 __scope__yeye）
    5. core/utils/data_paths.py：_VALID_SCOPES 新增 xiaolu、yeye
    6. 新增 _QQ_OFFICIAL_SLUG_TO_SCOPE 映射表，兼容旧 slug（qq_official_1/2）和新 slug（xiaolu/yeye）
    7. resolve_data_scope_from_conversation_id 新增 qq_official/xiaolu/yeye 匹配分支
    8. 新增 get_xiaolu_data_dir()、get_yeye_data_dir()，扩展 get_role_data_dir、get_all_chat_history_dirs、_iter_existing_chat_history_roots
    9. 新增 _scope_to_chat_history_root 统一管理 scope → 目录映射
    10. 清理 25 个无关文件（备份到 _quarantine/ 后删除）：4 qq_group + 1 mobile_user + 8 default + 12 test
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\verify_qq_official_scope.py`
    2. `venv_core\Scripts\python.exe tests\scripts\verify_qq_official_isolation.py`

### Q20260803-01 ling 角色每日总结记忆误写入 aveline_data 目录 (2026-08-03)
*   **问题描述**: companion_data/aveline_data/memories/short_term/ling_short.json 文件内容是 ling 角色的每日总结（source='ling'），却出现在 aveline_data 目录下，角色数据隔离被破坏。
*   **复现步骤**:
    1. 查看 aveline_data/memories/short_term/ling_short.json 内容，确认 source='ling'
    2. 追踪 journal_helpers.append_weighted_memory：source='ling' 时 target_conversation_id='ling'
    3. 追踪 get_weighted_memory_manager('ling') → resolve_memory_user_id('ling') → resolve_data_scope_from_conversation_id('ling')
    4. 发现裸 'ling' 不匹配任何 conversation_id 模式，fallback 到 default='aveline'
*   **预期行为**:
    1. source='ling' 的日记总结应存入 ling_data/memories/short_term/ling_short.json
    2. source='aveline' 的日记总结应存入 aveline_data/memories/short_term/aveline_short.json
*   **实际行为**:
    1. source='ling' 的日记总结存入了 aveline_data/memories/short_term/ling_short.json
    2. scope 解析错误：user_id='ling' 但 scope='aveline'，文件名与目录不匹配
*   **根因**:
    1. resolve_data_scope_from_conversation_id 只识别带 __scope__ / __persona__ / __circle__ / peer_ 前缀的 conversation_id，不识别裸 scope 名
    2. append_weighted_memory 直接用裸 source 当 conversation_id，没有转换为规范格式
*   **修复方案**:
    1. 在 resolve_data_scope_from_conversation_id 末尾增加对裸 scope 名（ling/aveline/active_care/wang_ling 等）的识别
    2. 在 _migrate_misplaced_memory_files 增加对裸 'ling' 文件名的识别和迁移规则
    3. 手动迁移 3 个历史文件到 ling_data
*   **验证**:
    1. `python -c "from core.utils.data_paths import resolve_data_scope_from_conversation_id; print(resolve_data_scope_from_conversation_id('ling'))" → 'ling'`
    2. `aveline_data/memories 下 glob ling_* 无结果`
    3. `ling_data/memories 下有 ling_short.json、ling_weighted.json、weighted/diary/ling_weighted.json`

### MEM-021 short_term 记忆文件膨胀到几千条,trim 逻辑完全失效 (2026-08-04)
*   **问题描述**: short_term 文件本应限制在 60 条(short_term_capacity),实际膨胀到 3114 条(peer_aveline) / 1879 条(peer_ling) / 812 条(aveline_qq_master),每次全量重写 IO 开销巨大(4MB 文件重写 100ms+)
*   **复现步骤**:
    1. 运行 `tests/scripts/memory/_tmp_stats.py` 统计所有 short_term 文件大小和记录数
    2. 发现 peer_aveline_short.json 有 3114 条 / 4MB,远超 60 条容量上限
    3. 运行 `tests/scripts/memory/_tmp_analyze.py` 分析时间跨度和类别分布
    4. 发现 peer_aveline/peer_ling 的消息 100% is_important=True
    5. 查看 `memory/core/distillation.py` 的 trim 逻辑,发现 important 消息全部保留不占配额
    6. 查看 `memory/core/lifecycle_ops.py` 的 load_memory,发现加载后不调用 trim
    7. 查看 `memory/core/manager_init_ops.py`,发现 trim 延迟 30 秒(`_trim_delay=30.0`)
*   **预期行为**:
    1. s
    2. h
    3. o
    4. r
    5. t
    6. _
    7. t
    8. e
    9. r
    10. m
    11. 文
    12. 件
    13. 记
    14. 录
    15. 数
    16. 不
    17. 超
    18. 过
    19. s
    20. h
    21. o
    22. r
    23. t
    24. _
    25. t
    26. e
    27. r
    28. m
    29. _
    30. c
    31. a
    32. p
    33. a
    34. c
    35. i
    36. t
    37. y
    38. (
    39. 6
    40. 0
    41. 条
    42. )
    43. ,
    44. t
    45. r
    46. i
    47. m
    48. 逻
    49. 辑
    50. 在
    51. 加
    52. 载
    53. 和
    54. 添
    55. 加
    56. 时
    57. 都
    58. 生
    59. 效
*   **实际行为**:
    1. 三
    2. 个
    3. b
    4. u
    5. g
    6. 叠
    7. 加
    8. 导
    9. 致
    10. s
    11. h
    12. o
    13. r
    14. t
    15. _
    16. t
    17. e
    18. r
    19. m
    20. 膨
    21. 胀
    22. :
    23. l
    24. o
    25. a
    26. d
    27. _
    28. m
    29. e
    30. m
    31. o
    32. r
    33. y
    34. 不
    35. t
    36. r
    37. i
    38. m
    39. +
    40. b
    41. a
    42. c
    43. k
    44. f
    45. i
    46. l
    47. l
    48. 追
    49. 加
    50. +
    51. t
    52. r
    53. i
    54. m
    55. 延
    56. 迟
    57. 3
    58. 0
    59. s
    60. 可
    61. 能
    62. 没
    63. 执
    64. 行
    65. +
    66. i
    67. m
    68. p
    69. o
    70. r
    71. t
    72. a
    73. n
    74. t
    75. 消
    76. 息
    77. 不
    78. 占
    79. 配
    80. 额
*   **根因**:
    1. `lifecycle_ops.py:218-275` 的 `load_memory` 加载全部记录后不调用 trim
    2. `distillation.py:92-94` 的 trim 逻辑对 important 消息全部保留(`remaining_quota = max(0, 60 - important_count)`),当 100% important 时配额为 0
    3. `proactive_messaging.py:327,345` 和 `message_dispatcher.py:245` 把所有主动关怀消息标记为 `is_important=True`
    4. `manager_init_ops.py:132` 的 `_trim_delay=30.0` 导致 trim 延迟 30 秒,进程可能在延迟期内退出
*   **修复方案**:
    1. `lifecycle_ops.py`: load_memory 末尾调用 `_trim_short_term_memory()`
    2. `distillation.py`: trim 改为 important/普通 各占 50% 配额,删除冗余的 `_select_meta_by_score`
    3. `proactive_messaging.py` + `message_dispatcher.py`: 去掉 3 处 `is_important=True`
    4. 运行 `trim_bloated_short_term.py` 裁剪已膨胀文件(5860 条 -> 488 条)
*   **验证**:
    1. ``trim_bloated_short_term.py --dry-run`: 15 个文件 0 需裁剪`
    2. ``cleanup_short_term_non_dialogue.py --dry-run --quiet`: 11 个文件 0 脏数据`

### MEM-022 sensitive 记忆进入 short_term 可能通过上下文注入泄漏到非敏感场景 (2026-08-04)
*   **问题描述**: sensitive 类别记忆通过 _index_new_memory 进入 short_term_memory,而 short_term 是上下文注入的数据源,可能导致敏感内容泄漏到非敏感场景的对话上下文中
*   **复现步骤**:
    1. 查看 `storage.py:549-553` 的 is_sensitive 判断逻辑
    2. 确认 `_NON_DIALOGUE_CATEGORIES` 未包含 sensitive
    3. 查看 `retrieval_ops.py:73` 的 exclude_sensitive=True 过滤只作用于检索,不作用于上下文注入
*   **预期行为**:
    1. s
    2. e
    3. n
    4. s
    5. i
    6. t
    7. i
    8. v
    9. e
    10. 记
    11. 忆
    12. 只
    13. 进
    14. w
    15. e
    16. i
    17. g
    18. h
    19. t
    20. e
    21. d
    22. _
    23. m
    24. e
    25. m
    26. o
    27. r
    28. i
    29. e
    30. s
    31. (
    32. 用
    33. 于
    34. 检
    35. 索
    36. 时
    37. 按
    38. 需
    39. 调
    40. 用
    41. )
    42. ,
    43. 不
    44. 进
    45. s
    46. h
    47. o
    48. r
    49. t
    50. _
    51. t
    52. e
    53. r
    54. m
    55. (
    56. 用
    57. 于
    58. 上
    59. 下
    60. 文
    61. 注
    62. 入
    63. )
*   **实际行为**:
    1. s
    2. e
    3. n
    4. s
    5. i
    6. t
    7. i
    8. v
    9. e
    10. 记
    11. 忆
    12. 同
    13. 时
    14. 进
    15. 入
    16. s
    17. h
    18. o
    19. r
    20. t
    21. _
    22. t
    23. e
    24. r
    25. m
    26. 和
    27. w
    28. e
    29. i
    30. g
    31. h
    32. t
    33. e
    34. d
    35. _
    36. m
    37. e
    38. m
    39. o
    40. r
    41. i
    42. e
    43. s
    44. ,
    45. s
    46. h
    47. o
    48. r
    49. t
    50. _
    51. t
    52. e
    53. r
    54. m
    55. 会
    56. 被
    57. 注
    58. 入
    59. 到
    60. 下
    61. 次
    62. 对
    63. 话
    64. 上
    65. 下
    66. 文
*   **根因**:
    1. `storage.py` 的 `_NON_DIALOGUE_CATEGORIES` 只包含 thinking/profile/context_injection/persona_prompt,遗漏了 sensitive
*   **修复方案**:
    1. `storage.py`: `_NON_DIALOGUE_CATEGORIES` 新增 sensitive
    2. `manager_init_ops.py`: 不再创建 sensitive 空目录
    3. 清理已落盘的 4 条 sensitive 脏数据 + 5 个空 sensitive 目录
*   **验证**:
    1. ``cleanup_short_term_non_dialogue.py --dry-run --quiet`: 0 脏数据`

### MEM-023 日记(diary)100% 占满 short_term 对话空间,导致无对话记录 (2026-08-04)
*   **问题描述**: aveline_short.json 被 13 条日记 100% 占满(7-21 到 8-03),没有任何对话空间;日记 role=journal 不是对话角色,注入到上下文会让 LLM 困惑
*   **复现步骤**:
    1. 查看 aveline_short.json,发现 13/13 条全是日记(category=diary, source=journal, role=journal)
    2. 查看 journal_helpers.py:228 的 append_weighted_memory,确认日记调用 add_memory 同时写入 short_term 和 weighted_memories
    3. 查看 weighted/diary/aveline_weighted.json,确认日记有 34 条完整备份
*   **预期行为**:
    1. s
    2. h
    3. o
    4. r
    5. t
    6. _
    7. t
    8. e
    9. r
    10. m
    11. 只
    12. 包
    13. 含
    14. u
    15. s
    16. e
    17. r
    18. /
    19. a
    20. s
    21. s
    22. i
    23. s
    24. t
    25. a
    26. n
    27. t
    28. 的
    29. 对
    30. 话
    31. 内
    32. 容
    33. ,
    34. 日
    35. 记
    36. 通
    37. 过
    38. r
    39. e
    40. t
    41. r
    42. i
    43. e
    44. v
    45. a
    46. l
    47. 检
    48. 索
    49. w
    50. e
    51. i
    52. g
    53. h
    54. t
    55. e
    56. d
    57. _
    58. m
    59. e
    60. m
    61. o
    62. r
    63. i
    64. e
    65. s
    66. 按
    67. 需
    68. 使
    69. 用
*   **实际行为**:
    1. 日
    2. 记
    3. 同
    4. 时
    5. 进
    6. 入
    7. s
    8. h
    9. o
    10. r
    11. t
    12. _
    13. t
    14. e
    15. r
    16. m
    17. 和
    18. w
    19. e
    20. i
    21. g
    22. h
    23. t
    24. e
    25. d
    26. _
    27. m
    28. e
    29. m
    30. o
    31. r
    32. i
    33. e
    34. s
    35. ,
    36. a
    37. v
    38. e
    39. l
    40. i
    41. n
    42. e
    43. _
    44. s
    45. h
    46. o
    47. r
    48. t
    49. .
    50. j
    51. s
    52. o
    53. n
    54. 被
    55. 日
    56. 记
    57. 1
    58. 0
    59. 0
    60. %
    61. 占
    62. 满
    63. ,
    64. 没
    65. 有
    66. 对
    67. 话
    68. 空
    69. 间
*   **根因**:
    1. `storage.py` 的 `_NON_DIALOGUE_CATEGORIES` 未包含 diary
    2. `journal_helpers.py` 的日记写入逻辑调用 add_memory,默认进 short_term
*   **修复方案**:
    1. `storage.py`: `_NON_DIALOGUE_CATEGORIES` 新增 diary
    2. 清理 aveline_short.json 的 13 条日记 + ling_short.json 的 1 条日记
*   **验证**:
    1. ``cleanup_short_term_non_dialogue.py --dry-run --quiet`: 0 脏数据`

### MEM-024 short_term 混入非对话记录且 persona 与 scope 多套文件并存 (2026-08-24)
*   **问题描述**: 短期记忆文件约 100 KiB 到 227 KiB，包含历史摘要、系统注入和重复派生字段；Ling同时存在多份 persona 与 scope 文件。
*   **复现步骤**:
    1. 扫描 companion_data 下所有 memories/short_term/*_short.json
    2. 统计 memory_type、role、source、category、记录数和文件体积
    3. 对照角色 chat_history 检查旧 persona 对话是否已有完整副本
*   **预期行为**:
    1. short_term 只含近期 user/assistant 对话
    2. 同一角色按 scope 使用统一短期记忆池
    3. 短期文件同时受记录数和体积约束
*   **实际行为**:
    1. event_summary、system_summary、workspace 等非对话记录进入 short_term
    2. 落盘保留完整记忆对象，60 条也可膨胀到 200 KiB 以上
    3. 解析异常静默回退 raw ID，遗留 persona 与 scope 文件并存
*   **根因**:
    1. _index_new_memory 仅按少数 category 排除
    2. build_short_term_disk_records 只移除 embedding
    3. get_weighted_memory_manager 捕获 scope 解析异常并回退 raw_uid
*   **修复方案**:
    1. 新增统一短期对话判定并在写入和加载两侧使用
    2. 紧凑落盘并限制为 64 KiB
    3. 强制 scope ID 解析，删除Ling已被 chat_history 覆盖的 persona 旧文件
*   **验证**:
    1. `verify_short_term_cleanup.py --check-data: 通过`
    2. `Ling persona 245/245 条在 chat_history 命中，删除后仅剩两份 scope 文件`

### MEM-025 weighted memory 跨作用域混存且派生索引长期膨胀 (2026-08-24)
*   **问题描述**: Aveline 与Ling的 weighted memory 中同时存在 scope、旧 persona、Telegram、测试和错放 dual-role manager；emotion_memory_map 大部分引用已失效，sensitive 分片保存后又无法加载。
*   **复现步骤**:
    1. 扫描两个角色 memories/weighted 下全部 *_weighted.json，按文件名逻辑 manager、category 和 scope 统计
    2. 跨分片统计记忆 ID、event_ref、emotion_memory_map 引用和 Chat/chat 主题
    3. 用 chat_history 验证 Aveline 与Ling事件引用，并检查 dual-role 正确目录
*   **预期行为**:
    1. 每个角色只保留当前 scope manager 与必要的角色级日记 manager
    2. Telegram、测试、思考缓存和运行时推理正文不进入 weighted
    3. 敏感记忆能随其他分类正常加载，所有派生索引仅引用有效记录
    4. dual-role 记忆位于 dual_role 数据域而非 Aveline 目录
*   **实际行为**:
    1. Aveline 83 个文件、4911 条、约 14.2 MiB，其中 3718 条 dual-role 记忆错放；Ling 29 个文件、297 条、约 1.13 MiB
    2. 两角色 emotion_memory_map 分别有约 88.5% 和 94.4% 的引用失效
    3. sensitive 目录被保存逻辑写入，却被加载和清理逻辑跳过
    4. weighted 内存在 thinking、persona_prompt 和大量 reasoning_content 等运行时字段
*   **根因**:
    1. 派生索引被当成持久真源增量维护，删除后没有统一重建
    2. sensitive 在读写路径中的目录排除规则不一致
    3. weighted 持久类别和落盘字段缺少明确边界
    4. 旧 persona 与 dual-role 身份升级后没有正式迁移工具
*   **修复方案**:
    1. 加载与批量删除后从有效记录重建全部派生索引
    2. 统一 sensitive 分片的加载、保存和清理规则
    3. 限制 weighted 持久类别并压缩运行时、推理和派生字段
    4. 按 scope 合并角色数据、迁移 dual-role、删除 TG/测试空壳与无正文孤立引用
*   **验证**:
    1. `verify_weighted_cleanup.py 验证 manager 拓扑、分片分类、重复、事件引用、敏感类型、派生字段和索引全部通过`
    2. `Aveline 缩减至 33 个文件、1120 条、1.53 MiB；Ling缩减至 18 个文件、276 条、0.375 MiB`
    3. `两组 dual-role 合并为 2506 条，维护脚本二次 dry-run 为幂等`

### MEM-026 自动重分类删除记录后 emotion 索引再次失效 (2026-08-24)
*   **问题描述**: 离线清理后的 weighted memory 在服务重启并执行自动重分类后，emotion_memory_map 又引用已淘汰的记忆 ID。
*   **复现步骤**:
    1. 清理 Aveline 与Ling weighted memory 并运行离线验证
    2. 启动主服务，等待 shared scope manager 完成加载和 reclassify_all_memories
    3. 再次运行 verify_weighted_cleanup.py 检查磁盘派生索引
*   **预期行为**:
    1. 任何新增、删除、重分类完成后，全部派生索引都只引用最终有效记录
    2. 重启和异步保存不能重新制造旧 manager 或测试分片
*   **实际行为**:
    1. 自动重分类淘汰低权重记录后 category/topic 已更新，但 emotion_memory_map 仍保留被删 ID
    2. 运行旧 test_memory_deduplication 时产生 test_user_dedup 文件，污染 Aveline weighted 目录
*   **根因**:
    1. maintenance_ops.py 在重分类末尾维护了一套不完整的手工索引重建逻辑
    2. 旧单测路径常量与当前按角色路由的真实存储目录不一致
*   **修复方案**:
    1. 重分类末尾调用统一索引重建函数
    2. 删除测试分片并在专项验证中直接检查 Aveline、Ling和 dual-role 的真实数据目录
    3. 维护脚本用 message_id 区分不同时间的相同短句
*   **验证**:
    1. `干净重启后专项验证通过，emotion 索引无失效 ID`
    2. `主服务健康，Aveline 与Ling QQ 适配器均连接成功`
    3. `最终 dry-run 所有删除、孤立引用和重复统计均为 0`

### QR-20260825-NIGHTLY-SCOPE-GLOBAL-REPEAT Nightly 将记忆 scope 当成用户导致全局任务重复执行 (2026-08-25)
*   **问题描述**: 05:00 fallback 后 nightly 对 6 个记忆 scope 完整执行 6 轮，日记、计划、数字健康和 MEMORY.md 整理均被重复调用；数字健康空建议连续写入空限额。
*   **复现步骤**:
    1. 在夜间调度时间窗内让 weighted_memory_manager 存在 private、mobile、shared、aveline、ling 等多个 scope
    2. 触发 NightlyProcessor.process_all_users
    3. 对照 nightly_processor.log 中每个 scope 的 execute_async_tasks 与数字健康 limits 写入次数
*   **预期行为**:
    1. 蒸馏和人物档案按记忆 scope 执行
    2. 日记、用户计划、数字健康和核心记忆整理每个 target_date 仅执行一次
    3. 重启或局部失败后只补跑未完成部分
*   **实际行为**:
    1. 6 个 scope 触发 6 套全局任务
    2. _task_executed_today 不持久化且无条件标完成
    3. 当日空 baseline 被重复写成 limits={}
*   **根因**:
    1. scope 分析回调与全局夜间业务共用同一 execute_async_tasks
    2. 缺少按 target_date 和阶段记录的持久化幂等状态
    3. 空数字健康建议未在落盘前过滤
*   **修复方案**:
    1. 拆分 scope/global 阶段并新增 run_state.json 进度账本
    2. 失败不再标记当日完成，超时协程取消后由下一轮补跑
    3. 空 baseline 改为 skipped_empty_baseline，不写文件
    4. 统一 target_date 自然日窗口与冷启动 scope 扫描
*   **验证**:
    1. `verify_nightly_orchestration.py 验证 3 scope 一次 + global 一次，并验证部分失败只重试失败 scope`
    2. `verify_nightly_task_timeout_fix.py 6/6 通过`
    3. `journal_plan 回归 12 passed，相关 Ruff 通过`

### QR-20260825-NIGHTLY-PEOPLE-PROFILE-UNGATED Nightly 无人物对话仍触发大量人物档案 LLM 请求 (2026-08-25)
*   **问题描述**: PeopleProfileExtractor 对当天全部原始聊天批次同时执行外部人物提取和角色演化提取，导致没有人物的普通对话也产生付费请求；当日 DeepSeek Pro 的 62 次请求中有 52 次来自该提取器。
*   **复现步骤**:
    1. 触发含多个记忆 scope 的 nightly fallback
    2. 统计 04_llm_media.log 中 deepseek-v4-pro 的 caller_name
    3. 对照 xiaoyou_main.log 的原始消息数、分批数、外部人物提取与角色更新批次
*   **预期行为**:
    1. 记忆蒸馏发现人物或角色演化线索后才调用对应详细提取
    2. 普通对话不触发人物档案 LLM
    3. 人物档案全局共享，每个目标日期仅汇总执行一次
*   **实际行为**:
    1. 172 条消息形成 21 批，外部人物提取与角色演化均遍历全部批次
    2. 外部人物最终提取 0 人，但仍已支付所有请求成本
    3. 角色更新得到少量事实，无法证明全量批次扫描合理
*   **根因**:
    1. 人物档案任务缺少前置候选门控
    2. 蒸馏语义结果未向人物系统提供结构化线索
    3. 人物共享任务错误挂在每个 scope 阶段
*   **修复方案**:
    1. 蒸馏输出并持久化人物线索和角色演化线索
    2. global 阶段汇总全量 scope 元数据，只放行候选原始聊天批次
    3. 加入零 API 本地兜底，并在无线索时记录 0 次 LLM 与跳过原因
*   **验证**:
    1. `verify_people_profile_signal_gate.py 验证普通技术对话原始 1 批、人物 0 批、角色演化 0 批、LLM 0 次`
    2. `verify_batch_distillation.py 15/15 通过`
    3. `相关 Python 文件 Ruff 全部通过`

### QR-20260825-NIGHTLY-PEOPLE-GOD-CLASS Nightly 与人物提取入口持续膨胀且职责混杂 (2026-08-25)
*   **问题描述**: 人物信号门控直接继续写入既有大文件，使 NightlyTaskRunner 达到 829 行、PeopleProfileExtractor 达到 1123 行，编排层与业务实现层没有稳定边界。
*   **复现步骤**:
    1. 统计 memory/nightly/task_runner.py 与 core/character/people/extractor.py 行数和方法列表
    2. 检查 TaskRunner 是否直接调用日记、计划、数字健康、蒸馏 scheduler
    3. 检查 Extractor 是否直接扫描 JSONL、解析两类 JSON 并创建 KnownFact
*   **预期行为**:
    1. 入口类只负责编排和兼容转发
    2. I/O、门控、Prompt/解析、外部人物与角色演化职责相互独立
    3. 重构后原有行为验证继续通过
*   **实际行为**:
    1. 两个入口文件均包含多类业务实现，任何小改动都需要在超大文件内定位
    2. 门控逻辑接入后仍继续增加入口类方法和依赖
*   **根因**:
    1. 早期门面类逐步吸收实现细节但未设置规模和职责回归检查
    2. 兼容私有方法缺少委托层，导致实现天然堆积在入口类
*   **修复方案**:
    1. 按执行、Codec、全局编排和人物子领域拆成 7 个兄弟模块
    2. 入口保留兼容委托，不要求调用方同步大规模迁移
    3. 新增门面规模与职责关键词验证，阻止再次膨胀
*   **验证**:
    1. `verify_nightly_responsibility_split.py 验证门面行数、模块职责和兼容入口`
    2. `批量蒸馏 15/15、人物档案 53/53、人物信号门控全部通过`
    3. `相关文件 Ruff 与 py_compile 通过`

### MEM-20260827-KEYWORD-RW-DEADLOCK 关键词搜索在读锁内请求写锁导致自死锁 (2026-08-27)
*   **问题描述**: 首次关键词搜索（或索引需要重建时）进程卡死，日志持续输出 ReadWriteLock: write lock waiting >5s。
*   **复现步骤**:
    1. 导入一批加权记忆（遗留关键词重建标志），或加载后首次执行关键词搜索。
    2. 调用 search_by_keyword 触发索引就绪检查。
    3. 观察进程是否长时间无响应并打印写锁等待日志。
*   **预期行为**:
    1. 关键词索引按需构建，搜索正常返回结果，不发生自死锁。
*   **实际行为**:
    1. search_by_keyword 在读锁内调用 ensure_keyword_index_ready，后者无条件获取写锁，同线程读锁未释放导致写锁等待永不满足。
*   **根因**:
    1. 关键词索引就绪检查被放在读锁临界区内，而该检查本身需要写锁。
    2. 批量导入在写锁外设置重建标志，标志遗留使首次搜索必然触发重建路径。
*   **修复方案**:
    1. 将 ensure_keyword_index_ready 移到读锁外调用（与 hybrid_search_memories 的既有模式一致）。
    2. 批量导入改为在写锁内完成索引重建并清除重建标志。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\memory\verify_chiba_weighted_import.py`
