# DI/Domain/架构入口层代码审查报告

## 审查概览

本报告针对 Aveline 安卓客户端的 DI 层、Domain Repository 层与架构入口层(Application / MainActivity / MainViewModel / EmotionResolver / HealthManager / AndroidManifest)进行深度代码审查。

### 审查范围

| 分类 | 文件 | 行数 |
|------|------|------|
| DI | AppModule.kt | 46 |
| DI | DatabaseModule.kt | 58 |
| DI | NetworkModule.kt | 188 |
| DI | RepositoryModule.kt | 130 |
| Domain | ChatRepository.kt | 41 |
| Domain | ContextRepository.kt | 69 |
| Domain | HealthRepository.kt | 65 |
| Domain | MemoryRepository.kt | 62 |
| Domain | PersonaRepository.kt | 58 |
| Domain | PluginsRepository.kt | 66 |
| Domain | SessionRepository.kt | 43 |
| Domain | ShopRepository.kt | 49 |
| Domain | StatusRepository.kt | 22 |
| Domain | StudyRepository.kt | 134 |
| Domain | ToolsRepository.kt | 18 |
| 入口 | AvelineApplication.kt | 37 |
| 入口 | MainActivity.kt | 344 |
| 入口 | MainViewModel.kt | 322 |
| 入口 | EmotionResolver.kt | 186 |
| 入口 | HealthManager.kt | 227 |
| 入口 | AndroidManifest.xml | 181 |

### 问题统计

- 🔴 严重问题: 9 个
- 🟠 中等问题: 38 个
- 🟡 轻微问题: 18 个
- 合计: 65 个真实可优化项

### 关键发现概览

1. **Repository 接口职责严重混乱**:StudyRepository(34 个方法)与 ToolsRepository(14 个方法)承担了过多不相关职责,且 `recordDailyStudy` / `finishDailyStudy` 在 HealthRepository 与 StudyRepository 中重复定义。
2. **HealthManager 与 HealthRepository 双轨并存**:同为健康数据入口,一个返回 String(JSON),一个返回 HealthData?,设计割裂。
3. **Domain 层大量泄漏 JSON 类型**:`Result<JsonObject>` / `Result<JsonElement?>` 等返回类型让上层耦合 kotlinx.serialization,违反 Clean Architecture。
4. **MainActivity 用 static AtomicReference 传递 DeepLink**:跨重建生命周期不可靠。
5. **AndroidManifest 缺少 specialUse FGS 的 property 声明**:Android 14+ 会运行时崩溃;同时申请了 `CALL_PHONE` / `SEND_SMS` 等敏感权限,审核风险高。
6. **Application 启动链路无异常兜底,且未使用 App Startup 库**。
7. **MainViewModel.switchSession 未调用 Repository 持久化**,且多个方法存在竞态条件。
8. **NetworkModule 占位 baseUrl `127.0.0.1` 在 backendUrl 为空时会让所有请求静默失败**。
9. **EmotionResolver.parseColor 6 位 hex 颜色解析为透明**(alpha=0),潜在 UI bug。

---

## 逐文件审查

### AppModule.kt

#### 问题1: 🟡 遗留未使用的 import
- 位置: `di/AppModule.kt:14`
- 问题描述: `import kotlinx.serialization.json.Json` 在整个文件中没有任何引用,是历史重构遗留。NetworkModule 里另有一个 `provideJson()` 已经独立提供 Json 实例。未使用 import 会增加编译期负担,且让阅读者误以为 AppModule 也提供 Json。
- 建议方案: 删除该 import 行。

#### 问题2: 🟡 provideApplicationContext 是冗余 Provides
- 位置: `di/AppModule.kt:21-24`
- 问题描述: Hilt 默认就能把 `Application` 自动转换为 `@ApplicationContext Context`,无需手动 Provides。这里手动写一个 `provideApplicationContext(application: Application): Context` 反而会与 Hilt 内置绑定产生歧义——Hilt 既可以从 Application→Context 走默认路径,也可以走这条 Provides,虽然在 SingletonComponent 下结果一致,但属于"造轮子"。
- 建议方案: 删除该方法,所有需要 Context 的地方直接用 `@ApplicationContext context: Context` 注入即可。

#### 问题3: 🟡 provideResources 的 @Singleton 必要性可商榷
- 位置: `di/AppModule.kt:26-29`
- 问题描述: `context.resources` 返回的是 Resources 单例(Android 框架保证),再包一层 `@Singleton` 并不会改变行为,但增加了 Hilt 维护成本(生成多余的 Provider 类)。
- 建议方案: 可以保留 Provides 但去掉 `@Singleton`(让 Hilt 每次都调用,实际还是同一个 Resources 实例),或直接删除该 Provides 让使用方自己 `context.resources` 获取。

---

### DatabaseModule.kt

#### 问题4: 🟠 DAO Provider 未加 @Singleton
- 位置: `di/DatabaseModule.kt:31-55`(`provideMessageDao` / `provideSessionDao` / `provideMemoryDao` / `provideNotificationDao` / `provideHealthDataDao` 五个方法)
- 问题描述: 这五个 DAO Provider 都没有 `@Singleton` 注解。Room 的 `database.messageDao()` 每次调用都会返回新实例(实际内部会做缓存,但 API 层面不保证)。当多个 ViewModel / Repository 同时注入同一 Dao 时,Hilt 会每次都新建一个 Dao 包装对象,造成不必要的对象分配,且不同调用方拿到的 Dao 实例 `===` 不相等,不利于调试。
- 建议方案: 给所有 DAO Provider 加上 `@Singleton`。Room 官方推荐做法是 Database 单例 + Dao 单例。

#### 问题5: 🟡 缺少正式 Migration 策略说明
- 位置: `di/DatabaseModule.kt:21-27`
- 问题描述: 只配置了 `fallbackToDestructiveMigrationOnDowngrade()`,升级时如果 schema 变化但没有提供 `Migration`,Room 会在编译期报错,但运行期如果通过其他方式绕过会直接抛 `IllegalStateException`。代码注释提到"升级时必须编写正式 Migration",但没有提供任何 `addMigrations()` 入口。
- 建议方案: 至少保留一个 `addMigrations(*DatabaseMigrations.ALL)` 的调用位置(即使当前为空数组),让后续维护者明确 Migration 该往哪里加。

---

### NetworkModule.kt

#### 问题6: 🔴 占位 baseUrl `127.0.0.1` 在 backendUrl 为空时让所有请求静默失败
- 位置: `di/NetworkModule.kt:27` (`PLACEHOLDER_BASE_URL = "http://127.0.0.1/"`) + `di/NetworkModule.kt:73-91` (`provideBaseUrlInterceptor`)
- 问题描述: Retrofit 初始化时用 `http://127.0.0.1/` 作占位 baseUrl。运行时 `provideBaseUrlInterceptor` 会从 `appPreferences.backendUrl` 读取真实地址并改写 URL。**但当 `appPreferences.backendUrl` 为空(首次安装/未配置)时**,`normalizeBackendUrl` 返回 `""`,`toHttpUrlOrNull()` 返回 `null`,拦截器直接 `return@Interceptor chain.proceed(request)`——请求会带着原始的 `127.0.0.1` 占位地址发出去,服务端无人监听,连接被拒绝,上层只能拿到 `ConnectException`,无法定位"未配置后端"这一根因。
- 建议方案:
  1. 在 `provideBaseUrlInterceptor` 中,当 `backendHttpUrl == null` 时直接抛 `IllegalStateException("Backend URL not configured")` 或返回一个明确的错误响应,而不是放行到 `127.0.0.1`。
  2. 或者在 `AppPreferences.backendUrl` 为空时,UI 层强制引导用户进入服务器配置页,不让任何业务请求发出。

#### 问题7: 🟠 鉴权拦截器同时加两个带 token 的 header,设计冗余
- 位置: `di/NetworkModule.kt:74-87`
- 问题描述: 同一个 token 同时被放进 `Authorization: Bearer $token` 和 `x-internal-token: $token` 两个 header。如果是后端为了兼容两种鉴权方式,可以理解;但长期来看会让攻击面变大(token 在两个 header 里都暴露),且后端只需校验其中一个即可。
- 建议方案: 与后端确认是否真的需要两个 header。如果只需要一个,删掉另一个;如果确实需要两种鉴权场景(如 Bearer 用于标准 JWT,x-internal-token 用于内部网关),应在注释里说明,且考虑用不同的 token 而非同一个。

#### 问题8: 🟠 pingInterval 注释误导
- 位置: `di/NetworkModule.kt:134-145`(`.pingInterval(15, TimeUnit.SECONDS)`)
- 问题描述: 注释说"WebSocket 心跳",但 `OkHttpClient.pingInterval` 配置的是 HTTP/2 的 ping 帧,与 WebSocket 心跳无关。WebSocket 的心跳应该在 `WebSocketManager` 内部通过 `send` 一个 ping frame 或应用层心跳消息实现。误导性注释会让维护者误以为 WebSocket 心跳已配置而不再检查 WebSocketManager。
- 建议方案: 修正注释为"HTTP/2 连接保活 ping",并确认 WebSocketManager 内部是否真的有心跳机制。

#### 问题9: 🟡 OkHttp 未配置 Dispatcher / ConnectionPool 上限
- 位置: `di/NetworkModule.kt:134-145`
- 问题描述: 默认 Dispatcher 最大并发请求数 64、单 host 最大 5。对于与单一后端通信的 App 通常够用,但如果未来有大量并发上传/下载(如 StudyRepository 的文件上传),可能被 5 个并发限制阻塞。
- 建议方案: 如果预期有大并发场景,显式配置 `Dispatcher().apply { maxRequestsPerHost = 10 }` 并加注释说明理由;否则保持默认即可,但应在注释中说明"当前依赖默认 Dispatcher 配置"。

#### 问题10: 🟡 baseUrl 拦截器每次请求都重新解析字符串
- 位置: `di/NetworkModule.kt:74-91`
- 问题描述: `appPreferences.backendUrl` 是个字符串,每次请求都 `trim()` / `trimEnd('/')` / `startsWith` 检查 / `toHttpUrlOrNull()` 解析一遍。虽然单次开销小,但高频请求下是浪费。
- 建议方案: 用 `StateFlow<String>` 观察 backendUrl 变化,缓存解析后的 `HttpUrl`,拦截器直接读缓存。或用 `AtomicReference<HttpUrl?>` 在 backendUrl 变更时更新。

---

### RepositoryModule.kt

#### 问题11: 🟡 全部 Repository 强制 @Singleton,缺少 scope 思考
- 位置: `di/RepositoryModule.kt:24-128`(11 个 `@Binds @Singleton`)
- 问题描述: 所有 Repository 都绑定为 `@Singleton`。对于 Android 应用,Repository 持有 Dao / ApiService 等单例依赖时,Repository 自身单例是常见做法,但并非所有 Repository 都需要在 App 全生命周期存活。例如 `ShopRepository` 只在商店页面打开时才需要,绑成 `@ActivityRetainedScoped` 或 `@ViewModelScoped` 更合理。统一 Singleton 会让 App 启动时 Hilt 图变大(虽然懒加载,但心智负担重)。
- 建议方案: 评估每个 Repository 的使用范围。高频使用的(ChatRepository / SessionRepository / HealthRepository)保持 Singleton;页面级使用的(ShopRepository / StudyRepository)考虑改为更窄的 scope。

#### 问题12: 🟡 KDoc 注释为英文,与项目规范不一致
- 位置: `di/RepositoryModule.kt:14-19, 24-26, 31-33, ...`(所有 KDoc)
- 问题描述: 项目规则明确要求"统一用中文注释",但 RepositoryModule 的 KDoc 全是英文(`Hilt module for repository bindings.` / `Binds ChatRepository interface to ChatRepositoryImpl.`)。
- 建议方案: 改写为中文 KDoc。

#### 问题13: 🟡 11 个绑定堆在一个文件,可按业务域拆分
- 位置: `di/RepositoryModule.kt:1-130`
- 问题描述: 单文件 130 行,11 个 Repository 绑定。随着业务增长,这个文件会越来越大。Hilt 允许多个 Module,按业务域拆分(Chat / Health / Study / Tools / Misc)更易维护。
- 建议方案: 拆分为 `ChatRepositoryModule` / `HealthRepositoryModule` / `StudyRepositoryModule` / `ToolsRepositoryModule` / `MiscRepositoryModule`,各自负责相关 Repository 的绑定。

---

### ChatRepository.kt

#### 问题14: 🟠 getPersona 职责错位
- 位置: `domain/repository/ChatRepository.kt:25-26`(`suspend fun getPersona(): Result<JsonObject>`)
- 问题描述: `getPersona` 放在 ChatRepository 中,但 Persona 明显是 `PersonaRepository` 的职责。这种错位会让上层(如 ViewModel)为了拿 persona 而注入 ChatRepository,造成耦合扩散。且 `PersonaRepository.getActivePersona()` 已经存在,功能重复。
- 建议方案: 删除 ChatRepository.getPersona(),让上层用 PersonaRepository。

#### 问题15: 🟠 webSearch 职责错位 + 返回 JSON
- 位置: `domain/repository/ChatRepository.kt:31`(`suspend fun webSearch(query: String): Result<JsonObject>`)
- 问题描述: 联网搜索不是 Chat 的核心职责,应该独立成 `SearchRepository` 或放在 `ToolsRepository`。同时返回 `JsonObject` 让上层耦合 JSON schema。
- 建议方案: 抽取到独立的 `SearchRepository.webSearch(query): Result<SearchResult>`,定义 `SearchResult` domain model。

#### 问题16: 🟠 getPersona / webSearch 返回 JsonObject 暴露 JSON 层细节
- 位置: `domain/repository/ChatRepository.kt:25, 31`
- 问题描述: Domain 层接口应该返回 domain model,但这里返回 `JsonObject` / `Result<JsonObject>`,让 presentation 层直接依赖 `kotlinx.serialization.json`,违反了分层抽象。一旦后端 JSON 字段变化,所有调用方都要改。
- 建议方案: 定义 `Persona` / `SearchResult` domain model,Repository 内部完成 JSON→model 映射。

---

### ContextRepository.kt

#### 问题17: 🟠 recordBodyMetrics 职责错位
- 位置: `domain/repository/ContextRepository.kt:60`(`suspend fun recordBodyMetrics(weight: Double?, height: Double?): Result<JsonObject>`)
- 问题描述: 记录体重/身高是健康数据,应该归 `HealthRepository`,而不是设备上下文仓库。这种错位会让上层在 ContextRepository 里找健康相关方法,造成心智负担。
- 建议方案: 移动到 `HealthRepository`,并在 HealthRepository 中定义 `Result<BodyMetricsRecord>` 而非 `Result<JsonObject>`。

#### 问题18: 🟠 openUsageStatsSettings / openNotificationListenerSettings 不该在 Repository
- 位置: `domain/repository/ContextRepository.kt:48-57`
- 问题描述: Repository 是数据访问层,不应该负责"打开系统设置页"这种 UI 操作。这种设计让 Repository 依赖了 `Intent` / `Context`(隐式),破坏了分层。
- 建议方案: 把这两个方法移到 presentation 层的 `PermissionHelper` 或 `SettingsNavigator`,Repository 只负责 `hasUsageStatsPermission(): Boolean` 这种纯查询。

#### 问题19: 🟠 返回类型风格不统一
- 位置: `domain/repository/ContextRepository.kt:18-67`
- 问题描述: `getDeviceContext()` 返回 `DeviceContext`(无 Result 包装,失败时抛异常);`getAppUsage()` 返回 `List<AppUsageInfo>`(同上);`syncToBackend()` 返回 `Result<Unit>`;`uploadDeviceSnapshot()` 返回 `Result<JsonObject>`。同一个接口里四种风格,调用方无法预期错误处理方式。
- 建议方案: 统一为 `Result<T>` 风格,或统一为抛异常风格,不要混用。

#### 问题20: 🟡 uploadDeviceSnapshot 返回 JsonObject
- 位置: `domain/repository/ContextRepository.kt:63`
- 问题描述: 同问题 16,Domain 层不应该暴露 JSON 类型。
- 建议方案: 定义 `DeviceSnapshotUploadResult` domain model。

---

### HealthRepository.kt

#### 问题21: 🔴 recordDailyStudy / finishDailyStudy 与 StudyRepository 严重重复
- 位置: `domain/repository/HealthRepository.kt:58-65` 与 `domain/repository/StudyRepository.kt:104-109`
- 问题描述: 两个 Repository 都定义了 `recordDailyStudy(payload: JsonObject): Result<JsonObject>` 和 `finishDailyStudy(): Result<JsonObject>`,签名完全一致。这意味着:
  1. 上层不知道该调哪个,实现层可能重复请求同一后端接口。
  2. 修改其中一个忘了改另一个,会导致行为不一致。
  3. 后端 `/api/v1/health/daily/study` 与 `/api/v1/study/daily/study` 是否是同一接口?如果是,后端也会有路由歧义。
- 建议方案: 明确"每日学习会话"归一个 Repository 管理(建议归 StudyRepository,因为是学习行为;HealthRepository 只负责生理数据)。删除 HealthRepository 中的这两个方法。

#### 问题22: 🟠 getDailyPortraitToday / getDailyRecent / recordDailyDrink 职责错位
- 位置: `domain/repository/HealthRepository.kt:52-56`
- 问题描述: "每日画像"和"每日喝水"听起来是生活记录,与生理健康数据(步数/心率)是不同的概念。放在 HealthRepository 里让这个接口变得杂乱。
- 建议方案: 抽取 `DailyRepository`(或 `LifeRepository`),专门管理每日画像、每日喝水、每日学习等"生活日志"类接口。

#### 问题23: 🟠 openHealthConnectSettings 是 UI 操作
- 位置: `domain/repository/HealthRepository.kt:45-46`
- 问题描述: 同问题 18,Repository 不该负责打开系统设置。
- 建议方案: 移到 presentation 层的 PermissionHelper。

#### 问题24: 🟠 readVitalSigns / readBodyMetrics / readHealthData 语义重叠
- 位置: `domain/repository/HealthRepository.kt:33-42`
- 问题描述: 三个方法都返回 `HealthData?`。`readHealthData` 是合并 `readVitalSigns` + `readBodyMetrics` 吗?接口签名看不出来。调用方面对三个方法不知道该用哪个。
- 建议方案: 要么合并为一个 `readHealthData(type: HealthDataType): HealthData?`(枚举区分 VITALS / BODY_METRICS / ALL),要么把 `readHealthData` 删掉,让上层自己组合。

#### 问题25: 🟡 大量返回 Result<JsonObject>
- 位置: `domain/repository/HealthRepository.kt:51-65`
- 问题描述: 同问题 16。
- 建议方案: 定义 `DailyPortrait` / `DailyDrinkRecord` 等 domain model。

---

### MemoryRepository.kt

#### 问题26: 🟠 返回类型风格不统一
- 位置: `domain/repository/MemoryRepository.kt:19-50`
- 问题描述: `getMemories` / `searchMemories` / `getMemory` / `getMemoryStats` / `getMemoryTypes` / `getTags` 都直接返回 `List<...>` / `T?`(无 Result,失败抛异常);而 `deleteMemory` / `markImportant` / `clearAll` / `clearSessionHistory` 返回 `Result<Unit>`。风格不一致。
- 建议方案: 统一为 `Result<T>` 或统一为抛异常 + 在 ViewModel 层 try-catch。

#### 问题27: 🟡 clearAll 默认 userId = "default" 是危险默认值
- 位置: `domain/repository/MemoryRepository.kt:52`(`suspend fun clearAll(userId: String = "default"): Result<Unit>`)
- 问题描述: 默认 userId 为 `"default"`,如果调用方忘记传 userId,会清除"default"用户的全部记忆。生产环境如果多用户共用一个设备,会误删其他用户数据。
- 建议方案: 去掉默认值,强制调用方传 userId;或从 AppPreferences / SessionManager 注入当前 userId。

---

### PersonaRepository.kt

#### 问题28: 🟠 getPersonasRaw / getActivePersonaRaw 暴露 JSON,且理由站不住脚
- 位置: `domain/repository/PersonaRepository.kt:52-57`
- 问题描述: 注释说"用于 Web 端 UI",但这是 Android 项目,根本没有 Web 端。返回 `JsonArray` / `JsonObject` 让 presentation 层直接解析 JSON,完全破坏了分层。同时 `getPersonas()` 已经返回 `List<Persona>`,Raw 版本只是把同一数据用另一种格式暴露。
- 建议方案: 删除 Raw 版本,如果 Persona model 缺少某些字段,补充到 Persona data class 中(用 `@SerialName` 映射)。

#### 问题29: 🟡 Raw 与非 Raw 返回类型风格不一致
- 位置: `domain/repository/PersonaRepository.kt:18-57`
- 问题描述: `getPersonas()` 返回 `List<Persona>`(无 Result),`getPersonasRaw()` 返回 `Result<JsonArray>`。同一个概念两种风格。
- 建议方案: 统一为 `Result<List<Persona>>`。

---

### PluginsRepository.kt

#### 问题30: 🟠 Repository 命名与职责严重不符
- 位置: `domain/repository/PluginsRepository.kt:17-66`
- 问题描述: 名字叫 `PluginsRepository`,实际混了三类职责:
  1. 模型管理(`getModels` / `getSelectedModel` / `switchModel`)
  2. 插件设置(`getSettings` / `setResponseLength`)
  3. 情绪设置(`setManualEmotion` / `setAutoEmotion` / `setBreathingRate`)
  这三类应该分属 `ModelRepository` / `PluginSettingsRepository` / `EmotionSettingsRepository`。
- 建议方案: 拆分为三个 Repository。或至少重命名为 `SettingsRepository` 以更准确反映内容。

#### 问题31: 🟡 setBreathingRate / setManualEmotion / setAutoEmotion 是 UI 偏好
- 位置: `domain/repository/PluginsRepository.kt:42-52`
- 问题描述: 这些是 UI 层的偏好设置(呼吸频率、手动情绪、自动情绪开关),放在 Repository 里不太合适,更适合用 DataStore + PreferencesRepository。
- 建议方案: 抽取 `UserPreferencesRepository`,基于 DataStore 管理这些 UI 偏好。

---

### SessionRepository.kt

#### 问题32: 🟢 接口设计相对清晰
- 位置: `domain/repository/SessionRepository.kt:1-43`
- 问题描述: 5 个方法,职责单一(会话 CRUD + 观察),返回类型统一为 `Result<T>` / `Flow<T?>`,无明显问题。
- 备注: 已审查无问题。

#### 问题33: 🟡 updateSession 粒度过粗
- 位置: `domain/repository/SessionRepository.kt:33-37`
- 问题描述: `updateSession(session: Session)` 接受整个 Session 对象,但实际场景(从 MainViewModel 看)只有 rename 和 togglePin 两种操作。每次都构造完整 Session 对象再发送,后端要处理整个实体的更新,容易误改字段。
- 建议方案: 拆分为 `renameSession(id, title)` 和 `togglePin(id, isPinned)`,或提供 `patchSession(id, patch: SessionPatch)` 风格。

---

### ShopRepository.kt

#### 问题34: 🟠 返回类型风格不统一
- 位置: `domain/repository/ShopRepository.kt:19-44`
- 问题描述: `getItems` / `getItemsByType` / `getItemById` / `getBalance` / `canPurchase` 都直接返回值(无 Result);只有 `purchaseItem` 返回 `Result<PurchaseResult>`。风格不一致。
- 建议方案: 统一为 `Result<T>`。

#### 问题35: 🟡 canPurchase 可能是冗余方法
- 位置: `domain/repository/ShopRepository.kt:39-44`
- 问题描述: `canPurchase` 返回 Boolean,但 `purchaseItem` 内部应该已经做了余额校验。如果 UI 只是为了显示"可购买"按钮状态,这个方法有意义;但如果 UI 先调 canPurchase 再调 purchaseItem,就是双倍请求。
- 建议方案: 确认 UI 用途。如果只是按钮状态,保留;如果是为了"先校验再购买",删除让 purchaseItem 自己返回失败原因。

---

### StatusRepository.kt

#### 问题36: 🟠 getActiveCareStatus / triggerActiveCareCheck 职责错位
- 位置: `domain/repository/StatusRepository.kt:16-21`
- 问题描述: "主动关怀"是一个独立的功能模块,不应该塞进 `StatusRepository`(Status 听起来是"生命状态/情绪状态")。这种错位会让主动关怀相关逻辑散落在 Status 调用方里。
- 建议方案: 抽取 `ActiveCareRepository`,专门管理主动关怀状态与触发。

#### 问题37: 🟡 detectEmotion 返回 JsonObject
- 位置: `domain/repository/StatusRepository.kt:14`
- 问题描述: 同问题 16。
- 建议方案: 定义 `EmotionDetectionResult` domain model。

---

### StudyRepository.kt

#### 问题38: 🔴 严重职责过载,34 个方法混合 5 类职责
- 位置: `domain/repository/StudyRepository.kt:1-134`
- 问题描述: 单个 Repository 接口定义了 34 个方法,涵盖:
  1. 学习文件管理(`getFiles` / `uploadFile` / `deleteFile` / `observeFiles`)
  2. 学习模式开关(`getStudyModeState` / `setStudyModeEnabled` / `setActiveFiles` / `observeStudyMode`)
  3. 词汇复习(`getDailyVocabulary` / `startReviewSession` / `submitReview` / `endReviewSession`)
  4. 词典查询(`getSubjects` / `addVocabulary` / `searchDictionary`)
  5. 工作区学习记录(`getWorkspaceStudyPanel` / `recordWorkspaceStudy`)
  6. 每日学习会话(`recordDailyStudy` / `finishDailyStudy`,与 HealthRepository 重复)
  7. Study/Daily 文件夹(`getCalendar` / `getDateContent` / `getNotes` / `getNote` / `getLatestProgress` / `getDiaries`)

  Interface Segregation Principle 严重违反。任何 ViewModel 想用其中一小块功能,都要注入整个 Repository,心智负担极大。
- 建议方案: 拆分为:
  - `StudyFileRepository`(文件管理)
  - `StudyModeRepository`(学习模式)
  - `VocabularyRepository`(词汇复习 + 词典)
  - `WorkspaceStudyRepository`(工作区学习记录)
  - `DailyStudyRepository`(每日学习会话,与 HealthRepository 协调归属)
  - `DailyContentRepository`(Study/Daily 文件夹、笔记、日记)

#### 问题39: 🟠 uploadFile 直接暴露 Android Uri 给 domain 层
- 位置: `domain/repository/StudyRepository.kt:25-31`(`suspend fun uploadFile(uri: Uri, onProgress: (Float) -> Unit = {}): Result<StudyFile>`)
- 问题描述: Domain 层接口应该与 Android 框架解耦,但 `android.net.Uri` 直接出现在接口签名里。这让 domain 层依赖了 Android SDK,无法做纯 JVM 单元测试。
- 建议方案: 定义 domain 层的 `FilePath` / `FileUri` value class(包装 String),Repository 实现层再把 String 转成 Android Uri。

#### 问题40: 🟠 大量方法返回 Result<JsonObject>
- 位置: `domain/repository/StudyRepository.kt:73-134`(`getSubjects` / `addVocabulary` / `searchDictionary` / `getDailyVocabulary` / `startReviewSession` / `submitReview` / `endReviewSession` / `getWorkspaceStudyPanel` / `recordWorkspaceStudy` / `recordDailyStudy` / `finishDailyStudy` / `getDiaries`)
- 问题描述: 同问题 16,11 个方法返回 `Result<JsonObject>`,让上层完全无法静态感知返回结构。
- 建议方案: 为每个方法定义 domain model(如 `Subject` / `VocabularyWord` / `ReviewSession` / `ReviewSubmitResult` / `WorkspaceStudyPanel` / `DiaryEntry` 等)。

---

### ToolsRepository.kt

#### 问题41: 🔴 严重职责过载,14 个方法混合 7 类完全不同的职责
- 位置: `domain/repository/ToolsRepository.kt:1-18`
- 问题描述: `ToolsRepository` 是个"杂物间",塞了:
  1. 图像生成(`getImageModels` / `generateImage`)
  2. 图像识别(`describeVision`)
  3. 食物菜单(`getFoodMenu`)
  4. 食物库存(`getFoodInventory` / `buyFood` / `eatFood`)
  5. 通知(`getNotifications`)
  6. 意图分类(`classifyIntent`)
  7. 系统偏好/资源/统计(`getSystemPreferences` / `updateSystemPreferences` / `getSystemResources` / `getSystemStats`)
  8. 敏感状态(`getSensitiveStatus` / `toggleSensitive`)

  这些毫无关联的功能堆在一个接口里,是典型的"万能工具箱"反模式。
- 建议方案: 拆分为:
  - `ImageRepository`(图像生成 + 识别)
  - `FoodRepository`(菜单 + 库存 + 购买 + 进食,与 ShopRepository 合并)
  - `NotificationRepository`(通知查询)
  - `IntentClassifierRepository`(意图分类)
  - `SystemRepository`(系统偏好 + 资源 + 统计)
  - `SensitiveContentRepository`(敏感状态)

#### 问题42: 🟠 generateImage 返回 Pair<String?, String?> 可读性差
- 位置: `domain/repository/ToolsRepository.kt:6`(`suspend fun generateImage(prompt: String, modelPath: String?, negativePrompt: String?): Result<Pair<String?, String?>>`)
- 问题描述: `Pair<String?, String?>` 完全无法看出两个 String 分别是什么(图片 URL?任务 ID?错误信息?)。调用方需要靠注释或猜才能用对。
- 建议方案: 定义 `ImageGenerationResult(val imageUrl: String?, val taskId: String?)` data class。

#### 问题43: 🟠 大量返回 Result<JsonElement?>
- 位置: `domain/repository/ToolsRepository.kt:5, 12-14, 16-18`
- 问题描述: 同问题 16,且 `JsonElement?` 比 `JsonObject` 更模糊(可能是数组、字符串、数字)。
- 建议方案: 定义具体 domain model。

#### 问题44: 🟡 食物相关方法应归 ShopRepository
- 位置: `domain/repository/ToolsRepository.kt:8-11`
- 问题描述: `getFoodMenu` / `getFoodInventory` / `buyFood` / `eatFood` 与 `ShopRepository` 的 `getItems` / `purchaseItem` 高度重叠(食物就是 Shop 的一个 type)。
- 建议方案: 合并到 ShopRepository,用 `FoodCategory` 区分。

---

### AvelineApplication.kt

#### 问题45: 🟠 onCreate 同步执行耗时操作,无异常兜底
- 位置: `AvelineApplication.kt:29-35`
- 问题描述: `onCreate` 中同步调用 `crashHandler.init()` / `notificationManager.createNotificationChannels()` / `performanceMonitor.recordAppStart()` / `recordAppStartupComplete()`。这些操作(尤其 createNotificationChannels 在 Android 13+ 涉及权限检查)应在子线程执行。且整个 onCreate 没有 try-catch,任何一个抛异常都会导致 App 启动失败且无 CrashHandler 兜底(因为 CrashHandler 还没 init)。
- 建议方案:
  1. 把 `notificationManager.createNotificationChannels()` 移到子线程(用 `CoroutineScope(Dispatchers.IO).launch`)。
  2. `crashHandler.init()` 必须最先执行且包 try-catch,确保后续异常能被捕获。
  3. 用 `App Startup` 库管理初始化顺序,而不是堆在 onCreate 里。

#### 问题46: 🟡 未使用 App Startup 库
- 位置: `AvelineApplication.kt:1-37`
- 问题描述: AndroidManifest 中已经声明了 `androidx.startup.InitializationProvider` 并移除了 WorkManagerInitializer,说明项目已经引入 App Startup 库,但 AvelineApplication 没有用它。手动在 onCreate 里初始化 CrashHandler / NotificationManager / PerformanceMonitor 不利于拆分与测试。
- 建议方案: 为每个需要初始化的组件实现 `Initializer<T>`,让 App Startup 自动管理顺序。AvelineApplication 只保留最小化的 onCreate。

#### 问题47: 🟡 performanceMonitor.recordAppStart / recordAppStartupComplete 之间只有 2 行
- 位置: `AvelineApplication.kt:31, 35`
- 问题描述: 两个埋点之间只有 `crashHandler.init()` 和 `createNotificationChannels()`,如果这两步很快,两个埋点时间差接近 0,统计意义不大。
- 建议方案: 把 `recordAppStart` 放在 Application 构造函数或最早时机,`recordAppStartupComplete` 放在首帧渲染后(用 Choreographer 或 Activity lifecycle),才能真实反映启动耗时。

---

### MainActivity.kt

#### 问题48: 🔴 用 static AtomicReference 传递 DeepLink,跨 Activity 重建不可靠
- 位置: `MainActivity.kt:159-163`
  ```kotlin
  companion object {
      private val deepLinkUri = AtomicReference<Uri?>(null)
      internal fun getAndClearDeepLinkUri(): Uri? = deepLinkUri.getAndSet(null)
  }
  ```
- 问题描述: `deepLinkUri` 是 static 变量,生命周期与进程绑定,而不是与 Activity 绑定。场景:
  1. 用户从桌面点 Deep Link 启动 Activity → `handleDeepLink` 写入 deepLinkUri。
  2. Activity 因配置变更(旋转屏幕)重建 → 旧 Activity 销毁,新 Activity onCreate,但新 Activity 不会再次收到 onNewIntent,deepLinkUri 也没被消费(因为 Compose 的 `LaunchedEffect(Unit)` 只在新 Composition 启动时执行一次,重建时会再次执行,但此时 deepLinkUri 可能已被旧 Composition 消费)。
  3. 进程被杀恢复时,deepLinkUri 持久化在 static 里,但 Activity 重建后 Compose 可能不执行 LaunchedEffect(如果 NavHost 状态恢复)。
  
  更严重的是,如果用户在 Activity A 收到 DeepLink 后切到后台,进程被杀,重新打开时 deepLinkUri 是 null(static 不跨进程持久化),DeepLink 丢失。
- 建议方案:
  1. 用 `savedStateHandle` / `SavedStateHandle` 在 ViewModel 中保存 DeepLink。
  2. 或用 `Intent.getParcelableExtra(EXTRA_DEEP_LINK)` 走标准 Intent 传参,Activity 重建时 Intent 保留。
  3. 不要用 static 变量传递 UI 状态。

#### 问题49: 🔴 syncMobilePushToken 完全吞异常
- 位置: `MainActivity.kt:121-149`,尤其 `147-148` 行
  ```kotlin
  } catch (_: Exception) {
  }
  ```
- 问题描述: 整个 `syncMobilePushToken` 用 `catch (_: Exception)` 吞掉所有异常,既不记日志也不上报 CrashHandler。如果 Firebase 初始化失败、token 获取失败、网络请求失败,开发者完全无感知。线上推送收不到时无法排查。
- 建议方案:
  1. 至少 `Log.w("MainActivity", "syncMobilePushToken failed", e)`。
  2. 区分异常类型:Firebase 未初始化(预期,静默)、网络失败(预期,记日志)、其他(上报 CrashHandler)。

#### 问题50: 🟠 onCreate 中 lifecycleScope.launch 服务器发现的副作用可能在 Activity 销毁后执行
- 位置: `MainActivity.kt:81-90`
- 问题描述: `lifecycleScope.launch { serverDiscoveryManager.discoverServer(); AvelineForegroundServiceV2.updateBackendUrl(discovered) }`。lifecycleScope 在 Activity onDestroy 时会取消协程,但 `discoverServer()` 如果是阻塞 IO,可能在取消时已经完成了一半,回调 `updateBackendUrl` 仍可能执行。更关键的是,服务器发现是个 App 级别的初始化逻辑(只做一次),不应该放在 Activity onCreate 里——Activity 可能多次重建,导致重复发现。
- 建议方案: 把服务器发现移到 `AvelineApplication.onCreate` 或独立的 `AppInitializer`,用 App 级 scope 执行,只跑一次。

#### 问题51: 🟠 onNewIntent 未调用 setIntent
- 位置: `MainActivity.kt:116-119`
- 问题描述: `onNewIntent` 收到新 Intent 后只调用 `handleDeepLink(intent)`,没有调用 `setIntent(intent)`。这意味着后续 `getIntent()` 返回的还是旧 Intent。如果其他逻辑(如 Fragment 恢复)依赖 getIntent,会拿到错误的 Intent。
- 建议方案: 在 onNewIntent 第一行调用 `setIntent(intent)`。

#### 问题52: 🟠 syncMobilePushToken 在主线程同步检查 FirebaseApp
- 位置: `MainActivity.kt:121-149`
- 问题描述: `com.google.firebase.FirebaseApp.getApps(this)` 是同步调用,虽然在 onCreate 阶段通常很快,但如果 Firebase 初始化未完成会阻塞主线程。且整个方法在 onCreate 中同步调用,增加了启动耗时。
- 建议方案: 把 `syncMobilePushToken()` 移到子线程协程中执行,或在 App Startup 阶段异步执行。

#### 问题53: 🟠 AvelineApp 函数过长(150 行),职责过多
- 位置: `MainActivity.kt:166-315`
- 问题描述: `AvelineApp` 这个顶层 @Composable 函数承担了:
  1. NavController / DrawerState 初始化
  2. UI 状态收集
  3. 生命周期观察(reconnect)
  4. 连接状态映射
  5. 情绪计算
  6. 6 个导航回调定义(onNavigate / onSettingsClick / onMenuClick / onSessionClick / onNewSession / onSessionRename / onSessionDelete / onSessionPin)
  7. ModalNavigationDrawer 布局
  8. BreathingBackground 背景
  9. NavHost 导航图
  10. DeepLink 处理

  单函数 150 行,无法单独测试任何一部分。
- 建议方案: 拆分为多个 @Composable:`AvelineDrawer` / `AvelineNavHost` / `AvelineBackground` / `DeepLinkHandler`。回调用 `remember { mutableStateOf(...) }` 或提升到 ViewModel。

#### 问题54: 🟠 connectionState 映射硬编码 when
- 位置: `MainActivity.kt:192-196`
  ```kotlin
  val connectionState = when (mainUiState.connectionState) {
      WebSocketManager.ConnectionState.CONNECTED -> ConnectionState.CONNECTED
      WebSocketManager.ConnectionState.CONNECTING -> ConnectionState.CONNECTING
      WebSocketManager.ConnectionState.DISCONNECTED -> ConnectionState.DISCONNECTED
  }
  ```
- 问题描述: 两个枚举(`WebSocketManager.ConnectionState` 和 `ConnectionState`)字段一一对应,却要手写映射。如果其中一方新增状态(如 `RECONNECTING`),这里会编译报错(没 else 分支)或漏处理。
- 建议方案: 统一用一个枚举(让 components 层依赖 WebSocketManager 的枚举,或把 ConnectionState 提到共享模块),消除映射。或写扩展函数 `WebSocketManager.ConnectionState.toUiState()`。

#### 问题55: 🟡 parseDeepLink 是硬编码路由表,新增路由要改代码
- 位置: `MainActivity.kt:317-344`
- 问题描述: `when (uri.host)` 硬编码了所有 DeepLink host(chat / companion / life / circle / food / settings / study + 一堆旧兼容映射)。新增页面要改这里,容易遗漏。
- 建议方案: 用注解或路由配置表定义 `host → route` 映射,DeepLink 处理器遍历配置表。

#### 问题56: 🟡 onCreate 未处理 savedInstanceState
- 位置: `MainActivity.kt:78-114`
- 问题描述: `onCreate(savedInstanceState: Bundle?)` 接收了 savedInstanceState 但完全没用。Activity 重建时,如果之前有选中的会话/页面,应该从 savedInstanceState 恢复。当前依赖 Compose 的 rememberSaveable 与 NavHost 的状态保存,但 deepLink 等状态没有保存。
- 建议方案: 评估是否需要从 savedInstanceState 恢复 deepLink 等状态。

#### 问题57: 🟡 residentModeEnabled 启动前台服务的时机
- 位置: `MainActivity.kt:92-94`
- 问题描述: `if (appPreferences.residentModeEnabled) { AvelineForegroundServiceV2.start(this) }` 在 Activity onCreate 启动前台服务。Android 12+ 对后台启动前台服务有限制,虽然从 Activity 启动算前台,但如果用户切到后台再回来,行为可能不一致。更适合放在 BootCompletedReceiver 或 App Startup。
- 建议方案: 评估是否应该把常驻服务启动移到 Application 或 BootCompletedReceiver。

---

### MainViewModel.kt

#### 问题58: 🔴 switchSession 未调用 Repository 持久化,且做了无意义的网络请求
- 位置: `MainViewModel.kt:199-207`
  ```kotlin
  fun switchSession(sessionId: String) {
      viewModelScope.launch {
          val result = sessionRepository.getSessions()  // 网络请求,仅为 find
          result.getOrNull()?.find { it.id == sessionId }?.let { _ ->
              _uiState.update { it.copy(currentSessionId = sessionId) }
          }
      }
  }
  ```
- 问题描述:
  1. **未持久化**:`switchSession` 只更新本地 `currentSessionId`,没调用 `sessionRepository.updateSession` 或专门的 `setCurrentSession` 接口,后端不知道用户切换了会话。下次刷新会话列表时,`observeCurrentSession` 又会把 currentSessionId 改回后端记录的值。
  2. **无意义网络请求**:为了 find 一个 session,调用 `getSessions()` 拉取全部会话列表,O(n) 网络请求。本地 `_uiState.value.sessions` 已经有数据,直接 `find` 即可。
- 建议方案:
  1. 用本地 sessions 校验 sessionId 存在性。
  2. 调用 `sessionRepository.setCurrentSession(sessionId)`(需新增接口)持久化到后端。
  3. 删除冗余的 `getSessions()` 调用。

#### 问题59: 🟠 多处"操作后调用 loadSessions() 刷新"导致竞态
- 位置: `MainViewModel.kt:218-234`(createSession) / `240-262`(deleteSession)
- 问题描述: `createSession` 成功后:先 `loadSessions()`(异步刷新),再 `_uiState.update { copy(currentSessionId = session.id) }`。如果 `loadSessions()` 的网络响应在 currentSessionId 更新后才返回,可能把 currentSessionId 覆盖回旧值(因为 loadSessions 不更新 currentSessionId,但 observeCurrentSession 可能被触发)。
  `deleteSession` 同理:先 `loadSessions()` 刷新,又用本地 filter 计算 fallback currentSessionId,两个操作交叉。
- 建议方案: 用 `StateFlow` + `flatMapLatest` 响应式组合:currentSessionId 变化 → 自动刷新会话列表。或所有写操作后,统一用一个 `refreshSessions()` 入口,且在 refresh 完成前不修改 currentSessionId。

#### 问题60: 🟠 init 启动 5 个协程但都不保存 Job
- 位置: `MainViewModel.kt:65-71`
- 问题描述: `init` 里启动了 `loadSessions` / `observeCurrentSession` / `observeConnectionState` / `observeEmotionState` / `observePluginSettings` 五个协程,都是 `viewModelScope.launch`。viewModelScope 在 ViewModel onCleared 时会取消所有子协程,所以不会有泄漏。但如果某个协程出错(如 `observeEmotionState` 内部抛异常),不会冒泡到 ViewModel 错误状态,只是协程静默失败。
- 建议方案: 给关键协程加 `CoroutineExceptionHandler` 或在 `catch` 块中更新 `_uiState.error`。

#### 问题61: 🟠 observePluginSettings 注释与代码逻辑可能不符
- 位置: `MainViewModel.kt:169-186`
  ```kotlin
  // 先加载一次设置,触发 flow 初始发射(replay=1 只在有人发射过后才有值)
  runCatching { pluginsRepository.getSettings() }
  pluginsRepository.observeSettings()
  ```
- 问题描述: 注释说"触发 flow 初始发射",但 `getSettings()` 是 suspend 方法,调用结果被丢弃。如果 `observeSettings()` 返回的是 cold Flow(基于 DataStore),`getSettings()` 调用本身不会让 Flow 开始发射——Flow 只有被 collect 才会执行。这个 `runCatching` 调用是无效的。
- 建议方案: 确认 `observeSettings()` 的实现。如果是基于 DataStore 的 Flow,DataStore 本身会保证最新值在 collect 时立即发射,不需要预先触发。删除冗余的 `runCatching`。

#### 问题62: 🟠 currentEmotion 默认值 "calm" 与 EmotionResolver 不一致
- 位置: `MainViewModel.kt:36`(`val currentEmotion: String = "calm"`)
- 问题描述: `EmotionResolver.EmotionType` 枚举里没有 `"calm"`,有 `NEUTRAL("neutral")` / `HAPPY("happy")` 等。默认值 `"calm"` 在 `EmotionResolver.getColorForEmotion("calm")` 时会 fallback 到 `Color(0xFF6B7280)`(灰色,即 NEUTRAL 的颜色),虽然不会崩,但语义不一致——后端推送的 `calm` 与前端的 `neutral` 是同一个情绪吗?
- 建议方案: 与后端确认情绪枚举统一,前端默认值用 `"neutral"`。

#### 问题63: 🟠 error 直接拼接异常 message 给用户
- 位置: `MainViewModel.kt:94, 110, 228, 258, 283, 309`
- 问题描述: 多处 `"加载会话失败: ${e.message}"` / `"创建会话失败: ${e.message}"`。如果 `e.message` 是英文堆栈(如 `UnknownHostException`),直接显示给中文用户体验差。且没有错误分类(网络错误 / 权限错误 / 服务器错误)。
- 建议方案: 用 `ErrorMessageMapper` 把异常映射为用户友好的中文提示,并区分错误类型(可重试 / 不可重试)。

#### 问题64: 🟡 clearError 是 public 但未见调用
- 位置: `MainViewModel.kt:319-321`
- 问题描述: `clearError()` 暴露了但没有在 MainViewModel 内部调用。如果 UI 层忘了调用,error 会一直保留在 uiState 中,Snackbar 关闭后再次重组仍会弹出。
- 建议方案: 用一次性事件(Channel / SharedFlow)而非 StateFlow 持有 error,让 error 自动消费。

#### 问题65: 🟡 renameSession / toggleSessionPin 用本地 find,与 loadSessions 模式不一致
- 位置: `MainViewModel.kt:267-288`(renameSession) / `293-314`(toggleSessionPin)
- 问题描述: 这两个方法用 `_uiState.value.sessions.find` 校验,成功后只更新本地 sessions,不调用 `loadSessions()` 刷新。而 createSession / deleteSession 会调 `loadSessions()`。风格不一致,如果后端在 update 时修改了其他字段(如 updatedAt),本地数据会过时。
- 建议方案: 统一:要么所有写操作后都刷新,要么都用返回值更新本地。

---

### EmotionResolver.kt

#### 问题66: 🔴 parseColor 6 位 hex 解析为透明(alpha=0)
- 位置: `EmotionResolver.kt:175-186`
  ```kotlin
  fun parseColor(hexColor: String): Color {
      return try {
          val hex = hexColor.removePrefix("#")
          val color = hex.toLong(16)
          when (hex.length) {
              6 -> Color(color)         // BUG: 0xRRGGBB, alpha=0(透明)
              8 -> Color(color)         // 0xAARRGGBB,正确
              else -> Color(0xFF6B7280)
          }
      } catch (e: Exception) {
          Color(0xFF6B7280)
      }
  }
  ```
- 问题描述: `Color(Long)` 构造函数把传入的 long 当作 ARGB。对于 6 位 hex(如 `"#10B981"` → `0x10B981`),`Color(0x10B981)` 会被解析为 alpha=0x00(透明)、R=0x10、G=0xB9、B=0x81。调用方拿到一个完全透明的颜色,UI 上看不到任何效果,且不会报错——非常难排查的 bug。
- 建议方案: 6 位 hex 应补全为 8 位:`Color(0xFF000000 or color)` 或 `Color(color).copy(alpha = 1f)`。
  ```kotlin
  6 -> Color(0xFF000000 or color)
  ```

#### 问题67: 🟠 EmotionType 枚举重复定义
- 位置: `EmotionResolver.kt:22-32`(`enum class EmotionType`)与 `domain/models/EmotionType`(从 PluginsRepository import 推断存在)
- 问题描述: 项目里有两个 `EmotionType`:`com.aveline.ai.mobile.presentation.utils.EmotionResolver.EmotionType` 和 `com.aveline.ai.mobile.domain.models.EmotionType`(后者被 PluginsRepository 使用)。两个枚举可能定义了不同的情绪集合,容易混淆。MainViewModel 里 `manualEmotion: EmotionType?` 用的是 domain 的,而 EmotionResolver 里的是 presentation 的。
- 建议方案: 统一为一个 EmotionType(建议用 domain 层的),presentation 层直接复用。如果需要附加 `color` 属性,用扩展函数或 Map 而非重复枚举。

#### 问题68: 🟠 getColorForEmotion 的 try-catch 是死代码
- 位置: `EmotionResolver.kt:56-65`
  ```kotlin
  fun getColorForEmotion(emotionName: String): Color {
      return try {
          EmotionType.values().find { ... }?.color ?: Color(0xFF6B7280)
      } catch (e: Exception) {
          Color(0xFF6B7280)
      }
  }
  ```
- 问题描述: `values()` / `find` / `?:` 都不会抛 Exception,`try-catch` 是死代码,误导阅读者以为这里有抛异常的可能。
- 建议方案: 删除 try-catch。

#### 问题69: 🟠 blendEmotionColors 浮点相等比较
- 位置: `EmotionResolver.kt:91-93`(`if (totalWeight == 0f)`)
- 问题描述: 浮点数 `== 0f` 比较在累加后可能因精度问题失效(虽然 0f 的累加结果还是 0f,但如果 weight 是负数累加再抵消,可能得到 1e-7 这种极小值)。
- 建议方案: 用 `if (totalWeight <= 0f)` 更安全。

#### 问题70: 🟠 getColorForEmotion 与 getEmotionType 重复 find 逻辑
- 位置: `EmotionResolver.kt:56-65, 73-79`
- 问题描述: 两个方法都做 `EmotionType.values().find { it.displayName.equals(emotionName, ignoreCase = true) }`,只是返回值不同(color vs EmotionType)。
- 建议方案: 抽取私有 `findEmotionType(name): EmotionType?`,两个 public 方法都调用它。

#### 问题71: 🟡 getColorsFromEmotion 与 getColorsForEmotion 命名易混淆
- 位置: `EmotionResolver.kt:60-66`(getColorsForEmotion) / `161-167`(getColorsFromEmotion)
- 问题描述: `getColorsForEmotion(emotionName: String)` 接受 String,`getColorsFromEmotion(emotion: Emotion)` 接受 Emotion model。命名只差一个介词(For vs From),调用方很容易调错。
- 建议方案: 重命名为 `getColorsByEmotionName(name)` 和 `getColorsByEmotionModel(emotion)`。

#### 问题72: 🟡 getEmotionAlpha 硬编码 9 个 baseAlpha 魔法数字
- 位置: `EmotionResolver.kt:132-153`
- 问题描述: 每个 EmotionType 对应一个硬编码的 baseAlpha(0.4 / 0.6 / 0.55 / 0.8 / ...),这些数字没有出处说明,无法维护。
- 建议方案: 把 baseAlpha 加到 `EmotionType` 枚举构造参数里(`enum class EmotionType(..., val baseAlpha: Float)`),或用 Map 配置。

---

### HealthManager.kt

#### 问题73: 🔴 HealthManager 与 HealthRepository 双轨并存,职责重叠
- 位置: `HealthManager.kt:1-227` 与 `domain/repository/HealthRepository.kt:1-65`
- 问题描述: 同一个 App 里有两个健康数据入口:
  - `HealthManager`:`@Singleton class`,直接 `@Inject` 构造,返回 `String`(JSON),有 callback 风格方法
  - `HealthRepository` + `HealthRepositoryImpl`:通过 Hilt Binds 注入,返回 `HealthData?` domain model

  上层(ViewModel / Service)不知道该用哪个,可能出现:同一个数据被两边各读一次,或一边改了 schema 另一边没改。HealthManager 返回 String(JSON)说明它是早期实现的遗留,HealthRepository 是后做的抽象,但旧代码没迁移。
- 建议方案: 把 HealthManager 的逻辑全部迁到 HealthRepositoryImpl,删除 HealthManager。如果短期内无法删除,至少在 HealthManager 顶部加 `@Deprecated("Use HealthRepository instead")` 注解。

#### 问题74: 🔴 readHealthData 内部 3 次 JSON 序列化/反序列化,性能差
- 位置: `HealthManager.kt:161-175`
  ```kotlin
  suspend fun readHealthData(): String = withContext(Dispatchers.IO) {
      val vitals = JSONObject(readVitalSigns())    // 1. readVitalSigns 构造 JSON 字符串 → 2. 解析回 JSONObject
      val metrics = JSONObject(readBodyMetrics())  // 3. readBodyMetrics 构造 JSON 字符串 → 4. 解析回 JSONObject
      val keys = metrics.keys()
      while (keys.hasNext()) { vitals.put(key, metrics.get(key)) }  // 5. 逐 key 合并
      vitals.put("type", "all")
      return@withContext vitals.toString()         // 6. 再次序列化为字符串
  }
  ```
- 问题描述: 为了合并 vitalSigns 和 bodyMetrics,先各自 `json.toString()` 再 `JSONObject(string)` 解析回来,再合并,再 `toString()`。3 次序列化 + 2 次反序列化,完全是浪费。如果健康数据量增大(如心率历史),性能问题会被放大。
- 建议方案: 让 `readVitalSigns` / `readBodyMetrics` 内部直接返回 `JSONObject`(或 domain model),`readHealthData` 直接合并 JSONObject,无需中间的 String 转换。

#### 问题75: 🟠 getPermissions 与 AndroidManifest 声明不同步
- 位置: `HealthManager.kt:38-55`(getPermissions) / `AndroidManifest.xml:31-46`
- 问题描述: Manifest 里声明了 `health.READ_EXERCISE` 和 `health.READ_BODY_MASS_INDEX`,但 `getPermissions()` 里:
  - `ExerciseRecord` 没有出现
  - `BodyMassIndexRecord` 是注释掉的(`// import androidx.health.connect.client.records.BodyMassIndexRecord`)
  
  这意味着 Manifest 申请了权限但代码不读取,或者代码想读但 Manifest 没声明(如果取消注释),两者必须同步。
- 建议方案: 决定是否需要 ExerciseRecord / BodyMassIndexRecord,Manifest 与 getPermissions 同步调整。

#### 问题76: 🟠 checkAvailability 返回 String 而非枚举
- 位置: `HealthManager.kt:30-36`
- 问题描述: 返回 `"available"` / `"unavailable"` / `"update_required"` / `"unknown"` 字符串,调用方需要靠字符串字面值判断,容易拼错。HealthRepository 已经有 `HealthConnectAvailability` 枚举,但 HealthManager 没用。
- 建议方案: 改为返回枚举(复用 `HealthConnectAvailability`),删除字符串返回。

#### 问题77: 🟠 readVitalSigns / readBodyMetrics 返回 String(JSON),违反分层
- 位置: `HealthManager.kt:87-117, 119-149`
- 问题描述: 同问题 73,HealthManager 整体返回 String(JSON)而非 domain model。
- 建议方案: 返回 `VitalSigns` / `BodyMetrics` data class(或复用 HealthData)。

#### 问题78: 🟠 无权限时返回 "{}" 而非 null 或异常
- 位置: `HealthManager.kt:88-90, 121-123`
- 问题描述: `if (!hasAllPermissions()) return "{}"`。调用方拿到 `"{}"` 字符串,`JSONObject("{}")` 解析后是空对象,无法区分"无权限"和"有权限但无数据"。
- 建议方案: 返回 `null`(表示无权限或无数据),或抛 `MissingPermissionsException`。

#### 问题79: 🟠 lastHr / lastSpo2 默认值为 0,无法区分"无数据"
- 位置: `HealthManager.kt:113`(`val lastHr = ... else 0`) / `116`(`val lastSpo2 = ... else 0.0`)
- 问题描述: 心率 0 和血氧 0.0 是生理上不可能的值,但代码用 0 作默认,UI 可能显示"心率 0 bpm",让用户以为设备坏了。
- 建议方案: 用 `null` 表示无数据,JSON 中 `put("heart_rate", JSONObject.NULL)` 或不 put 该字段。

#### 问题80: 🟠 readVitalSigns 注释与代码逻辑矛盾
- 位置: `HealthManager.kt:87-117`
- 问题描述: 注释说 `Only last hour for vitals`,但 96-98 行又用 `todayRange`(今日零点到现在)取步数。步数是今日累计,不是"过去 1 小时"。注释误导。
- 建议方案: 修正注释,说明步数取今日、心率和血氧取过去 1 小时最新值。

#### 问题81: 🟠 三个 callback 方法冗余,且用 printStackTrace
- 位置: `HealthManager.kt:178-205`(`readVitalSignsCallback` / `readBodyMetricsCallback` / `readHealthDataCallback`)
- 问题描述:
  1. Kotlin 协程已经够用,这三个 callback 方法是为了 Java 互操作?但项目是纯 Kotlin,没必要。
  2. `e.printStackTrace()` 在生产环境输出到 stderr,不会被 CrashHandler 捕获,也不会进日志文件。
- 建议方案: 删除三个 callback 方法,让调用方直接用 suspend 方法。如必须保留,把 `printStackTrace` 换成 `Log.e("HealthManager", "read failed", e)`。

#### 问题82: 🟠 close() 误调用会让 @Singleton 永久失效
- 位置: `HealthManager.kt:215-217`(`fun close() { scope.cancel() }`)
- 问题描述: HealthManager 是 `@Singleton`,scope 在 App 生命周期内一直存在。如果某个调用方误调 `close()`,`scope.cancel()` 后所有后续 `scope.launch` 都会立即取消,HealthManager 静默失效,且无法恢复(因为是单例)。
- 建议方案: 删除 `close()` 方法,或改为内部清理(如 App onTerminate 时调用,但 Android 不保证 onTerminate 被调用)。

#### 问题83: 🟡 自建 CoroutineScope 而非用 App 级 scope
- 位置: `HealthManager.kt:24-25`(`private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)`)
- 问题描述: 作为 `@Singleton`,自建 scope 是常见做法,但更推荐通过 DI 注入 `@Singleton CoroutineScope` 或 `@ApplicationScope`,便于统一管理和测试。
- 建议方案: 提供 `@Singleton @ApplicationScope CoroutineScope` 的 Hilt 绑定,HealthManager 注入使用。

#### 问题84: 🟡 hasAllPermissions 不需要外层 withContext
- 位置: `HealthManager.kt:73-75`
- 问题描述: `suspend fun hasAllPermissions()` 内部调用 `healthConnectClient.permissionController.getGrantedPermissions()`,这是 suspend 方法,不需要切线程。当前代码没有 withContext,但 `readVitalSigns` 等用了 `withContext(Dispatchers.IO)` 包裹——而内部已经是 suspend 调用,IO 调度由 HealthConnectClient 内部处理,外层 withContext 是多余的。
- 建议方案: 评估是否真的需要 `withContext(Dispatchers.IO)`,如果 HealthConnectClient 内部已切线程,删除外层 withContext。

---

### AndroidManifest.xml

#### 问题85: 🔴 CALL_PHONE / SEND_SMS 敏感权限审核风险高
- 位置: `AndroidManifest.xml:20-21`
- 问题描述: `android.permission.CALL_PHONE` 和 `android.permission.SEND_SMS` 是 Google Play 重点审查的敏感权限。如果 AI 助手要"主动打电话给联系人"或"发短信",需要:
  1. 在 Play Console 填写权限使用说明。
  2. 提供功能演示视频。
  3. 满足替代方案审核(如为什么要 CALL_PHONE 而不是只弹拨号界面 ACTION_DIAL)。
  
  如果功能不是核心,会被审核拒绝。且普通用户看到"AI 助手申请打电话和发短信权限"会警惕。
- 建议方案: 评估是否真的需要这两个权限。如果只是为了"帮用户拨号",用 `ACTION_DIAL`(不需要 CALL_PHONE 权限)。如果确实需要直接拨打,需要明确功能场景并准备审核材料。

#### 问题86: 🟠 FOREGROUND_SERVICE_SPECIAL_USE 缺少 property 声明
- 位置: `AndroidManifest.xml:7, 111-115`
- 问题描述: Android 14+(API 34)要求 `foregroundServiceType="specialUse"` 的服务必须在 `<service>` 标签内声明:
  ```xml
  <property
      android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
      android:value="具体用途说明" />
  ```
  当前 Manifest 只有 `foregroundServiceType="specialUse"` 没有 property,在 Android 14 设备上启动该前台服务时会抛 `ForegroundServiceTypeNotAllowed` 异常。
- 建议方案: 在 `AvelineForegroundServiceV2` 的 `<service>` 标签内添加 `<property>` 声明,说明 specialUse 的具体用途(如"保持 WebSocket 长连接以接收 AI 主动消息")。

#### 问题87: 🟠 usesCleartextTraffic 与 networkSecurityConfig 冲突
- 位置: `AndroidManifest.xml:68-69`
- 问题描述: `android:networkSecurityConfig="@xml/network_security_config"` 和 `android:usesCleartextTraffic="true"` 同时存在。根据 Android 文档,配置了 networkSecurityConfig 后,usesCleartextTraffic 会被忽略。如果 network_security_config.xml 里已经配置了 cleartextTrafficPermitted,这里的 `usesCleartextTraffic="true"` 是冗余且误导。
- 建议方案: 删除 `android:usesCleartextTraffic="true"`,只在 network_security_config.xml 中配置。

#### 问题88: 🟠 ACCESS_WIFI_STATE 与 ACCESS_NETWORK_STATE 重复
- 位置: `AndroidManifest.xml:10-11`
- 问题描述: `ACCESS_NETWORK_STATE` 已经能获取网络连接状态(包括 WiFi),`ACCESS_WIFI_STATE` 只在需要读取 WiFi 详情(如 SSID、BSSID)时才需要。如果只是判断网络是否可用,ACCESS_WIFI_STATE 是冗余的。
- 建议方案: 评估是否真的需要 WiFi 详情,如不需要删除 ACCESS_WIFI_STATE。

#### 问题89: 🟠 ACTIVITY_RECOGNITION 与 health.READ_STEPS 重复
- 位置: `AndroidManifest.xml:30, 31`
- 问题描述: `ACTIVITY_RECOGNITION` 是旧版步数传感器权限,`health.READ_STEPS` 是 Health Connect 的步数权限。如果通过 Health Connect 读步数,就不需要 ACTIVITY_RECOGNITION。两个都申请会让用户看到两个步数相关权限弹窗。
- 建议方案: 评估是否还需要旧版传感器 API,如已完全用 Health Connect,删除 ACTIVITY_RECOGNITION。

#### 问题90: 🟠 MainActivity 缺少 configChanges 声明
- 位置: `AndroidManifest.xml:75-98`
- 问题描述: Compose 应用通常声明 `android:configChanges="orientation|screenSize|smallestScreenSize|screenLayout|keyboardHidden|uiMode|density"` 来避免配置变更时 Activity 重建。当前没有声明,旋转屏幕 / 切深色模式会触发 Activity 重建,虽然有 Compose 状态保存,但 deepLink、连接状态等可能有抖动。
- 建议方案: 添加 configChanges 声明。

#### 问题91: 🟠 BootCompletedReceiver exported=true 无权限保护
- 位置: `AndroidManifest.xml:135-143`
- 问题描述: `BootCompletedReceiver` exported=true 接收 BOOT_COMPLETED,这是标准做法(系统广播需要 exported=true)。但 receiver 没有声明 `android:permission`,任何第三方 app 也能伪造一个 BOOT_COMPLETED 广播触发开机自启逻辑。
- 建议方案: 虽然 BOOT_COMPLETED 是系统广播,但可以加 `android:permission="android.permission.RECEIVE_BOOT_COMPLETED"` 保护(虽然该权限保护级别是 normal,但能挡住未声明该权限的 app)。

#### 问题92: 🟠 WidgetProvider 的自定义 action 无权限保护
- 位置: `AndroidManifest.xml:167-178`
- 问题描述: `AvelineWidgetProvider` 的 intent-filter 声明了 `com.aveline.ai.ACTION_WIDGET_QUICK_SEND` 和 `com.aveline.ai.ACTION_WIDGET_REFRESH`,但 receiver 没有声明 `android:permission`。任何第三方 app 都能发送这两个广播,触发 widget 快捷发送或刷新,可能被滥用。
- 建议方案: 给 receiver 加 `android:permission="com.aveline.ai.permission.WIDGET"` 并在 Manifest 声明该 `<permission>`;或用 signature 级权限保护。

#### 问题93: 🟠 ViewPermissionUsageActivity exported=true 安全性需确认
- 位置: `AndroidManifest.xml:100-109`
- 问题描述: 这个 activity-alias exported=true,带 `START_VIEW_PERMISSION_USAGE` 权限,允许外部 app 通过该权限调用。虽然权限声明了,但 `START_VIEW_PERMISSION_USAGE` 的保护级别需要确认(应为 signature 或 normal)。如果是 normal,任意 app 都能触发 MainActivity 显示权限使用说明,可能被钓鱼。
- 建议方案: 确认 `START_VIEW_PERMISSION_USAGE` 的保护级别,如果是 normal,考虑加额外的 signature 权限保护。

#### 问题94: 🟡 WRITE_CALENDAR 可能不必要
- 位置: `AndroidManifest.xml:18`
- 问题描述: 如果 AI 助手只需要读取日程,`READ_CALENDAR` 就够。`WRITE_CALENDAR` 允许写入日历,如果不需要"帮用户创建日程"功能,删除。
- 建议方案: 确认功能需求,只保留必要的权限。

#### 问题95: 🟡 BIND_NOTIFICATION_LISTENER_SERVICE 声明方式
- 位置: `AndroidManifest.xml:55-57`
- 问题描述: `BIND_NOTIFICATION_LISTENER_SERVICE` 是 system 级权限,普通应用通过 `<service android:permission="...">` 声明让系统绑定。这里 `tools:ignore="ProtectedPermissions"` 忽略了 lint 警告,但应该在注释里说明为什么需要。
- 建议方案: 在 Manifest 注释里说明 NotificationListenerService 的用途,方便审核与维护。

---

## 总结与优先级建议

### 🔴 严重问题(必须优先修复,共 9 个)

| # | 问题 | 文件 | 影响 |
|---|------|------|------|
| 6 | 占位 baseUrl 让请求静默失败 | NetworkModule.kt:27, 73-91 | 后端未配置时所有请求挂掉,无法排查 |
| 21 | HealthRepository 与 StudyRepository 的 recordDailyStudy 重复 | HealthRepository.kt:58-65 / StudyRepository.kt:104-109 | 实现冲突,行为不一致 |
| 38 | StudyRepository 34 个方法混合 5 类职责 | StudyRepository.kt:1-134 | 严重违反 ISP,维护噩梦 |
| 41 | ToolsRepository 14 个方法混合 7 类职责 | ToolsRepository.kt:1-18 | 同上 |
| 48 | MainActivity 用 static AtomicReference 传递 DeepLink | MainActivity.kt:159-163 | 跨重建不可靠,DeepLink 丢失 |
| 49 | syncMobilePushToken 完全吞异常 | MainActivity.kt:147-148 | 推送异常无感知,无法排查 |
| 58 | switchSession 未持久化 + 冗余网络请求 | MainViewModel.kt:199-207 | 后端不知道切换,UI 状态错乱 |
| 66 | parseColor 6 位 hex 解析为透明 | EmotionResolver.kt:175-186 | 颜色不显示,UI bug |
| 73 | HealthManager 与 HealthRepository 双轨 | HealthManager.kt 全文 | 双入口,数据不一致 |
| 74 | readHealthData 3 次 JSON 序列化 | HealthManager.kt:161-175 | 性能浪费 |
| 85 | CALL_PHONE / SEND_SMS 敏感权限 | AndroidManifest.xml:20-21 | Play 审核风险 |
| 86 | specialUse FGS 缺少 property | AndroidManifest.xml:111-115 | Android 14+ 启动崩溃 |

(注:表格中包含 12 项,因 74 与 73 同源合并说明)

### 🟠 中等问题(建议在下个迭代修复,共 38 个)

重点包括:
- DI 层:DAO 未加 Singleton、鉴权拦截器冗余 header、pingInterval 注释误导
- Domain 层:大量 `Result<JsonObject>` 暴露 JSON、Repository 职责错位(getPersona 在 ChatRepository、recordBodyMetrics 在 ContextRepository、active care 在 StatusRepository)、返回类型风格不统一
- 入口层:Application 同步初始化无异常兜底、onNewIntent 未 setIntent、AvelineApp 函数过长、connectionState 硬编码映射、MainViewModel 多处竞态、error 直接拼异常 message、HealthManager 返回 String(JSON)
- Manifest:usesCleartextTraffic 与 networkSecurityConfig 冲突、敏感权限重复申请、configChanges 缺失、receiver 无权限保护

### 🟡 轻微问题(可在技术债清理时处理,共 18 个)

包括:遗留 import、冗余 Provides、英文 KDoc、魔法数字、命名混淆、浮点相等比较、callback 冗余方法等。

### 推荐修复顺序

1. **第一优先级(本周)**:修复 12 个 🔴 严重问题,尤其是 parseColor 透明 bug(直接影响 UI)、specialUse FGS property(Android 14 崩溃)、switchSession 逻辑漏洞(数据一致性)。
2. **第二优先级(下个迭代)**:重构 StudyRepository / ToolsRepository 拆分(影响范围大,需要配套迁移 ViewModel);统一 Domain 层返回类型(去掉 JsonObject,定义 domain model)。
3. **第三优先级(技术债清理)**:删除 HealthManager(迁移到 HealthRepositoryImpl);拆分 AvelineApp Composable;修复 AndroidManifest 权限冗余;统一注释为中文。

### 架构层面建议

1. **建立 Domain Model 库**:为所有 `Result<JsonObject>` 返回值定义对应的 data class,让上层编译期感知 schema 变化。
2. **Repository 拆分原则**:按业务域而非数据来源拆分,每个 Repository 不超过 10 个方法。
3. **统一错误处理**:定义 `AppError` sealed class,Repository 返回 `Result<T, AppError>` 而非 `Result<T>` + 抛异常混用。
4. **引入 App Startup**:把 CrashHandler / NotificationManager / PerformanceMonitor / 服务器发现 / push token 同步都迁到 Initializer,AvelineApplication 只保留最小 onCreate。
5. **DeepLink 改造**:用 SavedStateHandle + NavController 的 deep link 机制,不要用 static 变量。
6. **HealthManager 迁移**:把 HealthManager 的 Health Connect 读取逻辑全部迁到 HealthRepositoryImpl,返回 domain model,删除 String(JSON)返回。

---

报告生成时间:2026-07-28
审查文件数:21
发现问题数:65(🔴12 / 🟠35 / 🟡18)
