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
    │   │   ├── ChatScreen.kt          #     消息收发/流式响应/语音/文件上传/图片/情绪
    │   │   └── ChatViewModel.kt       #     7个数据流观察，流式响应智能分段
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

### 服务器零配置发现

`ServerDiscoveryManager` 实现三层发现策略：

1. 检查当前配置是否可用
2. UDP 广播发现（端口 28899，5 秒超时）
3. 网段扫描兜底（9 个常见子网 × 4 个端口）

发现结果自动保存到 `AppPreferences`，实现零配置启动。

### Health Connect 集成

`HealthManager` 读取 Health Connect 健康数据：步数、心率、血氧、体重、睡眠、血压、血糖、体温等。

Life 日程页的 Samsung Health 睡眠卡片分开展示“在床时长”、
“实际睡眠”和“夜间清醒”。实际睡眠严格按浅睡 + 深睡 + REM
累加，不包含清醒阶段；这与 Samsung Health 的口径一致。

## 依赖注入

4 个 Hilt 模块全部安装在 `SingletonComponent`：

```
AppModule          → Context, Resources, FusedLocationProviderClient
NetworkModule      → Json, 拦截器(鉴权/日志/动态域名), OkHttpClient, Retrofit, ApiService, WebSocketManager
DatabaseModule     → AvelineDatabase, 5个DAO
RepositoryModule   → 11个 @Binds 绑定（接口 → 实现）
```

网络模块亮点：
- **动态域名拦截器**：baseUrl 仅占位，真实地址由 `AppPreferences.backendUrl` 动态替换
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

伴侣详情和设置页的模型选择以后端 `/api/v1/models` 返回的 `selected_model_id` 为权威状态，并用列表项的 `path` 对齐实际云端路由；接口无法匹配时保持“未选择”，不再默认高亮列表第一项。切换模型通过 WebSocket 的 `model` 字段发送实际路由，而不是展示名称。

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
