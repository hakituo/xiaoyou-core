# Aveline Android

Aveline AI 伴侣应用的 Android 原生客户端，基于 Kotlin + Jetpack Compose 构建，采用 MVVM + Clean Architecture 分层架构。

## 技术栈

| 类别 | 技术 | 版本 |
|------|------|------|
| 语言 | Kotlin | 1.9.22 |
| UI | Jetpack Compose + Material3 | BOM 2024.02.02 |
| 依赖注入 | Hilt (Dagger) | 2.48.1 |
| 本地数据库 | Room | 2.6.1 |
| 网络请求 | Retrofit + OkHttp | 2.9.0 / 4.12.0 |
| 序列化 | kotlinx-serialization | 1.6.0 |
| 图片加载 | Coil | 2.5.0 |
| 后台任务 | WorkManager | 2.9.0 |
| 推送 | Firebase Messaging | BOM 33.1.2 |
| 健康 | Health Connect | 1.1.0-alpha07 |
| 定位 | Play Services Location | 21.2.0 |
| 安全 | Android Security Crypto | 1.1.0-alpha06 |

构建配置：compileSdk 35 / minSdk 26 / targetSdk 35 / Java 17

模型与人设选择通过现有 `AppPreferences` 持久化。手动模型选择优先于后端默认模型，HTTP/SSE 请求使用保存的完整路由；人设版本按角色独立保存，切换成功后同步聊天会话和请求归属。退出重进或重启 App 会恢复选择。静态回归脚本：`tests/scripts/android_frontend/verify_chat_selection_persistence.py`；编译及设备上的退出重进、重启验收由 Android Studio 完成。

## 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                    Presentation Layer                            │
│  Compose UI + ViewModel + Navigation + Theme + Components       │
├─────────────────────────────────────────────────────────────────┤
│                    Domain Layer                                  │
│  领域模型 (17个) + Repository接口 (11个)                         │
├─────────────────────────────────────────────────────────────────┤
│                    Data Layer                                    │
│  Remote (REST API + WebSocket + DTO)                            │
│  Local (Room + SharedPreferences + EncryptedPrefs)              │
│  Repository实现 (11个)                                           │
├─────────────────────────────────────────────────────────────────┤
│                    Service Layer                                 │
│  前台服务 / 手机操作执行 / 服务器发现 / TTS / 语音输入            │
│  文件上传 / 数据同步 / FCM推送 / 通知监听                        │
├─────────────────────────────────────────────────────────────────┤
│                    DI Layer (Hilt)                               │
│  AppModule / NetworkModule / DatabaseModule / RepositoryModule  │
└─────────────────────────────────────────────────────────────────┘
```

## 项目结构

```
android/app/src/main/java/com/aveline/ai/
├── AvelineApplication.kt              # @HiltAndroidApp 入口，初始化CrashHandler/通知渠道/性能监控
├── HealthManager.kt                   # Health Connect 数据读取管理器
│
└── mobile/
    ├── di/                            # 依赖注入模块
    │   ├── AppModule.kt               #   Context / Resources / LocationProvider
    │   ├── NetworkModule.kt           #   Json / 拦截器 / OkHttpClient / Retrofit / ApiService / WebSocket
    │   ├── DatabaseModule.kt          #   Room数据库 / 5个DAO
    │   └── RepositoryModule.kt        #   11个 @Binds 绑定
    │
    ├── domain/                        # 领域层（纯Kotlin，无框架依赖）
    │   ├── models/                    #   领域模型
    │   │   ├── Message.kt             #     聊天消息
    │   │   ├── Session.kt             #     会话
    │   │   ├── Emotion.kt             #     情绪状态（含预定义常量）
    │   │   ├── LifeStatus.kt          #     AI生命状态（健康/饥饿/幸福/能量）
    │   │   ├── Memory.kt              #     记忆（含类型/重要性/排序/过滤）
    │   │   ├── Persona.kt             #     人格（含5个预设模板）
    │   │   ├── HealthData.kt          #     健康数据（步数/心率/血氧/睡眠等）
    │   │   ├── DeviceContext.kt        #     设备上下文（电池/网络/亮度/音量等）
    │   │   ├── PhoneAction.kt         #     手机操作指令（sealed class, 13种操作）
    │   │   ├── ShopItem.kt            #     商店物品
    │   │   ├── StudyFile.kt           #     学习文件
    │   │   ├── PluginSettings.kt      #     插件设置
    │   │   ├── FoodModels.kt          #     食物模型
    │   │   ├── IntentModels.kt        #     意图分类模型
    │   │   ├── NotificationModels.kt  #     通知模型
    │   │   └── SystemModels.kt        #     系统模型
    │   │
    │   └── repository/                #   Repository接口
    │       ├── ChatRepository.kt
    │       ├── SessionRepository.kt
    │       ├── StatusRepository.kt
    │       ├── HealthRepository.kt
    │       ├── ContextRepository.kt
    │       ├── MemoryRepository.kt
    │       ├── StudyRepository.kt
    │       ├── PersonaRepository.kt
    │       ├── PluginsRepository.kt
    │       ├── ShopRepository.kt
    │       └── ToolsRepository.kt
    │
    ├── data/                          # 数据层
    │   ├── remote/
    │   │   ├── api/
    │   │   │   ├── AvelineApiService.kt    # Retrofit接口，50+ REST端点
    │   │   │   ├── WebSocketManager.kt     # WebSocket连接/重连/心跳，指数退避策略
    │   │   │   └── WebSocketMessage.kt     # 消息类型（sealed class, 15+种）
    │   │   └── dto/                        # 网络传输对象 (18个)
    │   │       ├── MessageRequest.kt / MessageResponse.kt
    │   │       ├── SessionResponse.kt
    │   │       ├── LifeStatusResponse.kt
    │   │       ├── ContextSyncRequest.kt
    │   │       ├── MemoryDto.kt
    │   │       ├── PersonaDto.kt
    │   │       ├── ModelDto.kt
    │   │       ├── TTSRequest.kt / VoicesResponse.kt
    │   │       ├── UploadResponse.kt
    │   │       ├── ImageDtos.kt / VisionDtos.kt
    │   │       ├── FoodDtos.kt / ShopDto.kt
    │   │       ├── StudyFileDto.kt
    │   │       ├── IntentDtos.kt / NotificationDtos.kt / SystemDtos.kt
    │   │       └── MarkImportantRequest.kt
    │   │
    │   ├── local/
    │   │   ├── database/                   # Room数据库
    │   │   │   ├── AvelineDatabase.kt      #   数据库定义 (v1, 5个Entity)
    │   │   │   ├── dao/                    #   MessageDao / SessionDao / MemoryDao
    │   │   │   └── entity/                 #   MessageEntity / SessionEntity / MemoryEntity
    │   │   ├── db/                         # 扩展数据库组件
    │   │   │   ├── dao/                    #   HealthDataDao / NotificationDao
    │   │   │   └── entity/                 #   HealthDataEntity / NotificationEntity
    │   │   └── preferences/
    │   │       └── AppPreferences.kt       # SharedPreferences封装 (17+配置项)
    │   │                                    #   accessToken使用EncryptedSharedPreferences (AES256)
    │   │
    │   └── repository/                    # Repository实现 (11个)
    │       ├── ChatRepositoryImpl.kt
    │       ├── SessionRepositoryImpl.kt
    │       ├── StatusRepositoryImpl.kt
    │       ├── HealthRepositoryImpl.kt
    │       ├── ContextRepositoryImpl.kt
    │       ├── MemoryRepositoryImpl.kt
    │       ├── StudyRepositoryImpl.kt
    │       ├── PersonaRepositoryImpl.kt
    │       ├── PluginsRepositoryImpl.kt
    │       ├── ShopRepositoryImpl.kt
    │       └── ToolsRepositoryImpl.kt
    │
    ├── presentation/                  # UI层
    │   ├── MainActivity.kt            #   @AndroidEntryPoint 主入口
    │   ├── MainViewModel.kt           #   @HiltViewModel 主ViewModel
    │   ├── navigation/
    │   │   └── NavGraph.kt            #   主页面路由与 DeepLink (aveline://)
    │   │
    │   ├── chat/                      #   聊天（核心页面）
    │   │   ├── ChatScreen.kt          #     纯组装层：收集状态 + 拼装下面各子组件
    │   │   ├── ChatTopBar.kt          #     顶栏（返回 + 头像 + 昵称）
    │   │   ├── ChatMessageList.kt     #     消息列表 / 时间分隔 / 旁白 / 空状态
    │   │   ├── ChatPeerChatArea.kt    #     双角色对话折叠区
    │   │   ├── ChatInputBars.kt       #     底部输入栏 + 待发送图片/视频条 + 上传进度
    │   │   ├── ChatCompanionPanel.kt  #     伴侣详情全屏覆盖面板
    │   │   ├── ChatCompanionPanelGesture.kt  # 左滑打开伴侣面板的手势 Modifier
    │   │   ├── ChatEditMessageDialog.kt      # 编辑已发消息的对话框
    │   │   ├── ChatMediaPickers.kt    #     图片/视频/文件/录音权限选择入口
    │   │   ├── ChatPersonaTitle.kt    #     顶栏 persona 展示信息解析（标题/头像）
    │   │   ├── ChatViewModel.kt       #     薄壳协调者：组装各 Chat*Controller/Handler
    │   │   ├── ChatSessionController.kt      # 角色(persona)/会话(session)切换
    │   │   ├── ChatSessionObserver.kt        # 会话与消息流观察、WS 事件分发
    │   │   ├── ChatSendController.kt         # 发消息主流程（HTTP SSE 流式）
    │   │   ├── ChatIncomingMessageHandler.kt # WS 消息落库 + 会话列表预览
    │   │   ├── ChatFlushManager.kt    #     流式响应批量刷新
    │   │   ├── ChatUploadHelper.kt    #     文件/图片上传与图片视觉识别
    │   │   ├── ChatTtsController.kt   #     TTS 播报（跟随当前对话角色）
    │   │   ├── ChatVoiceInputController.kt   # 语音输入
    │   │   ├── ChatPeerChatHandler.kt #     双角色对话
    │   │   ├── ChatTextProcessor.kt   #     消息文本处理
    │   │   ├── ChatPreviewBuilder.kt  #     会话列表预览文本
    │   │   ├── ImageMessageText.kt    #     图片消息文本渲染
    │   │   └── VideoMessageText.kt    #     视频消息文本渲染
    │   │   ├── ChatUiState.kt         #     聊天页 UI 状态
    │   │   └── ChatAvatarStorageHolder.kt    # 顶栏头像数据持有者
    │   ├── status/                    #   AI生命状态展示
    │   ├── health/                    #   每日数据（健康+上下文+饮水+学习）
    │   ├── memory/                    #   记忆搜索/过滤/排序/标记重要
    │   ├── study/                     #   学习文件/学习模式/词汇复习
    │   ├── persona/                   #   人格切换
    │   ├── shop/                      #   商店
    │   ├── plugins/                   #   模型/情绪/学习模式/敏感词设置
    │   ├── tools/                     #   图像生成/视觉/食物/通知/系统
    │   └── settings/                  #   后端URL/Token/模型/语音/常驻模式等
    │
    │   ├── components/                #   共享UI组件
    │   │   ├── BreathingBackground.kt #     呼吸灯背景（情绪颜色联动）
    │   │   ├── DrawerContent.kt       #     侧边抽屉导航
    │   │   ├── InputArea.kt           #     消息输入区域
    │   │   ├── MessageBubble.kt       #     消息气泡
    │   │   ├── SessionDialogs.kt      #     会话操作对话框
    │   │   ├── TTSComponents.kt       #     TTS播放控制
    │   │   ├── TypingIndicator.kt     #     打字指示器
    │   │   ├── VoiceInputComponents.kt#     语音输入
    │   │   ├── ModuleHeader.kt        #     模块标题
    │   │   └── TimeSeparator.kt       #     时间分隔线
    │   │
    │   ├── theme/                     #   主题系统
    │   │   ├── Color.kt               #     颜色常量
    │   │   ├── EmotionColorMapping.kt #     情绪→颜色映射
    │   │   ├── Theme.kt               #     AvelineTheme (暗色主题)
    │   │   └── Typography.kt          #     字体排版
    │   │
    │   └── utils/
    │       └── EmotionResolver.kt     #     情绪解析工具
    │
    ├── services/                      # 服务层
    │   ├── AvelineForegroundServiceV2.kt   # 前台服务薄壳：生命周期与子控制器编排
    │   ├── foreground/                     # 前台保活子系统
    │   │   ├── ForegroundServiceContract.kt       # 启停/通知恢复 Intent 协议
    │   │   ├── ForegroundNotificationController.kt# 通知渠道、创建与发布
    │   │   ├── WebSocketCommandCoordinator.kt     # 消息监听与设备指令
    │   │   ├── ContextSyncController.kt            # 五分钟上下文同步
    │   │   ├── SamsungHealthSyncController.kt      # 三档健康同步
    │   │   ├── AccessibilityMonitor.kt             # 无障碍断线监测
    │   │   └── ResidentPowerController.kt          # WakeLock 生命周期
    │   ├── PhoneActionExecutor.kt          # @Singleton：执行13种手机操作指令
    │   ├── TTSEngine.kt                    # TTS语音合成引擎
    │   ├── VoiceInputManager.kt            # 语音输入管理器
    │   ├── FileUploadManager.kt            # 文件上传管理器
    │   ├── AvelineNotificationManager.kt   # 通知渠道管理
    │   ├── AvelineNotificationService.kt   # NotificationListenerService
    │   ├── AvelineFirebaseMessagingService.kt # FCM推送
    │   ├── BootCompletedReceiver.kt        # 开机自启
    │   ├── discovery/
    │   │   └── ServerDiscoveryManager.kt   # @Singleton：UDP广播+网段扫描，零配置发现
    │   └── worker/
    │       ├── DataSyncManager.kt          # @Singleton：WorkManager周期同步(15min)
    │       └── DataSyncWorker.kt           # 实际同步Worker
    │
    └── utils/                         # 工具类
        ├── CrashHandler.kt            #   全局未捕获异常处理
        ├── ErrorHandler.kt            #   统一错误处理
        ├── PerformanceMonitor.kt      #   性能监控
        ├── SecurityManager.kt         #   安全管理（XSS防护等）
        ├── InputValidator.kt          #   输入校验
        ├── RetryUtils.kt             #   重试工具（指数退避）
        ├── LanguageManager.kt         #   国际化管理
        ├── HapticFeedbackManager.kt   #   触觉反馈
        ├── AccessibilityManager.kt    #   无障碍功能
        ├── CoilImageLoader.kt         #   Coil图片加载配置
        ├── DataExportManager.kt       #   数据导出
        ├── DeepLinkHandler.kt         #   DeepLink处理
        ├── ShareUtils.kt             #   分享工具
        └── StateManager.kt           #   状态管理
```

## 核心特性

### WebSocket 实时通信

通过 `WebSocketManager` 维持与后端的长连接，支持 15+ 种消息类型：

| 消息类型 | 说明 |
|----------|------|
| `TextMessage` | 普通文本消息 |
| `ResponseChunk` | 流式响应片段（智能分段：正文 vs 括号内"内心独白"） |
| `ResponseReset` | AI 开始调用工具：只清空当前正在生成的临时消息，不影响历史消息（`ChatFlushManager.onResponseReset()`） |
| `ResponseDone` | 响应完成 |
| `EmotionUpdate` | 情绪状态推送 |
| `LifeStatusUpdate` | AI生命状态广播 |
| `PhoneActionCommand` | 手机操作指令 |
| `RitualEvent` | 仪式事件 |
| `SpontaneousReaction` | 自发反应 |
| `ImageResult` | 图像生成结果 |
| `VideoResult` | 视频/动图生成结果（气泡内用 ExoPlayer 渲染） |
| `Notification` | 通知推送 |
| `ConnectionEstablished` | 连接建立 |
| `ReconnectSync` | 重连同步 |

**真流式响应时序**（HTTP SSE `/v1/chat` 与 WebSocket 共用）：

```
普通文本 → ResponseChunk 逐块显示
AI 开始调用工具 → ResponseReset（清空当前生成中的临时消息，历史不动）
工具执行完成 → ResponseChunk 继续逐块显示（最终回答）
全部完成 → ResponseDone（消息完成，后端此刻才写入数据库）
```

连接管理采用指数退避重连策略，前台服务常驻模式下保持连接。

### AI 生命模拟

AI 拥有四维生命状态（`LifeStatus`）：

- **健康** (health) - AI身体状况
- **饥饿** (hunger) - AI饱食度
- **幸福** (happiness) - AI幸福度
- **能量** (energy) - AI精力值

状态通过 WebSocket 实时推送，UI 层通过伴侣详情的状态页展示。`GET /api/v1/life/status` 同时返回当前活动、基础回复策略、睡眠摘要与当前角色当天的 `DailyPlan`。其中 `activity_chat_eligible` 只表示该活动是否适合角色间 Peer Chat，用户消息的真实基础行为以 `reply_policy.mode` 为准：轻活动延迟回复，学习与睡眠暂不回复。状态页据此显示明确的回复方式及“唤醒 / 打断 / 跳过活动”，并直接复用后端现有生命与日程控制接口。

伴侣详情在“状态”和“模型”之间提供独立“日程”页，按当前聊天角色展示当天完整时间线、正在进行项、完成状态及时间是否可调整。打开详情和进入日程页都会强制刷新当前 persona scope，避免旧状态缓存已有当前活动却缺少新增的 `daily_plan` 字段；接口暂未同步时只显示同步提示及当前活动，不再误报角色没有生成日程。

### 情绪系统

- `Emotion` 模型定义 primary + intensity + colors
- 预定义情绪常量：NEUTRAL / HAPPY / CALM / EXCITED / SAD
- `EmotionColorMapping` 将情绪映射为颜色方案
- `BreathingBackground` 呼吸灯动画随情绪颜色联动

### 手机操作执行

`PhoneActionExecutor` 执行 AI 下发的 13 种手机操作指令：

| 操作 | 说明 |
|------|------|
| `CreateCalendarEvent` | 创建日历事件 |
| `SetAlarm` | 设置闹钟 |
| `SetTimer` | 设置定时器 |
| `OpenApp` | 打开应用 |
| `MakePhoneCall` | 拨打电话 |
| `SendSms` | 发送短信 |
| `OpenNavigation` | 打开导航 |
| `SetDndMode` | 勿扰模式 |
| `MediaControl` | 媒体控制 |
| `OpenSettings` | 打开设置 |
| `ShareContent` | 分享内容 |
| `SetVolume` | 调节音量 |
| `GetLocation` | 获取位置 |

### 后端通道：局域网 → 组网 → 公网

后端同时监听 `0.0.0.0:8000`（局域网入口）、Tailscale 组网地址（点对点入口）
和 Cloudflare Tunnel（公网入口），客户端**不再让用户手动切换**，
而是由 `EndpointResolver` 按当前网络类型自动裁决：

```
手动锁定（AppPreferences.backendUrl，非空即生效，不探测）
  > 局域网（AppPreferences.lanUrl，短超时 800ms 探测）—— 仅 WiFi / 以太网候选
    > 组网（AppPreferences.vpnUrl，1.5s 探测）—— 组网与公网是并存的两条远程通道
      > 公网域名（AppPreferences.tunnelUrl，宽松超时 3s 探测）
```

**局域网候选只在有 WiFi / 以太网链路时才排在前面**，蜂窝数据下它的顺序掉到最后
（手机热点、USB 网络共享等场景下仍会补探一次）。所以实际效果是：
在家走局域网，出门走组网，组网不通（`vpnUrl` 没配、手机没开 Tailscale、电脑关机）才退公网域名。

**组网与公网不是互斥开关**：`vpnUrl` 是手机直连电脑的点对点通道，不经公网边缘，
没有 Cloudflare 隧道的抖动与偶发 530；`tunnelUrl` 保留作兜底，两条都配着最稳。
只配其中一条也完全可用 —— 不配 `vpnUrl` 时行为与加这个槽位之前完全一致。

裁决结果写进 `AppPreferences.activeUrl`，所有网络消费方统一读
`AppPreferences.effectiveBackendUrl`（REST 拦截器 / `WebSocketManager` /
`MediaUrlResolver` / `FileUploadManager`）。冷启动探测还没跑完时，
`effectiveBackendUrl` 按「手动锁定 > 上次裁决结果 > 局域网 > 组网 > 公网」兜底。

> **判据陷阱**：Tailscale 用的是 CGNAT 段 `100.64.0.0/10`，外观像私网但蜂窝下可达。
> `BackendAddressRules.isLanOnlyHost()` 必须对它返回 `false`，否则兜底逻辑会在出门时
> 把生效地址从组网强制切走。`BackendAddressRulesTest` 有单测钉住这一点。

> **VPN 会骗过 `activeNetwork`**：手机开着 Tailscale 时 `activeNetwork` 是那条 VPN 网络
> （只有 `TRANSPORT_VPN`），只看默认网络会误判成「没有局域网链路」，人在家也绕走远程通道。
> 所以 `NetworkTransportInspector.hasLanTransport()` 在默认网络没命中时会遍历 `allNetworks`
> 把底层 WiFi / 以太网找回来。

**探测触发时机**（五处）：

1. 进程启动 —— `AvelineApplication` 调 `EndpointResolver.startMonitoring()`，
   两层回调注册时都会立刻各回调一次当前网络；
2. 网络变化 —— `NetworkWatcher` 的**两层**回调，去抖后重探：
   - 默认网络回调（`onAvailable` / `onCapabilitiesChanged` / `onLost`）负责「默认网络换没换、
     链路类型变没变」；
   - 物理链路回调（请求式，WiFi / 蜂窝 / 以太网）负责「底层链路来没来、走没走」。
     少了这层会漏掉一整类切换：开着 Tailscale 时默认网络恒为那条 VPN 网络、transport 恒为
     `other`，WiFi ↔ 蜂窝 的交接被上面那层的去重挡掉，通道永远不重选；
3. 连接失败降级 —— `WebSocketManager.scheduleReconnect()` 从第二次重连起问一次
   `resolveOnFailure()`（20 秒节流），避免在死通道上无限重连；
4. 设置页手动点「重新探测」；
5. 周期重探 —— `NetworkWatcher` 每 5 分钟过一遍 `ChannelPriority.hasBetterCandidate()`，
   只在「存在更优候选」时才真的探测。

> **为什么需要第 5 条**：事件型触发都靠 `ConnectivityManager` 回调，而「Tailscale 连上了 /
> 打洞完成了」**不产生任何回调** —— 默认网络一直是那条 VPN 网络，`transportOf()` 恒为 `other`，
> 被 `onCapabilitiesChanged` 的去重挡掉。少了周期重探，一次「组网还没就绪就探失败」的抖动就会
> 让用户整个外出期间挂在公网域名上：公网一直好用 → WebSocket 不失败 → `resolveOnFailure()`
> 也不会被调用，通道再也升不回组网。

**探测必须做对的三件事**（见 `EndpointProber.probe()`）：

- 走裸 `HttpURLConnection`，**不能复用业务 OkHttpClient** —— 后者挂了
  `baseUrlInterceptor`，会把地址重写成当前生效地址，探测就变成自己测自己；
- **带访问令牌** —— `/api/v1/health` 在 `is_protected_path` 名单里，无令牌会被 401/503 拒掉；
- **校验响应体的服务标识** —— 端口通不等于后端，局域网里任意开 8000 的设备都能连通。

**代码结构**：门面 `EndpointResolver` 只持有生效地址状态、按优先级链裁决、对外提供触发入口；
具体职责拆在 `services/endpoint/resolver/` 子目录里，改哪一层就只动哪个文件：

| 文件 | 职责 |
| --- | --- |
| `EndpointChannel.kt` | `EndpointChannel` 枚举 + `ResolvedEndpoint` 数据类（跨子模块共享，不嵌在门面里） |
| `EndpointProber.kt` | 探测某地址是不是本项目后端（裸连接 + 令牌 + 响应体身份校验 + 兜底超时） |
| `NetworkTransportInspector.kt` | 链路类型判定（含「开 VPN 时也找回底层 WiFi」） |
| `ChannelPriority.kt` | 候选排序判据（纯函数，`ChannelPriorityTest` 钉住） |
| `NetworkWatcher.kt` | 两层网络回调 + 去抖 + 周期重探 |

**地址判据收敛在 `BackendAddressRules`**（纯函数，可直接跑 JVM 单测）：私网 / 组网 / 公网
三类互斥。Tailscale 用的 CGNAT 段 `100.64.0.0/10` **既不是私网也不是普通公网** ——
判成私网会让「蜂窝 + 私网就强制降级」的兜底把组网地址一起切走，判成公网则让「出门时组网优先于
公网」的排序失去依据。

**地址槽位迁移**（`AppPreferences`，两步一次性迁移）：

- **V2** `migrateToDualEndpointIfNeeded()`：把旧的「单一 backendUrl + 手动 Tunnel 开关」
  迁移成多槽位（旧 `lanUrlBackup` → `lanUrl`，旧 `backendUrl` → `activeUrl` 缓存）；
  旧地址若落在组网段则一并认进 `vpnUrl`；
- **V3** `promoteVpnSlotIfNeeded()`：`vpnUrl` 为空时，把「手动锁定 / 上次裁决结果」里的组网
  地址**复制**进 `vpnUrl` 槽位（不碰手动锁定本身）。

> **组网槽位留空 = 未启用这条通道**：`vpnUrl` 默认空串，`EndpointResolver` 会直接跳过这一档，
> 绝不会去猜地址。老用户里有一批人把 Tailscale 的 100.x 填在「手动锁定」里用，升级后就会
> 出现「明明开着组网却一直走公网域名」—— V3 就是补这个洞。想切到自动模式，把「手动锁定」
> 那格清空即可。

组网槽位一共有三个来源：**设置页手填**、**V3 迁移升格**、**UDP 信标自报**（见下节）。

### 服务器零配置发现

`ServerDiscoveryManager` 实现三层发现策略：

1. 已配的局域网地址仍可用就直接用（省掉一次广播等待）
2. UDP 广播发现（端口 28899，5 秒超时）
3. 网段扫描兜底（9 个常见子网）

发现结果写入 `AppPreferences.lanUrl` **槽位**（不是 `backendUrl`），是否采用交给
`EndpointResolver` 按优先级裁决。旧实现「用户配过地址就不覆盖」会让设了公网域名后
永远切不回局域网，现在不再有这个限制。

**信标载荷同时带后端的组网地址**（可选段），客户端据此把 `vpnUrl` 槽位自动填上 ——
否则用户得自己从电脑上抄一个 `100.x` 地址填进设置页，而这正是「开着组网却走公网」最常见的成因：

```
后端 core/services/discovery/udp_beacon.py:
  AVELINE_SERVER|http://<局域网IP>:<port>[|http://<组网IP>:<port>]

客户端 services/discovery/BeaconPayload.kt: BeaconPayload.parse()
```

两侧是一对**线上契约**，各有单测钉住（`tests/unit/test_discovery_udp_beacon.py` /
`BeaconPayloadTest`）。第三段缺失即「后端没有组网入口」，不是「信标没发全」。

> **为什么只在局域网里问得到**：信标是局域网广播，手机出门切蜂窝后收不到。所以补槽位的
> 时机只能是「在家这次发现」—— 组网槽位为空时会跳过「已配局域网地址仍可用」的快速路径，
> 多听一遍广播（最多 5 秒，且在 `MainActivity` 的后台协程里，不阻塞界面）。
> 补上之后该快速路径恢复，这个额外等待只发生一次。

> **组网地址不做身份校验，局域网地址必须做**：信标是明文 UDP，局域网里谁都能伪造。
> 但组网地址只是**候选** —— 真正采纳前要过 `EndpointResolver` 的探测（HTTP 200 +
> 响应体含服务标识 + 令牌），伪造一个假地址最多让探测白跑 1.5 秒，劫持不了连接。
> 反过来在这里做校验会导致「手机当前没开组网 → 探测必然失败 → 槽位永远填不上」，
> 正好错过唯一能问到地址的时机。

> 身份校验走 `/api/v1/health` 并携带访问令牌。旧实现请求的是裸 `/health` 且不带令牌，
> 后端既没有该路由、该路径又需要认证，所以自动发现实际上从未成功过。

> **链路判定不要另写一份**：`ServerDiscoveryManager` 曾自带一份只查默认网络的
> `hasLanTransport()`，开着 Tailscale 时默认网络是 VPN 网络，于是「在家也判定为非局域网链路」
> → 直接跳过整轮发现。现在统一用 `NetworkTransportInspector`。

### Health Connect 集成

`HealthManager` 读取 Health Connect 健康数据：步数、心率、血氧、体重、睡眠、血压、血糖、体温等。

Life 日程页的 Samsung Health 睡眠卡片分开展示“在床时长”、
“实际睡眠”和“夜间清醒”。实际睡眠严格按浅睡 + 深睡 + REM
累加，不包含清醒阶段；这与 Samsung Health 的口径一致。

### Samsung Health 读取层（`data/samsung`）

国行设备 Health Connect 系统服务被裁剪，健康数据统一走 Samsung Health Data SDK：

```
SamsungHealthReader.kt             # 门面：权限转发 + readVitals/readBodyComposition/readAll 三档快照组装
SamsungHealthPermissions.kt        # 23 类数据类型的读取权限集合与请求/检查
SamsungHealthQuerySupport.kt       # 今日时间区间与 LocalTime/LocalDate 两种聚合查询
SamsungHealthVitalsReader.kt       # 高频：心率、步数、活动汇总、爬楼、皮温、血氧
SamsungHealthBodyReader.kt         # 低频：身体成分、血压、体温、血糖
SamsungHealthSleepReader.kt        # 睡眠记录选择与子会话/阶段合并
SamsungHealthDietActivityReader.kt # 饮食、饮水、运动会话
SamsungHealthScoreGoalReader.kt    # 能量评分、睡眠呼吸暂停/心律不齐、各类目标
```

`HealthDataStore` 由 `AppModule` 以单例提供，各读取器统一注入。

体成分的展示口径是“最近一次测量值”而不是“今天的值”：查询回溯 365 天、
最多取 200 条记录，每个字段独立取最近一次非空值。这样测量较久没做
（或最新一条只有体重）时，体脂率/骨骼肌/水分等字段仍能显示出来。

## 依赖注入

4 个 Hilt 模块全部安装在 `SingletonComponent`：

```
AppModule          → Context, Resources, FusedLocationProviderClient
NetworkModule      → Json, 拦截器(鉴权/日志/动态域名), OkHttpClient, Retrofit, ApiService, WebSocketManager
DatabaseModule     → AvelineDatabase, 5个DAO
RepositoryModule   → 11个 @Binds 绑定（接口 → 实现）
```

网络模块亮点：
- **动态域名拦截器**：baseUrl 仅占位，真实地址由 `AppPreferences.effectiveBackendUrl`
  动态替换（该值由 `EndpointResolver` 在局域网/组网/公网之间裁决，不是用户手填的单一地址）
- **鉴权拦截器**：自动添加 Bearer Token 和 x-internal-token
- **条件日志**：Debug 模式 BODY 级别，Release 模式 NONE

## 数据层设计

### 网络请求

```
Retrofit (AvelineApiService)  ──50+ REST端点──>  后端 /api/v1/*
WebSocketManager              ──实时双向通信──>  后端 /api/v1/ws
```

API 端点覆盖：消息、会话、状态、上下文同步、TTS、文件上传、记忆、学习、人格、模型、食物、商店、图像生成、视觉描述、通知、系统、每日数据、意图分类、插件。

上下文同步中的应用用量使用本地当天零点至今的统计窗口。`DataSyncWorker` 随请求上报 `usage_window_start` 与 `usage_source=android_today_since_midnight_v1`；后端只有在窗口起点可验证时才允许该批数据触发数字健康 Active Care，旧客户端数据仅保存和展示，不触发超限关怀。

### 本地存储

```
Room Database (aveline_database, v1)
├── MessageEntity      → MessageDao
├── SessionEntity      → SessionDao
├── MemoryEntity       → MemoryDao
├── NotificationEntity → NotificationDao
└── HealthDataEntity   → HealthDataDao

SharedPreferences (aveline_preferences)
└── 17+ 配置项

EncryptedSharedPreferences (aveline_encrypted_preferences)
└── accessToken (AES256 加密)
```

## 服务层架构

```
┌──────────────────────────────────────────────────────────┐
│       AvelineForegroundServiceV2（生命周期薄壳）          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Notification │  │ Context/Health│  │ WebSocket     │  │
│  │ + A11y/Power │  │ Controllers   │  │ Coordinator   │  │
│  └──────────────┘  └──────────────┘  └──────┬────────┘  │
└──────────────────────────────────────────────┼───────────┘
                                               │
               ┌───────────────────────────────┼──────────────────────┐
               │                               │                      │
         ┌─────▼──────┐              ┌────────▼────────┐    ┌────────▼──────┐
         │ 通知展示    │              │ PhoneAction     │    │ RitualEvent   │
         │             │              │ Executor        │    │ /Reaction     │
         └─────────────┘              │ (13种手机操作)   │    │ 通知展示      │
                                      └────────┬────────┘    └──────────────┘
                                               │
                                      ┌────────▼────────┐
                                      │ WebSocket 发送  │
                                      │ 操作结果回传    │
                                      └─────────────────┘
```

## UI 导航

```
AvelineApp (ModalNavigationDrawer + BreathingBackground + NavHost)
├── ConversationListScreen (默认路由, aveline://conversations)
├── ChatScreen             (aveline://chat)
├── StudyScreenV2          (aveline://study)
├── LifeScreen             (aveline://life)
├── FoodScreen             (aveline://food / aveline://mall)
├── WellbeingScreen        (aveline://wellbeing)
└── SettingsScreenV2       (aveline://settings)
```

主页面支持 DeepLink（`aveline://` 协议），可从外部直接跳转。旧版 `circle` 深链已退役并兼容重定向到消息主页。

侧边栏由 Compose Foundation `AnchoredDraggableState` 驱动，主页直接拖拽和 `HorizontalPager` 第一页的边界剩余拖拽共用同一份实时偏移；侧栏与遮罩随手指连续移动，松手后按距离和速度吸附展开或收回。抽屉只有产生实际位移后才接受本次 fling，避免伴侣详情等内层页面退出时把同一甩动继续传成侧栏打开。`MainActivity` 不再使用全屏 `pointerInput` 或透明边缘窗口抢占触摸事件；关闭态也不会创建遮罩点击层，主页内容可直接命中。

聊天页内的伴侣详情采用相同的锚点拖拽与 `NestedScroll` 接力：聊天页左滑进入和详情页右滑退出都直接驱动同一份面板实时偏移，页面随手指连续移动，松手后才按距离与速度吸附展开或收回。内层 Pager 采用逐层手势：从人设等页面右滑只切换到前一个 Tab，必须先松手并稳定停在“状态”，下一次新右滑才允许外层详情面板退出到聊天页。

学习、生活、伴侣详情与设置 Route 的顶部 Tab 共用纯文字选中态：不绘制蓝色下划线、胶囊底色或边框，仅用文字亮度与字重区分，并强制单行显示，避免窄屏标签竖排。

聊天 AI 消息使用整行 Markdown 富文本排版，支持标题、列表、多层引用、代码块、GFM 表格以及 `$...$` / `$$...$$` LaTeX 数学公式。超宽表格、代码块和块级公式可在消息内部横向滚动；内层内容已消费横向拖动时，聊天页不会把同一次手势解释为打开伴侣详情。

聊天消息使用持久化对话树而非覆盖式重新生成：`messages.parentId` 表示父消息，同一父消息和角色下的记录按 `variantIndex` 组成版本组，`isActiveVariant` 决定当前显示分支。点击 AI 消息可重新生成，点击用户消息可编辑并从该位置创建新分支；存在多个版本时显示 `当前 / 总数` 及左右切换按钮。Android 每次生成都会把当前选中路径作为 `history_override` 传给聊天接口，确保切换旧版本后继续对话时，模型使用的是可见分支而非服务端线性历史。

聊天记录长期保存在 Room，发送和回复完成不再按 200 条自动删除。聊天页复用上滑加载交互，首屏读取最近 50 条正文，每次向上扩展 50 条；路径选择只读取不含正文与媒体的轻量索引，正文按窗口 ID 分批查询。普通发送独立读取当前分支最近 200 条作为上下文，编辑和重新生成读取目标消息所在分支前缀；页面窗口大小不会改变上下文来源。索引目前仍按会话全量读取，长会话的索引开销与节点数成正比。

角色会话首次复用旧 `role -> sessionId` 映射，再绑定稳定的 persona filename 别名；后端 role 名称变化时优先恢复该别名，列表预览、主动消息和发送使用同一映射。已经分裂的两个容器不自动合并。后台回复更新仅拥有内容更新权，保留当前父链与版本选择；历史 API 只在返回时本地仍为空的事务中初始化。已有根或多个断链入口不再按时间自动改写根。回归用例为 `RoleSessionIdentityTest`、`ChatHistoryPersistenceTest`；本次待 Android Studio 编译与设备验收。

伴侣详情和设置页优先恢复手机明确保存的模型选择，尚未选择时才显示后端 `/api/v1/models` 返回的默认模型；列表项的 `path` 用于实际调用。HTTP/SSE 与非流式回退均携带保存的完整路由，WebSocket 的 `model` 字段也使用实际路由。角色默认模型或页面重建不会覆盖手动选择，接口无法匹配时保持“未选择”。

商城商品采用 Repository 单例内存快照缓存，按“全部/各类目”分别保存已加载分页、余额和更新时间。商城 Route 或 ViewModel 重建时同步恢复快照，10 分钟内不重复请求；缓存过期和手动刷新时保留当前商品，仅在后台更新。切换类目会取消旧类目的加载与翻页任务，避免过期响应覆盖当前页面。

## 开发

```bash
# 打开 Android Studio 项目
cd aveline-android/android

# 命令行构建
./gradlew assembleDebug

# 清理构建缓存
./gradlew clean
# 或使用项目提供的快速清理脚本
./fast-clean.bat        # Windows
```

仓库配置已使用阿里云镜像优先（settings.gradle.kts）。

## 测试

测试位于 `android/app/src/test/` 下，使用 JUnit + MockK + Kotest + coroutines-test：

- `presentation/chat/` - ChatViewModel 测试
- `presentation/components/` - BreathingBackground 测试
- `presentation/settings/` - ModelSelection 测试
- `presentation/theme/` - EmotionColorMapping 测试
- `services/` - FileUploadManager 测试
- `utils/` - InputValidator / SecurityManager 测试

```bash
./gradlew test
```
