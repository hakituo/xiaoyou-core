# Aveline Android 改进审查清单

审查日期：2026-08-17

范围：`android/app` 手机端、`android/wear` 手表端、构建配置、Manifest、网络、后台服务、数据存储、UI 与测试。

说明：本报告来自静态代码审查。没有把 Gradle/Android Studio 构建失败当成 App 缺陷；真机上的厂商 ROM、Health Connect、Samsung Health、Shizuku、无障碍和后台保活行为仍需单独验证。

## 结论

当前 App 功能很多，但最优先的问题不是继续加功能，而是收紧“自动发现服务器 → 带令牌连接 → 接收远程设备控制 → Shizuku 执行”的信任链。这个链条目前缺少服务器身份校验、指令签名/重放保护和严格参数校验，并且允许明文连接，风险高于普通聊天 App。

建议按以下顺序处理：

1. 先完成 P0 安全与兼容修复。
2. 再修 P1 的连接可靠性、数据一致性和后台服务问题。
3. 然后做 P2 的结构、测试、体积、国际化和可访问性治理。
4. 最后处理 P3 的工程体验和长期维护项。

## P0：必须优先修复

| # | 问题 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| 1 | 自动发现服务器没有身份校验，而且会自动覆盖已保存地址 | `ServerDiscoveryManager.kt:75-104,146-175,261-284`；只要 UDP 文本前缀正确或 TCP 端口可连就被接受 | 同一局域网中的恶意设备可冒充后端；随后 App 会把访问令牌发给该地址，并接受其远程设备指令 | 发现只返回候选，不自动切换；使用一次性配对码或签名发现包；健康检查必须校验应用级 challenge、服务 ID 和证书/公钥指纹；切换服务器必须用户确认 |
| 2 | 远程参数直接拼入 `sh -c`，存在命令注入 | `SystemControlExecutor.kt:129,205`，`ShizukuShellExecutor.kt:58` | 恶意或被劫持的后端可借 `package_name` / `activity` 插入 shell 元字符，以 shell UID 执行额外命令 | 不使用 `sh -c`；通过参数数组调用固定命令；包名用 `^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$` 校验，Activity 用 ComponentName 解析并验证属于目标包 |
| 3 | 全局允许明文 HTTP/WS，release 还信任用户安装的 CA | `network_security_config.xml:3-17` | 聊天、通知、健康数据、令牌和远程控制指令可被中间人读取或篡改 | release 默认只允许 HTTPS/WSS 和系统 CA；内网明文改为显式的开发开关或仅限用户确认的私网域；用户 CA 只放 `debug-overrides` |
| 4 | WebSocket 把访问令牌放在 URL 查询串 | `WebSocketManager.kt:232-244` | URL 容易进入代理、服务器访问日志、崩溃日志和网络诊断 | 改用 `Authorization` 请求头或首帧 challenge-response；短期令牌、可撤销、限制设备和作用域 |
| 5 | 远程设备命令只有“已连上后端”这一层信任，没有签名、时间窗、nonce、权限范围或危险操作确认 | `WebSocketManager.kt:306-329`，`AvelineForegroundServiceV2.kt:382-425`，`SystemControlExecutor.kt:82-102` | 后端被冒充、令牌泄露或消息重放后，可截图、读取屏幕、获取位置、强停/启动 App、控制蓝牙、改壁纸 | 建立设备配对密钥；每条命令校验签名、时间戳、nonce、设备 ID 和允许列表；高危操作弹本地确认；按功能授权而非一次授权全部能力；保留可审计记录和一键吊销 |
| 6 | Android 15 的常驻 `dataSync` 前台服务设计不成立 | `AndroidManifest.xml:118-123`，`AvelineForegroundServiceV2.kt:166-258`；未实现 `onTimeout(int,int)` | targetSdk 35 下，`dataSync` 后台累计 6 小时会超时；未及时 `stopSelf()` 会导致系统异常。当前服务试图长期常驻 | WebSocket 保活、健康采集、同步、无障碍监控拆分；短同步用 WorkManager，用户发起传输用 UIDT；实现 `onTimeout` 并停止服务；不要用 `dataSync` 冒充无限期常驻类型 |
| 7 | `BOOT_COMPLETED` 中启动 `dataSync` 前台服务与 target 35 的后台启动限制冲突 | `BootCompletedReceiver.kt:23-45`，`AndroidManifest.xml:151-158` | Android 15 上开机自启可能直接抛 `ForegroundServiceStartNotAllowedException`，代码只记录失败 | 开机仅恢复可调度任务/通知，等待用户进入 App 后再启动需要交互的能力；按官方允许的 FGS 类型和豁免重新设计 |
| 8 | 数据导出路径与 FileProvider 配置不匹配 | `DataExportManager.kt:117-135,265-279`，`file_paths.xml:1-5` | 文件写到公共 Downloads，但 FileProvider 只允许 app 专属 external-files/cache；`getUriForFile` 会失败。Android 10+ 直接写公共 Downloads 也受分区存储限制 | 优先用 Storage Access Framework `ACTION_CREATE_DOCUMENT`；或用 MediaStore 写 Downloads；不要再对公共 Downloads 文件调用当前 FileProvider |
| 9 | Android 8.0/8.1 存在 API 28 调用崩溃点 | `SettingsViewModel.kt:57,73`，`CrashHandler.kt:134`；minSdk 26 | API 26/27 调用 `PackageInfo.longVersionCode` 会触发兼容问题 | 统一用 `PackageInfoCompat.getLongVersionCode()` 或按 SDK 分支；增加 API 26/27 测试 |
| 10 | Samsung Health SDK 的 minSdk 要求被强制覆盖 | `AndroidManifest.xml:69-72`，项目 minSdk 26，SDK 要求 29 | 即使业务代码做版本判断，类加载/验证或依赖初始化仍可能在 API 26-28 失败 | 最稳妥是把 app minSdk 提到 29；否则把 Samsung 实现隔离到 API 29+ 动态加载边界，并在 API 26-28 真机做冷启动测试 |

## P1：高优先级可靠性与隐私

| # | 问题 | 证据/影响 | 建议 |
|---|---|---|---|
| 11 | 断线时发送消息会丢失 | `WebSocketManager.sendMessage()` 先异步 `connect()`，随后立刻对尚未 open 的 socket `send()`，也不检查 Boolean 返回值 | 增加有界发送队列；只在 `onOpen` 后发送；返回明确结果并让 UI 保留“待发送/失败/重试”状态 |
| 12 | 强制重连可能保留旧连接，旧 socket 回调还能覆盖新连接状态 | `connect(forceReconnect=true)` 在 URL 相同时不关闭旧 socket；回调没有校验 `webSocket === webSocketRef.get()` | 每次连接分配 generation ID；强连先 cancel/closeAndAwait 旧连接；只接受当前 generation 的回调 |
| 13 | 应用层心跳只发送 ping，不检测 pong 超时 | `WebSocketManager.kt:177-198,355-364` | 半开连接可能长时间显示 CONNECTED，消息继续丢失 | 记录最后 pong 时间；连续超时主动 cancel socket；结合前后台状态调整频率 |
| 14 | 每个 WS 消息都 `scope.launch { emit(...) }`，流式 chunk 可能乱序 | `WebSocketManager.onMessage()` | 调度压力下 chunk/done 顺序不再有硬保证 | 用单消费者 Channel/actor 顺序解析与分发，或在回调内 `tryEmit` 并显式处理背压 |
| 15 | WS 消息和远程参数没有体积上限 | 截图、壁纸 base64、设备参数和未知消息都可进入 JSON/内存 | 对帧、字段、base64 解码后的字节数设硬上限；截图先缩放/压缩；超限拒绝并记录 |
| 16 | 设备命令响应手工拼 JSON，`request_id` 未转义 | `AvelineForegroundServiceV2.kt:416-424` | 特殊字符会生成非法 JSON，也可能造成字段注入 | 全部使用 kotlinx.serialization/JSONObject 构造响应，不拼字符串 |
| 17 | 调试网络日志会输出 Authorization 和完整正文 | `NetworkModule.kt:99-126,167-188` | Debug 包/日志分享可能泄露令牌、聊天和健康数据 | `redactHeader("Authorization")`、`redactHeader("x-internal-token")`；正文日志改为显式开发开关并做字段脱敏 |
| 18 | 本地数据库未加密，却存聊天、健康、通知和记忆 | `AvelineDatabase.kt`；只有 access token 使用 EncryptedSharedPreferences | root、调试备份、物理提取或某些厂商工具可读取高敏数据 | 评估 SQLCipher/加密文件层；至少做数据分类、最短保留期、退出登录清理和用户可见的数据管理 |
| 19 | 导出文件是明文，且静默只导出每个会话最近 200 条并按倒序写出 | `DataExportManager.kt:91-110` 调用 `MessageDao.getRecentMessages()`；DAO 为 `DESC LIMIT 200` | 用户以为是完整备份，实际丢历史且顺序反了；公共目录明文泄露隐私 | 提供“完整/最近”选项和明确提示；分页导出全部并恢复升序；可选密码加密 ZIP；导出完成后显示位置和数据范围 |
| 20 | 导入不是事务，失败会留下半套数据 | `DataExportManager.kt:166-232` | 覆盖模式先清空再逐条插，任一错误会造成数据丢失/部分导入；设置已经提前变更 | 在 Room `withTransaction` 中验证后一次导入；先写临时库或做快照；成功后再提交设置 |
| 21 | 导入文件可改写 backend URL | `SettingsExport.backendUrl` 与 `importSettings()` | 用户导入来源不可信的备份后，App 会切到攻击者服务器；与自动远程控制组合风险更高 | 导入时不导入服务器/令牌，或单独列出差异并要求二次确认；URL 必须经统一验证器 |
| 22 | WorkManager 重试上限实际永远不会生效 | `DataSyncWorker.kt:41-43,107-128` 从 `inputData` 读取永远未写入的 `retry_count`，注释却说使用 runAttemptCount | 失败任务可能无限重试，耗电并刷日志 | 直接使用 `runAttemptCount`；配置指数退避；区分 4xx 永久失败与 5xx/网络临时失败 |
| 23 | 开启无障碍就无条件启动前台服务，即使“常驻模式”关闭 | `MainActivity.kt:109-121`，`BootCompletedReceiver.kt:35-42`，`AvelineForegroundServiceV2.onStartCommand()` | 用户关闭常驻模式仍看到常驻通知并被监控，语义和隐私预期不一致 | 将“无障碍功能”和“常驻连接”拆成独立开关；仅在用户明确启用时启动对应服务 |
| 24 | 常驻模式无限持有 PARTIAL_WAKE_LOCK，且健康数据 20 秒轮询 | `AvelineForegroundServiceV2.kt:128-134,212-257,555-605` | 显著耗电、发热、后台限制风险 | 用被动健康/数据变更 API；只在必要窗口持锁并设置超时；前台刷新由 UI lifecycle 驱动，后台采用更稀疏调度 |
| 25 | 单个前台服务承担 WebSocket、通知、设备控制、上下文同步、Samsung Health、无障碍监控、WakeLock | `AvelineForegroundServiceV2.kt` 713 行 | 生命周期耦合，任何一块失败都影响全部能力，难测试且前台服务类型无法准确表达 | 拆成连接协调器、同步 Worker、健康采集组件、设备命令处理器；Service 只做生命周期编排 |
| 26 | 服务器自动扫描范围过大且每次 MainActivity 创建都会执行 | `MainActivity.kt:98-108`，`ServerDiscoveryManager.kt:201-255` 扫多个常见网段约数千地址 | 启动耗电、网络噪声、可能触发路由器/安全软件告警 | 仅首次配置或用户点“发现”时执行；限制当前子网；并发、总时长、取消和进度均可控 |
| 27 | “测试连接”测试的是已保存 URL，不一定是输入框里的新 URL | `SettingsViewModel.testConnection()` 直接调用使用 AppPreferences 的单例 Retrofit；输入仅在 `saveBackendUrl()` 才落盘 | 用户输入新地址后点测试，得到旧地址结果 | 测试函数接收候选 URL，用临时 request/client；通过后再允许保存 |
| 28 | URL 校验逻辑重复且主路径只用宽松正则 | `SettingsViewModel.validateBackendUrl()` / `SettingsUiState.isBackendUrlValid` 与更严格但未复用的 `InputValidator.validateBackendUrl()` | `http://.` 等异常值可能通过；不同入口行为不一致 | 建立单一 `BackendEndpoint` value object，用 OkHttp HttpUrl 解析；限制 scheme、host、端口、路径、凭据和 fragment |
| 29 | Retrofit 动态 base URL 只替换 scheme/host/port，忽略后端 base path | `NetworkModule.kt:132-152` | 部署在反向代理子路径时请求会发到错误路径 | 用统一 endpoint resolver 合并 base path，或禁止配置带路径并在 UI 明确提示 |
| 30 | 对完整 URL 做 URLDecoder | `WebSocketManager.buildWsUrl()` | `+` 会变空格，转义的 `/`、`?` 等可改变 URL 结构 | 用 HttpUrl 分组件解析/修改，不对整段 URL 解码 |
| 31 | 危险权限声明多，但统一的运行时授权流程不完整 | Manifest 声明电话、短信、日历、定位、蓝牙、录音、通知、健康等；代码扫描只看到少量权限 launcher | 远程操作在很多设备上只会失败；用户也难理解为何需要权限 | 做功能级权限中心：使用时申请、逐项解释、拒绝后降级；未启用功能不请求；显示最近使用记录 |
| 32 | 通知内容默认被采集并上传，缺少明显的细粒度选择与保留策略 | `AvelineNotificationService.kt`，`AppPreferences.isContextSyncEnabled` 默认 true | 微信、QQ、支付、地图等通知可能包含高度敏感信息 | 首次启用时逐应用选择；默认关闭敏感应用；本地加密；内容最小化；设置保留期和立即删除入口；上传前可预览 |
| 33 | Crash 日志没有自动轮转 | `CrashHandler.kt:37-100,148-176` | 长期崩溃可无限占用 filesDir | 保留最近 N 份/总大小上限；导出时脱敏；增加用户清理入口 |
| 34 | 诊断日志在调用线程反复读取并重写整个文件，日期格式器也不是线程安全的 | `A11yDiagnosis.kt:24-48` | 生命周期回调上产生同步 IO；多线程日志可能格式错乱/丢失 | 单线程有界日志写入器，append + 定期裁剪；使用 `java.time.DateTimeFormatter` |

## P2：结构、测试、性能和体验

| # | 问题 | 当前情况 | 建议 |
|---|---|---|---|
| 35 | 测试覆盖不足 | 231 个 main Kotlin 文件，只有 15 个 JVM 测试，0 个 androidTest | 优先补安全链、WebSocket 状态机、Room migration/import/export、Deep Link、权限拒绝、Service 生命周期、Compose 关键流程测试 |
| 36 | Lint 被配置为不阻断 release | `abortOnError=false`、`checkReleaseBuilds=false` | CI/发布改为 `lintRelease` 阻断；仅对确认接受的单项设置 baseline，禁止全局放行 |
| 37 | Lint baseline 已积累 283 项且明显陈旧 | 100 UnusedResources、96 ExtraTranslation、5 MissingPermission、3 NewApi、1 MissingClass 等，部分还指向已删除的 Legacy 文件 | 先清理过期 baseline，再逐类消减；安全/权限/NewApi/MissingClass 不允许 baseline |
| 38 | Room schema 链不完整 | 有 v1、v3，没有 v2 schema | 把 v2 schema 纳入版本库；用 MigrationTestHelper 验证 1→2、2→3、1→3 和降级策略 |
| 39 | 多个 God class/大文件 | `SystemControlExecutor` 1097 行、`SamsungHealthReader` 989、`ChatScreen` 941、`ChatViewModel` 905、`AvelineApiService` 720、前台服务 713 | 按领域/用例拆分；UI 分 screen/state/content/dialog；API 按 chat/health/study/system 分接口；Executor 按 app/location/bluetooth/a11y/media 拆分 |
| 40 | Compose 状态和业务逻辑过度集中在 ViewModel/Screen | Chat、Study、Health 多文件 600-900 行 | 引入小型 use case/interactor；UI state 按 feature 分片；把纯转换逻辑做成可测试函数 |
| 41 | App 体积过大 | 现有 debug APK 约 87.8 MB；端侧 ASR 模型约 53.8 MB；5 份 launcher foreground PNG 各约 1.4 MB | ASR 模型做按需下载/动态交付；模型校验和断点续传；图标改矢量或正确密度 WebP；使用 App Bundle/ABI split |
| 42 | 只打包 arm64 原生库 | `jniLibs/arm64-v8a` | 明确最低设备范围；需要模拟器/Chromebook 时补 x86_64；用 ABI split 避免无关体积 |
| 43 | 国际化基本未完成 | 默认 values 约 5 条、values-zh 约 119 条，Kotlin 中约 198 处直接硬编码 UI 文案；却声明 `zh`、`en` | 所有用户可见文本进入资源；默认资源必须完整；增加资源一致性检查和伪本地化截图测试 |
| 44 | 可访问性不一致 | 大量点击元素与 Icon 使用 `contentDescription=null`，部分整块 `clickable` 没有 role/语义 | 区分装饰图标和操作图标；补 role、stateDescription、heading、合并语义；检查 48dp 触控区、字体缩放和 TalkBack 顺序 |
| 45 | UI 文案、错误和日志中中英混用 | 设置/通知/异常信息同时出现中英文 | 面向用户统一资源化中文/英文；内部错误码与本地化展示分离 |
| 46 | TTS 流式管线使用两个 UNLIMITED Channel | `TTSEngine.kt:348-349` | 超长响应或合成/播放速度失衡时队列无界增长 | 使用有界 Channel；明确背压/丢弃策略；限制单句和整段长度；取消时删除临时音频 |
| 47 | ProGuard keep 规则过宽 | 整包 serialization、Hilt、Work、Health 多处 `-keep class ... { *; }` | 依据库官方 consumer rules 缩小 keep；用 release mapping 和反射测试验证，改善体积与混淆效果 |
| 48 | Wear release 不压缩且引用不存在的 proguard 文件 | `wear/build.gradle.kts` 的 release `isMinifyEnabled=false`，`wear/proguard-rules.pro` 不存在 | 创建实际规则文件；对 release 开启 shrink/minify 并做手表真机回归 |
| 49 | FCM token 上传路径重复 | MainActivity 启动上传一次，FirebaseMessagingService onCreate/onNewToken 又上传 | 保留 `onNewToken` + 一次确保注册的仓库层；用 token hash/时间去重，服务端做幂等 |
| 50 | Release 版本与发布流程未成型 | 手机和 Wear 都固定 versionCode 1/versionName 1.0；没有 CI、签名或发布轨道配置 | 用统一版本源和自动递增；CI 做 unit/lint/release assemble；密钥只在安全环境注入；生成 changelog 与 SBOM |
| 51 | 依赖版本分散且 Compose BOM 又被 force 覆盖 | build 文件中直接写大量版本，同时 `resolutionStrategy.force` 固定 Compose | 引入 version catalog；优先只用 BOM；每月依赖更新和漏洞扫描；本地 Samsung AAR 记录来源、许可证、hash 和升级流程 |
| 52 | 手机与 Wear 的 Health Connect 版本不一致 | phone alpha07，wear alpha02 | 统一经过验证的版本矩阵；共享健康 DTO/协议契约；增加 Data Layer 兼容测试 |

## P3：长期维护建议

| # | 改进项 | 建议 |
|---|---|---|
| 53 | 模块化 | 至少拆成 `core-model`、`network`、`database`、`feature-chat`、`feature-health`、`feature-study`、`device-control`；高风险 device-control 可做独立可选模块/独立 flavor |
| 54 | 构建变体 | 增加 `devLan`（允许 HTTP/用户 CA/详细日志）与 `release`（只允许 TLS/脱敏日志）两个明确变体，避免安全策略靠运行时约定 |
| 55 | 权限与隐私仪表盘 | 展示每项权限用途、是否启用、最近调用、最近上传、保留数据量，并支持一键停止/删除/吊销配对 |
| 56 | 远程控制审计 | 对每条指令记录来源设备、签名 ID、时间、权限、结果；不记录敏感参数原文；提供高危操作历史 |
| 57 | 可观测性 | 网络层统一错误分类、连接代次、重连原因、心跳 RTT；避免直接把异常 message 暴露给用户；诊断包自动脱敏 |
| 58 | 性能基线 | 增加 Macrobenchmark/Baseline Profile，关注冷启动、Chat 首屏、长列表滚动、图片消息、ASR 模型加载和内存峰值 |
| 59 | 进程死亡恢复 | 对正在发送消息、SSE、TTS、文件上传、学习计时和导入任务定义恢复/取消语义，不只保存 Deep Link |
| 60 | 数据保留 | 对通知、健康、聊天、截图、TTS、崩溃和诊断数据分别规定保留期、空间上限与清理策略 |
| 61 | 统一序列化 | PhoneAction/DeviceCommand/response 全部使用强类型 kotlinx.serialization，避免 `JSONObject`、`toString().trim('"')` 与字符串拼 JSON 混用 |
| 62 | 文档与威胁模型 | 给“服务器发现、设备配对、令牌、WebSocket、Shizuku、无障碍、通知采集”画清晰的信任边界和攻击面，并把安全回归列入每次发布检查 |

## 推荐落地批次

### 第一批：安全止血

- 关闭 release 全局明文和用户 CA。
- 禁止自动覆盖后端，先做配对确认。
- 修复 shell 参数注入。
- WS 令牌移出 URL。
- 远程命令加入签名、nonce、权限和高危确认。
- 修复 Android 15 FGS/BOOT 设计。

### 第二批：功能可靠性

- 修数据导出、完整备份和事务导入。
- 修 API 26/27 崩溃。
- 修 WorkManager 重试计数。
- 重写 WebSocket 为单一状态机、有界队列、代次校验和 pong 超时。
- 统一 URL 校验与候选连接测试。

### 第三批：工程质量

- 打开 release Lint 阻断并清 baseline。
- 补 migration、网络状态机和关键 UI 自动化测试。
- 拆 God class 与 API 接口。
- 完成字符串资源化、TalkBack 与字体缩放。
- 模型按需下载、图标瘦身、ABI/App Bundle 优化。

## 已确认的优点

- Access token 已使用 `EncryptedSharedPreferences`。
- Room 升级方向上没有对升级使用 destructive migration，仅降级允许销毁。
- Service/FCM/通知监听的 CoroutineScope 多数已经使用 SupervisorJob 并在销毁时取消。
- WebSocket 已有指数退避和 jitter，也修过协议头归一化与重连后心跳恢复。
- TTS 缓存已有 50 MB 上限，通知去重 Map 也有限制。
- Deep Link 已有页面白名单和单参数长度限制。
- release 已开启 shrink/minify（手机端）。

这些基础是好的，但需要把安全信任链、Android 15 后台限制和数据一致性放到下一阶段的最高优先级。
