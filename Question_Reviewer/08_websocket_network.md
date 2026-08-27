# WebSocket 与网络

本分类共 6 条记录。按时间倒序（最新在前）排列。

---

### 10.141 WebSocket 连接数持续增长（连接泄漏）+ FastAPI WebSocket 断开检测无效 (2026-06-27)


*   **问题描述**: 用户反馈 WebSocket 连接数从 5 涨到 7，但实际只有 3 个端（QQ 两个角色 + App 一个端）。日志显示 mobile_user 反复以 `unknown` platform 注册新连接，旧连接未被清理。
*   **复现步骤**:
    1. App（mobile_user）连入，因 URL 无 `platform` 参数 → platform 默认为 `unknown` → `is_mobile=False`
    2. App 切到后台，移动端被系统休眠 / NAT 超时，WebSocket 异常断开
    3. Starlette 抛 `WebSocketDisconnect`，`adapter.handle_connection` 的 finally 块调用 `remove_connection` —— 但若断开发生在接收循环之外（如 OS 层面杀进程），finally 可能延迟或不触发
    4. App 回前台重连，`add_connection` 直接把新连接加入 `user_connections[mobile_user]`，**不清理同 user_id 的僵尸连接**
    5. `heartbeat_checker` 用 `hasattr(websocket, "closed") and websocket.closed` 检测 —— **FastAPI/Starlette WebSocket 没有 `closed` 属性**，检测恒为 False，僵尸连接永远不被清理
    6. 连接数累积：5 → 6 → 7 …
*   **预期行为**: 同一 user_id 的新连接注册时，主动清理已断开的旧连接；心跳检查器能正确检测 FastAPI WebSocket 的断开状态。
*   **实际行为**: 僵尸连接残留直到 60s heartbeat_timeout，期间连接数持续增长。
*   **原因分析**:
    1. `add_connection` 只做"加"，不做"清理同 user_id 僵尸连接"
    2. `heartbeat_checker` / `_cleanup_stale_connections` / `send_with_retry` 三处都用 `hasattr(websocket, "closed") and websocket.closed` —— 对 `websockets.WebSocketServerProtocol` 有效，对 FastAPI `WebSocket` 无效
    3. FastAPI/Starlette WebSocket 的状态在 `application_state` / `client_state` / `close_code` 三个属性上，需单独检测
*   **解决方案**（在本次解耦重构中一并修复）:
    1. `ConnectionManagementMixin.add_connection` 注册新连接时，锁内扫描同 user_id 的现有连接，用 `_is_starlette_websocket_closed` 判定僵尸，立即从 `connections` / `user_connections` 移除并标记 `ConnectionState.CLOSED`
    2. 新增 `_is_starlette_websocket_closed(websocket)` 方法：三重检测 `application_state`（DISCONNECTED）/ `client_state`（DISCONNECTED）/ `close_code is not None`
    3. `heartbeat_checker` / `_cleanup_stale_connections` / `send_with_retry` 三处检查点改为 `(hasattr(websocket, "closed") and websocket.closed) or self._is_starlette_websocket_closed(websocket)`，兼容两种 WebSocket 类型
    4. `_cleanup_stale_connections` 死锁修复：锁内只收集 stale_websockets 列表，锁外调用 `remove_connection`（原代码在锁内调用 `await remove_connection` 会重入死锁）
*   **验证**: [test_websocket_decouple.py](file:///d:/AI/xiaoyou-core/tests/test_websocket_decouple.py) 测试4/5/6 验证僵尸清理逻辑与两处死锁修复存在；[test_websocket_lock_deadlock.py](file:///d:/AI/xiaoyou-core/tests/test_websocket_lock_deadlock.py) 3/3 通过
*   **状态**: ✅ 已修复，需重启服务后观察连接数是否稳定在 3（QQ×2 + App×1）
*   **备注**: App 连接建议在前端 URL 补上 `platform=mobile` 参数，便于 `is_mobile` 判定与后续移动端专属逻辑

### 10.122 aiohttp Unclosed connector 错误 (2026-06-04)

*   **问题描述**: 程序退出时报 `[ERROR] [asyncio] Unclosed connector`，aiohttp ClientSession 的 TCPConnector 未被关闭
*   **复现步骤**:
    1. 启动项目，正常使用后退出
    2. 日志中出现 `Unclosed connector` 和 `connections: ['deque([(<aiohttp.client_proto.ResponseHandler ...>)'])']`
*   **预期行为**: 退出时所有 aiohttp session 和 connector 都应被正确关闭，无警告
*   **实际行为**: TTS 引擎的持久 session、InferServiceClient 的全局 session、OpenAIClient 动态 key 的临时 session 在退出时未被关闭
*   **根因分析**:
    1. TTS/STT 服务的 shutdown 函数在 `service_registry.py` 中定义了但未通过 `lifecycle.register_service()` 注册，导致主 shutdown 流程不会调用
    2. `InferServiceClient` 只有 `_close_session()` 没有 `shutdown()`，且全局实例未在主关闭流程中被清理
    3. `OpenAIClient._get_session_with_key()` 在动态 key 场景下创建临时 session，但调用方 `chat()` 从不关闭它
*   **修复方案**:
    1. 将 TTS/STT 服务注册到 lifecycle_manager（优先级5）
    2. 为 InferServiceClient 添加 `shutdown()` 方法，在 `lifecycle_manager.shutdown_all()` 中调用
    3. 移除 `_get_session_with_key()`，在 `chat()` 中直接管理临时 session 生命周期，用 `finally` 确保关闭

### 10.112 persona_filename 在 WebSocket 消息标准化时被丢弃 (2026-05-28)

*   **问题描述**: 双QQ模式下，Ling的QQ始终使用Aveline的人设。后端日志显示 `persona_filename=''`，但 `conversation_id` 正确包含了 `ling_qq_master`。
*   **复现步骤**:
    1. 启动双QQ适配器，给Ling的QQ发消息
    2. 后端日志显示 `[WS Handler] persona_filename=''`
    3. `[get_prompt_data]` 因外部未传入 persona_filename，fallback到全局PersonaManager的Aveline人设
*   **预期行为**: `persona_filename='qq/Ling_QQ_Master.json'` 传递到后端
*   **实际行为**: `persona_filename=''`，后端使用全局PersonaManager的Aveline人设
*   **根因分析**:
    1. QQAdapter 的 `send_text` 发送的 payload type 是 `"text_input"`
    2. 后端 `adapter.py` 第350行：当 `msg_type` 是 `"text"` 或 `"text_input"` 时，先调用 `handle_text_message` 标准化消息
    3. `handle_text_message`（handlers.py 第459-466行）在标准化时只保留了6个字段：`type`、`content`、`message_id`、`conversation_id`、`request_id`、`model`
    4. **`persona_filename` 和 `peer_role_context` 被丢弃**
    5. 这就是为什么 conversation_id 正确（在标准化前构建）但 persona_filename 为空（标准化后丢失）
*   **修复方案**: 在 `handle_text_message` 的标准化结果中保留 `persona_filename` 和 `peer_role_context` 字段

### 10.37 OpenAI 兼容流在传输中断导致 `TransferEncodingError` (2026-03-20)

*   **问题描述**: 云端对话偶发报错 `Response payload is not completed` / `TransferEncodingError` / `ConnectionResetError(指定的网络名不再可用)`，请求被直接失败。
*   **复现步骤**:
    *   使用 OpenAI 兼容云模型进行连续对话或流式输出。
    *   在网络抖动或上游连接提前断开时观察日志。
*   **预期行为**: 瞬时网络中断应自动重试，且返回可读中文错误。
*   **实际行为**: 旧逻辑仅对少量 SSL 错误重试，`TransferEncodingError` 会直接失败并回传原始异常。
*   **解决方案**:
    *   `openai_client.py` 新增 `_is_transient_network_error`，识别 `TransferEncodingError/ClientPayloadError/ConnectionReset` 等中断异常。
    *   `chat()` 与 `stream_chat()` 在瞬时传输异常下自动关闭会话并重试（最多 3 次）。
    *   流式模式仅在“尚未产出内容”时允许重试，避免重试后出现重复片段。
    *   统一错误归一为 `SSL_ERROR / NETWORK_INTERRUPTED / REQUEST_FAILED` 并输出中文提示。

### 10.27 WebSocket连接属性错误与断开异常 (2026-02-10)

*   **问题描述**: 集成QQ机器人时，WebSocket连接连续抛出 `AttributeError: 'coroutine' object has no attribute 'handle_connection'`，`WebSocketManager` 中 `disconnect` 方法缺失，以及 `remote_address` 属性访问错误。
*   **原因分析**:
    *   **协程未等待**: `get_websocket_adapter` 是异步函数，在路由中调用时未使用 `await`，导致返回协程对象而非实例。
    *   **接口不兼容**: `adapter.py` 使用了 `disconnect` 方法，但 `WebSocketManager` 仅提供 `remove_connection`。
    *   **属性缺失**: FastAPI 的 `WebSocket` 对象（继承自 Starlette）没有 `remote_address` 属性（属于 `websockets` 库），应使用 `client` 属性或 `scope`。
    *   **握手缺失**: `adapter.py` 中 `handle_connection` 未调用 `websocket.accept()`，导致连接未完成握手即被关闭。
*   **解决方案**:
    *   路由层添加 `await`。
    *   适配器层统一使用 `remove_connection` 并补全 `accept()`。
    *   管理器层添加对 `client` 和 `scope` 的属性检查，兼容不同类型的 WebSocket 对象。
*   **验证**: 编写 `tests/verify_websocket_fix.py` 模拟多种 WebSocket 对象进行连接测试，验证通过。

### 10.27 WebSocket 适配器初始化导出缺失 (2026-02-10)

*   **问题描述**: 服务启动时触发 `initialize_default_services`，导入 WebSocket 适配器初始化函数失败，应用启动直接退出。
*   **复现步骤**:
    *   启动后端服务（`python main.py`）。
    *   观察启动日志出现 `ImportError: cannot import name 'initialize_websocket_adapter'`。
*   **预期行为**: 生命周期可正常注册 WebSocket 适配器，服务启动成功。
*   **实际行为**: 导入失败导致 FastAPI lifespan 启动失败。
*   **原因分析**:
    *   WebSocket 适配器重构后，仅保留 `get_fastapi_websocket_adapter` 的向后兼容导出，缺失 `initialize_websocket_adapter` 与 `shutdown_websocket_adapter`。
*   **解决方案**:
    *   在适配器模块补齐初始化与关闭函数并导出，确保生命周期管理器可正常导入与调用。

### 10.146 QQ adapter WebSocket 连接不稳定（启动即断、重启后端连不上） (2026-07-10)
*   **问题描述**: QQ adapter（dual_qq 模式）与后端 WebSocket 连接玄学不稳定：启动时连接立即断开（1006，Duration 0.01s）又重连；重启后端后 QQ adapter 连不上后端；只有后端和 QQ adapter 同时启动才能连上。日志显示同一秒内建立两个完全相同的连接（client_id 都是 qq_private_10001）后立即断开（1006），然后重连。
*   **复现步骤**:
    1. 启动后端 main.py
    2. 启动 dual_qq_adapter.py
    3. 观察日志：同一秒内建立两个相同 client_id 的 WebSocket 连接，Duration 0.01s 后断开（1006），然后重连
    4. 单独重启后端，QQ adapter 无法重连（需指数退避很久或直接放弃）
    5. 只有后端和 QQ adapter 同时启动才能连上
*   **预期行为**:
    1. QQ adapter 启动后稳定连接后端，不出现启动即断又重连
    2. 重启后端后 QQ adapter 能在数秒内自动重连
    3. dual_qq 两个 adapter 的连接能被后端区分（不同 client_id）
*   **实际行为**:
    1. 启动时连接立即断开（1006，Duration 0.01s）又重连
    2. 重启后端后 QQ adapter 连不上后端（指数退避导致长时间无法重连）
    3. dual_qq 两个 adapter 创建相同 client_id，后端无法区分
*   **根因**:
    1. 客户端 _ws_connect 设置 ping_interval=None，完全依赖服务端 ping，连接空闲时可能被关闭
    2. 后端 _auto_start_engine 在 WebSocket 处理中懒加载 C++ 调度引擎，engine.start() 同步阻塞事件循环导致连接异常断开
    3. dual_qq 两个 adapter 的 master_qq_id 相同，创建相同 session_id 和 client_id，导致两个完全相同的连接同时建立
    4. 重连策略不合理：后端重启时使用指数退避，重试间隔增长到 8 秒，用户感觉连不上
*   **修复方案**:
    1. utils.py _ws_connect 启用 ping_interval=20, ping_timeout=10，客户端主动心跳
    2. lifespan.py 启动阶段 asyncio.to_thread(ensure_scheduler_started) 预启动调度引擎，避免懒加载阻塞事件循环
    3. session.py 新增 _client_id 属性，dual_qq 模式下包含 role_id 区分连接
    4. connection.py 后端未启动时固定 2 秒重试，master session delay_cap 从 8s 降到 5s
*   **验证**:
    1. `py_compile 和 ruff check 全部通过`
    2. `实际运行验证待用户确认`

### 10.147 QQ adapter 长时间运行后重启后端不自动重连（连接循环 task 静默死亡） (2026-07-10)
*   **问题描述**: QQ adapter 运行较长时间后，重启后端，QQ adapter 不会自动重连后端，必须两者同时重启才能连上。表现为连接循环 task 静默死亡但 session.running 仍为 True，监控器无法检测到。
*   **复现步骤**:
    1. 启动后端和 QQ adapter，正常运行一段时间
    2. 重启后端
    3. 观察 QQ adapter：不会自动重连后端
    4. 必须同时重启 QQ adapter 才能连上
*   **预期行为**:
    1. 重启后端后 QQ adapter 在数秒内自动重连
    2. 连接循环 task 异常退出时监控器能检测到并重启 session
*   **实际行为**:
    1. 重启后端后 QQ adapter 不自动重连
    2. 连接循环 task 静默死亡，session.running 仍为 True
    3. 监控器无法检测到死 task，需要等 120 秒超时
*   **根因**:
    1. connection.py finally 块中 await receive_task 只 catch CancelledError，ConnectionClosed 等异常泄漏导致 task 死亡
    2. 内层 except Exception 吞掉异常不 re-raise，session.ws 不清理
    3. monitor.py 不检查 task.done()，只检查 session.running 标志
    4. monitor.py ws 断开时需等 120 秒超时才重启
*   **修复方案**:
    1. finally 块改为 catch BaseException 防止异常泄漏
    2. 内层 except 改为 set ws=None + re-raise 触发外层重连
    3. 添加顶层 try-finally 强制 running=False
    4. monitor 新增 _is_task_dead() 检查 task.done()
    5. monitor ws 断开时 10 秒宽限期后重启
*   **验证**:
    1. `py_compile 和 ruff check 全部通过`
    2. `实际运行验证待用户确认`

### WS-2026-07-21-01 弱网下 ReplyPolicy 延迟回复被心跳检查器误杀，消息石沉大海 (2026-07-21)
*   **问题描述**: 用户在 sleep_recovery 状态下发消息，ReplyPolicy 决策延迟 38.6s 后回复，但延迟期间连接被心跳检查器以 60s 无 ping/pong 为由关闭，延迟任务醒来后回复送不到客户端，QQ 重连后新连接没有这个延迟任务，消息彻底丢失。
*   **复现步骤**:
    1. 用户网络不稳定（ping/pong 丢失概率高）
    2. 用户发消息触发 ReplyPolicy soft_delay_reply，延迟 38.6s
    3. 延迟期间心跳检查器发现 last_heartbeat 距今 60s+，调用 websocket.close(1001) 关闭连接
    4. adapter finally 块调用 cleanup_websocket 取消 _pending_chat_batches 里的延迟任务
    5. 延迟任务被 cancel，消息直接丢弃，没有转存到 pending_messages
    6. QQ 客户端重连，新连接没有这个延迟任务，用户消息石沉大海
*   **预期行为**:
    1. 弱网下 ping/pong 丢失时，用户发消息应刷新心跳计时器，不应被误判超时
    2. 即使连接被关闭，延迟回复任务应把用户消息转存到 pending_messages，等用户重连后发新消息时由 LLM 一起回复
*   **实际行为**:
    1. FastAPIWebSocketAdapter._process_message 处理用户消息时没有更新 connection.last_activity/last_heartbeat，心跳检查器仅看 ping/pong 计时
    2. 延迟任务被 cancel 时消息直接丢弃，没有转存到 pending_messages
    3. 延迟任务自然醒来后没有检测连接状态，断开时仍尝试发送流式回复必然失败
*   **根因**:
    1. FastAPIWebSocketAdapter._process_message 遗漏了 last_activity 更新逻辑（WebSocketManager 路径有，adapter 路径没有）
    2. ReplyPolicy 延迟回复任务没有 try/except CancelledError 包裹，被 cancel 时消息丢失
    3. 延迟任务醒来后没有检测连接状态，断开时仍尝试发送
*   **修复方案**:
    1. P0: adapter._process_message 收到任何客户端消息时刷新 connection.last_activity 和 last_heartbeat
    2. P1: chat_handlers._handle_chat_message_now 延迟 sleep 用 try/except CancelledError 包裹，被 cancel 时转存到 pending_messages
    3. P2: 延迟 sleep 自然醒来后调用 _is_websocket_disconnected 检测连接状态，断开时同样转存到 pending_messages
    4. 新增 _is_websocket_disconnected 辅助方法（复用 WebSocketManager._is_starlette_websocket_closed + 兜底 application_state/client_state/close_code 检测）
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\character_daily\verify_delayed_reply_resend.py`
    2. `venv_core\Scripts\python.exe -m ruff check core\interfaces\websocket\adapters\adapter.py core\interfaces\websocket\adapters\handlers\chat_handlers.py`
    3. `venv_core\Scripts\python.exe -m pytest tests/character_daily/test_message_deferral.py --tb=short -q（改动前后失败数一致，确认未破坏现有测试）`

### AOS-0805-02 Android 端全局 usesCleartextTraffic=true 放开明文 HTTP (2026-08-05)
*   **问题描述**: AndroidManifest 设置 android:usesCleartextTraffic=true，全局允许所有域名明文 HTTP 通讯，正式版在公共 WiFi 下容易遭受中间人攻击。
*   **复现步骤**:
    1. 用户连接公共 WiFi，中间人劫持 HTTP 请求
    2. Retrofit/OkHttp 默认允许 cleartext，请求直接明文泄漏 token/聊天内容
*   **预期行为**:
    1. release 构建默认禁止 cleartext，debug 构建可按需放开以便本地联调
    2. 如需内网 HTTP，走 domain-config 显式 whitelist
*   **实际行为**:
    1. AndroidManifest usesCleartextTraffic=true 全局放开；network_security_config 也无 debug-overrides 分层
*   **根因**:
    1. 早期开发阶段联调 HTTP 方便，直接全局放开，未在上线前收紧
*   **修复方案**:
    1. 删除 Manifest 的 usesCleartextTraffic 属性，依赖 network_security_config 生效
    2. network_security_config 中 base-config cleartextTrafficPermitted=false；新增 debug-overrides 块在 debuggable=true 时放开 cleartext 并允许用户证书(便于 Charles 抓包)
*   **验证**:
    1. `:app:compileDebugKotlin exit 0`
    2. `手动安装 release variant 后访问任意 HTTP URL 预期被 cleartext 拦截`

### WS-403-001 Android 端 WebSocket 反复 403（buildWsUrl 协议头转换 bug） (2026-08-09)
*   **问题描述**: Android 端 WebSocket 连接反复返回 403 Forbidden。后端日志：[WARNING] 拒绝未匹配的 WebSocket 连接（落入静态文件挂载点）: path=//192.168.31.225:8000/api/v1/ws；uvicorn 访问日志：WebSocket //192.168.31.225%3A8000/api/v1/ws?token=...&user_id=mobile_user 403。path 中包含了本应是 host:port 的 //192.168.31.225:8000 段，且 ':' 被 URL 编码成 %3A。
*   **复现步骤**:
    1. 后端启动，监听 192.168.31.225:8000
    2. Android 端设置后端地址为 http://192.168.31.225:8000（validateBackendUrl 强制 http(s):// 前缀）
    3. WebSocketManager.connect() 调用 buildWsUrl 构造 ws URL
    4. buildWsUrl 中 replaceFirst("^http", "ws") 字面量匹配不生效，wsBase 仍为 http://192.168.31.225:8000
    5. 兜底逻辑拼成 wss://http://192.168.31.225:8000/api/v1/ws
    6. OkHttp 解析：scheme=wss, host=http, path=//192.168.31.225:8000/api/v1/ws
    7. baseUrlInterceptor 修正 host=192.168.31.225, port=8000，但 path 未修正
    8. 服务端收到 path=//192.168.31.225%3A8000/api/v1/ws，匹配不到 /api/v1/ws 路由，落入静态文件挂载点返回 403
*   **预期行为**:
    1. buildWsUrl 把 http://192.168.31.225:8000 转成 ws://192.168.31.225:8000/api/v1/ws
    2. OkHttp 解析：scheme=ws, host=192.168.31.225, port=8000, path=/api/v1/ws
    3. 服务端收到 path=/api/v1/ws，匹配 WebSocket 路由，连接成功
*   **实际行为**:
    1. buildWsUrl 把 http://192.168.31.225:8000 拼成 wss://http://192.168.31.225:8000/api/v1/ws
    2. OkHttp 解析：host=http, path=//192.168.31.225:8000/api/v1/ws
    3. baseUrlInterceptor 修正 host/port 但 path 仍为 //192.168.31.225:8000/api/v1/ws
    4. 服务端收到畸形 path，落入静态文件挂载点返回 403
*   **根因**:
    1. Kotlin String.replaceFirst(oldValue: String, newValue: String) 是字面量匹配，'^http' 只匹配字面 5 个字符，不匹配以 http 开头的字符串
    2. 代码作者误以为 replaceFirst 支持 ^ 正则锚点，实际需要传入 Regex 对象才支持正则
    3. validateBackendUrl 强制 http(s):// 前缀，意味着所有用户输入都会命中这个 bug，而非只有无协议头的场景
*   **修复方案**:
    1. 提取 normalizeWsScheme 到 companion object，用 startsWith 显式分支：https:// 转 wss://、http:// 转 ws://、已有 ws(s):// 不变、无协议头补 wss://
    2. 用 internal 可见性便于单元测试覆盖
    3. 顺带修复 CompanionModelTab.kt 缺失的 Box/TextOverflow import（预先存在的编译错误）
*   **验证**:
    1. `python tests/scripts/android_ws_url/verify_ws_url_scheme_fix.py（9 用例全部通过，旧实现复现畸形 URL，新实现 host/path 解析正确）`

### QR-20260816-01 WebSocket 发送时连接已关闭仍重试并刷 ERROR (2026-08-16)
*   **问题描述**: errors_20260815.json 连续 5 条 "Failed to send message: Unexpected ASGI message 'websocket.send', after sending 'websocket.close'" 后再报 "Failed to send message after 3 retries"。
*   **复现步骤**:
    1. 客户端连接 WebSocket 后异常断开或服务端已发送 close
    2. message_sending.send_with_retry 再次调用 send_text/send
    3. uvicorn websockets_impl 抛 RuntimeError "Unexpected ASGI message 'websocket.send'..."
*   **预期行为**:
    1. 识
    2. 别
    3. 为
    4. 连
    5. 接
    6. 断
    7. 开
    8. ，
    9. 立
    10. 即
    11. 清
    12. 理
    13. 连
    14. 接
    15. 并
    16. 返
    17. 回
    18. F
    19. a
    20. l
    21. s
    22. e
    23. ，
    24. 不
    25. 再
    26. 重
    27. 试
    28. 、
    29. 不
    30. 刷
    31. E
    32. R
    33. R
    34. O
    35. R
    36. 日
    37. 志
*   **实际行为**:
    1. _
    2. i
    3. s
    4. _
    5. d
    6. i
    7. s
    8. c
    9. o
    10. n
    11. n
    12. e
    13. c
    14. t
    15. _
    16. e
    17. x
    18. c
    19. e
    20. p
    21. t
    22. i
    23. o
    24. n
    25. 未
    26. 匹
    27. 配
    28. 该
    29. 信
    30. 号
    31. ，
    32. 走
    33. 普
    34. 通
    35. 错
    36. 误
    37. 分
    38. 支
    39. 重
    40. 试
    41. 3
    42. 次
    43. 并
    44. 记
    45. 录
    46. 4
    47. 条
    48. E
    49. R
    50. R
    51. O
    52. R
*   **根因**:
    1. disconnect_signals 缺少 Starlette/uvicorn 在 close 后 send 的 RuntimeError 特征串
*   **修复方案**:
    1. message_sending.py 增加 "unexpected asgi message" / "after sending 'websocket.close'" / "response already completed" 识别
    2. 显式 import websockets.exceptions 避免 websockets>=11 属性访问 AttributeError
*   **验证**:
    1. `venv_core tests/scripts/websocket_errors/verify_debug_20260815_20260816.py 覆盖该错误串识别与原有断开识别回归`

### QR-20260824-TELEGRAM-MAIN-HOSTING Telegram 未由 app.yaml 统一控制且托管状态存在假就绪 (2026-08-24)
*   **问题描述**: Telegram 本应随主程序直接启动，但配置仍分散在独立 JSON 和环境变量；主程序只提交后台任务就记录已启动，异常后无法可靠恢复，媒体路由与 WebSocket 发送也有丢消息风险。
*   **复现步骤**:
    1. 检查 AppSettings 与 config/yaml/app.yaml，找不到 telegram 配置段
    2. 检查 get_telegram_adapter_settings，发现从 config/telegram_config.json 读取并允许 TELEGRAM_ENABLED 覆盖
    3. 检查 lifespan，发现 spawn 后立即记录 STARTED 且不保存任务引用
    4. 检查 handler 注册和 session 发送循环，发现宽泛 handler 排在媒体前且 send 异常后 payload 已出队
*   **预期行为**:
    1. Telegram 是否启动只由 app.yaml 的 telegram.enabled 决定，并在主程序生命周期内托管
    2. 只有 polling 确认启动后才对外报告 ready，退出和异常都能清理资源
    3. 图片、语音和文本进入正确 handler，临时断线不丢失待发消息
    4. 验证测试使用断言并覆盖启动所有权、重试和清理路径
*   **实际行为**:
    1. app.yaml 无法控制 Telegram，旧 JSON 和 TELEGRAM_ENABLED 才是实际来源
    2. 任务创建被误报为启动成功，后台失败与主程序关闭缺少闭环
    3. 媒体可能被先注册的宽泛 handler 截获，WebSocket send 失败后消息不会重入队列
    4. 旧测试即使返回 False 也可能被 pytest 计为通过
*   **根因**:
    1. Telegram 未纳入统一 Pydantic 配置模型
    2. 主程序托管仅完成了 fire-and-forget，没有定义真实就绪和关闭语义
    3. python-telegram-bot 同组 handler 的首匹配规则与队列取出后的失败语义处理不正确
    4. 测试偏向在线诊断输出，缺少离线可重复断言
*   **修复方案**:
    1. 迁移到 app.yaml telegram 段并禁止遗留环境变量覆盖开关
    2. 完善 lifespan 任务所有权、ready 状态、监督重启和幂等清理
    3. 修正媒体路由顺序、WebSocket 重连重发和空闲会话回收
    4. 新增 8 个离线专项测试和统一验证脚本
*   **验证**:
    1. `Telegram 离线专项测试 8 项通过`
    2. `Telegram 关键文件完整 Ruff 检查通过`
    3. `独立调试脚本 PowerShell 静态解析无错误`
    4. `关键 Python 文件 compileall 通过`

### WS-20260824-WIN121-ACTIVE-CARE-DELIVERY WinError 121 重连期间 Active Care 消息进入错误离线队列 (2026-08-24)
*   **问题描述**: WebSocket 长连接反复出现传输超时，Active Care 后端记录为已分发，但 QQ 端在下午多个时段没有收到主动消息。
*   **复现步骤**:
    1. 对齐 active_care_messages.log、xiaoyou_main.log 与 qq_adapter.log 的同一时间戳
    2. 统计 QQ 连接失败、重连和 proactive_message 接收记录
    3. 检查 ConversationRouter、Aveline proactive_messaging、WebSocket broadcast 与 offline_queue
    4. 模拟双角色共用主人 ID 且只有一个角色重连的离线重放
*   **预期行为**:
    1. 逻辑人格会话与真实传输 ID 分离，离线消息能在 QQ 重连后被找到
    2. 只有目标角色连接能取走主动消息，发送失败不会丢队列
    3. 短时 Windows 调度或网络抖动不触发密集重连，真实断连仍能自动恢复
*   **实际行为**:
    1. 消息被存到 shared__scope__* 队列，真实 private_* 连接重连时无法读取
    2. 多角色广播只要任一连接发送成功就被视为送达，即使目标角色没有收到
    3. 10 秒协议 ping 超时导致同一下午出现大量连接失败与重连
*   **根因**:
    1. ConversationRouter 提前返回 persona 会话时没有把 original_conversation_id 更新为真实 QQ user_id
    2. 广播和离线队列只按主人 user_id 路由，缺少角色 client_id 维度
    3. 离线重放忽略布尔发送结果，协议心跳容忍度不足
*   **修复方案**:
    1. 保留 private_* 传输 ID 并按角色 client_id 定向广播和重放
    2. 失败重放保留消息，心跳超时统一为 60 秒
    3. 精确降级 WinError 121 日志，不吞掉其他 WebSocket 异常
*   **验证**:
    1. `verify_winerror121_active_care_delivery.py 覆盖传输 ID、角色筛选、失败保留、心跳与日志降级`
    2. `test_session_heartbeat.py 6 项全部通过`
    3. `Ruff 与 py_compile 通过`
