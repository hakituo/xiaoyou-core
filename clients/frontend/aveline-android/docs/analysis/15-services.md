# 15 - 服务层

## 服务清单（7个后台服务 + 3个管理器）

### AvelineForegroundServiceV2 — 前台常驻服务

**文件**: `services/AvelineForegroundServiceV2.kt` (343行)

功能完整的前台服务，实现后台常驻：

**核心能力**:
- **WebSocket 保活**: 前台 Notification 保持进程不被杀死
- **上下文同步**: 每5分钟自动采集设备上下文并同步到后端
- **WebSocket 消息处理**: 实时接收 AI 消息 → 本地通知
- **PhoneAction 执行**: 接收后端指令 → 执行手机操作

**通知管理**:
- 两个通知：前台状态通知（NOTIFICATION_ID=1001）+ 后端消息通知（BACKEND_NOTIFICATION_ID=1002）
- 通知渠道：`aveline_backend_v2`

**生命周期**:
- `start(context)` / `stop(context)` — 静态启动/停止
- `updateBackendUrl(url)` — 运行时更新后端地址（自动重连 WebSocket）
- `getInstance()` — 获取当前实例（Volatile 单例）

**注入依赖**: ContextRepository, AppPreferences, WebSocketManager, NotificationManager, PhoneActionExecutor, ApplicationContext

### AvelineNotificationService — 通知监听服务

**文件**: `services/AvelineNotificationService.kt` (111行)

继承 `NotificationListenerService`，实现通知拦截：

- `onNotificationPosted(sbn)` — 捕获所有系统通知
- `onNotificationRemoved(sbn, reason)` — 捕获通知移除事件
- 通知数据组织为 NotificationEntity → Room 本地缓存
- 支持 `isSent` 标记进行批量同步

### AvelineFirebaseMessagingService — FCM 推送

**文件**: `services/AvelineFirebaseMessagingService.kt` (97行)

继承 `FirebaseMessagingService`：

- `onMessageReceived` — 收到远程推送 → 本地通知
- `onNewToken` — Token 更新 → 注册到后端

### BootCompletedReceiver — 开机自启动

**文件**: `services/BootCompletedReceiver.kt` (43行)

BroadcastReceiver：
- 监听 `BOOT_COMPLETED` + `LOCKED_BOOT_COMPLETED`
- 检查常驻模式开关 → 自动启动 ForegroundService + 周期同步

### TTSEngine — 文字转语音引擎

**文件**: `services/TTSEngine.kt` (274行)

后端 TTS 方案：
1. 调用 `/api/v1/tts` 获取 base64 WAV
2. 缓存到本地文件（`tts_cache/`）
3. MediaPlayer 播放，带进度更新

**状态机**:
```
Idle → Loading → Playing → Paused/Idle
Playing ↔ Paused（点击暂停/继续）
Error → Idle（错误恢复）
```

**功能**:
- `playMessage(messageId, text, voiceId?)` — 播放/暂停切换
- `pause()` / `resume()` — 暂停/恢复
- `stop()` — 停止播放，释放资源
- `seekTo(position)` — 跳转播放位置
- 进度通过 `StateFlow<TTSState>` 暴露

### VoiceInputManager — 语音输入

**文件**: `services/VoiceInputManager.kt` (175行)

Android 原生语音识别：

- 使用 `SpeechRecognizer` + `RecognizerIntent`
- `RecognitionListener` 回调：`onPartialResults`（部分识别）→ `partialText` + `amplitude`
- 状态：Idle → Recording → Processing → Result/Error
- 权限检查：`RECORD_AUDIO`

### FileUploadManager — 文件上传

**文件**: `services/FileUploadManager.kt` (353行)

**功能**:
- `uploadImage(uri)` — 从 URI 上传图片
- `uploadFile(uri)` — 通用文件上传
- 文件大小验证（最大 10MB）
- 文件类型验证（仅支持 jpeg/png/gif/webp/bmp）
- 多部分上传（Multipart request）
- 进度跟踪 → `StateFlow<UploadState>`

**路径方案**:
1. 优先调用 `/api/v1/upload`（通用）
2. 如果是图片，可选择 `/api/v1/study/upload`

### AvelineNotificationManager — 通知管理器

**文件**: `services/AvelineNotificationManager.kt` (327行)

**3个通知渠道**:
| 渠道 | ID | 优先级 | 用途 |
|------|-----|--------|------|
| 消息通知 | aveline_messages | HIGH | AI 消息推送 |
| 警告通知 | aveline_warnings | HIGH | 生命状态警告 |
| 系统通知 | aveline_system | DEFAULT | 系统更新/状态 |

**通知类型**:
- `showMessageNotification(title, body)` — 消息通知（带点击跳转）
- `showWarningNotification(title, body)` — 警告通知
- `showSystemNotification(title, body)` — 系统通知
- PendingIntent 都指向 MainActivity

### PhoneActionExecutor — 手机操作执行器

**文件**: `services/PhoneActionExecutor.kt` (551行)

已在之前的分析中详细介绍。14种操作类型，权限降级处理，协程支持。

### ServerDiscoveryManager — 服务端自动发现

**文件**: `services/discovery/ServerDiscoveryManager.kt` (329行)

零配置启动的核心：

**三级发现策略**:
1. 检查当前已配置 URL 是否可达（TCP 连接测试，800ms 超时）
2. UDP 广播监听（端口 28899，Magic: "AVELINE_SERVER"，5s 超时）
3. 网段扫描兜底（9个常见网关 × 4个端口 + 9个子网 × 254台 × 4端口）

**WiFi 多播锁**: Android 默认过滤 UDP 广播包，需要 `WifiManager.MulticastLock`

**实际网段优先**: 通过 `WifiManager.dhcpInfo` 获取本机网关和子网，优先扫描本网段

### DataSyncManager / DataSyncWorker

**文件**: `services/worker/DataSyncManager.kt`, `DataSyncWorker.kt`

WorkManager 周期同步：
- 15分钟最小周期
- 网络连接约束（NetworkType.CONNECTED）
- `ExistingPeriodicWorkPolicy.KEEP` — 不重复创建
- 同步内容：设备上下文 + 未发送的 notificaiton + 未发送的健康数据
