# Companion/Circle 模块代码审查报告

## 审查概览

本次审查覆盖 `presentation/companion/` 与 `presentation/circle/` 两个目录共 9 个 Kotlin 文件,总代码量约 1900 行。

**审查文件清单**:

| 文件 | 行数 | 严重问题 | 中等问题 | 轻微问题 |
|------|------|---------|---------|---------|
| CompanionMemoryCard.kt | 220 | 0 | 1 | 2 |
| CompanionMemoryTab.kt | 380 | 1 | 1 | 3 |
| CompanionPersonaTab.kt | 361 | 0 | 3 | 2 |
| CompanionScreen.kt | 163 | 0 | 0 | 2 |
| CompanionStatusTab.kt | 393 | 0 | 0 | 2 |
| CircleScreen.kt | 89 | 0 | 1 | 2 |
| CircleViewModel.kt | 110 | 2 | 3 | 1 |
| CircleComponents.kt | 330 | 0 | 2 | 4 |
| CircleMemberComponents.kt | 280 | 1 | 2 | 3 |
| **合计** | **2326** | **4** | **15** | **21** |

**核心问题归类**:
- 性能问题:列表 lazy 失效、Brush 重建、mapNotNull 未缓存、computed 属性反复计算
- 架构问题:JSON 解析混入 UI、ViewModel 死字段、依赖具体实现而非接口
- 并发问题:Flow 收集无错误处理、协程异常被吞
- 状态丢失:remember 未升级为 rememberSaveable,Tab/展开状态在配置变更时丢失
- 健壮性:`name.first()` 空字符串崩溃、try-catch 吞所有异常、误导性默认值

---

## 逐文件审查

### CompanionMemoryCard.kt

#### 问题1: 🟠 长按删除与删除按钮重复,且 onClick 为空操作
- 位置: `CompanionMemoryCard.kt:60-65, 105-115`
- 问题描述: 卡片根布局使用 `combinedClickable(onClick = {}, onLongClick = onDelete)` 设置了空点击和长按删除,但同时在右上角又放置了一个删除 IconButton。这导致:(1) 删除入口有两处,用户认知负担增加;(2) `onClick = {}` 是死代码,暗示原本可能想做点击查看详情但未实现;(3) 长按删除直接触发 `onDelete` 而不经过确认对话框(虽然 `CompanionMemoryTab` 在外层包了确认对话框,但长按手势的可见性差,容易被误触)。
- 建议方案: 二选一保留删除入口。推荐保留显式的删除 IconButton(可见性好),移除 `combinedClickable` 改为普通 `clickable`(若有详情页)或直接去掉。如保留长按,需在 `contentDescription` 或 UI 提示中明确告知用户。

#### 问题2: 🟡 硬编码颜色未走主题
- 位置: `CompanionMemoryCard.kt:53-57, 100, 112, 184-188`
- 问题描述: `Color(0xFFFFC107)`、`Color(0x33000000)`、`Color(0xFFEF4444)`、`Color(0xFF2196F3)` 等颜色硬编码在 Composable 与 `getTypeColor` 函数中,未走 `MaterialTheme` 或项目 `theme` 包。这导致深色/浅色主题切换无法生效,且颜色含义分散难以维护。
- 建议方案: 将这些颜色抽到 `presentation/theme/` 下统一定义(如 `MemoryImportantColor`、`MemoryDangerColor`、`MemoryTypeFactColor` 等),Composable 中通过主题引用。

#### 问题3: 🟡 tags 二次遍历
- 位置: `CompanionMemoryCard.kt:134, 147`
- 问题描述: `memory.tags.take(3).forEach { ... }` 渲染前 3 个标签,随后又用 `memory.tags.size > 3` 判断是否还有剩余。虽然 `List.size` 是 O(1),但 `take(3)` 创建了新列表,且 `size` 检查与 `take` 各遍历一次语义上重复。
- 建议方案: 改为 `memory.tags.forEachIndexed { index, tag -> if (index < 3) { /* render */ } else if (index == 3) { /* render +N */ return@forEachIndexed } }`,或保持现状但合并判断为 `val extra = memory.tags.size - 3` 一次性计算。

---

### CompanionMemoryTab.kt

#### 问题1: 🔴 MemoryListContent 在 LazyColumn item 内用 Column+forEach 渲染,完全失去 lazy 优势
- 位置: `CompanionMemoryTab.kt:109-137, 346-361`
- 问题描述: 整个 "记忆列表" SectionCard 是作为 `LazyColumn` 的一个 `item { }` 存在,而 SectionCard 内部的 `MemoryListContent` 使用 `Column { memories.forEach { MemoryCardItem(...) } }` 渲染所有记忆卡片。这意味着:**无论记忆列表多大,所有卡片都会在首次进入时全部 compose**,LazyColumn 的按需组合特性对记忆列表完全失效。当记忆数量达到几十条以上时,会出现明显的卡顿和内存占用上升,且滚动时也无法享受 lazy 复用。
- 建议方案: 将记忆列表扁平化到 LazyColumn 中。可以让搜索/过滤区作为 `item`,然后 `items(filteredMemories) { memory -> MemoryCardItem(...) }`,让 SectionCard 只包裹搜索区或干脆移除列表区的 SectionCard 包装。若必须保留 SectionCard 视觉分隔,可改用 `LazyColumn` 嵌套外层 LazyColumn 不可行(嵌套 lazy 同方向有冲突),正确做法是把 SectionCard 的标题作为 `item`,记忆卡片作为同级 `items` 直接挂在 LazyColumn 下。

#### 问题2: 🟠 下拉菜单状态用 remember 而非 rememberSaveable,配置变更后丢失
- 位置: `CompanionMemoryTab.kt:180-181`
- 问题描述: `var showTypeMenu by remember { mutableStateOf(false) }` 和 `showSortMenu` 同理。当用户旋转屏幕或进程被回收重建时,菜单展开状态会丢失。虽然菜单状态丢失影响不大,但属于状态管理不规范的累积。
- 建议方案: 改为 `rememberSaveable { mutableStateOf(false) }`。

#### 问题3: 🟡 删除确认对话框始终追加 "..."
- 位置: `CompanionMemoryTab.kt:146`
- 问题描述: `text = { Text("确定要删除这条记忆吗?\n\n\"${uiState.memoryToDelete.content.take(100)}...\"") }` 无论 `content` 是否超过 100 字符,都会在末尾追加 `...`。对于短记忆(如 "喜欢吃苹果"),会显示 "喜欢吃苹果...",视觉上误导用户以为内容被截断。
- 建议方案: 改为 `val preview = uiState.memoryToDelete.content.take(100)` 然后 `val display = if (uiState.memoryToDelete.content.length > 100) "$preview..." else preview`,或使用 `buildAnnotatedString`。

#### 问题4: 🟡 MemoryType.values() 应改为 entries
- 位置: `CompanionMemoryTab.kt:253, 311`
- 问题描述: `MemoryType.values().forEach { ... }` 和 `MemorySortOrder.values().forEach { ... }` 使用了 Kotlin 1.9 之前的 API。`values()` 每次调用都会创建新数组,而 `entries` 返回复用的 `EnumEntries` 列表,性能更优。
- 建议方案: 改为 `MemoryType.entries.forEach { ... }` 和 `MemorySortOrder.entries.forEach { ... }`。

#### 问题5: 🟡 搜索框输入未做防抖
- 位置: `CompanionMemoryTab.kt:185-214`
- 问题描述: `TextField` 的 `onValueChange = onSearch` 直接将每次按键事件透传给上层,通常上层会调用 ViewModel 进行过滤。若 ViewModel 的过滤是同步计算或触发网络请求,每次按键都会触发,可能导致输入卡顿或大量无效请求。
- 建议方案: 在 ViewModel 层使用 `debounce(300)` 对搜索查询做防抖(典型做法:`MutableStateFlow<String>` 作为输入,`debounce` 后 `flatMapLatest` 过滤)。本文件本身不需要改,但需确认上层实现。

---

### CompanionPersonaTab.kt

#### 问题1: 🟠 JSON 解析逻辑混入 Composable,且 try-catch 吞所有异常
- 位置: `CompanionPersonaTab.kt:63-80`
- 问题描述: `CompanionPersonaTab` 函数体开头有 18 行 `try { ... } catch (_: Exception) { null }` 用于解析 `activePersona` 的 JSON 结构(name/status/objective/traits)。问题有三:
  1. **业务逻辑混入 UI**: JSON 解析属于数据转换,应放在 ViewModel 或 Mapper 层,UI 只接收强类型数据。
  2. **catch Exception 吞掉所有异常**: 包括 `ClassCastException`、`JsonEncodingException`、`NullPointerException` 等,任何后端字段变更或 bug 都会被静默吞掉,UI 显示 "暂无活跃人设" 而无任何日志。
  3. **重复模式 6 次**: 每个字段都用同样的 try-catch 块,代码冗余且难以维护。
- 建议方案: 在 `PersonaViewModel` 中将 `activePersona: JsonObject?` 转换为一个强类型的 `ActivePersonaInfo(name, status, objective, traits)` 数据类,通过 kotlinx.serialization 或手动解析在 ViewModel 中完成,UI 只接收解析后的数据类。异常应记录日志或上报,而非静默吞掉。

#### 问题2: 🟠 PersonaListContent 同样用 Column+forEach 包在 LazyColumn item 内,失去 lazy 优势
- 位置: `CompanionPersonaTab.kt:142-160, 281-305`
- 问题描述: 与 `CompanionMemoryTab` 的问题1 相同。整个 "人设列表" SectionCard 作为单个 LazyColumn `item`,内部 `PersonaListContent` 用 `Column { personaList.forEach { PersonaListItem(...) } }` 渲染所有人设。人设数量虽通常不多,但仍违反 lazy 列表的最佳实践,且人设多了同样会卡顿。
- 建议方案: 同前,将人设项扁平化到 LazyColumn 的 `items` 中。

#### 问题3: 🟠 personas.mapNotNull 在 Composable 中未 remember,每次重组都重建列表
- 位置: `CompanionPersonaTab.kt:288`
- 问题描述: `val personaList = personas.mapNotNull { it.jsonObject }` 在 `PersonaListContent` 函数体内,没有 `remember` 包裹。每次 `PersonaListContent` 重组(例如父级状态变化、`isSwitching` 切换),都会重新遍历整个 `personas` 数组并创建新列表。
- 建议方案: 改为 `val personaList = remember(personas) { personas.mapNotNull { it.jsonObject } }`。

#### 问题4: 🟡 LazyColumn 第一个 item 在非切换状态时为空,浪费布局
- 位置: `CompanionPersonaTab.kt:90-110`
- 问题描述: `item { if (uiState.isSwitching) { Row { ... } } }` 当 `isSwitching` 为 false 时,这个 item 仍然存在,只是内容为空。LazyColumn 会为它分配一个空 item 槽位,虽然开销极小,但属于代码不规范的累积。
- 建议方案: 改为 `if (uiState.isSwitching) { item { ... } }`,把条件判断移到 `item` 外面。

#### 问题5: 🟡 使用完全限定名 kotlinx.serialization.json.JsonArray 而非 import
- 位置: `CompanionPersonaTab.kt:282`
- 问题描述: `personas: kotlinx.serialization.json.JsonArray` 在函数签名中使用了完全限定名,而本文件并未 import `JsonArray`。同一文件其他地方已经 import 了 `JsonObject`、`JsonPrimitive` 等,风格不一致。
- 建议方案: 在文件头添加 `import kotlinx.serialization.json.JsonArray`,函数签名改为 `personas: JsonArray`。

---

### CompanionScreen.kt

#### 问题1: 🟡 @OptIn(ExperimentalFoundationApi::class) 可能已不必要
- 位置: `CompanionScreen.kt:56`
- 问题描述: 文件使用了 `@OptIn(ExperimentalFoundationApi::class)` 标注。在较新的 Compose 版本(1.6+ / Compose BOM 2024+)中,`HorizontalPager` 和 `rememberPagerState` 已转为稳定 API,不再需要 OptIn。保留无用的 OptIn 会让代码看起来依赖实验性 API,误导维护者。
- 建议方案: 检查当前 Compose 版本,若 `HorizontalPager` 已稳定,删除 `@OptIn` 注解和 `ExperimentalFoundationApi` import。

#### 问题2: 🟡 rememberPagerState 未持久化当前页,配置变更后回到第一个 Tab
- 位置: `CompanionScreen.kt:76`
- 问题描述: `val pagerState = rememberPagerState(initialPage = 0) { tabs.size }`。当用户切换到 "记忆" Tab 后旋转屏幕,会回到 "状态" Tab。`rememberPagerState` 内部用了 `rememberSaveable`,但 `currentPage` 的保存依赖 `SaveableStateHolder`,在某些场景(进程回收)下仍可能丢失。更重要的是,初始页硬编码为 0,无法从外部恢复。
- 建议方案: 若需持久化,可将当前页索引提升到 ViewModel 的 `SavedStateHandle` 中,或使用 `rememberSaveable` 单独保存页码并通过 `LaunchedEffect` 同步给 pagerState。

---

### CompanionStatusTab.kt

#### 问题1: 🟡 LazyColumn 错误条目 item 在无错误时仍占位
- 位置: `CompanionStatusTab.kt:77-84`
- 问题描述: `item { uiState.error?.let { errorMsg -> ErrorBanner(...) } }`。当 `uiState.error` 为 null 时,这个 item 仍然存在但内容为空,LazyColumn 会为它保留一个空槽位。虽然单 item 开销很小,但累积起来(多个文件都有此模式)会影响代码整洁度。
- 建议方案: 改为 `uiState.error?.let { errorMsg -> item { ErrorBanner(message = errorMsg, onRetry = onRefresh) } }`,把 `let` 移到 `item` 外面。

#### 问题2: 🟡 情绪卡片无 loading 态,与生命状态卡片不一致
- 位置: `CompanionStatusTab.kt:109-121`
- 问题描述: 生命状态卡片在 `uiState.isLoading && uiState.lifeStatus == null` 时显示 `CircularProgressIndicator`,但情绪卡片(`EmotionContent`)没有对应的 loading 态。当数据未加载时,情绪卡片会显示空的 `emotionPrimary` 和 0% 强度,视觉上像数据已加载但为空。
- 建议方案: 在情绪 SectionCard 内增加 `if (uiState.isLoading && uiState.emotion == Emotion.NEUTRAL) { CircularProgressIndicator() } else { EmotionContent(...) }` 的判断,或与生命状态卡片保持一致的 loading 策略。

---

### CircleScreen.kt

#### 问题1: 🟠 onClearError 参数声明但完全未使用,且 CircleUiState.error 在 UI 层无出口
- 位置: `CircleScreen.kt:16, 25-39`
- 问题描述: `@Suppress("UNUSED_PARAMETER") onClearError: () -> Unit = {}` 显式声明了 `onClearError` 回调,但函数体内从未调用,需要用 `@Suppress` 压制警告。同时 `CircleUiState` 定义了 `error: String?` 字段(见 CircleViewModel.kt:32),但 `CircleScreen` 整个 UI 树中没有任何地方渲染这个 error。这意味着:**即使 ViewModel 未来设置了 error,用户也看不到**。当前是死代码,未来是隐患。
- 建议方案: 二选一:(1) 移除 `onClearError` 参数和 `CircleUiState.error` 字段(若确认不需要错误展示);(2) 在 `CircleScreen` 的 LazyColumn 顶部增加一个 ErrorBanner(参考 CompanionStatusTab 的实现),并连接 `onClearError`。

#### 问题2: 🟡 @file:Suppress("DEPRECATION") 隐藏了已弃用 API 的使用
- 位置: `CircleScreen.kt:1`
- 问题描述: 文件级 `@file:Suppress("DEPRECATION")` 压制了整个文件中所有弃用警告。本文件用到了 `statusBarsPadding()`(可能在新版本中有替代)等 API。这种全局压制会让真实的弃用警告(未来可能移除的 API)被静默,后续升级 Compose 版本时容易踩坑。
- 建议方案: 移除文件级压制,改为针对每个具体弃用调用使用 `@Suppress("DEPRECATION")` 行内压制,并添加注释说明为何使用弃用 API / 何时迁移。

#### 问题3: 🟡 MemberStatusSection 调用处缩进不一致
- 位置: `CircleScreen.kt:48-56`
- 问题描述: `MemberStatusSection(...)` 的参数列表缩进与上下文不一致——`avelineLifeStatus`、`avelineThreadCount`、`lingThreadCount` 三个参数的缩进比 `RelationshipSection`、`SessionStatsSection` 等同级调用少了几个空格,看起来像被复制粘贴时未对齐。
- 建议方案: 统一为 8 空格续行缩进或保持参数在一行。

---

### CircleViewModel.kt

#### 问题1: 🔴 Flow 收集器无任何错误处理,异常会导致协程静默死亡
- 位置: `CircleViewModel.kt:76-106`
- 问题描述: `observeLifeStatus()` 和 `observeWebSocketMessages()` 都使用 `viewModelScope.launch { ... .collect { ... } }` 模式,没有 `.catch { }` 或 `try-catch`。一旦 `statusRepositoryImpl.observeLifeStatus()` 或 `webSocketManager.messages` 抛出任何异常(网络错误、JSON 解析错误、上游 flow 异常),collect 协程会立即终止且**不会有任何用户可见的反馈**(因为 `CircleUiState.error` 也从未被设置)。ViewModel 之后再也收不到生命状态更新,UI 静默停滞,用户以为 "没数据" 而实际是 "订阅死了"。
- 建议方案: 使用 `.catch { e -> _uiState.update { it.copy(error = "加载失败: ${e.message}") } }` 操作符,或在 collect 内 try-catch。同时考虑 `retry` 或重启策略,避免一次性异常导致永久失活。

#### 问题2: 🔴 CircleUiState.error 和 isLoading 是死字段,clearError() 是死代码
- 位置: `CircleViewModel.kt:30, 32, 130`
- 问题描述: `CircleUiState` 定义了 `isLoading: Boolean = false` 和 `error: String? = null` 两个字段,但通读整个 ViewModel **没有任何一处**对这两个字段进行非默认值的更新。`clearError()` 函数(行 130)把 error 设为 null,但既然 error 从未被设为非 null,这个函数也是死代码。同时 `CircleScreen` 也未渲染 error(见 CircleScreen 问题1)。这套错误处理链路是 "声明了但没接通" 的状态。
- 建议方案: 要么完整接入错误处理(在 Flow 收集器 catch 中设置 error,UI 渲染 error,提供 clearError 给 UI 调用),要么删除这套死代码避免误导后续维护者。

#### 问题3: 🟠 依赖 StatusRepositoryImpl 具体类而非接口,违反依赖倒置
- 位置: `CircleViewModel.kt:65`
- 问题描述: `private val statusRepositoryImpl: StatusRepositoryImpl` 构造参数类型是具体实现类。Hilt 注入虽然能工作,但这违反了 SOLID 的依赖倒置原则——ViewModel 应该依赖 `StatusRepository` 接口(若存在),便于测试时替换 mock、未来切换实现。同时变量名 `statusRepositoryImpl` 暴露了实现细节,不符合 "面向接口编程"。
- 建议方案: 改为 `private val statusRepository: StatusRepository`(假设接口名为 StatusRepository)。若接口不存在,应抽出一个接口。

#### 问题4: 🟠 addLingMessage 是 public 但从未被 ViewModel 内部调用,疑似死代码
- 位置: `CircleViewModel.kt:122-130`
- 问题描述: `addAvelineMessage` 在 `observeWebSocketMessages` 中被 `RitualEvent` 和 `SpontaneousReaction` 调用,但 `addLingMessage` 在 ViewModel 内部**从未被调用**。它是 public 的,理论上可被外部调用,但 Circle 模块的 UI 也没有任何地方调用它(用户无法发送消息给Ling)。这意味着 `lingThread` 列表永远为空,`CircleScreen` 中 `lingThreadCount` 永远是 0,`SessionStatsSection` 中 "Ling" 的消息数永远显示 0。
- 建议方案: 确认是否计划接入Ling的消息流。若是,补充 WebSocket 事件处理;若否,移除 `addLingMessage` 和 `lingThread` 字段,简化 UI。

#### 问题5: 🟠 lingRelationshipScore 是 computed property,每次访问都重新计算
- 位置: `CircleViewModel.kt:41-49`
- 问题描述: `val lingRelationshipScore: Float get() { ... }` 是一个计算属性,每次访问都会遍历 `relationships` Map。在 `CircleScreen` 中,`RelationshipSection(score = uiState.lingRelationshipScore)` 在 Composable 中访问该属性。由于 `CircleUiState` 是 data class,每次 `_uiState.update` 都会创建新实例,`lingRelationshipScore` 也会跟着重新计算。虽然 Map 遍历开销不大,但属性语义上是 "派生状态",更适合预计算。
- 建议方案: 改为在 `_uiState.update` 时一并计算并存储为字段:`data class CircleUiState(val lingRelationshipScore: Float = 0f, ...)`。或在 ViewModel 中暴露一个 `DerivedStateFlow`。

#### 问题6: 🟡 RitualEvent 和 SpontaneousReaction 处理逻辑重复
- 位置: `CircleViewModel.kt:88-99`
- 问题描述: 两个 when 分支 `is WebSocketMessage.RitualEvent` 和 `is WebSocketMessage.SpontaneousReaction` 的处理逻辑完全相同:`if (message.content.isNotEmpty()) { addAvelineMessage(message.content) }`。重复代码。
- 建议方案: 合并分支:`is WebSocketMessage.RitualEvent, is WebSocketMessage.SpontaneousReaction -> { if (message.content.isNotEmpty()) addAvelineMessage(message.content) }`。注意需要确认两个类型是否有共同的基类或 `content` 属性来源。

#### 问题7: 🟡 takeLast(100) 每次添加消息都创建新列表
- 位置: `CircleViewModel.kt:117, 127`
- 问题描述: `it.copy(avelineThread = newThread.takeLast(100))`。每次新增消息都会 `+ MessageItem(...)` 创建新列表,再 `takeLast(100)` 再创建一个新列表。对于高频消息场景(如每秒数条),会产生大量短生命周期对象,增加 GC 压力。
- 建议方案: 考虑使用 `ArrayDeque` 或环形缓冲区实现,或在列表超过阈值时才截断:`if (newThread.size > 100) newThread.takeLast(100) else newThread`。对于消息量不大的场景,保持现状也可,但应明确注释上限。

---

### CircleComponents.kt

#### 问题1: 🟠 硬编码成员名 "Aveline" 和 "Ling" 散落在 UI 中,未数据驱动
- 位置: `CircleComponents.kt:175-179, 230, 261`
- 问题描述: `GroupModeToggle` 中 `Tag(text = "Aveline", ...)`、`Tag(text = "Ling", ...)`、`RelationshipMeter` 中 `Text(text = "Aveline ↔ Ling", ...)`、`MessageStatCard` 调用处 `name = "Aveline"` / `name = "Ling"` 等均为硬编码字符串。这意味着:(1) 成员名变更需要改多处;(2) 无法国际化;(3) 与 `CircleUiState` 中本应承载成员信息的设计脱节。
- 建议方案: 在 `CircleUiState` 中增加 `members: List<MemberInfo>` 数据,UI 通过遍历渲染。成员名、颜色、角色等都从状态读取。

#### 问题2: 🟠 Brush.linearGradient 在 Composable 中未 remember,每次重组都重建
- 位置: `CircleComponents.kt:207-211`
- 问题描述: `Brush.linearGradient(colors = listOf(EmotionPink, EmotionPurple))` 在 `RelationshipMeter` 函数体内直接调用,没有 `remember` 包裹。每次 `RelationshipMeter` 重组(例如 `animatedScore` 每帧变化驱动重组),都会创建新的 `Brush` 和 `List`。动画期间(800ms)每帧都重建,产生大量短生命周期对象。
- 建议方案: 改为 `val brush = remember { Brush.linearGradient(colors = listOf(EmotionPink, EmotionPurple)) }`。

#### 问题3: 🟡 大量使用完全限定名 androidx.compose.foundation.BorderStroke 而非 import
- 位置: `CircleComponents.kt:78-80, 137-141, 165-170, 282-296, 327-354`
- 问题描述: 多处 `border = androidx.compose.foundation.BorderStroke(1.dp, ...)` 使用完全限定名,而文件头并未 import `BorderStroke`。同时 `fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace` 也是完全限定。代码冗长且不一致。
- 建议方案: 在文件头添加 `import androidx.compose.foundation.BorderStroke` 和 `import androidx.compose.ui.text.font.FontFamily`,然后简写。

#### 问题4: 🟡 关系亲密度阈值 80/60/40/20 为魔法数字
- 位置: `CircleComponents.kt:199-204`
- 问题描述: `when { score >= 80f -> "SOULMATE" to "💕"; score >= 60f -> "CLOSE" ... }` 中的阈值 80/60/40/20 硬编码在函数内,且对应的标签和 emoji 也硬编码。这些是业务规则,应集中管理。
- 嵌入方案: 抽到一个 `enum class RelationshipLevel(val threshold: Float, val label: String, val emoji: String)` 或顶层常量,UI 只做映射。

#### 问题5: 🟡 Math.round 应替换为 Kotlin roundToInt()
- 位置: `CircleComponents.kt:269`
- 问题描述: `Math.round(animatedScore)` 使用了 Java 的 `Math.round`,返回 `Int`。Kotlin 惯用 `Float.roundToInt()`(需 `import kotlin.math.roundToInt`),更符合 Kotlin 风格且对 NaN 处理更明确。
- 建议方案: 改为 `animatedScore.roundToInt()`。

#### 问题6: 🟡 InfoCard 颜色 Color(0x057835) 硬编码且含义不明
- 位置: `CircleComponents.kt:327`
- 问题描述: `colors = CardDefaults.cardColors(containerColor = Color(0x057835))`。这个 ARGB 值 `0x057835` 看起来是 RGB(0x78, 0x35) 加 alpha 0x05,但写法歧义,实际是 0x057835 = ARGB(0x00, 0x05, 0x78, 0x35) 即几乎完全透明。这种魔法颜色值无法从代码看出意图。
- 建议方案: 改为 `EmotionGreen.copy(alpha = 0.02f)` 或定义到 theme 中作为 `InfoCardBackground`。

---

### CircleMemberComponents.kt

#### 问题1: 🔴 name.first() 在空字符串时抛 NoSuchElementException
- 位置: `CircleMemberComponents.kt:145`
- 问题描述: `Text(text = name.first().toString(), ...)` 用于显示成员名首字母作为头像占位。但 `String.first()` 在字符串为空时抛 `NoSuchElementException`。虽然当前调用处传入的是硬编码的 "Aveline" 和 "Ling",但 `MemberStatusCard` 是 `internal fun`,未来若被其他地方调用或数据来自后端,空名字会直接崩溃。
- 建议方案: 改为 `name.firstOrNull()?.toString() ?: "?"` 或 `name.takeIf { it.isNotEmpty() }?.first()?.toString() ?: "?"`。

#### 问题2: 🟠 expandedMember 状态用 remember 而非 rememberSaveable,配置变更后折叠
- 位置: `CircleMemberComponents.kt:36-37`
- 问题描述: `var expandedMember by remember { mutableStateOf<String?>(null) }`。用户展开 "Aveline" 卡片查看详细数据后,旋转屏幕,展开状态丢失,卡片折叠。这是典型的状态管理不规范。
- 建议方案: 改为 `rememberSaveable { mutableStateOf<String?>(null) }`。

#### 问题3: 🟠 stats 为 null 时用全 1f 默认值误导用户,且 System.currentTimeMillis() 在 Composable 中
- 位置: `CircleMemberComponents.kt:73-78`
- 问题描述: `val s = stats ?: LifeStatus(health = 1f, hunger = 1f, happiness = 1f, energy = 1f, timestamp = System.currentTimeMillis())`。两个问题:
  1. **误导性默认值**: Ling没有生命状态数据(`stats = null`),但默认显示 health=1f/hunger=1f/... 即 100%,用户会以为Ling状态满分。应显示 "无数据" 或 0%。
  2. **Composable 中调用 `System.currentTimeMillis()`**: 这个值在每次重组时都会重新计算(虽然 timestamp 在这里并未被使用),属于副作用,且违反 Composable 应为纯函数的原则。
- 建议方案: (1) `MemberStatusCard` 改为接收 `stats: LifeStatus?` 并在 UI 中处理 null(显示 "无数据" 占位);(2) 移除默认 LifeStatus 的构造,避免 `System.currentTimeMillis()` 调用。

#### 问题4: 🟡 StatItem 与 MetricBar 重复展示 SATIETY/ENERGY/MOOD
- 位置: `CircleMemberComponents.kt:197-246`
- 问题描述: 展开区先渲染三个 `StatItem`(SATIETY/ENERGY/MOOD 数值),紧接着又渲染三个 `MetricBar`(SATIETY/ENERGY/MOOD 进度条+数值)。同一组指标在同一屏内以两种形式重复展示,且 MetricBar 本身也包含数值,信息冗余。
- 建议方案: 二选一保留。推荐保留 MetricBar(进度条+数值,信息密度更高),移除 StatItem 行;或反之。

#### 问题5: 🟡 StatItem 内不必要的 Row 包裹单个 Text
- 位置: `CircleMemberComponents.kt:213-218`
- 问题描述: `StatItem` 中 `Row(verticalAlignment = Alignment.CenterVertically, ...) { Text(text = label, ...) }` —— 一个 Row 只包了一个 Text,Row 完全多余。
- 建议方案: 直接 `Text(text = label, ...)` 即可。

#### 问题6: 🟡 完全限定名 BorderStroke 和 FontFamily.Monospace 重复
- 位置: `CircleMemberComponents.kt:81-86, 117-122, 154, 175-181`
- 问题描述: 同 CircleComponents.kt 问题3。
- 建议方案: 添加 import,简写。

---

## 总结与优先级建议

### 🔴 严重问题(应优先修复,4 项)

1. **CompanionMemoryTab.kt:109-137, 346-361** — MemoryListContent 在 LazyColumn item 内用 Column+forEach 渲染,失去 lazy 优势。记忆数量大时显著卡顿。
2. **CompanionPersonaTab.kt:142-160, 281-305** — PersonaListContent 同样的 lazy 失效问题。
3. **CircleViewModel.kt:76-106** — Flow 收集器无错误处理,异常导致协程静默死亡,UI 永久停滞。
4. **CircleMemberComponents.kt:145** — `name.first()` 空字符串崩溃风险。

### 🟠 中等问题(建议修复,15 项)

1. **CompanionMemoryCard.kt:60-65** — 长按删除与删除按钮重复,onClick 空操作。
2. **CompanionMemoryTab.kt:180-181** — 下拉菜单状态未 rememberSaveable(轻微,归类中等)。
3. **CompanionPersonaTab.kt:63-80** — JSON 解析混入 UI 且吞所有异常。
4. **CompanionPersonaTab.kt:288** — personas.mapNotNull 未 remember。
5. **CircleScreen.kt:16** — onClearError 死参数,error 字段在 UI 无出口。
6. **CircleViewModel.kt:30, 32, 130** — error/isLoading 死字段,clearError 死代码。
7. **CircleViewModel.kt:65** — 依赖 StatusRepositoryImpl 具体类而非接口。
8. **CircleViewModel.kt:122-130** — addLingMessage 死代码,lingThread 永远为空。
9. **CircleViewModel.kt:41-49** — lingRelationshipScore computed property 每次访问重算。
10. **CircleComponents.kt:175-179, 230, 261** — 硬编码成员名 "Aveline"/"Ling"。
11. **CircleComponents.kt:207-211** — Brush.linearGradient 未 remember,动画期间每帧重建。
12. **CircleMemberComponents.kt:36-37** — expandedMember 未 rememberSaveable。
13. **CircleMemberComponents.kt:73-78** — stats null 时全 1f 误导默认值 + System.currentTimeMillis() 在 Composable。
14. **CircleMemberComponents.kt:197-246** — StatItem 与 MetricBar 重复展示同一组指标。

### 🟡 轻微问题(可批量清理,21 项)

- 多个文件: `@file:Suppress("DEPRECATION")` 应改为行内压制并注释。
- 多个文件: 完全限定名 `BorderStroke`、`FontFamily.Monospace` 应 import。
- 多个文件: `Math.round` 应替换为 `roundToInt()`。
- CompanionMemoryCard.kt: 硬编码颜色未走主题。
- CompanionMemoryTab.kt: 删除对话框始终追加 "..."。
- CompanionMemoryTab.kt: `MemoryType.values()` / `MemorySortOrder.values()` 应改 `entries`。
- CompanionPersonaTab.kt: 空的 LazyColumn item(isSwitching 为 false 时)。
- CompanionPersonaTab.kt: 完全限定名 JsonArray。
- CompanionScreen.kt: `@OptIn(ExperimentalFoundationApi::class)` 可能已不必要。
- CompanionScreen.kt: pagerState 未持久化当前页。
- CompanionStatusTab.kt: 错误条目 item 在无错误时仍占位。
- CompanionStatusTab.kt: 情绪卡片无 loading 态。
- CircleScreen.kt: MemberStatusSection 调用缩进不一致。
- CircleComponents.kt: 关系亲密度阈值魔法数字。
- CircleComponents.kt: InfoCard 颜色 `Color(0x057835)` 含义不明。
- CircleMemberComponents.kt: StatItem 内多余 Row 包裹。
- CircleViewModel.kt: RitualEvent/SpontaneousReaction 处理逻辑重复。
- CircleViewModel.kt: takeLast(100) 每次创建新列表。

### 修复建议路径

**第一批(影响功能与稳定性,1-2 天)**:
- 修复 `name.first()` 崩溃风险(立即修)。
- 接入 CircleViewModel 的错误处理链路(Flow catch → error 字段 → UI 渲染)或删除死字段。
- 重构 CompanionMemoryTab 和 CompanionPersonaTab 的列表渲染,扁平化到 LazyColumn。

**第二批(架构与可维护性,2-3 天)**:
- 将 CompanionPersonaTab 的 JSON 解析下沉到 ViewModel,引入强类型数据类。
- 将 Circle 模块硬编码的成员名数据驱动化。
- 修复 expandedMember、showTypeMenu 等状态的 rememberSaveable。
- 修复 stats 为 null 时的误导性默认值。

**第三批(代码清理,0.5-1 天)**:
- 批量处理完全限定名、Math.round、values()→entries、@file:Suppress 等。
- 抽取主题颜色、关系等级阈值、InfoCard 颜色等魔法值。
- 合并重复的 when 分支,移除多余 Row 包裹。

### 整体评价

Companion 模块的代码组织较为清晰,SectionCard + LazyColumn 的结构合理,但存在 **"列表项 lazy 失效"** 这一典型性能反模式。Circle 模块的主要问题是 **错误处理链路声明了但未接通**、**死代码较多**、**UI 与状态数据驱动不彻底**(成员名硬编码)。两个模块共同的问题包括:大量 `remember` 应升级为 `rememberSaveable`、Java 风格 API(Math.round、values())未用 Kotlin 惯用法、完全限定名泛滥。整体代码质量中等偏上,但若不修复上述严重问题,在数据量增长或异常场景下会出现可感知的卡顿和静默故障。
