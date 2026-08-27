# 05 - WebSocket 实时通信层

## WebSocketManager — 持久化连接管理器

`@Singleton` 注入，通过 OkHttp WebSocket 实现与后端的长连接。管理连接生命周期、心跳保活、自动重连、消息解析。

### 连接管理

```
connect(forceReconnect=false)
  → 构建 WebSocket URL（ws/wss + token + user_id 参数）
  → 去重检查（同URL+已连接则跳过）
  → 设置 manualDisconnect=false
  → 取消旧的重连任务
  → 创建 OkHttp WebSocket 连接

disconnect()
  → manualDisconnect=true
  → 停止心跳 + 取消重连
  → 关闭 WebSocket (code=1000 "client_disconnect")
```

### 自动重连机制

```
onFailure / onClosed（非手动断开）
  → scheduleReconnect()
    → 指数退避：baseDelay = RetryUtils.calculateExponentialBackoff(
        attempt, initialDelay=1000ms, multiplier=1.6, maxDelay=30000ms
      )
    → 随机 Jitter：+0~500ms
    → 强制重连 (forceReconnect=true)
```

**重连次数序列**: 1s → 1.6s → 2.56s → 4.1s → 6.6s → ... → 30s（上限）

### 心跳机制

```
connection_established 消息
  → 解析 heartbeat_interval（默认30s）
  → startHeartbeat(interval)
    → 每 interval 秒发送 {"type":"ping","timestamp":...}
```

### 重连同步

重连成功后自动发送：
```json
{"type":"reconnect","platform":"android","timestamp":...}
```

后端返回 `reconnect_sync` 消息，包含：
- `currentModel` — 当前模型
- `emotionState` — 当前情绪状态
- `lifeStatus` — 生命模拟状态

## WebSocketMessage — 15种消息类型

### 结构

```
sealed class WebSocketMessage
  ├── TextMessage          — 文本消息
  ├── ResponseChunk        — 流式响应块
  ├── ResponseDone         — 响应完成
  ├── EmotionUpdate        — 情绪更新
  ├── LifeStatusUpdate     — 生命状态推送（每秒广播）
  ├── RitualEvent          — 仪式事件
  ├── SpontaneousReaction  — 自发反应
  ├── PhoneActionCommand   — 手机操作指令
  ├── ImageResult          — 图片生成结果
  ├── Notification         — 通知推送
  ├── ConnectionEstablished — 连接建立确认
  ├── ReconnectSync        — 重连同步数据
  ├── Ping                 — 心跳请求
  ├── Pong                 — 心跳应答
  ├── Error                — 错误消息
  └── Unknown              — 未识别消息（保留原始JSON）
```

### 消息解析流程

```
parseMessage(rawJson)
  → JSONObject(text)
  → 读取 type 字段
  → 按类型分发：
    "emotion_update"        → EmotionUpdate（含 colors[] + emotion_mix{}）
    "connection_established" → ConnectionEstablished（触发 startHeartbeat）
    "reconnect_sync"        → ReconnectSync（含 emotion_state + life_status）
    "life_status"           → LifeStatusUpdate（含 life{} + bio{}）
    "ritual_event"          → RitualEvent
    "spontaneous_reaction"  → SpontaneousReaction
    "phone_action"          → PhoneActionCommand（解析 params）
    "image_result"          → ImageResult
    "notification"          → Notification
    "message"               → 按 subtype 分发：
        "response_done"     → ResponseDone
        "response_chunk"    → ResponseChunk（content + chunkIndex + emotion）
        其他                → TextMessage
    "error"                 → Error
    "pong"                  → Pong
    其他                    → Unknown（保留 rawJson）
```

### 关键设计

1. **额外缓冲区**: `MutableSharedFlow(extraBufferCapacity=64)` — 允许缓存64条消息，避免慢消费者丢消息
2. **线程安全**: webSocketRef 使用 `AtomicReference`，url 使用 `AtomicReference`，重连计数使用 `AtomicInteger`
3. **手动断开标记**: `AtomicBoolean` 防止自动重连干扰用户主动断开
4. **URL 变更处理**: 当检测到 URL 变化时，先关闭旧连接（code=1000 "url_changed"），再建立新连接
5. **coroutine scope**: IO 线程，避免阻塞主线程
