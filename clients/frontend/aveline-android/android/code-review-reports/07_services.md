# Services 服务层代码审查报告

## 审查概览

本报告对 `services/` 目录下共 17 个 Kotlin 文件进行了逐行审查,涵盖 FCM 推送、前台服务、通知管理、通知监听、文件上传、手机动作执行、TTS 引擎、语音输入、服务发现、Widget 组件、数据同步 Worker 等模块。

### 审查文件清单

| # | 文件 | 行数 | 问题数 |
|---|------|------|--------|
| 1 | AvelineFirebaseMessagingService.kt | 97 | 3 |
| 2 | AvelineForegroundServiceV2.kt | 350 | 8 |
| 3 | AvelineNotificationManager.kt | 327 | 3 |
| 4 | AvelineNotificationService.kt | 111 | 4 |
| 5 | BootCompletedReceiver.kt | 43 | 3 |
| 6 | FileUploadManager.kt | 353 | 7 |
| 7 | MediaActionExecutor.kt | 107 | 2 |
| 8 | NotificationActionExecutor.kt | 76 | 2 |
| 9 | PhoneActionExecutor.kt | 464 | 4 |
| 10 | TTSEngine.kt | 274 | 6 |
| 11 | VoiceInputManager.kt | 175 | 4 |
| 12 | discovery/ServerDiscoveryManager.kt | 340 | 6 |
| 13 | widget/AvelineWidgetProvider.kt | 177 | 4 |
| 14 | widget/AvelineWidgetWorker.kt | 146 | 4 |
| 15 | widget/WidgetData.kt | 103 | 2 |
| 16 | worker/DataSyncManager.kt | 40 | 1 |
| 17 | worker/DataSyncWorker.kt | 149 | 3 |

### 问题严重程度统计

| 严重程度 | 数量 | 说明 |
|----------|------|------|
| 🔴 严重 | 8 | 可能导致崩溃、数据丢失、功能完全失效 |
| 🟠 中等 | 22 | 影响性能、可维护性、边界场景可靠性 |
| 🟡 轻微 | 27 | 代码规范、可读性、小优化点 |

---

## 逐文件审查

### 1. AvelineFirebaseMessagingService.kt

#### 问题1: 🔴 serviceScope 未在 onDestroy 中取消,协程泄漏

- 位置: AvelineFirebaseMessagingService.kt:30, 32-36
- 问题描述: `serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)` 在第 30 行创建,但整个类没有重写 `onDestroy()` 来取消该 scope。`FirebaseMessagingService` 会被系统多次创建和销毁,每次创建都会产生一个新的 `serviceScope`,而旧的 scope 及其 SupervisorJob 不会被取消,导致协程和持有的引用(如 `apiService`、`appPreferences`)泄漏。
- 建议方案: 重写 `onDestroy()`,调用 `serviceScope.cancel()`:
  ```kotlin
  override fun onDestroy() {
      serviceScope.cancel()
      super.onDestroy()
  }
  ```

#### 问题2: 🟡 Token 上传失败无重试机制

- 位置: AvelineFirebaseMessagingService.kt:79-92
- 问题描述: `uploadToken` 在 `onFailure` 时仅打印日志,不进行重试。如果上传时网络不可用,token 将丢失,直到下次 `onNewToken` 回调(可能很久才触发)才会重新上传。后端将无法向该设备推送消息。
- 建议方案: 使用指数退避重试(如 WorkManager 或简单的 delay+retry),或将 token 暂存到本地,在下一次网络恢复时重新上传。

#### 问题3: 🟡 onCreate 每次都刷新并上传 Token

- 位置: AvelineFirebaseMessagingService.kt:32-36
- 问题描述: `onCreate()` 中调用 `refreshAndUploadToken()`,而 FCM 服务可能被系统多次创建。每次创建都会触发 token 刷新和网络请求,造成不必要的网络流量和电量消耗。
- 建议方案: 在本地缓存上次上传的 token,仅在 token 变化时才上传。可在 `uploadToken` 中对比 `appPreferences.lastFcmToken`,相同则跳过。

---

### 2. AvelineForegroundServiceV2.kt

#### 问题1: 🔴 startForeground 未声明 foregroundServiceType,Android 14+ 崩溃

- 位置: AvelineForegroundServiceV2.kt:102
- 问题描述: `startForeground(NOTIFICATION_ID, createForegroundNotification())` 未传入 `foregroundServiceType` 参数。从 Android 14 (API 34) 起,系统要求前台服务必须在 manifest 中声明 `android:foregroundServiceType` 并在 `startForeground()` 中指定对应类型,否则抛出 `MissingForegroundServiceTypeException` 导致崩溃。该服务用于 WebSocket 连接和数据同步,应声明为 `dataSync` 或 `connectedDevice` 类型。
- 建议方案:
  1. 在 AndroidManifest.xml 的 `<service>` 标签中添加 `android:foregroundServiceType="dataSync"`;
  2. 修改 `startForeground` 调用:
     ```kotlin
     if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
         startForeground(NOTIFICATION_ID, createForegroundNotification(),
             ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
     } else {
         startForeground(NOTIFICATION_ID, createForegroundNotification())
     }
     ```

#### 问题2: 🔴 updateBackendUrlInternal 未实际更新后端 URL,url 参数被忽略

- 位置: AvelineForegroundServiceV2.kt:184-187
- 问题描述: 方法名为 `updateBackendUrlInternal`,接收 `url` 参数,但方法体中仅检查 `url.isEmpty()` 后直接调用 `webSocketManager.connect(forceReconnect = true)`,**从未将 url 设置到任何地方**(如 `appPreferences.backendUrl` 或 `webSocketManager` 的配置)。这意味着用户在后端设置页面切换 URL 后,WebSocket 连接的目标地址不会改变,功能完全失效。
- 建议方案: 在调用 `connect` 前,实际更新后端地址:
  ```kotlin
  fun updateBackendUrlInternal(url: String) {
      if (url.isEmpty()) return
      appPreferences.backendUrl = url
      webSocketManager.updateBaseUrl(url) // 如果 WebSocketManager 有此方法
      webSocketManager.connect(forceReconnect = true)
  }
  ```

#### 问题3: 🟠 handlePhoneAction 手动拼接 JSON 字符串,易出错

- 位置: AvelineForegroundServiceV2.kt:216-228
- 问题描述: `handlePhoneAction` 通过字符串模板 `"""{"type":"phone_action_result","data":$resultJson}"""` 手动拼接 JSON。如果 `resultJson` 中包含特殊字符(如未转义引号),会导致 JSON 格式错误,后端解析失败。虽然 `resultJson` 来自 kotlinx.serialization 序列化,通常安全,但这种模式是代码坏味道,未来维护时容易引入注入漏洞。
- 建议方案: 使用 `buildJsonObject` 或 `JsonObject` 构造消息:
  ```kotlin
  val message = buildJsonObject {
      put("type", "phone_action_result")
      put("data", Json.encodeToJsonElement(result))
  }.toString()
  ```

#### 问题4: 🟠 parsePhoneAction 函数过长且参数解析脆弱

- 位置: AvelineForegroundServiceV2.kt:230-311
- 问题描述: `parsePhoneAction` 函数长达 82 行,包含一个巨大的 `when` 表达式,覆盖 14 种动作类型。其中局部辅助函数 `str` 使用 `p[key]?.toString()?.trim('"')` 解析字符串,这种方式很脆弱——如果 JSON 值是 `"hello"world"`,`trim('"')` 只会去掉首尾引号,无法正确处理。此外,所有默认值都硬编码在解析逻辑中(如 `reminderMinutes` 默认 10),不利于维护。
- 建议方案:
  1. 将 `parsePhoneAction` 拆分为独立的解析函数或使用策略模式;
  2. 使用 `kotlinx.serialization` 的 `Json.decodeFromJsonElement` 直接将 `command.params` 反序列化为对应的 `PhoneAction` 子类,避免手动解析。

#### 问题5: 🟠 上下文同步首次延迟 5 分钟才执行

- 位置: AvelineForegroundServiceV2.kt:313-332
- 问题描述: `startContextSync` 的 `while(isActive)` 循环中,`delay(CONTEXT_SYNC_INTERVAL_MS)` 放在循环开头,意味着服务启动后第一次同步要等 5 分钟才执行。如果用户刚开机,这段时间内后端无法获取设备上下文。
- 建议方案: 将同步逻辑放在 delay 之前,或使用 `delay` 的变体在首次执行时跳过延迟:
  ```kotlin
  while (isActive) {
      try {
          // 先执行同步
          if (appPreferences.isContextSyncEnabled) {
              val context = contextRepository.getFullContext()
              contextRepository.syncToBackend(context)
              appPreferences.lastSyncTimestamp = System.currentTimeMillis()
          }
      } catch (e: Exception) { ... }
      delay(CONTEXT_SYNC_INTERVAL_MS) // 然后等待
  }
  ```

#### 问题6: 🟡 updateNotification 和 showBackendNotification 未设置 PendingIntent

- 位置: AvelineForegroundServiceV2.kt:166-176, 339-349
- 问题描述: `updateNotification` 和 `showBackendNotification` 创建的通知都没有设置 `setContentIntent`,用户点击通知后无任何反应。前台服务通知(行 166)和后端推送通知(行 339)都应该能点击跳转到主界面。
- 建议方案: 复用 `createForegroundNotification` 中的 PendingIntent 构造逻辑,为这两个通知也设置 `setContentIntent`。

#### 问题7: 🟡 前台通知使用系统图标而非应用图标

- 位置: AvelineForegroundServiceV2.kt:159, 170, 343
- 问题描述: 通知使用 `android.R.drawable.ic_menu_info_details` 和 `android.R.drawable.ic_dialog_info` 等系统内置图标,而非应用自己的图标资源。这在状态栏中显示为通用系统图标,品牌识别度低,且不同 Android 版本图标样式不一致。
- 建议方案: 使用 `R.drawable.ic_notification` 或 `R.mipmap.ic_launcher` 等应用图标资源。

#### 问题8: 🟡 observeWebSocketMessages 中的 else -> Unit 可能遗漏新消息类型

- 位置: AvelineForegroundServiceV2.kt:210
- 问题描述: `when (message)` 的 `else -> Unit` 静默忽略所有未识别的消息类型。如果后端新增了消息类型(如 `SystemAlert`、`UpdateEvent`),前端不会处理也不会报错,问题难以发现。
- 建议方案: 在 `else` 分支添加日志:
  ```kotlin
  else -> Log.d(TAG, "未处理的消息类型: ${message::class.simpleName}")
  ```

---

### 3. AvelineNotificationManager.kt

#### 问题1: 🟠 SecurityException 被静默吞掉,无任何日志

- 位置: AvelineNotificationManager.kt:149-151, 176-178, 200-202
- 问题描述: `showMessageNotification`、`showLifeStatusWarning`、`showSystemNotification` 三处 `catch (e: SecurityException)` 的 catch 块体为空(仅有注释 `// 权限被拒绝`)。虽然有 `hasNotificationPermission()` 前置检查,但在权限被动态撤销等边缘场景下仍可能抛出 SecurityException。完全无日志输出使得这类问题无法排查。
- 建议方案: 在每个 catch 块中添加 `Log.w(TAG, "通知显示被拒绝", e)`,便于排查。

#### 问题2: 🟠 所有消息通知复用同一通知 ID,新消息覆盖旧消息

- 位置: AvelineNotificationManager.kt:42, 148
- 问题描述: 所有消息通知都使用 `NOTIFICATION_MESSAGE = 2001` 作为通知 ID。当用户收到多条消息时,后到的通知会直接覆盖前面的,用户只能看到最后一条消息,无法查看历史消息。
- 建议方案:
  1. 使用基于 sessionId 或时间戳的唯一通知 ID;
  2. 或使用 `setGroup()` 和摘要通知实现消息分组:
     ```kotlin
     .setGroup("aveline_messages_group")
     // 并在最后发送一个摘要通知
     ```

#### 问题3: 🟡 showMessageNotification 截断后仍使用 BigTextStyle,语义矛盾

- 位置: AvelineNotificationManager.kt:135-145, 251-254
- 问题描述: `showMessageNotification` 先将消息截断为 50 字符(行 135-139),然后传入 `createMessageNotification`,后者又用 `BigTextStyle().bigText(message)` 展示完整文本。BigTextStyle 的设计初衷是展示未截断的完整内容,这里传入的已是截断后的文本,使 BigTextStyle 失去意义。
- 建议方案: 要么不截断直接使用 BigTextStyle 展示完整内容,要么去掉 BigTextStyle 仅用 setContentText。建议前者,因为 BigTextStyle 正是为了显示长文本。

---

### 4. AvelineNotificationService.kt

#### 问题1: 🔴 onNotificationPosted 不去重,通知更新导致数据库洪水

- 位置: AvelineNotificationService.kt:58-93
- 问题描述: `onNotificationPosted` 在每次通知发布或更新时都会被调用。对于音乐播放器等持续更新通知的应用(可能每秒更新一次进度条),这会导致大量重复的 `NotificationEntity` 被插入数据库。例如网易云音乐(`com.netease.cloudmusic` 在 TRACKED_PACKAGES 中)播放音乐时,每秒可能产生一条新记录,一小时就是 3600 条垃圾数据。
- 建议方案:
  1. 使用 `sbn.id` + `packageName` 作为唯一键去重,仅在内容变化时插入;
  2. 或过滤掉 `FLAG_ONGOING_EVENT` 和 `FLAG_FOREGROUND_SERVICE` 类型的通知:
     ```kotlin
     if (sbn.notification.flags and Notification.FLAG_ONGOING_EVENT != 0) return
     ```

#### 问题2: 🟠 tryEmit 静默丢弃事件,缓冲区满时无感知

- 位置: AvelineNotificationService.kt:83-90
- 问题描述: `_notificationFlow.tryEmit(...)` 在缓冲区(容量 16)满时返回 false,事件被静默丢弃。如果短时间内通知密集到达(如多个应用同时推送),超出 16 条的事件全部丢失,订阅者无法感知。
- 嵌入建议方案: 改用 `emit` 挂起函数(需将 `onNotificationPosted` 改为 suspend 或用 `serviceScope.launch` 包裹),或增大 `extraBufferCapacity`,或使用 `BufferOverflow.DROP_OLDEST` 策略并记录丢弃日志。

#### 问题3: 🟠 未过滤持续型通知和前台服务通知

- 位置: AvelineNotificationService.kt:58-92
- 问题描述: 当前仅检查 `shouldTrack(packageName)`,但不区分通知类型。前台服务通知(如音乐播放、下载进度、健身追踪)会持续存在并频繁更新,这些通知通常不是用户关心的消息,却会被完整记录并同步到后端,浪费存储和流量。
- 建议方案: 在 `shouldTrack` 之后增加通知标志过滤:
  ```kotlin
  if (sbn.notification.flags and Notification.FLAG_ONGOING_EVENT != 0) return
  if (sbn.notification.flags and Notification.FLAG_FOREGROUND_SERVICE != 0) return
  ```

#### 问题4: 🟡 companion object 中的 MutableSharedFlow 为静态,生命周期不可控

- 位置: AvelineNotificationService.kt:20-25
- 问题描述: `_notificationFlow` 定义在 companion object 中,是 App 级别的静态单例。即使 `AvelineNotificationService` 被销毁,Flow 仍然存在。如果有订阅者忘记取消订阅,会导致引用泄漏。此外,`replay = 0` 意味着后订阅者无法收到之前的事件,这在某些场景下可能不符合预期。
- 建议方案: 如果确实需要 App 级事件总线,可保留但需确保订阅者在销毁时取消。否则改为实例字段,在 `onDestroy` 中完成清理。

---

### 5. BootCompletedReceiver.kt

#### 问题1: 🟠 catch (_: Exception) 吞掉所有异常,无任何日志

- 位置: BootCompletedReceiver.kt:40-41
- 问题描述: 整个开机启动逻辑被 try-catch 包裹,catch 块完全为空。如果 Hilt EntryPoint 不可用、Service 启动失败或 DataSyncManager 初始化异常,用户完全无感知,开机自启动功能静默失效。这是开机保活功能失效的常见原因,但无法排查。
- 建议方案: 至少添加日志:
  ```kotlin
  } catch (e: Exception) {
      Log.e("BootCompletedReceiver", "开机自启动失败", e)
  }
  ```

#### 问题2: 🟠 onReceive 在主线程执行可能耗时操作

- 位置: BootCompletedReceiver.kt:22-42
- 问题描述: `onReceive` 默认在主线程执行。其中 `EntryPointAccessors.fromApplication(...)` 和后续的 Service 启动、`dataSyncManager.startPeriodicSync()` 都可能在主线程造成延迟。BroadcastReceiver 的 `onReceive` 必须快速返回(系统默认 10 秒超时),否则会触发 ANR。
- 建议方案: 使用 `goAsync()` 将耗时操作转移到异步线程:
  ```kotlin
  val pendingResult = goAsync()
  Thread {
      try {
          // ... 原有逻辑
      } finally {
          pendingResult.finish()
      }
  }.start()
  ```
  或使用 WorkManager 在开机后调度一次性任务。

#### 问题3: 🟡 使用 context 而非 context.applicationContext 启动服务

- 位置: BootCompletedReceiver.kt:37
- 问题描述: `AvelineForegroundServiceV2.start(context)` 传入的是 BroadcastReceiver 的 context,其生命周期与 onReceive 调用绑定。虽然 `startForegroundService` 会将 Intent 交给系统处理,通常不会有问题,但最佳实践是使用 `context.applicationContext` 避免潜在的 Context 泄漏。
- 建议方案: `AvelineForegroundServiceV2.start(context.applicationContext)`。

---

### 6. FileUploadManager.kt

#### 问题1: 🔴 读取整个文件到内存,大文件 OOM 风险

- 位置: FileUploadManager.kt:316-335
- 问题描述: `readFileBytes` 通过 `ByteArrayOutputStream` 将整个文件读入内存为 `ByteArray`,然后在 `performUpload` 中再通过 `bytes.toRequestBody(mediaType)` 转为 RequestBody。对于 10MB 的文件,这意味着同时存在两份内存拷贝(ByteArray + RequestBody 内部缓冲),峰值内存占用约 20-30MB。在低内存设备上极易触发 OOM。
- 建议方案: 使用 OkHttp 的流式 RequestBody,直接从 InputStream 读取,避免全量加载:
  ```kotlin
  val requestBody = object : RequestBody() {
      override fun contentType() = mediaType
      override fun writeTo(sink: BufferedSink) {
          context.contentResolver.openInputStream(uri)?.use { input ->
              val source = input.source()
              sink.writeAll(source)
          }
      }
      // 可覆盖 contentLength 支持进度
  }
  ```
  或使用 OkHttp 的 `RequestBody.create(file, mediaType)` 变体(需先将 Uri 转为 File)。

#### 问题2: 🟠 readFileBytes 用 input.available() 估算大小,不可靠

- 位置: FileUploadManager.kt:319-320
- 问题描述: `input.available()` 返回的是"不阻塞情况下可读的字节数",对于某些 ContentProvider(如云端文件、压缩流),这个值可能为 0 或远小于实际大小。用它做大小校验(`if (fileSize > MAX_FILE_SIZE) return null`)可能误判。实际上,`getFileInfo` 已经通过 ContentResolver 查询了准确大小,这里的大小校验是冗余且可能错误的。
- 建议方案: 移除 `readFileBytes` 中的大小检查,仅依赖 `getFileInfo` 返回的 `OpenableColumns.SIZE`。如果仍需在流级别校验,可在读取过程中累计字节数并在超限时抛出异常。

#### 问题3: 🟠 performUpload 上传进度为伪造值,误导用户

- 位置: FileUploadManager.kt:275-280
- 问题描述: `performUpload` 在发起 HTTP 请求前将进度硬编码为 `0.5f`(50%),`bytesUploaded` 设为 `bytes.size / 2`。实际的上传过程中没有任何进度回调,用户看到的进度条从 0% 直接跳到 50% 然后等待直到成功或失败。`UploadState.Uploading` 数据类定义了 `progress`、`bytesUploaded`、`totalBytes` 字段,但都没有真实使用。
- 建议方案: 使用 OkHttp 的 `ProgressRequestBody` 包装器,在 `writeTo` 中记录已写字节数,通过 `_uploadState` 发射真实进度。

#### 问题4: 🟡 performUpload 内的 try-catch 仅重新抛出,是无效代码

- 位置: FileUploadManager.kt:257-311
- 问题描述: `performUpload` 整个函数体被 `try { ... } catch (e: Exception) { throw e }` 包裹,catch 块仅重新抛出异常,没有做任何额外处理(如日志、资源清理)。这个 try-catch 完全是多余的。
- 建议方案: 移除内层 try-catch,让异常直接抛给调用方 `uploadFile` 的 try-catch 处理。

#### 问题5: 🟡 上传失败无重试机制

- 位置: FileUploadManager.kt:240-250
- 问题描述: `uploadFile` 在异常时直接返回 `UploadResult(success=false)`,没有重试逻辑。网络抖动或临时服务器错误会导致上传失败,用户体验差。
- 建议方案: 添加简单的重试逻辑(如最多 3 次,指数退避),或使用 WorkManager 调度可重试的上传任务。

#### 问题6: 🟡 uploadFile 不支持取消,长上传无法中断

- 位置: FileUploadManager.kt:174-251
- 问题描述: `uploadFile` 是 suspend 函数,但内部没有任何 `isActive` 检查或 `suspendCancellableCoroutine` 机制。如果用户在上传过程中离开页面,协程虽然会被取消,但底层的 OkHttp `execute()` 调用是阻塞的,不会响应取消。
- 建议方案: 使用 OkHttp 的 `enqueue()` 异步调用配合 `suspendCancellableCoroutine`,在取消时 `call.cancel()`。

#### 问题7: 🟡 不支持并发上传,单一 _uploadState

- 位置: FileUploadManager.kt:96-97
- 问题描述: `_uploadState` 是单一 `MutableStateFlow<UploadState>`,如果同时上传多个文件,后一个上传的状态会覆盖前一个,无法分别跟踪每个文件的上传进度。
- 建议方案: 如果需要并发上传,可将 `uploadState` 改为 `Map<String, UploadState>` 或使用多个 UploadManager 实例。如果不需要并发,至少在文档中注明限制,并在新上传开始前检查是否有进行中的上传。

---

### 7. MediaActionExecutor.kt

#### 问题1: 🟡 未通过 Hilt 注入,手动创建实例

- 位置: MediaActionExecutor.kt:20-22(类定义);PhoneActionExecutor.kt:39(实例化处)
- 问题描述: `MediaActionExecutor` 直接通过构造函数接收 `Context`,在 `PhoneActionExecutor` 中通过 `MediaActionExecutor(context)` 手动创建。项目其他执行器(如 `PhoneActionExecutor` 本身)都使用了 `@Inject` + Hilt 注入,这里不一致。虽然功能上可行,但如果 `MediaActionExecutor` 未来需要注入其他依赖(如日志、配置),就需要重构。
- 建议方案: 添加 `@Inject constructor` 并通过 Hilt 注入到 `PhoneActionExecutor`。

#### 问题2: 🟡 dispatchMediaKeyEvent 无错误处理

- 位置: MediaActionExecutor.kt:58-60
- 问题描述: `audioManager.dispatchMediaKeyEvent(downEvent)` 和 `dispatchMediaKeyEvent(upEvent)` 调用没有 try-catch。在极少数情况下(如 AudioManager 服务未就绪),可能抛出异常。虽然外层 `PhoneActionExecutor.execute` 有 try-catch 兜底,但错误信息可能不够精确。
- 建议方案: 可保持现状(依赖外层兜底),或在方法内添加 try-catch 返回更精确的错误类型。

---

### 8. NotificationActionExecutor.kt

#### 问题1: 🟡 未通过 Hilt 注入

- 位置: NotificationActionExecutor.kt:15-16(类定义);PhoneActionExecutor.kt:42(实例化处)
- 问题描述: 与 `MediaActionExecutor` 相同的问题,手动创建实例而非 Hilt 注入。
- 建议方案: 同上,添加 `@Inject constructor`。

#### 问题2: 🟡 setInterruptionFilter 无异常保护

- 位置: NotificationActionExecutor.kt:55-58
- 问题描述: 虽然在行 48 检查了 `isNotificationPolicyAccessGranted`,但在检查和实际调用 `setInterruptionFilter` 之间,权限理论上可能被撤销(虽然在单线程中极不可能)。更实际的问题是,某些设备的 `setInterruptionFilter` 实现有 bug,可能抛出异常。
- 建议方案: 在 `setInterruptionFilter` 调用处添加 try-catch,返回错误结果而非让异常上抛。

---

### 9. PhoneActionExecutor.kt

#### 问题1: 🟠 getDefaultCalendarId 回退到 1L,可能写入无效日历

- 位置: PhoneActionExecutor.kt:126-152
- 问题描述: `getDefaultCalendarId` 查询 Google 日历,如果未找到任何日历,返回默认值 `1L`。日历 ID 1 在大多数设备上不存在,后续 `contentResolver.insert(CalendarContract.Events.CONTENT_URI, values)` 会因 `CALENDAR_ID` 无效而失败,但这里没有检查 insert 返回值是否为 null(实际上行 99 有检查)。更严重的是,如果设备没有 Google 日历但有其他日历(如华为日历),这些日历会被忽略。
- 建议方案:
  1. 移除 `ACCOUNT_TYPE = "com.google"` 过滤,查询所有日历;
  2. 找不到时返回 null 并返回失败结果,而非回退到 `1L`。

#### 问题2: 🟠 getDefaultCalendarId 执行同步 ContentProvider 查询可能阻塞

- 位置: PhoneActionExecutor.kt:126-152
- 问题描述: `getDefaultCalendarId` 执行 `contentResolver.query(...)`,这是同步 I/O 操作。它被 `createCalendarEvent` 调用,而 `createCalendarEvent` 不是 suspend 函数,被 `execute` 直接调用。虽然 `execute` 是 suspend 函数,但 `createCalendarEvent` 内部没有切换到 IO 线程,整个日历操作在调用方的线程上同步执行。如果调用方是主线程(如从 WebSocket 消息处理调用),可能导致 ANR。
- 建议方案: 将 `createCalendarEvent` 改为 suspend 函数,并用 `withContext(Dispatchers.IO)` 包裹 ContentProvider 操作。

#### 问题3: 🟡 sendSms 不支持长短信分片

- 位置: PhoneActionExecutor.kt:273-306
- 问题描述: `smsManager.sendTextMessage(action.phoneNumber, null, action.message, null, null)` 直接发送完整文本。当消息长度超过单条 SMS 限制(70 字符 Unicode 或 160 字符 GSM)时,`sendTextMessage` 在部分设备上会自动分片,但更可靠的做法是使用 `divideText` + `sendMultipartTextMessage`。
- 建议方案:
  ```kotlin
  val parts = smsManager.divideMessage(action.message)
  if (parts.size > 1) {
      smsManager.sendMultipartTextMessage(action.phoneNumber, null, parts, null, null)
  } else {
      smsManager.sendTextMessage(action.phoneNumber, null, action.message, null, null)
  }
  ```

#### 问题4: 🟡 getLocation 的失败回调忽略了错误信息

- 位置: PhoneActionExecutor.kt:418
- 问题描述: `addOnFailureListener { _ -> cont.resume(null) }` 使用 `_` 忽略了异常。当位置获取失败时,仅返回 null,不记录失败原因。如果是权限问题、位置服务关闭或超时,用户和开发者都无法区分原因。
- 建议方案: 记录失败原因:
  ```kotlin
  .addOnFailureListener { e ->
      Log.w(TAG, "位置获取失败: ${e.message}")
      cont.resume(null)
  }
  ```

---

### 10. TTSEngine.kt

#### 问题1: 🔴 TTS 缓存无大小限制,存储可能被占满

- 位置: TTSEngine.kt:254-260, 89-128
- 问题描述: `getCacheDir()` 返回 `context.cacheDir/tts_cache` 目录,每次合成 TTS 音频后通过 `audioFile.writeBytes(bytes)` 写入缓存(行 120)。但没有任何机制限制缓存总大小或清理旧文件。如果用户频繁使用 TTS 功能播放不同消息,缓存文件会无限增长,最终可能占满设备存储(cache 目录虽然系统可能在低存储时自动清理,但不能依赖)。
- 建议方案:
  1. 实现 LRU 缓存淘汰策略,保留最近 N 条(如 20 条)音频;
  2. 在 `synthesizeAndCache` 后检查目录总大小,超过阈值(如 50MB)时删除最旧文件;
  3. 在 App 启动时清理超过 N 天的缓存文件。

#### 问题2: 🟠 playMessage 未取消上一次合成协程,可能并发冲突

- 位置: TTSEngine.kt:57-87
- 问题描述: `playMessage` 调用 `stop()` 后立即 `scope.launch { synthesizeAndCache(...) }`。如果用户快速连续调用 `playMessage`(如点击多条消息的播放按钮),前一个 `synthesizeAndCache` 协程可能还在运行(网络请求未返回),`stop()` 只清理了 MediaPlayer,没有取消正在进行的网络请求。当旧请求返回时,会覆盖新的缓存文件和 MediaPlayer 状态。
- 建议方案: 在 `playMessage` 中保存 Job 引用,在开始新播放前取消上一个 Job:
  ```kotlin
  private var synthesizeJob: Job? = null
  // 在 playMessage 中:
  synthesizeJob?.cancel()
  synthesizeJob = scope.launch { ... }
  ```

#### 问题3: 🟠 playAudioFile 中 MediaPlayer 创建后异常导致资源泄漏

- 位置: TTSEngine.kt:130-169
- 问题描述: `playAudioFile` 中 `mediaPlayer = MediaPlayer().apply { ... }`,如果在 `setDataSource` 或 `prepareAsync` 之前的任何步骤抛出异常(如 `setAudioAttributes` 在某些设备上可能失败),MediaPlayer 对象已经创建但不会被释放(因为异常跳过了 `prepareAsync`,也不会触发 `onErrorListener`)。此时 `mediaPlayer` 持有已分配的 native 资源但永远不会被释放。
- 建议方案: 在 catch 块中释放 MediaPlayer:
  ```kotlin
  } catch (e: Exception) {
      mediaPlayer?.release()
      mediaPlayer = null
      Log.e(TAG, "Failed to setup MediaPlayer", e)
      _state.value = TTSState.Error(...)
  }
  ```

#### 问题4: 🟡 stop() 中异常被静默吞掉

- 位置: TTSEngine.kt:199-202
- 问题描述: `try { if (isPlaying) stop() } catch (_: Exception) {}` 完全忽略异常。`MediaPlayer.stop()` 在某些状态下(如未 prepared)会抛出 IllegalStateException,虽然这里可能确实不需要处理,但完全无日志不利于排查问题。
- 建议方案: 添加 debug 级别日志:
  ```kotlin
  catch (e: Exception) {
      Log.d(TAG, "MediaPlayer.stop 异常(通常可忽略): ${e.message}")
  }
  ```

#### 问题5: 🟡 setSpeed 中异常被静默吞掉

- 位置: TTSEngine.kt:222-227
- 问题描述: `catch (_: Exception) {}` 同样忽略所有异常。`playbackParams.speed` 设置失败时用户无感知,变速功能静默失效。
- 建议方案: 至少添加日志,或通过 StateFlow 发出警告。

#### 问题6: 🟡 Base64 解码将整个音频加载到内存

- 位置: TTSEngine.kt:119-120
- 问题描述: `Base64.decode(base64Data, Base64.DEFAULT)` 将整个 Base64 字符串解码为 `ByteArray`,然后 `audioFile.writeBytes(bytes)` 写入文件。对于较长的 TTS 音频(如 1 分钟语音约 1MB WAV,Base64 编码后约 1.3MB),内存占用尚可。但如果后端返回更长的音频,Base64 解码会产生原始数据 1.33 倍的内存占用。
- 建议方案: 短期可保持现状(语音通常不长);长期可让后端返回二进制流或文件 URL,改为流式下载。

---

### 11. VoiceInputManager.kt

#### 问题1: 🟠 SpeechRecognizer 必须在主线程创建和调用

- 位置: VoiceInputManager.kt:69-132
- 问题描述: `SpeechRecognizer.createSpeechRecognizer(context)` 和 `startListening(intent)` 必须在主线程调用,否则可能崩溃或无响应。`VoiceInputManager` 是 `@Singleton`,其方法可能从任意线程调用。`startListening` 没有线程切换逻辑。
- 建议方案: 确保在主线程创建和调用:
  ```kotlin
  fun startListening() {
      Handler(Looper.getMainLooper()).post {
          // 原有 SpeechRecognizer 创建和 startListening 逻辑
      }
  }
  ```

#### 问题2: 🟡 onError 后未重置识别器状态

- 位置: VoiceInputManager.kt:93-97
- 问题描述: `onError` 回调仅设置 `_state.value = VoiceInputState.Error(errorMessage)`,但没有调用 `speechRecognizer?.cancel()` 或 `destroy()`。识别器在出错后可能仍占用麦克风资源或处于异常状态,下次 `startListening` 可能无法正常工作。
- 建议方案: 在 `onError` 中清理识别器:
  ```kotlin
  override fun onError(error: Int) {
      val errorMessage = getErrorMessage(error)
      Log.e(TAG, "onError: $errorMessage")
      _state.value = VoiceInputState.Error(errorMessage)
      speechRecognizer?.cancel() // 释放当前识别会话
  }
  ```

#### 问题3: 🟡 stopListening 不重置状态

- 位置: VoiceInputManager.kt:135-138
- 问题描述: `stopListening()` 仅调用 `speechRecognizer?.stopListening()` 和重置 amplitude,但 `_state` 仍保持 `Recording` 或 `Processing`。用户停止录音后,UI 可能仍显示录音中状态。
- 建议方案: 在 stopListening 中重置状态:
  ```kotlin
  fun stopListening() {
      speechRecognizer?.stopListening()
      _amplitude.value = 0f
      _state.value = VoiceInputState.Processing // 等待结果
  }
  ```

#### 问题4: 🟡 onResults 后未销毁识别器,资源泄漏

- 位置: VoiceInputManager.kt:99-109
- 问题描述: `onResults` 回调设置 `VoiceInputState.Result(text)` 后不做清理。`SpeechRecognizer` 仍然持有资源(包括麦克风),直到下次 `startListening` 时才通过 `speechRecognizer?.destroy()` 释放。如果用户识别一次后不再使用,资源会一直占用。
- 建议方案: 在 `onResults` 中完成识别后清理:
  ```kotlin
  override fun onResults(results: Bundle?) {
      // ... 处理结果
      speechRecognizer?.stopListening()
      // 不要立即 destroy,因为用户可能再次启动
      // 但可以在一段时间无操作后自动 destroy
  }
  ```

---

### 12. discovery/ServerDiscoveryManager.kt

#### 问题1: 🔴 使用已废弃的 WifiManager.dhcpInfo,Android 10+ 无法获取网关

- 位置: ServerDiscoveryManager.kt:285-309
- 问题描述: `getLocalSubnet()` 和 `getLocalGateway()` 使用 `WifiManager.dhcpInfo`,该 API 从 Android 10 (API 29) 起已废弃,在 Android 11+ 上对非系统应用返回 null 或无效数据。这意味着在大多数现代设备上,实际网段和网关无法获取,只能回退到硬编码的 `COMMON_SUBNETS` 和 `COMMON_GATEWAYS`,服务发现在非标准网段(如公司网络 10.x.x.x)上基本失效。文件顶部的 `@file:Suppress("DEPRECATION")` 只是抑制了编译器警告,不解决问题。
- 建议方案: 使用 `ConnectivityManager.getLinkProperties()` 获取网关信息:
  ```kotlin
  private fun getLocalGateway(): String? {
      val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
      val linkProperties = cm.getLinkProperties(cm.activeNetwork) ?: return null
      return linkProperties.routes
          .firstOrNull { it.isGateway }?.gateway?.hostAddress
  }
  ```

#### 问题2: 🟠 multicastLock 可能在异常时泄漏

- 位置: ServerDiscoveryManager.kt:85-87
- 问题描述: `discoverServer` 中 `acquireMulticastLock()` 在前,`tryDiscoverByUdp()` 在中间,`releaseMulticastLock()` 在后。如果 `tryDiscoverByUdp()` 抛出未预期的异常(如 `OutOfMemoryError` 或 `CancellationException` 未被内层 catch),`releaseMulticastLock()` 不会执行,multicast lock 永远不会释放,导致 WiFi 模块持续工作,耗电增加。
- 建议方案: 使用 try-finally 确保释放:
  ```kotlin
  acquireMulticastLock()
  try {
      val discoveredByUdp = tryDiscoverByUdp()
  } finally {
      releaseMulticastLock()
  }
  ```

#### 问题3: 🟠 网段扫描范围过大,最坏情况耗时数十秒

- 位置: ServerDiscoveryManager.kt:197-252
- 问题描述: `scanForServer` 扫描 9 个子网 × 254 个 IP = 2286 个地址,每个地址 TCP 连接超时 300ms。虽然使用批处理(每批 30 个并行),但批内是顺序的——`async batch@{ for (port in PORTS_TO_TRY) { ... } }` 中 PORTS_TO_TRY 只有 1 个端口所以影响不大,但 254 个 IP 分 9 批(254/30≈9),每批 30 个并行连接 × 300ms = 300ms/批,9 批 = 2.7 秒/子网,9 个子网 = ~24 秒。加上网关扫描,最坏情况超过 30 秒,用户体验差。
- 建议方案:
  1. 优先扫描实际网段(已实现),如果找到立即返回(已实现 awaitAll().firstOrNull);
  2. 减少 COMMON_SUBNETS 数量,只保留最常见的 2-3 个;
  3. 将 TCP_TIMEOUT_MS 从 300ms 降到 150ms;
  4. 增加并行批次大小(如 50)。

#### 问题4: 🟠 checkServerHealth 不执行 HTTP 健康检查,方法名误导

- 位置: ServerDiscoveryManager.kt:275-280
- 问题描述: 方法注释为"更精确的健康检查（HTTP /health）",但实现仅调用 `isServerReachable(url)`,即 TCP 端口连接测试。TCP 可达不代表 HTTP 服务正常(如服务进程卡死但端口仍监听)。方法名和注释与实现不符,可能误导调用者。
- 建议方案: 要么实现真正的 HTTP /health 检查:
  ```kotlin
  suspend fun checkServerHealth(url: String): Boolean = withContext(Dispatchers.IO) {
      try {
          val request = Request.Builder().url("$url/health").build()
          uploadClient.newCall(request).execute().use { it.isSuccessful }
      } catch (e: Exception) { false }
  }
  ```
  要么修改方法名和注释,避免误导。

#### 问题5: 🟠 stopDiscovery 不取消正在进行的 TCP 扫描协程

- 位置: ServerDiscoveryManager.kt:335-339
- 问题描述: `stopDiscovery()` 仅关闭 UDP socket 和释放 multicast lock,不取消 `scanForServer` 中的协程。虽然 `scanForServer` 内部有 `if (!isActive) return@async null` 检查,但这依赖外部协程的取消传播。如果 `discoverServer` 是从一个未被取消的 scope 调用的,扫描会继续执行,浪费电量和网络资源。
- 建议方案: 维护一个 `discoveryJob: Job?` 字段,在 `stopDiscovery` 中取消它:
  ```kotlin
  fun stopDiscovery() {
      discoveryJob?.cancel()
      discoveryJob = null
      discoverySocket?.close()
      discoverySocket = null
      releaseMulticastLock()
  }
  ```

#### 问题6: 🟡 COMMON_GATEWAYS 和 COMMON_SUBNETS 数据重叠,网关扫描冗余

- 位置: ServerDiscoveryManager.kt:52-61, 215-226
- 问题描述: `COMMON_GATEWAYS` 中的 IP(如 `192.168.1.1`)本身就是 `COMMON_SUBNETS` 对应子网(如 `192.168.1`)中的 `.1` 地址。先扫网关再扫子网时,网关地址会被扫描两次。虽然先扫网关可以快速命中(网关通常就是服务器),但代码可以简化。
- 建议方案: 合并扫描逻辑,在子网扫描中优先扫描 `.1`(网关地址),然后扫其余 IP。移除单独的网关扫描步骤。

---

### 13. widget/AvelineWidgetProvider.kt

#### 问题1: 🟡 sendQuickMessage 从 BroadcastReceiver Context 显示 Toast 可能失败

- 位置: AvelineWidgetProvider.kt:约163-171
- 问题描述: `sendQuickMessage` 中 `Toast.makeText(context, "消息已发送", Toast.LENGTH_SHORT).show()` 使用的 `context` 是 `onReceive` 传入的 BroadcastReceiver context。在 Android 12+ 上,从非前台应用 context 显示 Toast 可能受限。此外,BroadcastReceiver 的 context 生命周期短,Toast 可能不显示或延迟显示。
- 建议方案: 使用 `context.applicationContext` 显示 Toast,或通过 Intent 将消息传递给 Activity/Service 处理。

#### 问题2: 🟡 sendQuickMessage 通过启动 Activity 发送消息,设计不佳

- 位置: AvelineWidgetProvider.kt:约163-171
- 问题描述: `sendQuickMessage` 通过 `Intent(context, MainActivity::class.java).putExtra("send_message", message)` + `context.startActivity(intent)` 发送消息。这种方式会打开主界面,打断用户当前操作。对于"快速发送"的交互意图,应该通过后台服务或 WorkManager 静默发送。
- 建议方案: 通过 Intent 启动一个无 UI 的 Service(或使用 WorkManager)来发送消息,完成后通过 Widget 更新显示发送状态。

#### 问题3: 🟡 硬编码颜色值而非使用颜色资源

- 位置: AvelineWidgetProvider.kt:约136-137
- 问题描述: `0xFF4CAF50.toInt()`(绿色)和 `0xFFF44336.toInt()`(红色)直接硬编码在代码中。`0xFF4CAF50.toInt()` 在 Kotlin 中会产生负数(-12345664),虽然 `setInt` 调用 `setBackgroundColor` 时能正确解析,但代码可读性差,且不支持暗色模式适配。
- 建议方案: 在 `res/values/colors.xml` 中定义颜色,通过 `ContextCompat.getColor(context, R.color.connected)` 获取。

#### 问题4: 🟡 getEmotionIconRes 始终返回应用图标,功能未实现

- 位置: AvelineWidgetProvider.kt:约153-156
- 问题描述: `getEmotionIconRes()` 注释说"实际可以创建不同情绪的图标",但始终返回 `R.mipmap.ic_launcher`。Widget 显示的情绪图标不会随情绪变化,用户无法从图标一眼看出 AI 当前情绪状态。
- 嵌入建议方案: 为不同情绪创建图标资源(如 `ic_emotion_happy`、`ic_emotion_sad`),根据 `widgetData.emotionPrimary` 返回对应资源。

---

### 14. widget/AvelineWidgetWorker.kt

#### 问题1: 🔴 缺少 @HiltWorker 注解,Worker 无法被 Hilt 实例化

- 位置: AvelineWidgetWorker.kt:27
- 问题描述: `AvelineWidgetWorker` 使用 `@AssistedInject constructor` 但**缺少 `@HiltWorker` 注解**。对比同项目 `DataSyncWorker`(行 25 有 `@HiltWorker`),缺少此注解会导致 WorkManager 无法通过 Hilt 的 WorkerFactory 创建该 Worker,运行时抛出 `IllegalStateException: Could not instantiate Worker`。Widget 后台更新功能完全无法工作。
- 建议方案: 在类上添加 `@HiltWorker` 注解:
  ```kotlin
  @HiltWorker
  class AvelineWidgetWorker @AssistedInject constructor(...)
  ```
  同时确保 Application 配置了 `HiltWorkerFactory`(在 Application 的 `onCreate` 中 `WorkManager.initialize(..., Configuration.Builder().setWorkerFactory(hiltWorkerFactory).build())`)。

#### 问题2: 🟠 WorkRequest 未设置任何约束条件

- 位置: AvelineWidgetWorker.kt:44-53
- 问题描述: `PeriodicWorkRequestBuilder<AvelineWidgetWorker>(UPDATE_INTERVAL_MINUTES, TimeUnit.MINUTES).build()` 没有设置任何 `Constraints`。Widget 更新需要从网络获取生命状态和消息历史,但当前即使用户处于无网络状态也会执行,导致 `loadHistoryFromApi` 失败。对比 `DataSyncManager`(设置了 `NetworkType.CONNECTED` 约束),这里应该也设置网络约束。
- 建议方案:
  ```kotlin
  val constraints = Constraints.Builder()
      .setRequiredNetworkType(NetworkType.CONNECTED)
      .build()
  val workRequest = PeriodicWorkRequestBuilder<AvelineWidgetWorker>(...)
      .setConstraints(constraints)
      .build()
  ```

#### 问题3: 🟡 ExistingPeriodicWorkPolicy.KEEP 不会更新已存在任务的约束

- 位置: AvelineWidgetWorker.kt:50-52
- 问题描述: 使用 `ExistingPeriodicWorkPolicy.KEEP`,如果之前已注册过同名 Work(可能约束不同),新配置(包括约束)不会生效。如果用户更新 App 后约束逻辑变化,旧配置会继续使用。
- 建议方案: 如果希望更新约束,使用 `ExistingPeriodicWorkPolicy.UPDATE`(WorkManager 2.8.0+ 支持)。

#### 问题4: 🟡 loadHistoryFromApi 失败时 Widget 显示空消息

- 位置: AvelineWidgetWorker.kt:89-93
- 问题描述: `chatRepository.loadHistoryFromApi(currentSessionId).getOrNull()?.lastOrNull()` 在网络失败时返回 null,`lastMessage` 设为空字符串。Widget 会显示"点击打开聊天..."而非真实的最近消息,用户误以为没有新消息。且 `getOrNull()` 吞掉了异常,无法排查。
- 建议方案: 保留上一次成功的消息(不覆盖 SharedPreferences 中的 `lastMessage`),或使用本地缓存(如 Room 数据库)而非每次都从 API 加载。

---

### 15. widget/WidgetData.kt

#### 问题1: 🟡 getEmotionColor 返回 String 而非 Int,使用不便

- 位置: WidgetData.kt:约80-90
- 问题描述: `getEmotionColor()` 返回十六进制字符串(如 `"#4CAF50"`),调用方需要额外解析(`Color.parseColor(...)`)才能使用。返回 Int (ARGB) 或直接返回颜色资源 ID 更方便。
- 建议方案: 返回 `Int`(Color ARGB 值)或返回颜色资源 ID。注意 `0xFF4CAF50.toInt()` 在 Kotlin 中会变为负数,建议用 `Color.parseColor("#4CAF50")` 或直接定义 Int 值。

#### 问题2: 🟡 浮点字段无范围校验

- 位置: WidgetData.kt:约3-15
- 问题描述: `health`、`happiness`、`energy`、`hunger` 等字段定义为 `Float`,语义上应为 0.0-1.0,但没有校验。如果后端返回异常值(如 -1 或 100),Widget 的 ProgressBar 会显示异常(负数进度或超过 100)。
- 建议方案: 在 `toPreferences` 或构造时 `coerceIn(0f, 1f)`,或在 Widget 渲染时 clamp。

---

### 16. worker/DataSyncManager.kt

#### 问题1: 🟡 ExistingPeriodicWorkPolicy.KEEP 不更新已存在任务

- 位置: DataSyncManager.kt:约30-35
- 问题描述: 与 AvelineWidgetWorker 相同的问题,使用 `KEEP` 策略。如果未来修改约束条件(如增加充电约束),已注册的旧任务不会更新。
- 建议方案: 考虑使用 `ExistingPeriodicWorkPolicy.UPDATE`(WorkManager 2.8.0+)。

**除此之外,该文件结构清晰、约束设置合理(要求网络连接),无其他问题。**

---

### 17. worker/DataSyncWorker.kt

#### 问题1: 🟠 KEY_RETRY_COUNT 从 inputData 读取但从未设置,重试逻辑失效

- 位置: DataSyncWorker.kt:37-43, 129, 141
- 问题描述: `companion object` 定义了 `KEY_RETRY_COUNT = "retry_count"`,在 `doWork()` 中 `inputData.getInt(KEY_RETRY_COUNT, 0)` 读取它。但 `DataSyncManager.startPeriodicSync()` 创建 WorkRequest 时从未设置该 input data,所以 `currentRetryCount` 永远是 0(默认值)。这意味着重试次数判断 `currentRetryCount >= MAX_RETRY_COUNT`(MAX_RETRY_COUNT=3)永远不会为 true,Worker 会无限重试,直到 WorkManager 的默认重试上限(通常 5 次后强制 failure)。行 133 的注释"WorkManager 通过 getRunAttemptCount() 追踪重试次数,无需手动传 data"与实际代码矛盾——代码仍在用 inputData 追踪。
- 建议方案: 使用 `runAttemptCount`(WorkerParameters 提供的属性,继承自 ListenableWorker)替代 inputData:
  ```kotlin
  val currentRetryCount = runAttemptCount
  // 移除 KEY_RETRY_COUNT 常量和 inputData 读取
  ```

#### 问题2: 🟡 e.printStackTrace() 而非使用正式日志

- 位置: DataSyncWorker.kt:139
- 问题描述: `e.printStackTrace()` 输出到 stderr,在 Android 上不会出现在 Logcat 的应用标签下,难以过滤和排查。项目其他地方使用 `android.util.Log.w/e`。
- 建议方案: `Log.e("DataSyncWorker", "同步异常", e)`。

#### 问题3: 🟡 markAsSent 在部分同步失败时可能误标记

- 位置: DataSyncWorker.kt:119-126
- 问题描述: 当 `response.isSuccessful` 为 true 时,所有 `unsentNotifications` 和 `unsentHealthData` 都被标记为已发送。但如果 response 成功但部分数据被后端拒绝(如某条通知格式错误,后端返回 200 但 body 中标注部分失败),这些被拒绝的数据也会被标记为已发送,永远不会重试。
- 建议方案: 解析 response body,仅标记后端确认接收的数据。如果后端 API 是全有或全无的,则当前实现可接受,但需在注释中说明假设。

---

## 总结与优先级建议

### 🔴 严重问题(必须尽快修复)

| # | 文件 | 问题 | 影响 |
|---|------|------|------|
| 1 | AvelineForegroundServiceV2.kt:102 | startForeground 未声明 foregroundServiceType | Android 14+ 上前台服务启动崩溃 |
| 2 | AvelineForegroundServiceV2.kt:184-187 | updateBackendUrlInternal 不更新后端 URL | 后端切换功能完全失效 |
| 3 | AvelineFirebaseMessagingService.kt:30 | serviceScope 未取消,协程泄漏 | 多次创建服务导致内存泄漏 |
| 4 | AvelineNotificationService.kt:58-93 | 通知不去重,数据库被通知更新洪水淹没 | 存储爆炸、性能下降 |
| 5 | FileUploadManager.kt:316-335 | 整个文件读入内存 | 大文件上传时 OOM 崩溃 |
| 6 | TTSEngine.kt:254-260 | TTS 缓存无大小限制 | 存储被占满 |
| 7 | ServerDiscoveryManager.kt:285-309 | 使用已废弃 WifiManager.dhcpInfo | Android 10+ 服务发现基本失效 |
| 8 | AvelineWidgetWorker.kt:27 | 缺少 @HiltWorker 注解 | Widget 后台更新功能完全无法工作 |

### 🟠 中等问题(建议在下一版本修复)

重点推荐优先处理的:
1. **FileUploadManager 进度伪造**——用户看到的进度是假的,影响信任
2. **TTSEngine playMessage 并发冲突**——快速点击播放可能播放错误音频
3. **BootCompletedReceiver 吞异常**——开机自启动失效无法排查
4. **ServerDiscoveryManager multicastLock 泄漏**——持续耗电
5. **DataSyncWorker 重试逻辑失效**——Worker 可能无限重试或过早放弃
6. **AvelineNotificationManager 通知覆盖**——多条消息只能看到最后一条

### 🟡 轻微问题(可在技术债清理时一并处理)

主要集中在:
- 异常静默吞掉缺少日志(多处)
- 硬编码颜色/图标而非使用资源
- 函数过长(parsePhoneAction 82 行)
- Hilt 注入不一致(MediaActionExecutor/NotificationActionExecutor)
- 线程安全问题(VoiceInputManager/SpeechRecognizer 主线程要求)

### 建议的修复顺序

1. **第一优先级**:修复 8 个🔴严重问题,这些会导致崩溃或功能失效
2. **第二优先级**:修复影响用户体验的🟠中等问题(进度伪造、通知覆盖、重试逻辑)
3. **第三优先级**:清理异常处理(添加日志)和代码规范问题
4. **第四优先级**:重构长函数、统一 Hilt 注入模式
