# Components 通用组件代码审查报告

## 审查概览

- **审查范围**: `app/src/main/java/com/aveline/ai/mobile/presentation/components/` 下全部 13 个 Kotlin 文件
- **审查日期**: 2026-07-28
- **总问题数**: 56 条
- **严重程度分布**:
  - 🔴 严重: 6 条
  - 🟠 中等: 35 条
  - 🟡 轻微: 15 条
- **主要问题类型**:
  1. **性能**: 无限动画常驻、Column+forEach 替代 LazyColumn、每帧重复计算
  2. **API 设计**: 大量 `@Suppress("UNUSED_PARAMETER")` 死参数、硬编码颜色未走主题
  3. **Compose 用法**: `remember` 缺失 key、`rememberSaveable` 缺失、不稳定 lambda
  4. **手势冲突**: 左边缘手势条未在抽屉打开时禁用
  5. **状态管理**: UI 状态(`isPlaying`)与数据模型(`MessageData`)耦合
  6. **无障碍**: `clickable` 缺 `role`、选中态无语义、Dialog 按钮 disabled 状态缺失

### 优先级速览

| 优先级 | 文件 | 问题 |
|--------|------|------|
| P0 | MessageBubble.kt | `remember` 缺 key 导致操作菜单状态错乱 |
| P0 | PeerChatComponents.kt | `Column+forEach` 渲染消息列表，长列表性能差 |
| P0 | TTSComponents.kt | Paused 状态进度计算 `/1000f` 逻辑错误 |
| P0 | VoiceInputComponents.kt | `repeat` 内部调用 `rememberInfiniteTransition` 产生多个 transition 实例 |
| P0 | DrawerContent.kt | 8 个未使用参数暴露在公开 API |
| P0 | LeftEdgeDrawerGesture.kt | 抽屉打开时手势条仍拦截触摸 |

---

## 逐文件审查

### BreathingBackground.kt

#### 问题1: 🟠 `emotionColors` 参数为死代码
- **位置**: BreathingBackground.kt:24-26
- **问题描述**: `emotionColors: List<String> = emptyList()` 标注 `@Suppress("UNUSED_PARAMETER")` 且函数体内从未引用。该参数对外暴露但无任何作用，调用方可能误以为传入颜色字符串会被使用，导致调试困难。
- **建议方案**: 直接删除该参数；若历史调用方仍需兼容，可标注 `@Deprecated` 并提供空实现，但更建议全局搜索调用处一并清理。

#### 问题2: 🟠 三个无限动画在抽屉可见时常驻耗电
- **位置**: BreathingBackground.kt:36-66
- **问题描述**: `rememberInfiniteTransition` 启动了 3 个 `animateFloat`（5000/5500/6000ms），驱动 `Canvas` 每帧重绘 4 个径向渐变。`DrawerContent` 内嵌本组件并 `fillMaxSize()`，只要抽屉内容处于组合中（`ModalNavigationDrawer` 默认保留组合），动画就持续运行，对低端机耗电与发热不友好。
- **建议方案**: 
  1. 在 `DrawerContent` 调用处根据 `drawerState.isOpen` 用 `AnimatedVisibility` 包裹或使用 `if (drawerState.isOpen) BreathingBackground(...)` 退出组合；
  2. 或为本组件增加 `active: Boolean` 参数，`active=false` 时跳过 `rememberInfiniteTransition` 改用静态值。

#### 问题3: 🟡 顶部光斑未参与呼吸动画
- **位置**: BreathingBackground.kt:118-132
- **问题描述**: Blob1/2/3 都使用 `scale1/2/3` 动画值，但"Top blob"使用固定 `topRadius = maxDim * 0.38f`。注释说明是"呼吸灯背景"，顶部光斑静止破坏整体呼吸感。
- **建议方案**: 为顶部光斑增加第 4 个 `animateFloat`（或复用 `scale3`），保持视觉一致性。

#### 问题4: 🟡 硬编码 alpha 与位置百分比
- **位置**: BreathingBackground.kt:96, 108, 120, 128
- **问题描述**: alpha 值 `0.3f / 0.24f / 0.2f` 与位置 `0.2f/0.3f`、`0.8f/0.7f`、`0.55f/0.45f`、`0.5f/0.02f` 均为魔法数字，后续调优时难以定位。
- **建议方案**: 提取为 `private const val BLOB1_ALPHA = 0.3f` 等文件级常量，或封装到 `EmotionColorScheme` 中由主题控制。

#### 问题5: 🟡 `backgroundAlpha` 参数语义不一致
- **位置**: BreathingBackground.kt:25, 80
- **问题描述**: `backgroundAlpha` 仅作用于 `MaterialTheme.colorScheme.background.copy(alpha = backgroundAlpha)` 这一层底色，4 个光斑的 alpha 不受其控制。参数名暗示"整体背景透明度"，实际只影响底色块，调用方（如 DrawerContent 传 `0.9f`）可能误以为整张图都被压暗。
- **建议方案**: 重命名为 `baseColorAlpha` 并在 KDoc 中明确说明；或将光斑 alpha 也乘以 `backgroundAlpha`。

---

### DrawerContent.kt

#### 问题1: 🔴 8 个 `@Suppress("UNUSED_PARAMETER")` 死参数污染公开 API
- **位置**: DrawerContent.kt:144-156
- **问题描述**: `connectionState`、`sessions`、`currentSessionId`、`onSessionClick`、`onNewSession`、`onSessionRename`、`onSessionDelete`、`onSessionPin` 共 8 个参数均被 `@Suppress("UNUSED_PARAMETER")` 标注。文件末尾注释"遗留的 SessionItem 和其他代码被清理了"说明这些是历史遗留。它们:
  1. 误导调用方以为这些功能仍生效；
  2. 强制所有调用方传入无用 lambda（如 `onSessionClick = {}`）；
  3. 让真实的 API 表面积膨胀一倍。
- **建议方案**: 全部删除，并全局搜索调用处同步清理。如未来需要恢复会话列表，应在新组件中实现而非保留死参数。

#### 问题2: 🟠 大量未使用 import
- **位置**: DrawerContent.kt:1-68
- **问题描述**: 文件顶部 `@file:Suppress("DEPRECATION")` 但未指明抑制什么。同时大量 import 未使用：`SimpleDateFormat`/`Date`/`Locale`（会话项清理后遗留）、`Icons.Filled.Build/Dashboard/Extension/Memory/MoreVert/Person/PushPin/School/ShoppingBag`、`Icons.Outlined.Build/Dashboard/Delete/Extension/Memory/Person/PushPin/ShoppingBag`、`Divider`/`DropdownMenu`/`DropdownMenuItem`/`MenuDefaults`/`LazyColumn`/`items`/`Card`/`CardDefaults` 等。
- **建议方案**: 运行 ktlint 或手动清理未使用 import；移除 `@file:Suppress("DEPRECATION")` 或在抑制点用 `@Suppress("DEPRECATION", "Reason: ...")` 注明原因。

#### 问题3: 🟠 硬编码颜色未走主题
- **位置**: DrawerContent.kt:175, 196-198, 208, 210, 212
- **问题描述**: `Color(0x88101522)`（毛玻璃遮罩）、`Color(0x1A000000)`（选中背景）、`Color(0x66FFFFFF)`（未选中图标色）、`Color(0xE6FFFFFF)`（未选中文字色）、`Color(0x14000000)`（选中边框）均为硬编码。文件已经 import 了 `TextMuted`/`TextPrimary`/`TextSecondary`/`InteractivePrimary` 等主题色却完全未使用。
- **建议方案**: 将这些颜色移入 `Color.kt`/`Theme.kt`，命名为 `DrawerScrimOverlay`、`DrawerItemSelectedBackground`、`DrawerItemUnselectedContent` 等，统一在暗色/亮色主题中定义。

#### 问题4: 🟠 `DrawerNavigationItem` 缺无障碍语义
- **位置**: DrawerContent.kt:189-227
- **问题描述**: `Row.clickable(onClick = onClick)` 未指定 `role = Role.Tab` 或 `Role.Button`，也未通过 `Modifier.semantics` 暴露选中状态。TalkBack 读屏时只会读出"图标 聊天"，无法告知用户这是导航项还是当前选中项。
- **建议方案**:
  ```kotlin
  .clickable(
      interactionSource = remember { MutableInteractionSource() },
      indication = ripple(),
      role = Role.Tab,
      onClick = onClick
  )
  .semantics {
      contentDescription = "${item.contentDescription}${if (isSelected) "，已选中" else ""}"
      selected = isSelected
  }
  ```

#### 问题5: 🟠 `clickable` 无 ripple 反馈
- **位置**: DrawerContent.kt:202
- **问题描述**: `clickable(onClick = onClick)` 使用默认 `indication`，但实际未显式传入。Material3 的 `clickable` 默认带 ripple，但当前实现未指定 `interactionSource`，每次重组都创建新的 `MutableInteractionSource`。更重要的是，点击时无明显视觉反馈（无 ripple 也无 state 层变化），用户体验差。
- **建议方案**: 显式 `remember { MutableInteractionSource() }`，并用 `indication = ripple()` 确保有水波纹反馈。

#### 问题6: 🟡 `drawerItems` 应为 `const` 或私有
- **位置**: DrawerContent.kt:74-127
- **问题描述**: `val drawerItems` 是顶层公开 `val`，外部可修改（虽然 `List` 不可变，但暴露内部导航结构不利于封装）。同时未用 `private` 限制可见性。
- **建议方案**: 改为 `private val DrawerItems` 或放入 `internal object DrawerConfig`；若需外部访问，提供 `getDrawerItems()` 函数。

#### 问题7: 🟡 选中态对比度过低
- **位置**: DrawerContent.kt:196
- **问题描述**: 选中背景 `Color(0x1A000000)` 是 10% 黑色，未选中文字 `Color(0x66FFFFFF)` 是 40% 白色，未选中图标 `Color(0x66FFFFFF)` 同样 40%。在毛玻璃背景上这些低对比度组合对视障用户不友好，违反 WCAG AA 标准。
- **建议方案**: 选中态使用 `InteractivePrimary.copy(alpha = 0.2f)` 提供品牌色反馈，未选中文字提升到 `Color(0xB3FFFFFF)`（70%）以上。

---

### InputArea.kt

#### 问题1: 🟠 `onImagePick` 为死参数
- **位置**: InputArea.kt:78-79
- **问题描述**: `onImagePick: (() -> Unit)? = null` 标注 `@Suppress("UNUSED_PARAMETER")`，函数体从未调用。与 DrawerContent 类似的死参数问题。
- **建议方案**: 删除该参数，调用处同步清理。

#### 问题2: 🟠 `isTyping` 语义混乱导致发送按钮被禁用
- **位置**: InputArea.kt:76, 173, 216
- **问题描述**: `isTyping` 参数用于：
  1. 占位符显示"正在输入..."（line 217）；
  2. 发送按钮 `enabled = !isTyping && enabled`（line 173）。
  若 `isTyping` 表示"用户正在打字"，则禁用发送按钮毫无意义；若表示"AI 正在回复"，则参数应命名为 `isAiResponding`/`isWaitingReply`。当前命名导致语义模糊，调用方易误用。另外占位符只在 `text.isEmpty()` 时显示，用户正在打字时 `text` 非空，占位符根本看不到，"正在输入..."提示实际只在"AI 回复中且用户清空了输入框"时出现，逻辑混乱。
- **建议方案**: 重命名为 `isAiResponding`，并将"AI 正在回复"的提示移到输入框外部（如顶部 `LinearProgressIndicator`），不要污染占位符。

#### 问题3: 🟠 硬编码颜色遍布全文
- **位置**: InputArea.kt:122, 124, 144, 174, 184, 198, 222, 232
- **问题描述**: `Color(0x1AEF4444)`、`Color(0x1AFFFFFF)`、`Color(0xFFEF4444)`、`Color(0x99FFFFFF)`、`Color(0x4DFFFFFF)`、`Color(0x2A38BDF8)`、`Color(0xFFE2E8F0)` 等大量硬编码。`InputArea` 已 import `InteractivePrimary`/`TextMuted`/`TextPrimary`/`TextSecondary` 但仅在 `CompactInputArea` 中使用。
- **建议方案**: 抽取 `RecordingBackground`/`InputBackground`/`SendButtonBackground` 等主题色，`InputArea` 与 `CompactInputArea` 共用一套颜色定义。

#### 问题4: 🟠 `AnimatedContent` 在每次按键时触发
- **位置**: InputArea.kt:209-238
- **问题描述**: `AnimatedContent(targetState = text.isNotBlank())` 在 `text` 每次变化时都会评估 `isNotBlank()`。虽然 `Boolean` 是稳定类型，但 `AnimatedContent` 内部仍会在状态切换时启动过渡动画。用户从空输入到输入第一个字符时，发送按钮和"+"按钮会做一次 `scaleIn + fadeIn` 切换，这通常符合预期；但若用户快速清空再输入，会反复触发动画。
- **建议方案**: 可接受，但建议加 `label` 已经加了。若要优化，可改为 `Crossfade` 或仅在 `text.isEmpty()` 切到非空时触发一次。

#### 问题5: 🟠 `CompactInputArea` 的 `BasicTextField` 无 `maxLines`
- **位置**: InputArea.kt:277-299
- **问题描述**: `CompactInputArea` 内的 `BasicTextField` 未设置 `maxLines`，用户输入大量文本时输入框会无限增高，撑爆布局。`InputArea` 主版本有 `maxLines = 4`，紧凑版反而没有限制，不一致。
- **建议方案**: 设置 `maxLines = 2` 或 `3`，并配合 `heightIn(max = ...)`。

#### 问题6: 🟠 `RecordingIndicator` 是死代码
- **位置**: InputArea.kt:247-271
- **问题描述**: `RecordingIndicator` 在本文件定义但未被 `InputArea` 使用，`isRecording` 状态在 `InputArea` 内仅改变麦克风按钮颜色，不显示该指示器。需全局搜索确认是否有调用方；若无则为死代码。
- **建议方案**: 全局搜索 `RecordingIndicator(`，若无调用方则删除；若有调用方，应将其与 `InputArea` 的录音状态联动。

#### 问题7: 🟡 `interactionSource` 未被观察
- **位置**: InputArea.kt:95
- **问题描述**: `val interactionSource = remember { MutableInteractionSource() }` 创建后仅传给 `BasicTextField`，未 `collectIsFocusedAsState()` 观察焦点状态。若不需要观察焦点，可直接传 `null`；若需要焦点反馈（如边框高亮），应补全观察逻辑。
- **建议方案**: 明确意图——不需要焦点反馈则传 `null`；需要则在 `decorationBox` 中根据 `interactionSource.collectIsFocusedAsState()` 改变边框颜色。

#### 问题8: 🟡 未使用 import
- **位置**: InputArea.kt:14, 20-22, 28-31, 45
- **问题描述**: `AttachFile`、`Image`、`outlined.AttachFile`、`outlined.KeyboardVoice`、`outlined.Send`、`BorderStroke`、`height`、`BorderLight` 等 import 未使用。
- **建议方案**: 清理未使用 import。

---

### LeftEdgeDrawerGesture.kt

#### 问题1: 🔴 抽屉打开时手势条仍拦截触摸
- **位置**: LeftEdgeDrawerGesture.kt:43-58
- **问题描述**: `pointerInput(Unit)` 始终激活，未判断 `drawerState.isOpen`。当抽屉打开后，手势条（x=24-56dp）覆盖区域内的触摸仍会被 `detectHorizontalDragGestures` 拦截，导致：
  1. 抽屉内容在该区域的水平滑动无法传给抽屉自身；
  2. 用户在抽屉左边缘右滑会再次触发 `drawerState.open()`（虽然 no-op，但消费了事件）。
- **建议方案**:
  ```kotlin
  if (drawerState.isOpen) return  // 在 Box 之前判断，或用 Modifier.alpha(0f).pointerInput(Unit) {} 屏蔽
  ```
  或在外部调用处用 `if (!drawerState.isOpen) LeftEdgeDrawerGesture(...)` 包裹。

#### 问题2: 🟠 `pointerInput(Unit)` key 不响应 `drawerState`/`scope` 变化
- **位置**: LeftEdgeDrawerGesture.kt:46
- **问题描述**: `pointerInput(Unit)` 用 `Unit` 作 key，意味着 lambda 内捕获的 `drawerState`/`scope` 永远是首次组合时的实例。若 `ModalNavigationDrawer` 在某些场景下重建 `drawerState`（如配置变化未走 `rememberSaveable`），手势条仍指向旧状态，调用 `open()` 无效。
- **建议方案**: 改为 `pointerInput(drawerState, scope) { ... }`，确保依赖变化时重建手势检测器。

#### 问题3: 🟠 无最小拖拽阈值，1px 右滑即触发
- **位置**: LeftEdgeDrawerGesture.kt:50-53
- **问题描述**: `if (!opened && dragAmount > 0)` 任何大于 0 的 `dragAmount` 都触发 `open()`。用户在边缘轻微触摸、抖动即可能误触，且 `detectHorizontalDragGestures` 的 `dragAmount` 是单帧位移，未累积。误开抽屉影响 Pager 浏览体验。
- **建议方案**: 累积位移，达到 `touchSlop` 或固定阈值（如 16dp 对应像素）后再触发：
  ```kotlin
  var totalDrag = 0f
  onHorizontalDrag = { _, dragAmount ->
      totalDrag += dragAmount
      if (!opened && totalDrag > with(density) { 16.dp.toPx() }) { ... }
  }
  ```

#### 问题4: 🟠 外部传入 `CoroutineScope` 不符合 Compose 惯例
- **位置**: LeftEdgeDrawerGesture.kt:33-34, 54
- **问题描述**: 组件要求调用方传入 `scope: CoroutineScope`，这迫使调用方记一个 `rememberCoroutineScope()` 再传入。Compose 组件应内部管理协程作用域，保持调用方 API 简洁。
- **建议方案**:
  ```kotlin
  @Composable
  fun LeftEdgeDrawerGesture(drawerState: DrawerState) {
      val scope = rememberCoroutineScope()
      // ...
  }
  ```

#### 问题5: 🟡 手势条宽度固定 32dp 不适配平板
- **位置**: LeftEdgeDrawerGesture.kt:43-45
- **问题描述**: `width(32.dp).offset(x = 24.dp)` 在手机上合理，但在大屏平板上 32dp 过窄，用户难以精准命中；在折叠屏外屏上又可能过宽。系统手势区在不同设备宽度也不同。
- **建议方案**: 用 `LocalConfiguration.current.screenWidthDp` 适配，或提供 `width: Dp` 参数。

---

### MessageBubble.kt

#### 问题1: 🔴 `remember` 缺 key 导致操作菜单状态错乱
- **位置**: MessageBubble.kt:151
- **问题描述**: `var showActions by remember { androidx.compose.runtime.mutableStateOf(false) }` 未传入 `message.id` 作 key。在 `LazyColumn` 中，当列表项复用（recycle）时，复用的槽位会保留前一条消息的 `showActions` 状态。例如用户长按第 1 条消息展开操作菜单，向下滚动后第 10 条消息复用同一槽位，会错误地显示操作菜单已展开。
- **建议方案**: `var showActions by remember(message.id) { mutableStateOf(false) }`。

#### 问题2: 🔴 `clip` 与 `Surface.shape` 圆角不一致产生视觉错位
- **位置**: MessageBubble.kt:170-176, 185-191
- **问题描述**: `Modifier.clip(RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomStart = if (isUser) 18.dp else 6.dp, bottomEnd = if (isUser) 6.dp else 18.dp))` 使用 18/6dp，而 `Surface(shape = RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp, bottomStart = if (isUser) 16.dp else 2.dp, bottomEnd = if (isUser) 2.dp else 16.dp))` 使用 16/2dp。外层 clip 18dp 先裁剪内容，内层 Surface shape 16dp 再裁剪一次，`BorderStroke` 沿 16dp 绘制但内容已被 18dp 裁掉一圈，导致边框与内容之间出现 2dp 错位缝隙，且圆角不重合处可见锯齿。
- **建议方案**: 删除 `Modifier.clip(...)`，仅依赖 `Surface` 的 `shape` 参数统一裁剪；或将两者改为同一 `RoundedCornerShape` 实例。

#### 问题3: 🟠 `aiEmotionColor` 在用户消息路径上仍计算
- **位置**: MessageBubble.kt:152
- **问题描述**: `val aiEmotionColor = EmotionResolver.getColorForEmotion(message.emotion ?: "neutral").copy(alpha = 0.15f)` 在 `isUser` 与非 `isUser` 分支前都执行。用户消息不需要这个颜色，浪费一次 `getColorForEmotion` 调用与一次 `copy`。
- **建议方案**: 移到 `val isUser = message.isUser` 之后用 `if (!isUser)` 守卫，或用 `remember(message.emotion)` 包裹。

#### 问题4: 🟠 `buildAnnotatedStringWithRetraction` 每次重组都重新编译正则
- **位置**: MessageBubble.kt:336-372
- **问题描述**: `Regex("（[\\s\\S]*?）|\\([\\s\\S]*?\\)")` 在函数内部构造，每次 `MessageBubble` 重组（如 `showActions` 切换、`isPlaying` 变化）都重新编译正则。`buildAnnotatedString` 也每次重新构建。
- **建议方案**:
  ```kotlin
  private val RETRACTION_REGEX = Regex("（[\\s\\S]*?）|\\([\\s\\S]*?\\)")
  ```
  并在 `MessageBubble` 内 `val annotatedText = remember(cleanedText, isUser) { if (!isUser) buildAnnotatedStringWithRetraction(displayText) else AnnotatedString(displayText) }`。

#### 问题5: 🟠 `Surface.color` 含 RETRACTION 分支为死代码
- **位置**: MessageBubble.kt:181-185
- **问题描述**: `when (message.messageType) { ... MessageType.RETRACTION -> aiEmotionColor }` 永远不会执行——RETRACTION 类型在第 142-148 行已 `return` 退出函数。
- **建议方案**: 删除 `MessageType.RETRACTION -> aiEmotionColor` 分支，或用 `else ->` 兜底。

#### 问题6: 🟠 `MessageData.isPlaying` 将 UI 状态混入数据模型
- **位置**: MessageBubble.kt:75-83
- **问题描述**: `data class MessageData(... val isPlaying: Boolean = false)` 把"TTS 当前是否正在播放此消息"这一纯 UI 状态塞进消息数据。当播放状态变化时，整条 `MessageData` 实例变化，导致 `LazyColumn` 中该 item 完全重组（包括图片、文本）。数据类应只承载业务数据。
- **建议方案**: 将 `isPlaying` 移出 `MessageData`，改为 `MessageBubble` 接收 `isPlaying: Boolean` 参数，由上层 ViewModel 维护 `Map<String, Boolean>` 跟踪当前播放消息。

#### 问题7: 🟠 `clickable` 缺 `role` 与无障碍语义
- **位置**: MessageBubble.kt:169-176
- **问题描述**: `clickable(interactionSource = interactionSource, indication = null) { if (!isUser) showActions = !showActions }`：
  1. 无 `role = Role.Button`，TalkBack 不会播报"按钮"；
  2. 无 `Modifier.semantics` 告知点击可展开操作菜单；
  3. `indication = null` 无视觉点击反馈。
- **建议方案**: 加 `role = Role.Button`，`semantics { contentDescription = "点击展开操作菜单" }`，并用 `indication = ripple()` 提供反馈。

#### 问题8: 🟠 复制操作复制了原始文本而非清理后文本
- **位置**: MessageBubble.kt:230
- **问题描述**: `onClick = { onCopy(message.text) }` 复制的是 `message.text`（含 `（开心）` 括号标记和末尾句号），而界面上显示的是 `cleanedText`（去句号）+ 括号内容斜体化。用户复制后粘贴会发现内容与所见不一致。
- **建议方案**: 复制 `displayText`（已去句号）或 `cleanedText`；若需保留括号原文，提供单独的"复制原文"选项。

#### 问题9: 🟡 `androidx.compose.runtime.mutableStateOf` 与 `AnimatedVisibility` 全限定名
- **位置**: MessageBubble.kt:151, 222
- **问题描述**: `androidx.compose.runtime.mutableStateOf(false)` 和 `androidx.compose.animation.AnimatedVisibility(...)` 用全限定名而非 import。文件顶部已 import 部分相关符号，风格不统一。
- **建议方案**: 补 import `mutableStateOf` 和 `AnimatedVisibility`，与其他文件保持一致。

#### 问题10: 🟡 `ImageMessageBubble` 与 `MessageImage` 功能重复
- **位置**: MessageBubble.kt:263-289, 380-403
- **问题描述**: `MessageImage`（私有）和 `ImageMessageBubble`（公开）都用 `AsyncImage` 显示图片消息，差别仅在 `widthIn(max)` 和圆角。维护时易改一处漏一处。
- **建议方案**: 合并为一个 `ImageMessageBubble`，通过参数控制尺寸；`MessageBubble` 内部复用之。

---

### ModuleHeader.kt

#### 问题1: 🟠 硬编码 `Color.White` 与 `Color(0x1A000000)`
- **位置**: ModuleHeader.kt:62, 88
- **问题描述**: `Text(color = Color.White)` 与 `Box(modifier = ... .background(color = Color(0x1A000000), ...))` 硬编码。在亮色主题下白色文字不可见，违反主题适配。
- **建议方案**: 改为 `MaterialTheme.colorScheme.onBackground` 和 `MaterialTheme.colorScheme.surface.copy(alpha = 0.1f)`。

#### 问题2: 🟡 `Spacer(height = 18.dp)` 占位脆弱
- **位置**: ModuleHeader.kt:70-72
- **问题描述**: 当 `subtitle` 为空时用 `Spacer(Modifier.height(18.dp))` 占位以保持标题垂直居中。但 `title` 若换行成两行，Column 高度变化，Spacer 仍占 18dp，整体高度不再固定为 76dp。
- **建议方案**: 给 `Column` 设 `fillMaxHeight()`，标题用 `Arrangement.Center`，无需 Spacer 占位。

#### 问题3: 🟡 `letterSpacing` 魔法数字
- **位置**: ModuleHeader.kt:64, 68
- **问题描述**: `letterSpacing = 2.sp` 和 `0.8.sp` 为魔法数字。
- **建议方案**: 提取为 `private val TitleLetterSpacing = 2.sp` 常量，或纳入 Typography 主题。

---

### PeerChatComponents.kt

#### 问题1: 🔴 `PeerChatMessageList` 用 `Column+forEach` 而非 `LazyColumn`
- **位置**: PeerChatComponents.kt:191-201
- **问题描述**: `Column { messages.forEach { PeerChatMessageBubble(message = message) } }` 一次性组合所有消息项。双角色对话消息可能很长（数十轮），全部驻留组合树会导致：
  1. 首帧渲染耗时随消息数线性增长；
  2. 内存占用高（每条消息的 `Card`/`Text` 都在树中）；
  3. 滚动时无回收机制。
- **建议方案**: 改为 `LazyColumn { items(messages, key = { it.id }) { PeerChatMessageBubble(message = it) } }`，并传入 `modifier`。

#### 问题2: 🟠 `Color(PeerChatMessage.getRoleColor(message.role))` 每次重组都构造 Color
- **位置**: PeerChatComponents.kt:35
- **问题描述**: `PeerChatMessage.getRoleColor(message.role)` 返回 `Int`（ARGB），`Color(int)` 每次重组都创建新 `Color` 实例。虽 `Color` 是 value class，但 `getRoleColor` 可能含 `when` 分支，重复求值浪费。
- **建议方案**: `val roleColor = remember(message.role) { Color(PeerChatMessage.getRoleColor(message.role)) }`。

#### 问题3: 🟠 硬编码颜色 `0xFF9C27B0` / `0xFF4CAF50` 等
- **位置**: PeerChatComponents.kt:109, 116, 124, 142, 156, 167, 174
- **问题描述**: 紫色 `0xFF9C27B0`、绿色 `0xFF4CAF50`、半透明白 `0x80FFFFFF`/`0x60FFFFFF` 散落各处，无主题统一管理。
- **建议方案**: 抽取 `PeerChatAccent`/`PeerChatActive`/`PeerChatMuted` 等主题色，便于暗色/亮色适配与品牌色调整。

#### 问题4: 🟠 `LinearProgressIndicator` 进度未 clamp
- **位置**: PeerChatComponents.kt:152-159
- **问题描述**: `progress = { progress }` 直接传入，若 `progress` 为负或大于 1（上游 bug），`LinearProgressIndicator` 会绘制异常。条件 `isActive && progress > 0` 只过滤了 ≤0 的情况。
- **建议方案**: `progress = { progress.coerceIn(0f, 1f) }`。

#### 问题5: 🟠 `PeerChatMessageBubble` 缺 `key` 支持
- **位置**: PeerChatComponents.kt:33-79
- **问题描述**: 虽然组件本身不负责列表 key，但若上层用 `Column+forEach`（当前实现）且消息列表变化（增删），无 key 会导致状态错乱。组件应假设上层会传 key，但当前 `PeerChatMessageList` 未传。
- **建议方案**: 配合问题1改为 `LazyColumn` 并 `items(messages, key = { it.id })`。

#### 问题6: 🟡 未使用 import `width`
- **位置**: PeerChatComponents.kt:21
- **问题描述**: `import androidx.compose.foundation.layout.width` 在文件内未使用。
- **建议方案**: 删除。

---

### SectionCard.kt

#### 问题1: 🟠 `expanded` 状态未 `rememberSaveable`，旋转屏幕丢失
- **位置**: SectionCard.kt:64
- **问题描述**: `var expanded by remember { mutableStateOf(defaultExpanded) }` 用 `remember` 而非 `rememberSaveable`。屏幕旋转、进程重建后折叠状态丢失，用户需重新点击展开。
- **建议方案**: `var expanded by rememberSaveable { mutableStateOf(defaultExpanded) }`。

#### 问题2: 🟠 `expanded` 不响应 `defaultExpanded` 变化
- **位置**: SectionCard.kt:64
- **问题描述**: `remember` 无 key，若同一组件实例的 `defaultExpanded` 参数变化（如父组件根据状态切换默认值），`expanded` 不会更新。
- **建议方案**: 用 `rememberSaveable(defaultExpanded) { mutableStateOf(defaultExpanded) }`，或在 `LaunchedEffect(defaultExpanded) { expanded = defaultExpanded }` 中同步。

#### 问题3: 🟠 `MutableInteractionSource` 在 `clickable` 内每次重组创建
- **位置**: SectionCard.kt:84-87
- **问题描述**: `Modifier.clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = { expanded = !expanded })`——`remember` 嵌在 `Modifier.then(...)` 链中，每次重组都会求值。虽然 `remember` 会缓存，但 `indication = null` 让点击无水波纹反馈。
- **建议方案**: 将 `interactionSource` 提到组件顶部 `val interactionSource = remember { MutableInteractionSource() }`；`indication` 改为 `ripple()`。

#### 问题4: 🟠 折叠时 `content()` 不调用导致内部状态丢失
- **位置**: SectionCard.kt:115-117
- **问题描述**: `if (!collapsible || expanded) { content() }`——折叠时 `content` lambda 不执行，其内部的 `remember` 状态全部丢失。下次展开时，`content` 重新组合，如内部 `TextField` 文本、`Switch` 状态（未 hoist 的话）都会重置。
- **建议方案**: 用 `AnimatedVisibility(visible = !collapsible || expanded) { content() }` 保持组合树；或要求调用方 hoist 状态。注意 KDoc 已注释"避免 AnimatedVisibility 包装导致子组件位置异常"，应在子组件用 `Modifier.animateContentSize()` 解决位置问题而非放弃 AnimatedVisibility。

#### 问题5: 🟡 `Spacer(size = 16.dp)` 在 Row 中用方形 Spacer 占位
- **位置**: SectionCard.kt:80-82
- **问题描述**: `else { Spacer(modifier = Modifier.size(16.dp)) }` 用 `size`（即 width×height=16×16）作图标占位。在 `Row` 中只需水平占位，`size` 多余设置了高度。
- **建议方案**: 改为 `Spacer(Modifier.width(16.dp))`，避免意外影响 Row 高度。

#### 问题6: 🟡 `valueColor` 全限定名风格不一致
- **位置**: SectionCard.kt:139
- **问题描述**: `valueColor: androidx.compose.ui.graphics.Color = com.aveline.ai.mobile.presentation.theme.TextPrimary` 用全限定名而非 import。文件未 import `Color` 与 `TextPrimary`。
- **建议方案**: 补 import `Color` 和 `TextPrimary`，简化签名。

---

### SessionDialogs.kt

#### 问题1: 🟠 `RenameSessionDialog` 的 `newTitle` 不响应 `currentTitle` 变化
- **位置**: SessionDialogs.kt:30
- **问题描述**: `var newTitle by remember { mutableStateOf(currentTitle) }` 无 key。若同一 Dialog 实例被复用（如重命名 A 后不关闭直接重命名 B），`currentTitle` 变化但 `newTitle` 仍是 A 的标题。
- **建议方案**: `var newTitle by remember(currentTitle) { mutableStateOf(currentTitle) }`；更稳妥用 `LaunchedEffect(currentTitle) { newTitle = currentTitle }`。

#### 问题2: 🟠 `newTitle` 未 `rememberSaveable`，旋转丢失输入
- **位置**: SessionDialogs.kt:30
- **问题描述**: 用户在重命名对话框中输入了一长串新名称，此时旋转屏幕，`remember` 丢失，输入框回到 `currentTitle`。
- **建议方案**: `var newTitle by rememberSaveable(currentTitle) { mutableStateOf(currentTitle) }`。

#### 问题3: 🟠 确认按钮在输入为空时仍可点击
- **位置**: SessionDialogs.kt:60-65
- **问题描述**: `TextButton(onClick = { if (newTitle.isNotBlank()) onConfirm(newTitle) })`——按钮始终 enabled，点击空白时静默无反应。用户以为按钮坏了。
- **建议方案**: `TextButton(onClick = { onConfirm(newTitle) }, enabled = newTitle.isNotBlank())`，让 disabled 状态视觉提示。

####问题4: 🟠 无输入长度限制
- **位置**: SessionDialogs.kt:46-58
- **问题描述**: `OutlinedTextField` 无 `maxLength`、无字符计数器。用户可输入超长名称（如 1000 字），持久化时可能截断或抛 SQL 异常。
- **建议方案**: 加 `Modifier.semantics` 与 `viewModel` 校验，或用 `TextFieldValue` 配合 `onValueChange` 截断：`if (it.length <= 50) newTitle = it`，并在 UI 显示 `50` 字符上限。

#### 问题5: 🟡 未使用 `imePadding`，键盘可能遮挡
- **位置**: SessionDialogs.kt:34-67
- **问题描述**: `AlertDialog` 默认不处理 IME。在窄屏设备上，弹出键盘后对话框可能被顶出可视区域，确认按钮不可见。
- **建议方案**: 在 `modifier` 上加 `.imePadding()`，或用 `Dialog` 自定义布局并 `imePadding()`。

#### 问题6: 🟡 `ConfirmDialog` 无破坏性样式
- **位置**: SessionDialogs.kt:139-155
- **问题描述**: `ConfirmDialog` 的确认按钮用默认颜色，无法区分"确认"与"删除"等破坏性操作。`DeleteSessionDialog` 单独把按钮文字设为 `error` 色，但 `ConfirmDialog` 不能复用此样式。
- **建议方案**: 增加 `destructive: Boolean = false` 参数，为 true 时确认按钮用 `MaterialTheme.colorScheme.error` 色。

---

### TTSComponents.kt

#### 问题1: 🔴 Paused 状态进度计算逻辑错误
- **位置**: TTSComponents.kt:48-50
- **问题描述**: 
  ```kotlin
  val progress = when (state) {
      is TTSState.Playing -> state.progress
      is TTSState.Paused -> state.position.toFloat() / 1000f // 简化处理
      else -> 0f
  }
  ```
  `state.position` 是毫秒，`/1000f` 得到的是秒数，而 `LinearProgressIndicator` 的 `progress` 应为 0..1 的比例值。若 `position = 5000ms`，`progress = 5.0f`，进度条会溢出绘制。注释"简化处理"掩盖了 bug。
- **建议方案**: `TTSState.Paused` 应携带 `duration` 或 `progress` 字段；若仅有 `position`，需 `state.position.toFloat() / state.duration.coerceAtLeast(1)`。若无法获取 duration，暂停时直接显示上次的 `progress`（缓存最近一次 Playing 的 progress）。

#### 问题2: 🟠 `CompactTTSButton` 与 `CompactVoiceButton` 在非播放时仍跑动画
- **位置**: TTSComponents.kt:120-133
- **问题描述**: `rememberInfiniteTransition` 始终启动，`targetValue = if (isPlaying) 1.1f else 1f`。非播放时 `initialValue = 1f`、`targetValue = 1f`，动画仍在跑（虽然值不变），每帧仍触发重组与重绘。在消息列表中多个 `CompactTTSButton` 同时存在时累计耗电。
- **建议方案**: 用 `if (isPlaying)` 条件启动动画：
  ```kotlin
  val scale = if (isPlaying) {
      val t = rememberInfiniteTransition()
      t.animateFloat(...).value
  } else 1f
  ```
  或用 `AnimatedContent`/`remember(isPlaying)`。

#### 问题3: 🟠 `TTSControls.progress` 在 Loading 时未隐藏
- **位置**: TTSComponents.kt:46-55
- **问题描述**: `progress` 在 `Loading` 状态返回 `0f`，但 `LinearProgressIndicator` 仅在 `isPlaying || isPaused` 时显示。Loading 时进度条不显示，仅显示"加载中..."文字。逻辑上 OK，但 `progress = 0f` 的分支冗余。
- **建议方案**: 用 `else -> 0f` 兜底即可，无需单独 `is TTSState.Loading ->` 分支。

#### 问题4: 🟠 `TTSStatusIndicator` 接收 `messageId` 但仅做相等比较
- **位置**: TTSComponents.kt:200-211
- **问题描述**: `TTSStatusIndicator(state: TTSState, messageId: String, ...)` 内部只做 `state.messageId == messageId`。把整个 `state` 传入，每条消息都会因 `state` 变化而重组（即使不是自己的消息）。在长消息列表中，任意消息的 TTS 状态变化会触发所有 `TTSStatusIndicator` 重组。
- **建议方案**: 调用方预先计算 `val isThisMessage = state is TTSState.Playing && state.messageId == messageId`，组件只接收 `isThisMessage: Boolean`。

#### 问题5: 🟡 `isLoading` 时图标无加载反馈
- **位置**: TTSComponents.kt:140-150
- **问题描述**: `CompactTTSButton` 在 `isLoading = true` 时仅把 `tint` 透明度降到 0.5，无旋转/脉冲动画提示加载中。用户可能以为按钮卡死。
- **建议方案**: 加 `CircularProgressIndicator` 覆盖或在图标上加 `alpha` 动画。

---

### TimeSeparator.kt

#### 问题1: 🟠 `formatMessageTime` 内部调用 `System.currentTimeMillis()` 不可测试
- **位置**: TimeSeparator.kt:58-96
- **问题描述**: `fun formatMessageTime(timestamp: Long): String` 内部 `val now = System.currentTimeMillis()`。这使函数成为非纯函数，单元测试需 mock 系统时间。同时 `TimeSeparator` 组件每次重组都调用该函数，每次都重新计算"今天/昨天/周几"。
- **建议方案**: 改为 `fun formatMessageTime(timestamp: Long, now: Long = System.currentTimeMillis()): String`，便于测试；组件内 `val formattedTime = remember(timestamp) { formatMessageTime(timestamp) }`。

#### 问题2: 🟠 `SimpleDateFormat` 与 `Calendar` 每次调用都新建
- **位置**: TimeSeparator.kt:75, 90, 110
- **问题描述**: `SimpleDateFormat("HH:mm", Locale.getDefault())`、`SimpleDateFormat("MM月dd日", Locale.getDefault())`、`Calendar.getInstance()` 每次调用都新建对象。`SimpleDateFormat` 构造较重（解析 pattern）。
- **建议方案**: 顶层 `private val TIME_FORMAT = SimpleDateFormat(...)`（注意线程安全，Compose 主线程单线程可用）；或改用 `java.time.format.DateTimeFormatter`（API 26+，需 desugaring）。

#### 问题3: 🟠 跨日用毫秒差计算未考虑夏令时
- **位置**: TimeSeparator.kt:88
- **问题描述**: `val diffDays = ((now - timestamp) / 86400000L).toInt()` 假设每天 86400000ms。在实行夏令时的时区，切换日当天可能是 23 或 25 小时，导致 `diffDays` 计算偏差，"周二"显示成"周三"。
- **建议方案**: 用 `Calendar` 滚动日字段比较，或用 `java.time.LocalDate` 的 `until(other, ChronoUnit.DAYS)`。

#### 问题4: 🟠 `week` 数组硬编码中文不随 locale 变化
- **位置**: TimeSeparator.kt:91-93
- **问题描述**: `val week = arrayOf("周日", "周一", ...)` 硬编码中文。在英文环境下显示中文星期，与系统语言不一致。
- **建议方案**: `SimpleDateFormat("EEE", Locale.getDefault()).format(Date(timestamp))`，让系统 locale 决定语言。

#### 问题5: 🟠 `Divider` 已废弃
- **位置**: TimeSeparator.kt:120, 134
- **问题描述**: `@Suppress("DEPRECATION") Divider(...)`——Material3 中 `Divider` 已被 `HorizontalDivider` 取代。
- **建议方案**: 改用 `HorizontalDivider(modifier = ..., color = ..., thickness = ...)`，移除 `@Suppress`。

#### 问题6: 🟡 `DateSeparator` 用 `Locale.CHINA` 与 `formatMessageTime` 的 `Locale.getDefault()` 不一致
- **位置**: TimeSeparator.kt:108, 75
- **问题描述**: 两个格式化函数用不同 locale 策略，海外用户会看到日期是中文格式、时间是英文格式。
- **建议方案**: 统一用 `Locale.getDefault()`，或抽取 `private val LocaleProvider` 便于切换。

---

### TypingIndicator.kt

#### 问题1: 🟠 三个 `animateFloat` 各自独立，可合并
- **位置**: TypingIndicator.kt:33-66
- **问题描述**: 三个 `animateFloat`（dot1/2/3）分别用 `tween(400, delayMillis=0/150/300)`。实际上 `rememberInfiniteTransition` 启动后，三个动画共享同一 transition 但各自有独立 `animateFloat`，每帧都计算 3 个值。可优化为单动画 + 计算相位偏移。
- **建议方案**: 
  ```kotlin
  val phase by infiniteTransition.animateFloat(0f, 1f, infiniteRepeatable(tween(1200)))
  val dot1Scale = 0.8f + 0.4f * sin(phase * PI * 2)
  val dot2Scale = 0.8f + 0.4f * sin((phase - 0.25f) * PI * 2)
  val dot3Scale = 0.8f + 0.4f * sin((phase - 0.5f) * PI * 2)
  ```
  减少 2/3 的动画状态。

#### 问题2: 🟠 `CompactTypingIndicator` 三点同步闪烁无波浪
- **位置**: TypingIndicator.kt:121-145
- **问题描述**: `repeat(3) { _ -> Box(... color = TextSecondary.copy(alpha = alpha) ...) }`——三个点用同一个 `alpha`，同时亮同时暗，无波浪效果。与 `TypingIndicator` 的设计意图（"每个点有不同的动画相位偏移，创建波浪效果"）不一致。
- **建议方案**: 复用 `TypingIndicator` 的实现，或为每个点计算 `alpha = baseAlpha * (0.5f + 0.5f * sin(phase + index * offset))`。

#### 问题3: 🟡 `TextSecondary` 不适配亮色主题
- **位置**: TypingIndicator.kt:51, 142
- **问题描述**: `TextSecondary` 是固定颜色（多半为白/浅灰），在亮色主题下可能不可见。
- **建议方案**: 改为 `MaterialTheme.colorScheme.onSurfaceVariant`。

---

### VoiceInputComponents.kt

#### 问题1: 🔴 `ProcessingIndicator` 在 `repeat` 内多次调用 `rememberInfiniteTransition`
- **位置**: VoiceInputComponents.kt:135-155
- **问题描述**: 
  ```kotlin
  repeat(3) { index ->
      val infiniteTransition = rememberInfiniteTransition(label = "processing_$index")
      val alpha by infiniteTransition.animateFloat(...)
      Box(...)
  }
  ```
  每次 `repeat` 迭代都调用 `rememberInfiniteTransition`，创建 3 个独立的 `InfiniteTransition` 实例。每个 transition 内部维护独立的协程与帧调度，3 个 transition = 3 套动画协程。且 `remember` 在 `repeat` 内部的行为依赖调用顺序，列表项增删时可能错位。
- **建议方案**: 提取单一 transition 到 `repeat` 外：
  ```kotlin
  val infiniteTransition = rememberInfiniteTransition(label = "processing")
  val alphas = (0..2).map { index ->
      infiniteTransition.animateFloat(
          initialValue = 0.3f, targetValue = 1f,
          animationSpec = infiniteRepeatable(tween(400, delayMillis = index * 150), Reverse),
          label = "alpha_$index"
      )
  }
  repeat(3) { index -> Box(... alphas[index].value ...) }
  ```

#### 问题2: 🟠 `AudioWaveform` 在 `repeat` 内多次 `animateFloat`
- **位置**: VoiceInputComponents.kt:215-235
- **问题描述**: `repeat(barCount) { index -> val animatedHeight by infiniteTransition.animateFloat(...) }`——虽然 `infiniteTransition` 在 repeat 外，但每个 bar 调用一次 `animateFloat`，5 个 bar = 5 个动画状态。`delayMillis = phaseOffset` 仅延迟首次启动，`RepeatMode.Reverse` 后续循环不再有相位差，波形很快退化为同步起伏。
- **建议方案**: 用单动画 + `sin` 计算各 bar 高度，参考 TypingIndicator 问题1的方案。

#### 问题3: 🟠 `CompactVoiceButton` 非录音时仍跑动画
- **位置**: VoiceInputComponents.kt:243-254
- **问题描述**: 同 `CompactTTSButton` 问题2。`targetValue = if (isRecording) 1.1f else 1f`，非录音时动画空转。
- **建议方案**: `if (isRecording)` 条件启动动画。

#### 问题4: 🟠 `amplitude` 未 clamp 到 [0,1]
- **位置**: VoiceInputComponents.kt:23, 225
- **问题描述**: `amplitude: Float = 0f` 注释标明 0-1，但代码未校验。若上游传入 1.5 或 -0.3，`0.3f + amplitude * 0.7f` 计算出 1.35 或 0.09，`height = 40 * 1.35 * heightFactor` 可能超出 `modifier = Modifier.height(40.dp)` 父约束（被裁剪），但负值会导致 `height` 为负抛异常。
- **建议方案**: `val safeAmplitude = amplitude.coerceIn(0f, 1f)` 在组件入口处理。

#### 问题5: 🟠 硬编码 `Color.White` 与魔法数字 `40`
- **位置**: VoiceInputComponents.kt:104, 240
- **问题描述**: `tint = Color.White`（停止图标）、`height((40 * animatedHeight * heightFactor).dp)` 中的 `40` 为魔法数字，与 `Modifier.height(40.dp)` 重复但无关联。
- **建议方案**: 提取 `private val WaveformHeight = 40.dp`，组件用 `tint = MaterialTheme.colorScheme.onPrimary`。

#### 问题6: 🟡 `kotlin.math.abs` 全限定名
- **位置**: VoiceInputComponents.kt:238
- **问题描述**: `val centerFactor = 1f - kotlin.math.abs(index - barCount / 2f) / (barCount / 2f)` 用全限定名。
- **建议方案**: `import kotlin.math.abs` 后直接用 `abs(...)`。

#### 问题7: 🟡 `barCount` 未校验为 0 时的除零
- **位置**: VoiceInputComponents.kt:238
- **问题描述**: `barCount / 2f` 若 `barCount = 0`，除以 0 得 `NaN`，`1f - NaN / NaN = NaN`，`height = 40 * NaN * NaN = NaN`，`NaN.dp` 行为未定义。
- **建议方案**: `require(barCount > 0) { "barCount must be positive" }` 或 `if (barCount <= 0) return`。

---

## 总结与优先级建议

### P0（立即修复，影响功能正确性与稳定性）

1. **MessageBubble.kt 问题1**: `remember` 加 `message.id` key，否则 LazyColumn 复用时操作菜单状态错乱。
2. **MessageBubble.kt 问题2**: 统一 `clip` 与 `Surface.shape` 圆角，消除视觉错位。
3. **PeerChatComponents.kt 问题1**: `PeerChatMessageList` 改用 `LazyColumn` + `key`。
4. **TTSComponents.kt 问题1**: 修复 `Paused` 进度计算，避免进度条溢出。
5. **VoiceInputComponents.kt 问题1**: 将 `rememberInfiniteTransition` 移出 `repeat`，合并为单实例。
6. **DrawerContent.kt 问题1**: 删除 8 个死参数，清理公开 API。
7. **LeftEdgeDrawerGesture.kt 问题1**: 抽屉打开时禁用手势条，避免拦截触摸。

### P1（优先修复，影响性能与可维护性）

- 清理所有文件的未使用 import 与死参数（DrawerContent、InputArea、PeerChatComponents 等）。
- 将硬编码颜色统一抽取到主题（DrawerContent、InputArea、MessageBubble、PeerChatComponents、ModuleHeader）。
- 为 `SectionCard.expanded`、`SessionDialogs.newTitle` 使用 `rememberSaveable` 与正确的 key。
- `TimeSeparator.formatMessageTime` 改为纯函数，`now` 作参数传入。
- `CompactTTSButton`/`CompactVoiceButton` 非激活时停止动画。
- `MessageData.isPlaying` 移出数据类，解耦 UI 状态。

### P2（机会修复，提升体验与一致性）

- 补全无障碍语义：`clickable` 加 `role`、选中态 `semantics`、Dialog 按钮 `enabled` 状态。
- `TypingIndicator` 与 `CompactTypingIndicator` 实现波浪动画合并优化。
- `Divider` 替换为 `HorizontalDivider`。
- `week` 数组改用 `SimpleDateFormat("EEE", locale)`。
- `LeftEdgeDrawerGesture` 增加 `touchSlop` 阈值与 `rememberCoroutineScope` 内部化。

### 整体观察

1. **死参数/死代码普遍**: DrawerContent 与 InputArea 大量 `@Suppress("UNUSED_PARAMETER")` 反映"清理了一半"的重构残留，应彻底清理调用方。
2. **硬编码颜色泛滥**: 多数组件已 import 主题色却仍写 `Color(0x...)`，说明主题色定义不完整或开发者习惯不佳。建议建立 lint 规则禁止 `Color(0x...)` 字面量。
3. **无限动画治理缺失**: 5+ 处 `rememberInfiniteTransition` 在非激活态空转，长列表中累计耗电明显。建议封装 `ActiveInfiniteTransition(active: Boolean)` 工具组件。
4. **`remember` key 普遍缺失**: 多处 `remember { ... }` 未传 key，是 Compose 状态错乱的常见根源。团队需建立代码规范要求 `remember` 必须带 key 除非明确只依赖首次组合。
5. **UI 状态混入数据模型**: `MessageData.isPlaying` 是典型反例，应推广"数据模型只含业务字段，UI 状态外置"原则。
