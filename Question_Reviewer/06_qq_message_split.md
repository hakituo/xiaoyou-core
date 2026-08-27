# QQ 适配器与消息断句

本分类共 21 条记录。按时间倒序（最新在前）排列。

---

### QR-20260702-QQ-SELF-RECOVER QQ Adapter 在主程序重启后仍依赖用户消息才能体感恢复 (2026-07-02)

*   **问题描述**: 用户明确要求主程序重新启动后，QQ Adapter 要自己自动连上；用户发来的消息不应该承担消息处理职责，而只能被视为类似唤醒刺激。但实际表现仍是后端一关就收到错误提示，恢复阶段也容易体感成“发一条消息才连上”。
*   **复现步骤**:
    1. 保持 QQ Adapter 运行并让主人的私聊会话处于已建立状态。
    2. 关闭 Xiaoyou Core 主程序。
    3. 观察 QQ 端是否立即收到核心服务失败提示。
    4. 重新启动主程序，在不发送任何 QQ 消息的情况下观察会话是否能自行恢复。
*   **预期行为**:
    1. 主程序短时重启期间，QQ Adapter 自己持续重连并在后端恢复后自动接回。
    2. 用户无需额外发送 QQ 消息来触发或加速恢复。
    3. 短时重启不应立即给 QQ 用户推送失败告警。
*   **实际行为**:
    1. 主会话存在失败上限，可能在重启窗口内自行停掉。
    2. 旧版失败提示依据 session 存活时长判断，导致运行一段时间后后端一关就立刻报错到 QQ。
*   **根因**:
    1. 主会话重连策略没有针对主人私聊这个关键链路做持续自恢复保障。
    2. 故障告警宽限逻辑绑定错了时间参考点。
*   **修复方案**:
    1. 主人私聊会话改为持续重试且不因重试次数耗尽而停掉。
    2. 失败提示改为按本次连续故障计时，并增加 20 秒重启宽限期。
    3. 补充针对“无消息自恢复”的回归验证。
*   **验证**:
    1. `./venv_core/Scripts/python.exe -m unittest clients.bots.tests.test_session_heartbeat`
    2. `./venv_core/Scripts/python.exe tests/scripts/qq/verify_backend_restart_reconnect.py`

### QR-20260701-QQ-RECONNECT-RACE QQ Adapter 在后端重启后不会稳定自动重连 (2026-07-01)

*   **问题描述**: 后端主程序关闭并重启后，QQ Adapter 的私聊会话会持续重连失败，甚至触发 Too many failures 停止；用户再发送一条 QQ 消息后才可能重新恢复。
*   **复现步骤**:
    1. 启动 Xiaoyou Core 与 QQ Adapter，确保主人的 private 会话已建立。
    2. 关闭后端主程序，保持 QQ Adapter 继续运行。
    3. 重新启动后端，观察 QQ Adapter 日志中的 reconnect 与 Too many failures。
    4. 此时向 QQ 再发送一条消息，观察会话是否重新拉起。
*   **预期行为**:
    1. 后端恢复后，QQ 会话应自行感知接收链路中断并持续自动重连。
    2. 旧会话退出不应影响新会话注册，也不应要求用户额外发消息触发恢复。
*   **实际行为**:
    1. 接收循环结束后，会话可能仍卡在等待 queue.get。
    2. 旧会话 stop 未等待退出，导致相同 session_id 的旧新循环并发。
    3. 旧循环退出时可能删除新会话注册，日志表现为重连计数和 Too many failures 交错。
*   **根因**:
    1. 连接循环缺少对接收协程自然结束的即时断线感知。
    2. 会话停止流程未等待连接任务真正退出。
    3. adapter.sessions 的清理逻辑未校验实例身份。
*   **修复方案**:
    1. 让连接循环同时等待 queue.get 与 receive_task，receive_task 先结束则立即重连。
    2. 在 stop 中等待旧任务退出，避免残留循环继续跑。
    3. 只允许旧循环删除它自己对应的 sessions 条目。
*   **验证**:
    1. `./venv_core/Scripts/python.exe -m unittest clients.bots.tests.test_session_heartbeat`
    2. `./venv_core/Scripts/python.exe tests/scripts/qq/verify_backend_restart_reconnect.py`

### 10.146 QQ 断句无法识别“纯空格短语串”的人工分泡泡意图 (2026-06-30)

*   **问题描述**: 像 `像我现在这样 没有标点 但是很长一串 并且不断句` 这种没有标点、只靠空格表达停顿和分泡泡意图的文本，QQ 侧会整条发出去，导致气泡体验很差。
*   **复现步骤**:
    1. 调用 `_split_message_for_qq("像我现在这样 没有标点 但是很长一串 并且不断句")`。
    2. 调用 `_split_message_for_qq("今天 学习 数学 英语 物理")`。
    3. 再对照 `_split_message_for_qq("I think this is a normal english sentence with spaces")`，确认不能把普通英文句子误拆。
*   **预期行为**:
    1. 明显像人工短语分段的中文空格串应拆成多个 QQ 气泡。
    2. 普通英文空格句和非人工分段文本不应被误拆。
*   **实际行为**:
    1. 旧逻辑完全忽略纯空格边界，整条文本直接返回为单个 chunk。
*   **根因**:
    1. 断句逻辑只关注换行和标点，没有单独建模“纯空格短语串”。
*   **修复方案**:
    1. 新增纯空格中文短语串识别与合并限制逻辑。
    2. 补充中文短语串和英文句的区分测试，避免误伤普通文本。
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_qq_split.py -q -k "plain_space or period_space or ellipsis_space or comma_space or wait_phrase or slash_n or escaped_backslash_n"`

### 10.145 QQ 断句对“标点 + 空格”边界识别太弱，续接合并还会把已断开的气泡重新粘回去 (2026-06-30)

*   **问题描述**: 模型输出里出现 `就是这样。 然后继续`、`我知道了…… 然后呢`、`嗯， 我看看` 这种带显式停顿的文本时，QQ 侧没有按气泡拆开，或者先断开又被后处理重新合并。
*   **复现步骤**:
    1. 调用 `_split_message_for_qq("就是这样。 然后继续")`。
    2. 调用 `_split_message_for_qq("我知道了…… 然后呢")`。
    3. 调用 `_split_message_for_qq("嗯， 我看看")`，并对照 `等等， 你先别急` 的等待短语场景。
*   **预期行为**:
    1. 显式“标点 + 空格”应被视为用户或模型主动给出的气泡边界。
    2. 已断开的句子不应在续接合并阶段又被重新粘回去。
*   **实际行为**:
    1. 旧逻辑对中等长度的 `。 `、`， ` 等边界不会稳定断开。
    2. 续接合并会把 `然后`、`再到` 等开头重新并回上一句。
*   **根因**:
    1. 断句阶段对显式空格边界利用不足。
    2. 合并阶段没有把 `。`、`……`、`，` 等显式断点视为硬边界。
*   **修复方案**:
    1. 增强 `_split_message_for_qq()` 对显式空格边界的判定。
    2. 增强 `_merge_continuation_chunks()` 的硬边界识别。
    3. 新增针对 `。 `、`…… `、`， ` 与等待短语的回归测试。
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_qq_split.py -q -k "period_space or ellipsis_space or comma_space or wait_phrase or slash_n or escaped_backslash_n"`

### 10.144 QQ 断句无法识别 /n，流式剩余 buffer 还会吞掉换行边界 (2026-06-30)

*   **问题描述**: QQ 侧希望把 `/n` 当成显式分泡泡标记时，最终没有拆成多个气泡；在流式场景下，剩余 buffer 还会丢失显式换行边界，导致后续断句效果继续变差。
*   **复现步骤**:
    1. 让模型输出 `就/n像/n这/n样`，观察 QQ 发送结果。
    2. 再构造 `第一句……\n第二句\n第三句` 的流式 buffer，检查 `_process_stream_buffer()` 返回的 remaining。
    3. 对照 `_split_message_for_qq()` 和 `SessionMessageHandler.process_stream_buffer()` 的实现。
*   **预期行为**:
    1. `/n`、`\n`、`\\n` 都应被识别成显式换行，并拆成多个 QQ 气泡。
    2. 流式路径保留尚未发送部分的换行边界，不能在回填 buffer 时直接拼成一整坨。
*   **实际行为**:
    1. 旧逻辑只识别字面 `\n`，`/n` 根本不会触发分泡泡。
    2. 流式路径用空字符串拼接剩余 chunks，换行分隔在 buffer 回填时会丢失。
*   **根因**:
    1. 显式换行标记归一化过窄，只覆盖一种写法。
    2. 流式剩余 buffer 重组时没有保留结构信息。
*   **修复方案**:
    1. 扩展 `_split_message_for_qq()` 的换行标记归一化规则。
    2. 将 `process_stream_buffer()` 的剩余内容改为按 `\n` 拼回。
    3. 新增断句与会话层回归测试，覆盖 `/n` 与流式 remaining 两条链路。
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_qq_split.py -q -k "slash_n or escaped_backslash_n"`
    2. `venv_core\Scripts\python.exe -m pytest clients\bots\tests\test_adapter_optimizations.py -q -k "slash_n_markers or preserve_remaining_newlines"`

### 10.143 Ling QQ emoji 过滤失效且历史记录残留脏数据 (2026-06-30)

*   **问题描述**: Ling会发出当前人设未声明的 emoji，且这些 emoji 还会原样进入聊天历史和记忆，导致后续上下文继续被污染。
*   **复现步骤**:
    1. 使用 `qq/Ling_QQ_Master.json` 作为当前 persona 生成一条包含 `🎉`、`😭` 等 emoji 的 assistant 回复。
    2. 观察发送前过滤、`save_conversation_history()` 入库和 `_sanitize_history_messages()` 历史回灌三个链路。
    3. 检查 `companion_data/ling_data` 下聊天历史与记忆文件，可看到历史中已残留非允许 emoji。
*   **预期行为**:
    1. Ling对外发送的消息应自动去掉人设外 emoji。
    2. 写入聊天历史和记忆的 assistant 文本也应是去除 emoji 的版本。
    3. 旧历史中的非法 emoji 应能批量清理，避免继续污染上下文。
*   **实际行为**:
    1. 历史回灌链因错误导入静默失效，assistant 历史中的 emoji 会被原样喂回上下文。
    2. 统一历史保存链没有做最终兜底过滤，未清洗文本会直接落盘。
    3. Ling persona 允许集为空时被旧策略当成“不过滤”，导致人设未声明任何 emoji 反而全部放行。
*   **根因**:
    1. 多个调用点仍引用已不存在的 `clients.bots.qq_adapter_utils`。
    2. emoji 过滤语义没有区分“persona 加载失败”和“persona 成功但允许集为空”两种状态。
    3. 缺少针对Ling历史数据的离线修复脚本，旧脏数据会一直存在。
*   **修复方案**:
    1. 抽离并统一 `emoji_filter.py`，修正所有错误导入与缓存清理路径。
    2. 在统一历史保存入口补 assistant emoji 兜底过滤，并修复历史回灌清洗链。
    3. 新增Ling历史清理脚本，已完成实际写回清理并复核为 0 残留。
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_wangling_emoji_filter.py -q`
    2. `venv_core\Scripts\python.exe tests\scripts\qq\verify_wangling_emoji_filter.py`
    3. `venv_core\Scripts\python.exe scripts\qq\clean_wangling_ooc_emoji_history.py --apply`
    4. `venv_core\Scripts\python.exe scripts\qq\clean_wangling_ooc_emoji_history.py`

### 10.138 WebSocketManager.handle_heartbeat / handle_message 自死锁导致 QQ Adapter 反复断连 (2026-06-27)

*   **问题描述**: QQ Adapter 日志频繁出现 `ERROR - [private_10001] Receive error: no close frame received or sent`，连接断开后走指数退避重连（1s → 2s → 4s → ...），重连成功后过 10-20 分钟再次断连。服务端日志只看到客户端 1006 异常关闭，没有任何服务端主动关闭的记录。用户消息仍能正常往返，所以容易误判为"网络抖动"。
*   **复现步骤**:
    1. 启动 Xiaoyou Core 后端 + QQ Adapter
    2. QQ Adapter 连接后，服务端心跳检查器每 30 秒发 `{"type":"ping"}`
    3. QQ Adapter 收到后回 `{"type":"pong"}`
    4. 服务端 `handle_pong` → `handle_heartbeat`：在 `async with self.connections_lock:` 内调用 `send_to_client` → `send_with_retry`，而 `send_with_retry` 又要 `async with self.connections_lock:` → 死锁
    5. 接收循环冻结、心跳检查器也拿不到锁、广播拿不到锁
    6. 几十秒后 websockets 库/OS 关闭 TCP 连接，QQ Adapter 报 "no close frame received or sent"
*   **预期行为**: 服务端收到 `pong` 后更新 `last_heartbeat` 并回 `pong`，连接长期稳定
*   **实际行为**: 接收循环死锁，连接在 1-2 分钟内死亡，QQ Adapter 反复重连
*   **根因**: `asyncio.Lock` 非重入。同任务持锁后再 `await lock.acquire()` 会无限阻塞。`handle_heartbeat` 在锁内调用 `send_to_client`（最终走到 `send_with_retry` 的 `async with self.connections_lock:`），形成自死锁。`handle_message` 的重复消息分支也是同样模式（持锁状态下 `await self.send_to_client(...)` 发 `duplicate_message`）
*   **诊断技巧**:
    1. 写最小复现脚本（FakeWS + `mgr.handle_heartbeat(ws)` + `asyncio.wait_for(..., timeout=3)`），3 秒超时直接确认死锁
    2. 服务端日志中"准备发送消息 - 类型: pong"出现但没有对应的"消息发送完成"，是死锁的特征签名
    3. QQ Adapter 端 `Receive error: no close frame received or sent` 配合 10-20 分钟周期性出现，强烈提示服务端长期冻结而不是网络问题
*   **修复**:
    1. `handle_heartbeat`：锁内只做 `connection.update_heartbeat()` 和设置 `should_send_pong = True`，锁外再 `await self.send_to_client(...)`
    2. `handle_message`：锁内只标记 `is_duplicate = True`，锁外再发送 `duplicate_message`
*   **验证**: `tests/test_websocket_lock_deadlock.py` 3 个测试（handle_heartbeat、重复消息分支、正常消息流程），修复前测试 1 直接 `DEADLOCK`，修复后 3/3 全部通过且确认 `pong` / `duplicate_message` 都已成功发送
*   **教训**:
    1. **任何在 `async with lock:` 临界区内调用又会获取同一把锁的函数都是潜在死锁点**。`send_to_client` / `send_with_retry` / `broadcast` 都会再获取 `connections_lock`，所以持锁状态下不能直接调它们
    2. 模式化修复：锁内只做"读取 / 修改共享状态"和"记录发送意图"，所有 I/O（发送消息、关闭连接）放到锁外
    3. 长期稳定的连接突然周期性断开，且没有网络层异常佐证时，优先怀疑应用层死锁而非网络抖动
*   **关键文件**: `core/interfaces/websocket/websocket_manager.py`、`tests/test_websocket_lock_deadlock.py`（**新建**）

### 10.117 QQ Adapter 获取人设列表失败 404 Not Found (2026-05-29)

*   **问题描述**: 用户发送 `/切人设 5` 命令时，QQ Adapter 返回 "获取人设列表失败: {"detail": "Not Found"}"
*   **复现步骤**:
    1. 启动 QQ Adapter（Ling）
    2. 用户发送 `/切人设 5`
    3. QQ Adapter 调用 `/api/personas` 获取人设列表
    4. 后端返回 404 Not Found
*   **预期行为**: 正确获取人设列表，执行切换
*   **实际行为**: 返回 404 错误，无法获取人设列表
*   **根因**: API 路径不匹配。`resources.py` 和 `qq_adapter_main.py` 中使用的是 `/api/personas` 和 `/api/models`，但实际路由前缀是 `/api/v1/personas` 和 `/api/v1/models`（`v1` 前缀缺失）
*   **修复**: 将所有 API 路径从 `/api/personas` 改为 `/api/v1/personas`，`/api/models` 改为 `/api/v1/models`
*   **涉及文件**:
    - `clients/bots/handlers/resources.py` (5处)
    - `clients/bots/qq_adapter_main.py` (2处)

### 10.116 QQ Adapter 发送消息时报 `_normalize_qq_face_position` 未定义 (2026-05-29)

*   **问题描述**: QQ Adapter 在发送消息时报错 `name '_normalize_qq_face_position' is not defined`，导致消息发送失败
*   **复现步骤**:
    1. 启动 QQ Adapter
    2. 用户发送消息
    3. QQ Adapter 尝试发送回复
    4. 报错 `_normalize_qq_face_position` 未定义
*   **预期行为**: 消息正常发送，表情标签位置被规范化
*   **实际行为**: 消息发送失败，报未定义错误
*   **根因**: `clients/bots/qq_adapter_main.py` 第 478 行使用了 `_normalize_qq_face_position(c)` 函数，但文件头部没有导入该函数。该函数定义在 `clients/bots/qq_adapter_utils.py` 第 672 行
*   **修复**: 在 `clients/bots/qq_adapter_main.py` 的导入部分添加 `from clients.bots.qq_adapter_utils import _normalize_qq_face_position`
*   **涉及文件**: `clients/bots/qq_adapter_main.py`
*   **测试脚本**: `tests/test_qq_adapter_import.py`

### 10.113 双角色私聊时对方bot使用错误persona（两个Aveline在聊天）(2026-05-28)

*   **问题描述**: 双QQ角色互聊时，Ling的adapter收到Aveline的消息后，用Aveline的人设回复，导致"两个Aveline在聊天"。Aveline也不知道对面是Ling，以为是在跟主人聊天。
*   **复现步骤**:
    1. 启动双QQ适配器
    2. Aveline主动给Ling发私聊消息
    3. Ling的adapter收到消息后回复
    4. 回复内容完全是Aveline的语气，不是Ling的
*   **预期行为**: Ling的adapter应该用 `Ling_QQ_Master.json` 人设回复，conversation_id 应该是 `private_{AvelineQQ号}__persona__ling_qq_master`
*   **实际行为**: Ling的adapter用 `Aveline_QQ_Master.json` 人设回复，conversation_id 是 `private_{AvelineQQ号}__persona__aveline_qq_group`
*   **根本原因**: `clients/bots/handlers/config.py` 的 `get_session_prefs()` 中，当 `qq_user_id` 不是主人时，`persona_filename` 被强制设置为 `PUBLIC_PERSONA_FILE`（默认 `Aveline_QQ_Master.json`），没有考虑对方bot的情况。
*   **修复**: 在 `get_session_prefs()` 中新增 `is_peer_bot` 判断，当发送者是对方bot时，使用adapter自身的persona（`own_persona`），而非公共人设。

### 10.111 双QQ角色共用同一人设 - persona_filename 未透传 + 全局状态污染 (2026-05-27)

*   **问题描述**: 双QQ独立角色架构中，两个QQ Bot只能使用同一个人设，无法各自使用不同人设（Aveline和Ling）。在Ling账号切换人设后，Aveline账号也被影响。
*   **复现步骤**:
    1. 启动双QQ适配器（dual_qq_adapter.py），配置两个角色各自不同的 persona_filename
    2. 分别给两个QQ号发消息
    3. 观察回复内容，两个角色使用的是同一个人设
    4. 在Ling账号使用 /切人设 命令切换人设
    5. 给Aveline账号发消息，发现Aveline也变成了Ling的人设
*   **预期行为**: Aveline使用 `qq/Aveline_QQ_Master.json`，Ling使用 `qq/Ling_QQ_Master.json`，各自独立互不影响
*   **实际行为**: 两个角色都使用全局 PersonaManager 的当前人设，切换一个影响全部
*   **根因分析**:
    1. `persona_filename` 在后端调用链中被完全丢弃（handlers→streaming→service→prompt全未透传）
    2. `_sync_config_from_backend` 启动时从后端全局API获取人设，覆盖了adapter自身配置
    3. `handle_switch_persona` 调用全局 `PersonaManager.set_persona()`，影响所有adapter实例
    4. `handle_switch_persona` 调用后端全局API `/api/personas/switch`，影响全局状态
    5. **`config.json` 的 `user_overrides` 按 QQ号 索引，两个adapter的master是同一个QQ号，共享同一个override条目，后写入的人设覆盖先写入的**
*   **修复方案**:
    1. 全链路透传 persona_filename（8个文件）
    2. _sync_config_from_backend 优先使用adapter自身配置
    3. handle_switch_persona 双QQ模式下不调全局API、不改变全局PersonaManager
    4. send_text 人设优先级：session prefs > adapter配置 > 全局PersonaManager
    5. **`user_overrides` 的 key 包含 role_id 区分（如 `10001__aveline` vs `10001__ling`）**

### 10.95 QQ 消息断句在前引号处错误分割，前引号单独成一条消息 (2026-05-09)

*   **问题描述**: LLM 输出含中文引号的对话时，前引号 `"` 被单独拆成一条消息发送，如第一条消息只有 `"`，第二条才是实际内容
*   **复现步骤**:
    1. LLM 输出类似 `"\n你倒是记得做空香港那段。"` 的文本（前引号后跟换行符）
    2. `_split_message_for_qq` 按换行符拆分，前引号变成独立一行
    3. 前引号作为单独的 chunk 发送，形成只有引号的消息气泡
*   **预期行为**: 前引号应与后续引用内容合并在同一条消息中
*   **实际行为**: 前引号单独成一条消息，阅读体验割裂
*   **根因**: `_split_message_for_qq` 中 `split('\n')` 逻辑将前引号后的换行符作为分割点，而现有的括号换行合并逻辑（第370-378行）只处理了 `（`/`(` 的情况，没有覆盖中文引号 `\u201c`/`\u2018`/`「`/`『`
*   **修复方案**: 在换行拆分之前，用正则合并前引号后的换行符（`([\u201c\u2018「『])\s*\n` → `\1`），同时合并闭合引号前的换行符（`\n\s*([\u201d\u2019」』])` → `\1`）
*   **涉及文件**: `clients/bots/qq_adapter_utils.py`、`tests/unit/test_qq_split.py`

### 10.73 QQ Adapter WebSocket 路由 user_id 与 persona conversation_id 不匹配 (2026-05-03)

*   **问题描述**: QQ Adapter 在线时，Active Care 消息仍被判为"用户不在线"并存入离线队列，消息无法送达 QQ
*   **复现步骤**: QQ Adapter 正常连接到 Core 服务端，触发 Active Care 消息，观察日志显示"主动消息已存入离线队列（用户不在线）"
*   **预期行为**: QQ Adapter 在线时，`broadcast()` 应找到对应 WebSocket 连接并实时推送消息
*   **实际行为**: `broadcast()` 未找到连接，消息存入离线队列
*   **根因**: 
    1. QQ Adapter 注册 WebSocket 连接时使用原始 `session_id`：`ws_url = f"...?user_id={self.session_id}&..."`，即 `private_10001`（不含 `__persona__` 后缀）
    2. Active Care 的 `_resolve_target_conversation()` 在 `qq_user_id == base_cid` 时保留了 persona conversation_id：`private_10001__persona__aveline_qq_master`
    3. `dispatch_proactive_message()` 用带 persona 后缀的 ID 调用 `broadcast(user_id=persona_cid)`，在 `user_connections` 中查找 `private_10001__persona__aveline_qq_master` → 找不到
*   **修复方案**:
    1. `dispatch_proactive_message()` 中新增 `broadcast_user_id` 计算逻辑：QQ 路由时剥离 `__persona__*` 后缀
    2. `is_user_online()` 调用也改用 `broadcast_user_id`
    3. payload 中的 `conversation_id` 保持 persona ID 不变，QQ Adapter handler 已有 base CID 匹配逻辑（第1021-1032行）
    4. `append_proactive_message` 继续使用 `target_conversation_id`（persona ID），确保消息存入正确的 persona 对话历史
*   **关键文件**: `core/services/aveline/service.py:272-278`, `core/services/active_care/executor.py:766-774`, `clients/bots/qq_adapter_session.py:167`

### 10.66 QQ适配器发送60条base64乱码消息 (2026-05-01)

*   **问题描述**: 用户只发了一条"？起床"，QQ适配器却发送了60条含 `[CQ:record,file=base64://UklGRiR2AgBXQVZFZm10...]` 的乱码消息
*   **复现步骤**: 发送消息触发TTS语音回复，TTS生成的音频base64编码后通过CQ码发送
*   **预期行为**: 只发送一条正常的语音消息或文本消息
*   **实际行为**: 发送了60条base64乱码消息
*   **根因**:
    1. `_send_voice_response` 将TTS音频编码为base64后直接构建 `[CQ:record,file=base64://...]` CQ码发送
    2. `send_to_napcat` 中的 `_split_plain_text` 将超长的base64 CQ码（通常数千到数万字符）按1200字符拆分，导致CQ码被拆碎成多个无效片段
    3. NapCat无法解析拆碎的CQ码片段，将其作为纯文本显示，用户看到的就是base64乱码
    4. 全链路无任何base64过滤/防护机制
*   **修复方案**:
    1. `_send_voice_response` 改为优先保存音频到本地文件后用文件路径发送，避免base64 CQ码
    2. `_split_plain_text` 新增CQ码保护：含 `[CQ:` 的文本不拆碎CQ码，使用占位符策略保留CQ码完整性
    3. 全链路添加base64防护：`qq_adapter_utils.py` 新增 `_contains_raw_base64()`、`_strip_base64_from_text()`、`_is_base64_cq_code()`
    4. `send_to_napcat` 添加base64拦截：合法CQ码放行，裸base64尝试剥离，剥离失败则丢弃
    5. `qq_adapter_session.py` 三处发送函数添加base64防护
    6. 核心层 `streaming.py` 和 WebSocket `streaming.py` 添加base64过滤

### 10.65 QQ消息断句不自然——续接词被拆到新消息 (2026-05-01)

*   **问题描述**: 长文本被分割成多条QQ消息时，分割点不自然。如"MLP、词嵌入、RNN/LSTM做序列建模"后接"再到Seq2Seq"被拆成两条消息，"Week 15讲LLM怎么反哺NLP"后接"以及AGI的想象空间"也被拆开
*   **复现步骤**: 发送包含多行枚举内容的长文本，观察消息分割点
*   **预期行为**: 续接词（如"再到"、"以及"）应与上文合并在同一条消息中
*   **实际行为**: 续接词被拆到新消息开头，读起来像话没说完就断了
*   **根因**: 1) 换行优先分割导致跨行语义被切断；2) 分割后不考虑下一段是否以续接词开头；3) 句号处断句未检查 `min_split_len`（代码与文档不一致）
*   **修复方案**: 使用 jieba.posseg 词性标注识别连词(c)和特定副词字根开头的续接词，在断句后合并不自然的分段；同时修复 `min_split_len` 检查缺失的bug

### 10.60 QQ消息chunk数量过多 (2026-04-30)

*   **问题描述**: QQ端AI回复被拆分成过多消息气泡，影响阅读体验
*   **复现步骤**:
    1. AI回复包含多个短句
    2. 每个句号处都断句，产生5-6个chunk
    3. 用户收到大量短消息气泡
*   **预期行为**: 一般2-3个消息气泡，最多6个
*   **实际行为**: 可能产生7个以上的消息气泡
*   **根因**: 断句函数没有软上限控制，句号处无限制断句
*   **修复**:
    1. 硬上限从7降到6
    2. 新增软上限：已产生2个chunk后，后续句号/问号/感叹号/省略号处不再断句，剩余内容合并到最后一个chunk
    3. 句号断句最小长度阈值从40降到`min(10, min_split_len)`

### 10.58 QQ消息遇到句号不断句 (2026-04-30)

*   **问题描述**: QQ端AI回复遇到句号时不断句，整段话合成一条超长消息发送，聊天体验差
*   **复现步骤**:
    1. AI回复包含多个短句，如"今天天气不错。明天会更好。后天可能有雨。"
    2. `_split_message_for_qq`中句号断句要求`current_len >= min_split_len`（默认40字）
    3. 每个短句不到40字，句号处不会断句
    4. 整段话合成一条消息发送
*   **预期行为**: 句号处应该断句，每个句子作为独立消息发送
*   **实际行为**: 句号处不断句，整段话合成一条消息
*   **根因**: `_split_message_for_qq`中，句号断句的`min_split_len`阈值（40字）太大，导致短句后的句号无法触发断句
*   **修复**: 将句号断句的最小长度阈值从`min_split_len`（40字）降低到`min(15, min_split_len)`（15字），让大多数短句都能在句号处断句

### 10.55 QQ消息断句过度拆分 - AI回复一断一断的 (2026-04-30)

*   **问题描述**: QQ端AI回复被过度拆分成多条短消息（每条只有十几字），读起来感觉"话没说完就被断开了"。例如"我刚才话没说完就被你岔开了。生蚝本身对肾确实有点好处——锌含量很高，你第二天腰不痛不奇怪。但重点是你只吃了三个，剩下..."被拆成4条消息
*   **复现步骤**:
    1. 在QQ端与AI对话，AI回复稍长（>40字）
    2. 观察AI回复被拆成多条短消息
*   **预期行为**: 短回复（<150字）应作为一条完整消息发送，长回复按语义自然断句
*   **实际行为**: 每个逗号/句号都可能断句，标点被剥离，消息感觉没说完
*   **根因**: (1) MAX_BUBBLE_LEN=60太短 (2) comma_split_prob=0.72太高 (3) 断句时剥离标点 (4) 无最小断句长度限制
*   **修复**: 提升MAX_BUBBLE_LEN到150，降低comma_split_prob到0.2，保留标点，添加min_split_len=40

### 10.45 QQ适配器WebSocket keepalive ping timeout 反复断连 (2026-04-28)

*   **问题描述**: QQ适配器与Xiaoyou Core的WebSocket连接反复断开，日志报 `sent 1011 (unexpected error) keepalive ping timeout; no close frame received`，重试3次后session永久停止，用户发消息无响应
*   **复现步骤**:
    1. 启动 Xiaoyou Core 后端和 QQ 适配器
    2. 等待约20-30秒，观察日志出现 keepalive ping timeout 错误
    3. 连接断开后重试3次即永久停止
*   **预期行为**: WebSocket连接保持稳定，偶有断连能自动恢复
*   **实际行为**: 连接反复断开，3次重试后session永久死亡
*   **根因**（双重bug）:
    1. **协议层ping不兼容**：`websockets` 客户端库的 `ping_interval`/`ping_timeout` 参数控制的是 WebSocket 协议层（RFC 6455）的 ping/pong 控制帧，但 FastAPI/Starlette 的 ASGI 实现不会自动回复协议层 ping 帧。客户端发了协议层 ping，服务端永远不回协议层 pong，导致客户端判定超时断连
    2. **应用层心跳回复类型错误**：客户端 `_handle_server_heartbeat` 收到服务端 `{"type": "ping"}` 后回复的是 `{"type": "ping"}`，而服务端 `handle_pong` 期望收到 `{"type": "pong"}` 才会更新 `last_heartbeat` 时间戳。由于回复类型错误，服务端的心跳检查器始终认为客户端无响应，60秒后也会主动断连
*   **修复**:
    1. 禁用 `websockets` 库的协议层 ping：`ping_interval=None, ping_timeout=None`，完全依赖应用层心跳
    2. 修复客户端心跳回复：`{"type": "ping"}` → `{"type": "pong"}`，并回传服务端的 timestamp
    3. 优化重连逻辑：区分临时错误（keepalive timeout等）和致命错误，临时错误允许20次重试（原3次），指数退避上限从8秒提升到30秒

### 10.34 QQ 动作描写被误转颜文字并污染发送内容 (2026-03-09)

*   **问题描述**: 回复中 `（瞥了眼消息）` 这类动作描写在发送到 NapCat 前被替换成颜文字，导致“原文没颜文字但最终发出颜文字”。
*   **复现步骤**:
    *   让模型生成以 `（...）` 开头的动作描写文本并发送到 QQ。
    *   观察适配器日志中 chunk 原文正常，但发往 NapCat 的 message 已变成颜文字。
*   **预期行为**: 动作描写保留原文发送，不应被当作表情标签处理。
*   **实际行为**: `QQFaceInjector` 将圆括号内容误识别为标签，未命中 QQ 小黄脸映射时回退为颜文字。
*   **原因分析**:
    *   标签匹配正则同时接受 `()（）`，覆盖了普通动作描写场景。
    *   未识别标签存在“兜底选颜文字”分支，放大误匹配影响。
*   **解决方案**:
    *   收紧标签识别到 `[]/【】`，不再解析圆括号动作描写。
    *   增加 `enable_kaomoji` 开关并默认关闭；未识别标签保持原文，不再兜底注入颜文字。
    *   移除 `_send_friendly_error` 中的颜文字后缀，避免系统错误消息再带颜文字。

### 10.11 前沿上下文管理与 QQ Bot 功能增强 (2026-01-02)

*   **上下文管理优化**:
    *   **问题**: 长对话导致 Token 溢出与“Lost in the Middle”语义丢失。
    *   **解决**: 引入 LongLLMLingua 思想，在 [context.py](file:///d:/AI/xiaoyou-core/core/agents/chat_agent_components/context.py) 中实现混合压缩策略。将 Token 换算比从 4.0 优化为更保守的 1.5 chars/token，并增加 200 字符语义缓冲区。
*   **QQ Bot 权限与功能增强**:
    *   **新功能**: 实现了 `/清除本地记忆` (彻底删除历史) 与 `/调试模式` (无状态对话，`save_history=False`)。
    *   **权限控制**: 为高风险指令增加了 `Master` 权限校验，确保系统安全性。
    *   **交互优化**: 重构了 [qq_adapter.py](file:///d:/AI/xiaoyou-core/clients/bots/qq_adapter.py) 的 `_show_help` 逻辑，更新了指令列表。
*   **理论深度集成**: 
    *   **MemGPT**: 在 `WeightedMemoryManager` 中实现了类似虚拟内存的记忆分页机制。
    *   **vLLM**: 在配置层引入了动态 Token 预算管理。
    *   **LongLLMLingua**: 实现了基于关键锚点的语义压缩。

### 10.92 角色晚安消息未送达 QQ：trigger_character_goodnight 未传 client_type="qq" (2026-07-06)
*   **问题描述**: 用户反馈 AI 角色睡觉时没有发晚安消息。排查 2026-07-05 日志发现 23:10 和 23:40 都成功生成了 goodnight_proactive 消息，但日志显示「主动消息已存入离线队列（用户不在线）」，QQ 端从未收到。同时 23:40 触发 ling 的晚安时，persona_filename=core_ling.json 但 target_cid=private_10001__persona__aveline_qq_master，ling 的晚安被错路由到 aveline 会话。
*   **复现步骤**:
    1. 服务运行中，用户在 23:09 发送消息「嗯嗯晚安小澪」后被 BERT 检测到晚安意图
    2. 23:10:00 aveline 触发 goodnight_proactive，LLM 生成「晚安。先去睡，记得你答应我的。」
    3. 23:10:04 日志：主动消息已存入离线队列（用户不在线）: conversation=private_10001__persona__aveline_qq_master
    4. 23:40:00 ling 触发 goodnight_proactive，但 target_cid=private_10001__persona__aveline_qq_master（错路由到 aveline 会话）
    5. 23:40:08 同样存入离线队列，QQ 端两条都没收到
*   **预期行为**:
    1. 用户在线时（QQ Adapter WebSocket 已注册 private_10001），晚安消息应实时送达 QQ
    2. ling 的晚安应发到 private_10001__persona__ling_qq_master，而非 aveline 的会话
*   **实际行为**:
    1. 两条晚安消息都只存入离线队列，QQ 端从未收到
    2. ling 的晚安被错路由到 aveline 会话（persona_filename=core_ling.json 但 target_cid 是 aveline 的）
*   **根因**:
    1. core/services/active_care/goodnight_proactive.py 的 trigger_character_goodnight 调用 executor.trigger_message() 时未传 client_type="qq"
    2. dispatch_proactive_message 中 if client_type == "qq" and "__persona__" in target_conversation_id 条件不成立（client_type=""），broadcast_user_id 未剥离 __persona__ 后缀，仍为 private_10001__persona__aveline_qq_master
    3. ws_manager.broadcast(user_id=private_10001__persona__aveline_qq_master) 找不到连接（QQ Adapter 注册时用的是 private_10001），返回 False，存入离线队列
    4. resolve_target_conversation 因 client_type 为空，is_qq_client=False，不走 persona 路由，直接用 resolve_primary_conversation_id() 返回的主会话（aveline 的），导致 ling 的晚安被错发到 aveline 会话
*   **修复方案**:
    1. core/services/active_care/goodnight_proactive.py:183-198: trigger_character_goodnight 调用 executor.trigger_message() 时补传 client_type="qq"，并加注释说明不传会引发的两个连锁问题
    2. tests/scripts/active_care/verify_character_goodnight.py: 在 test_trigger_character_goodnight_delivers_and_marks_sent 和 test_sleep_again_uses_sleep_again_sys_prompt_type 中新增 client_type="qq" 断言
*   **验证**:
    1. `.\venv_core\Scripts\python.exe -m pytest tests/scripts/active_care/verify_character_goodnight.py -v （13 passed）`

### BRACKET-001 中文直角引号「」内的换行符导致断句问题 (07-09)
*   **问题描述**: 用户发现「嗯？\n」被断成两条消息发送，导致引号内容不完整
*   **复现步骤**:
    1. 模型回复包含「嗯？\n」这样的内容
*   **预期行为**:
    1. 引号内的换行符应被去除，保持引号内容的完整性
*   **实际行为**:
    1. 「嗯？」和「」什么啦...被分成两条消息发送
*   **根因**:
    1. _split_message_for_qq 函数的正则表达式只处理西文引号（\u201c \u2018 \u201d \u2019），漏掉了中文直角引号「」（\u300c \u300d）的 Unicode 码点
*   **修复方案**:
    1. 在正则表达式中添加 \u300c \u300e（左引号）和 \u300d \u300f（右引号）的码点
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests/unit/test_qq_split.py::test_japanese_bracket_after_newline_should_not_split -v`

### ELLIPSIS-001 省略号断句问题：感叹词模式和括号后省略号 (07-09)
*   **问题描述**: 用户发现两个省略号断句问题：1) ……哈？！被拆成三段；2) 括号后的省略号单独成条
*   **复现步骤**:
    1. 模型回复包含……哈？！这种感叹词+标点模式
    2. 模型回复包含（动作描写） ……后续句子这种结构
*   **预期行为**:
    1. ……哈？！应该合并成一条消息
    2. （动作描写）和……后续句子应该分开，省略号和后续句子合并
*   **实际行为**:
    1. ……哈？！被拆成：……哈？和！
    2. （动作描写） ……和后续句子被拆成：（动作描写） ……和后续句子
*   **根因**:
    1. 省略号被当作强句子结束符无条件断句
    2. 感叹词+标点模式在第一个标点处断句
    3. 括号后省略号单独成一条
*   **修复方案**:
    1. 添加感叹词+标点模式检测
    2. 括号结束处检测省略号+普通句子模式
    3. 省略号处理中检测刚断过句+省略号+普通句子模式

### QR-20260804-01 dual_qq_adapter N 角色改造引入 AttributeError: QQAdapterConfig 无 qq_id 字段 (2026-08-04)
*   **问题描述**: 启动双QQ适配器时崩溃：AttributeError: 'QQAdapterConfig' object has no attribute 'qq_id'，导致 dual_qq_adapter.py 异常退出。
*   **复现步骤**:
    1. 运行 python clients/bots/dual_qq_adapter.py 启动双QQ适配器
    2. load_dual_config() 在第82行执行 if env_qq and not cfg.qq_id: 时崩溃
    3. 异常被 __main__ 捕获，打印 '按回车键退出...'
*   **预期行为**:
    1. 适配器正常启动，加载 aveline/ling 两个角色配置
*   **实际行为**:
    1. AttributeError: 'QQAdapterConfig' object has no attribute 'qq_id'，适配器无法启动
*   **根因**:
    1. N 角色改造时错误地假设 QQAdapterConfig 有 qq_id 字段存储角色自己的 QQ 号，实际该 dataclass 只有 master_qq_id（主人QQ）和 peer_qq_id（对端QQ）两个QQ字段，角色自己的 QQ 号从未存到 config 对象
    2. 原双角色逻辑是：XIAOYOU_QQ_BOT_NUMBER(aveline的QQ) 用于填充 ling 的 peer_qq_id，XIAOYOU_QQ_BOT_NUMBER_LING(ling的QQ) 用于填充 aveline 的 peer_qq_id，即 env var 给的是角色自己的QQ，用于填其他角色的 peer_qq_id
    3. 改造代码把 env var 当成角色自己的 qq_id 存到 cfg.qq_id（不存在），然后又从其他角色的 qq_id 读出来填 peer_qq_id，两处都错
*   **修复方案**:
    1. dual_qq_adapter.py: 去掉 cfg.qq_id 赋值，改为收集 role_own_qq 字典（role_id→角色自己QQ），然后遍历 role_own_qq 选第一个非自己的QQ填入 peer_qq_id
    2. settings_adapters.py: 同步去掉 role_cfg['qq_id'] 赋值，peer_qq_id 直接从 role_qq_from_env 遍历填充
    3. 角色自己的 QQ 号不存到 QQAdapterConfig（无该字段），仅用于在启动时填充其他角色的 peer_qq_id，与原双角色逻辑一致
*   **验证**:
    1. `python -c "from clients.bots.dual_qq_adapter import load_dual_config; cfgs = load_dual_config(); print(list(cfgs.keys()))" (输出 aveline/ling 两个角色，peer_qq_id 正确)`
    2. `python tests/scripts/multi_role/verify_multi_role_support.py (7 项检查全过)`

### QR-20260805-BOTPY-LOG QQ官方适配器 botpy 日志按天轮转 PermissionError 崩溃 (2026-08-05)
*   **问题描述**: QQ 官方机器人跨天时 botpy.log 轮转失败，报 PermissionError [WinError 32] 另一个程序正在使用此文件，进程无法访问，日志输出链路中断。
*   **复现步骤**:
    1. 运行 QQ 官方适配器（clients/bots/qq_official/adapter.py）
    2. 跨越午夜零点，TimedRotatingFileHandler 触发按天轮转
    3. logs/botpy.log 被其他句柄占用，os.rename 到 botpy.log.2026-08-04 失败
*   **预期行为**:
    1. 日志轮转失败时不应中断日志输出链路，心跳线程继续正常工作
*   **实际行为**:
    1. 抛出 PermissionError [WinError 32]，打印 --- Logging error --- 堆栈
    2. 心跳维持线程的日志输出连锁失败
*   **根因**:
    1. 标准库 TimedRotatingFileHandler.doRollover 在 Windows 下对文件占用没有容错
    2. transport.py 直接用了 TimedRotatingFileHandler 而非项目已有的 Safe 模式
*   **修复方案**:
    1. 新增 SafeTimedRotatingFileHandler，doRollover 捕获 PermissionError 后重新打开当前文件继续写入
    2. _BOTPY_LOG_HANDLER 改用 SafeTimedRotatingFileHandler
*   **验证**:
    1. `python tests/scripts/test_safe_timed_rotating_handler.py`

### Q-2026-0823-001 QQ 表情包 PNG 发送白边：自定义贴纸字段映射错误 (2026-08-23)
*   **问题描述**: QQ 表情包 PNG 通过普通图片通道发送出现白边（PNG 被转 JPG 丢失透明）。改用 NapCat add_custom_face + mface 贴纸通道后，日志出现「无法获取自定义表情 emoji_id，回退到 CQ:image」，贴纸发送始终不生效。
*   **复现步骤**:
    1. 发送 [MEME] 标签让机器人挑选本地 PNG 表情包
    2. 观察 QQ 客户端收到的图片出现白色背景填充
*   **预期行为**:
    1. 表
    2. 情
    3. 包
    4. 以
    5. Q
    6. Q
    7. 贴
    8. 纸
    9. 形
    10. 式
    11. 发
    12. 送
    13. ，
    14. 保
    15. 留
    16. P
    17. N
    18. G
    19. 透
    20. 明
    21. 背
    22. 景
    23. ，
    24. 无
    25. 白
    26. 边
*   **实际行为**:
    1. 始
    2. 终
    3. 回
    4. 退
    5. 到
    6. C
    7. Q
    8. :
    9. i
    10. m
    11. a
    12. g
    13. e
    14. ，
    15. P
    16. N
    17. G
    18. 被
    19. 转
    20. J
    21. P
    22. G
    23. 出
    24. 现
    25. 白
    26. 边
*   **根因**:
    1. fetch_custom_face_detail 返回字段为 md5/epId/resId，旧代码按 emoji_id/emoji_package_id 读取取空
    2. mface CQ 码缺少 key 字段，即使拿到 id 也可能发送失败
*   **修复方案**:
    1. 按 NapCat 源码映射 md5→emoji_id、epId→emoji_package_id、resId→key、desc→summary
    2. mface CQ 码补充 key，summary 做 CQ 安全净化
    3. 按本地 MD5 精确匹配刚上传贴纸，未同步时重试 3 次
    4. 表情缓存按账号(napcat_ws_url)+文件路径键控，避免多账号串号
*   **验证**:
    1. `ruff 检查通过`
    2. `tests/scripts/qq/verify_meme_mface.py 4 组用例全部通过`

### QR-20260824-QQ-VOICE-ORDER QQ 语音段先提交但后续文字先显示 (2026-08-24)
*   **问题描述**: 同一条分段回复先包含语音段、后包含文字段时，日志显示语音段先发送，但 QQ 客户端中后续文字可能先于语音出现。
*   **复现步骤**:
    1. 让模型返回一个 VOICE 语音段，后面紧跟普通文字段
    2. 观察适配器日志中 Voice segment sent 与 Sending chunk 的时间
    3. 同时观察 NapCat 的语音文件转换成功和最终语音发送日志
*   **预期行为**:
    1. 等待 TTS 生成完成并确认语音真正投递
    2. 语音投递完成后才发送后续文字段
*   **实际行为**:
    1. 适配器提交语音 CQ 码后立即认为发送成功
    2. 后续文字在数毫秒内提交，可能早于 NapCat 完成语音转码并先显示
*   **根因**:
    1. 普通 send_message 没有 echo，也不等待 NapCat action 结果
    2. await 只覆盖 TTS 生成和 WebSocket 写入，没有覆盖 NapCat 的语音转码及投递
*   **修复方案**:
    1. 为需要严格顺序的媒体消息增加 wait_for_result action 确认模式
    2. QQ 语音发送统一启用确认模式，失败时保留文字回退
*   **验证**:
    1. `verify_voice_send_order.py 模拟 50ms 语音确认延迟，确认事件顺序为提交语音、确认语音、提交文字`
    2. `verify_voice_segments.py 原有 11 项分段规则全部通过，Ruff 检查通过`
