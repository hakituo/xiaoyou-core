# Android / 前端

本分类共 26 条记录。按时间倒序（最新在前）排列。

---

### 10.140 数字健康「计时不准」+「没在用却触发 active care」(2026-08-10)

*   **问题描述**: 用户反馈每天打开数字健康页面，哔哩哔哩都是固定显示 3h40m，且明明没在用却触发超额关怀。
*   **根因分析**:
    1. **计时不准根因**: `DataSyncWorker.getAppUsage(hours=24)` 查询过去 24h 的 UsageStatsManager INTERVAL_DAILY bucket，会混入昨天的全天用量（前天 B 站 3h40m），后端 `read_today_app_usage` 再取历史最大值聚合，峰值被永久保留。
    2. **假关怀根因**: `maybe_notify_exceeded_via_active_care` 只判断"今日累计用量超限"，不检查"用户此刻是否在活跃"。
    3. **日期口径不一致**: ViewModel 拉今天、后端默认返回明天限额。
*   **修复内容**:
    - `DataSyncWorker.kt`: `getAppUsage(hours=24)` → `getAppUsageSince(todayMidnightMs)`，只上报今天 00:00 至今
    - `UsageLimitMonitor.kt`: 同上 + 会话 cap 从全局 min 起点改为各自独立 `getAppUsageSince(appStart)`
    - `read_today_app_usage`: 聚合从取最大值改为取最新 `server_timestamp`
    - `maybe_notify_exceeded_via_active_care`: 增加 `last_used_time` 30min 活跃窗口检查
    - `AppLimitDto.kt`: 新增 `sessionCapMs` 字段
    - `WellbeingScreen.kt`: 展示一次性会话限额 + `formatDuration` 边界修复

### 10.139 ChatFlushManager 流式消息气泡不显示 / 文字倒退（根因：createNewMessage 只写数据库不更新 uiState + Flow 回流覆盖）(2026-06-27)

*   **问题描述**: Android 端发消息后，后端能正常输出流式响应，但前端不展示对方回复——连气泡都没有，只能看到自己发的消息。
*   **复现步骤**:
    1. 前端发送一条消息
    2. 后端正常生成流式响应（ResponseChunk 逐个到达前端）
    3. 前端 ChatViewModel 接收到 ResponseChunk，交给 ChatFlushManager.handleResponseChunk
    4. 前端 UI 不显示任何对方消息气泡
*   **预期行为**: 流式 chunk 到达时，前端实时显示对方消息气泡并逐字累积文本。
*   **实际行为**: 对方消息气泡完全不显示。
*   **根因（双重 bug）**:
    1. **createNewMessage 只写数据库，不更新 uiState.messages**：`ChatFlushManager.createNewMessage` 调用 `chatRepository.insertMessage(newMessage)` 写数据库，但没把新气泡加入 `uiState.messages`。后续 `appendToCurrentMessage` 从 `uiState.value.messages` 用 `indexOfFirst { it.id == messageId }` 找气泡 idx——新气泡还在等数据库 Flow 异步回流，回流前 idx=-1，`if (idx >= 0)` 不成立，文字直接丢弃。
    2. **Room Flow 回流覆盖 uiState 累积文本（文字倒退）**：即使 Flow 回流让气泡出现在 uiState，数据库此时只有 createNewMessage 写入的初始单字符。回流用初始字符版本覆盖 uiState 已累积的完整文本，导致文字倒退。后续 INSERT 会再次触发回流，反复倒退。
*   **修复**:
    1. `createNewMessage` 立即把新气泡加入 `uiState.messages`（保证 appendToCurrentMessage 能立即找到 idx），同时记入内存 `streamingMessages` 累积区
    2. 流式期间**不写数据库**，避免 INSERT 触发 Room Flow 回流覆盖 uiState 累积文本
    3. `appendToCurrentMessage` 更新 uiState + 同步更新 streamingMessages 对应 Message 的 text
    4. `onResponseDone` 时把 streamingMessages 用 `insertMessage`（`@Insert(onConflict = REPLACE)`）一次性写入数据库，此时 uiState 与数据库版本一致，回流不会倒退
    5. 去掉 `scheduleDbFlush` / `pendingDbUpdates` / `dbFlushIntervalMs`（流式期间批量写数据库的机制，已被上述策略取代）
*   **关键点**:
    - `insertMessage` 是 `@Insert(onConflict = OnConflictStrategy.REPLACE)`（upsert），`updateMessageText` 是纯 `UPDATE`（消息不存在则更新 0 行）。改用 insertMessage REPLACE 保证幂等且能 upsert 完整 Message
    - 用户消息能正常显示，证明数据库 Flow 本身工作正常，问题在流式消息的 uiState 同步时序
*   **教训**:
    1. UI 状态（uiState）和数据源（数据库 Flow）不能各管各的——写数据库后 UI 必须有对应的即时更新，不能只靠 Flow 回流（回流是异步的，有时延）
    2. Flow 回流是"用数据源版本覆盖 UI"，在流式累积场景下会倒退。流式期间应只更新 UI，数据源写入推迟到流式结束
    3. `if (idx >= 0)` 这种静默失败的判断是 bug 温床——idx=-1 时直接丢弃，没有任何日志，难以发现
*   **关键文件**: `ChatFlushManager.kt`、`ChatViewModel.kt`

### 10.137 LeftEdgeDrawerGesture 全屏覆盖方案导致点击和左滑失效（v4/v5 均失败，根因：pointerInput 持有 down 事件）(2026-06-27)

*   **问题描述**: 为解决 10.135（HorizontalPager 消费手势导致侧边栏无法呼出），尝试用全屏 Box 覆盖 + `detectHorizontalDragGestures`（v5）或 `awaitEachGesture` + `awaitHorizontalDragOrCancellation`（v4）来检测右滑。两种方案都导致子菜单点击失效、Pager 左滑切 tab 失效。
*   **复现步骤**:
    1. `LeftEdgeDrawerGesture` 用 `Box(Modifier.fillMaxSize().pointerInput(Unit) { detectHorizontalDragGestures(...) })` 全屏覆盖在 NavHost 之上
    2. 进入 Study/Life 页面，点击 Tab 内的子菜单按钮 → 无响应
    3. 在 Pager 内容区左滑切 tab → 无响应
*   **预期行为**: 全屏覆盖的手势检测器应该只拦截右滑，点击和左滑应正常传递给下层 NavHost。
*   **实际行为**: 点击和左滑都失效。
*   **根因**: `detectHorizontalDragGestures` / `awaitEachGesture` 在 `pointerInput` 中注册后，会在收到 down 事件时进入"等待 touchSlop"状态。这个"持有"行为使得即使最终判定不是水平拖拽（比如是点击），事件也不会传递给下层组件（NavHost）。`pointerInput` 在父 Box 上会拦截所有手势，子组件收不到事件。
*   **修复**: 放弃全屏覆盖方案，改用窄手势条：
    1. `Box(Modifier.width(32.dp).fillMaxHeight().offset(x = 24.dp).pointerInput(Unit) { detectHorizontalDragGestures(...) })`
    2. 只覆盖左边缘 24-56dp 这块 32dp 宽的区域
    3. 其他区域（56dp 以右）的点击、左滑、垂直滚动都不受影响，正常传递给 NavHost
    4. 24dp 以左不覆盖，留给系统全面屏返回手势
*   **trade-off**:
    1. 动画速度：`drawerState.open()` 是固定动画，无法跟手指（Material3 1.3.2 中 `animateTo` 是 private，`dispatchRawDelta` 不公开）
    2. 只能从左边缘 24-56dp 区域触发，不能从屏幕任意位置右滑
*   **教训**:
    1. `detectHorizontalDragGestures` 不是"只消费水平拖拽"——它在 down 阶段就持有事件，会阻塞子组件
    2. Compose 中 `pointerInput` 在父组件上会拦截所有手势，无论是否最终消费
    3. 想要不影响子组件的手势检测，必须缩小 `pointerInput` 的物理范围（用窄手势条），而不是靠"只消费特定手势"
*   **关键文件**: `LeftEdgeDrawerGesture.kt`、`MainActivity.kt`

### 10.135 HorizontalPager 消费手势导致 ModalNavigationDrawer 侧边栏无法呼出（2026-06-27）

*   **问题描述**: Study/Life 页面（含 HorizontalPager）右滑无法打开侧边栏，只有标题区域（无 Pager）可以。
*   **复现步骤**:
    1. 进入 Study 或 Life 页面（有 Tab + HorizontalPager）
    2. 在 Pager 内容区域从左向右滑
    3. 侧边栏不弹出
*   **预期行为**: 任何页面都能从左边缘右滑呼出侧边栏。
*   **实际行为**: HorizontalPager 消费了水平拖拽手势，ModalNavigationDrawer 的 `gesturesEnabled = true` 手势被拦截，侧边栏无法打开。
*   **根因**: Compose 手势分发机制中，子组件（HorizontalPager）在 Main pass 消费了水平拖拽事件，ModalNavigationDrawer 的手势检测器拿不到事件。
*   **修复**: 新增 `leftEdgeDrawerOpen` Modifier 扩展，用 `PointerEventPass.Initial` 在 Pager 之前（Initial pass 先于 Main pass）消费左边缘 24dp 区域的右滑手势。非左边缘起始的手势不消费，Pager 正常工作。
*   **关键文件**: `LeftEdgeDrawerGesture.kt`、`MainActivity.kt`

### 10.138 Android 编译错误：`Switch` `onCheckedChange` 漏传布尔参数（2026-06-26）

*   **问题描述**: `SettingsGeneralTab.kt:202` 编译报错 `No value passed for parameter 'p1'`。
*   **复现步骤**:
    1. 在 `Switch` 组件中写 `onCheckedChange = { onToggleSensitive() }`；
    2. 编译器期望 `(Boolean) -> Unit`，但传入的是 `() -> Unit`。
*   **预期行为**: 开关切换时应把新布尔值传给 `onToggleSensitive`。
*   **实际行为**: lambda 签名不匹配，编译失败。
*   **解决方案**: 改为 `onCheckedChange = { onToggleSensitive(it) }` 或直接传递 函数引用。

### 10.137 Android 编译错误：手势 API import 路径错误（2026-06-26）

*   **问题描述**: `MainActivity.kt` 实现侧边栏边缘手势时，Android Studio 编译报错 `Unresolved reference: awaitPointerEventScope / awaitEachGesture / awaitPointerEvent / consume`。
*   **复现步骤**:
    1. 在 `MainActivity.kt` 的 `pointerInput` 块中使用 `awaitPointerEventScope { ... }`；
    2. import 写为 `androidx.compose.ui.input.pointer.awaitEachGesture` 且缺少 `awaitPointerEvent` import；
    3. 执行编译即报多处未解析引用。
*   **预期行为**: 代码应正常编译，且侧边栏边缘手势优先于 `HorizontalPager` 消费事件。
*   **实际行为**: `awaitPointerEventScope`/`awaitPointerEvent` 在当前 BOM(2024.02.02, Compose 1.6.x) 不存在；`awaitEachGesture` 实际位于 `androidx.compose.foundation.gestures` 而非 `androidx.compose.ui.input.pointer`；尝试用 `drag(..., pass = Initial)` 时发现 1.6 的 `drag` 没有 `pass` 参数。
*   **原因分析**: 要在 `PointerEventPass.Initial` 阶段持续拦截 move 事件以打败 `HorizontalPager`，必须使用 Compose 1.7+ 才提供的 `awaitPointerEventScope`/`awaitPointerEvent`；当前 BOM 版本过低，且 `drag` 等旧 API 不支持指定 pass。
*   **解决方案**: 
    1. 保留 Compose BOM `2025.03.00`（Compose UI 1.8.0、Foundation 1.8.0、Material3 1.3.2、material-icons-extended 1.7.8）及 Kotlin `2.0.21`、KSP `2.0.21-1.0.28`、Hilt `2.55`、kotlinx-serialization `2.0.21`/`1.7.3` 的升级；
    2. 在 `app/build.gradle.kts` 中增加 `resolutionStrategy.force(...)` 强制 Compose 库版本,避免 transitive dependency 或镜像缓存把版本拉低；
    3. 手势实现改为:在内容最外层 Box 上监听 pointerInput,使用 `awaitFirstDown(pass = PointerEventPass.Initial)` 在 Initial pass 消费左边缘 down 事件,阻止 HorizontalPager 等子组件参与同一手势;然后用 `drag(down.id)` 在 Main pass 持续监听 move,累计右滑超过 50px 时打开抽屉。这套 API 在 Compose 1.6.x 即可使用,不需要 `drag(pass = ...)`。

### 10.59 AI生成时间戳导致前端显示异常和上下文重复 (2026-04-30)

*   **问题描述**: AI模仿上下文中的时间戳格式`[MM-DD HH:MM]`，在回复中自行生成时间戳前缀（如`[04-30 05:02]`），导致：1)前端显示带时间戳 2)历史记录出现重复时间戳 3)上下文注入也出现重复时间戳
*   **复现步骤**:
    1. 系统在上下文中注入带时间戳的历史消息（如`[04-30 05:02] 用户消息`）
    2. AI模仿格式，回复也带时间戳（如`[04-30 05:04] （盯着你看了两秒...）`）
    3. 前端QQ显示带时间戳的消息
    4. 保存历史时系统又添加时间戳，变成`[04-30 05:04] [04-30 05:04] （盯着你看了两秒...）`
    5. 下次注入上下文时出现双重时间戳
*   **预期行为**: 前端不显示AI生成的时间戳；历史记录和上下文注入中只有一个系统添加的时间戳
*   **实际行为**: 前端显示时间戳；历史记录和上下文注入出现重复时间戳
*   **根因**: AI看到上下文中的时间戳格式后模仿生成，但系统没有在回复处理链路中剥离AI生成的时间戳
*   **修复**:
    1. `handler.py`：在非流式路径中，情感标签提取后立即剥离AI时间戳前缀
    2. `streaming.py`：在流式路径中，think标签清理后剥离AI时间戳前缀（确保历史保存干净）
    3. `qq_adapter_session.py`：在`_send_full_response_with_split`中剥离AI时间戳（确保前端不显示）
    4. `context_budget.py`：扩展`_sanitize_history_messages`中的时间戳清理正则，同时匹配`[MM-DD HH:MM]`和`[MM-DD HH:MM:SS]`格式，防止旧历史数据中的重复时间戳

### 10.32 Android 编译失败：DrawerContent 混乱与 Hilt 拦截器冲突 (2026-03-03)

*   **问题描述**: 编译 Android 时出现 Kotlin 解析错误与 Hilt DuplicateBindings。
*   **复现步骤**:
    *   运行 `.\\gradlew :app:assembleDebug`。
*   **预期行为**: 编译成功。
*   **实际行为**: DrawerContent.kt 出现“imports only allowed at beginning of file”与多处语法错误；Hilt 报 Interceptor 重复绑定。
*   **原因分析**:
    *   DrawerContent.kt 存在中段 import 与重复函数定义。
    *   NetworkModule 同时提供多个未加限定符的 Interceptor。
*   **解决方案**:
    *   重写 DrawerContent.kt，清理重复定义与非法 import。
    *   为 Interceptor 增加 @Named 区分，并在 OkHttpClient 中显式注入。
        *   当 `task_type='image_gen'` 时，强制卸载 LLM 和 Vision 模型。
    *   **Voice Offloading**: 在执行重型任务前，自动将 TTS 和 STT 迁移至 CPU (`move_to_cpu`) 或卸载，释放约 1-2GB 显存。
*   **效果**: 彻底解决了 VRAM 争抢导致的死锁和性能骤降问题，实现了在 8GB 显存下流畅运行多模态全流程。

### 10.31 Android 网络优化脚本路径错误 (2026-03-03)

*   **问题描述**: 运行 `tests/diagnostics/verify_android_network_optimizations.py` 报 `FileNotFoundError`，无法读取 Android 源码文件。
*   **复现步骤**:
    *   在项目根目录执行 `python tests/diagnostics/verify_android_network_optimizations.py`。
*   **预期行为**: 脚本能正确定位 `clients/frontend/aveline-android` 并完成校验。
*   **实际行为**: 脚本把仓库根目录误判为 `D:\AI`，导致路径指向不存在的 `D:\AI\clients\...`。
*   **原因分析**: 通过 `Path(__file__).parents[3]` 计算根目录时层级偏大，跨过项目根目录。
*   **解决方案**: 将根目录定位修正为 `Path(__file__).parents[2]`。

### 10.26 原生安卓聊天白屏背景来源 (2026-02-07)

*   **问题描述**: 原生聊天页键盘弹出后出现白屏区域，表现为滚动空白。
*   **复现步骤**:
    *   进入原生聊天页，点击输入框呼出键盘。
    *   出现白屏区域。
*   **预期行为**: 聊天区背景保持黑色，无白屏。
*   **实际行为**: 聊天区出现白色空白。
*   **原因分析**:
    *   ScrollView/容器未显式设置背景，露出窗口背景。
    *   NativeMobileActivity 使用启动主题，窗口背景为 splash。
*   **解决方案**:
    *   为聊天容器与滚动区显式设置黑色背景。
    *   NativeMobileActivity 切换到非启动主题并设置黑色窗口背景。

### 10.26 原生安卓样式校验脚本误报 (2026-02-07)

*   **问题描述**: 调整聊天输入条背景色后，样式校验脚本仍提示缺少旧色值。
*   **复现步骤**:
    *   将输入条背景由 #12141b 调整为 #0f1117。
    *   执行 `python tests\diagnostics\verify_native_mobile_chat_ui.py`。
*   **预期行为**: 脚本通过校验。
*   **实际行为**: 脚本报 “主界面样式 缺少: #12141b”。
*   **原因分析**:
    *   系统 resize/pan 行为与布局层级冲突，导致可视高度不稳定。
*   **解决方案**:
    *   禁用系统 resize/pan，改用 IME Insets 驱动布局。
    *   监听 IME Insets 并自动回滚到底部。

### 10.25 原生安卓键盘白屏 insets 驱动修复 (2026-02-07)

*   **问题描述**: adjustResize/回位处理仍无法消除白屏与滚动异常。
*   **复现步骤**:
    *   进入原生聊天页，点击输入框呼出键盘。
    *   白屏依旧出现。
*   **预期行为**: 键盘弹出后聊天区稳定缩放，无白屏。
*   **实际行为**: 白屏仍存在。

### 10.24 原生安卓键盘白屏可滚动 (2026-02-07)

*   **问题描述**: 原生安卓聊天页键盘弹出后出现白屏，向下滑动才回到正常区域。
*   **复现步骤**:
    *   进入原生聊天页，点击输入框呼出键盘。
    *   白屏出现，需手动下滑。
*   **预期行为**: 键盘弹出后聊天区自动回位，无白屏。
*   **实际行为**: 需要手动下滑才能回到正常区域。
*   **原因分析**:
    *   软键盘触发布局挤压，但未强制回到底部。
    *   系统未稳定执行 adjustResize，导致界面被顶起。
*   **解决方案**:
    *   代码层强制设置 adjustResize。
    *   监听布局变化，键盘弹出时滚动到底部。

### 10.23 移动端键盘白屏可滚动 (2026-02-07)

*   **问题描述**: 键盘弹出后出现白屏，但向下滑动可回到正常聊天界面。
*   **复现步骤**:
    *   进入移动端聊天页，点击输入框呼出键盘。
    *   观察白屏区域并尝试向下滑动。
*   **预期行为**: 键盘弹出后聊天区保持在可见区域，无需手动滑动。
*   **实际行为**: 白屏区域可滚动，需向下滑动才恢复正常。
*   **原因分析**:
    *   视觉视口滚动导致整体页面被顶起，但聊天区未被强制回位。
    *   html/body 未锁定高度与滚动，页面整体产生滚动空间。
*   **解决方案**:
    *   锁定 html/body 高度与滚动，避免页面整体滚动。
    *   监听 visualViewport 滚动并强制回到底部。

### 10.22 移动端键盘白屏仍然存在 (2026-02-07)

*   **问题描述**: 修复后仍出现键盘上方大块白屏，聊天区看起来被“挖空”。
*   **复现步骤**:
    *   进入移动端聊天页，点击输入框呼出键盘。
    *   观察键盘上方区域出现明显白屏。
*   **预期行为**: 聊天区高度正常缩放，键盘上方无白屏。
*   **实际行为**: 键盘弹出后页面出现大块白屏。
*   **原因分析**:
    *   可视高度已被系统缩放，但前端再次按键盘高度二次缩高。
    *   聊天列表额外增加键盘高度 padding，形成双重留白。
*   **解决方案**:
    *   仅在可视高度未变化时才使用键盘高度修正。
    *   移除聊天列表基于键盘高度的 padding，只保留滚动触发。

### 10.21 移动端断句不生效与键盘留白 (2026-02-07)

*   **问题描述**: 移动端聊天页在回复时不按句号断句，且呼出键盘后聊天列表不抬起，底部出现大块留白。
*   **复现步骤**:
    *   进入移动端聊天页，发送消息。
    *   LLM 回复中包含中文句号。
    *   点击输入框呼出键盘。
*   **预期行为**: 回复按句号断句展示；键盘弹出后聊天自动滚动到最新消息，底部无异常留白。
*   **实际行为**: 回复未断句；键盘弹出后聊天不抬起，底部出现空白。
*   **解决方案**: 非流式回复沿用网页端断句逻辑，移除句末中文句号；键盘事件驱动聊天滚动与底部留白，并补齐 Android `adjustResize` 配置。

### 10.21 移动端消息气泡类型检查报错 (2026-02-06)

*   **问题描述**: 执行前端 typecheck 时，`MessageBubble.tsx` 报错 `Unexpected token`。
*   **复现步骤**:
    *   运行 `npm run typecheck`。
*   **预期行为**: TypeScript 校验通过。
*   **实际行为**: JSX 解析失败，指向多余的 `>`。
    *   **语音消息**: 修改 `MessageBubble.tsx`，确保语音消息始终同时显示文本内容。
    *   **消息重复**: 禁用了 `Aveline.tsx` 中的主动空闲检查 (Idle Check)。

### 10.21 前端诊断提示找不到新建 Hook (2026-02-06)

*   **问题描述**: IDE 诊断提示 `MobileApp.tsx` 中找不到 `useMobileNativeSync/useMobileInitialData/useMobileSidebarSwipe` 模块，但文件实际存在。
*   **复现步骤**:
    1. 新增 hook 文件并在 `MobileApp.tsx` 中引用。
    2. IDE 仍显示旧的“找不到模块”诊断。
*   **预期行为**: 诊断应在文件存在后立即消失。
*   **实际行为**: 诊断残留，需要重新索引后才消失（Typecheck 与诊断 API 已无错误）。
*   **经验总结**:
    *   **避免手动编译**: 除非必要，尽量避免在 Windows 上手动编译涉及 CUDA 的 Python 扩展。
    *   **使用预编译包**: 推荐使用 GitHub 上的预编译 Wheels（如 `jllllll/llama-cpp-python-cuBLAS-wheels`）。
    *   **`ggml-cuda.cu:*: CUDA error`（pip 编译阶段）**: 通常意味着 pip 未找到对应的预编译 Wheel 而走了源码编译；优先确认 Python 版本为 3.10-3.12，并使用带 CUDA 的 Wheel 源安装（例如：`pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124`）。
    *   **版本匹配**: 必须严格匹配 CUDA 版本 (e.g., `cu124` for CUDA 12.4) 和 Python 版本 (`cp310`)。
    *   **DLL 依赖**: 运行时若报 DLL 缺失，通常是因为 CUDA Runtime 库 (`cudart64_xx.dll`) 未在 PATH 中。

### 10.19 Capacitor 前端后台常驻通知点击无反应 (2026-02-04)

*   **问题描述**: 移动端 App 开启后台常驻通知后，点击通知无法跳转回 App，且任务列表清除后虽然显示后台运行，但进入 App 仍需重新加载。
*   **原因分析**:
    *   **PendingIntent 缺失**: 在 Android 原生代码 `AvelineForegroundService.java` 中，创建通知时未设置 `setContentIntent`，导致点击事件无任何响应。
    *   **Background Mode 依赖冲突**: 尝试安装 `@capacitor-community/background-mode` 时报错 404 或 ERESOLVE，导致前端无法通过代码控制后台保活行为。
*   **解决方案**:
    *   **注入 PendingIntent**: 修改 Java 原生代码，获取 `MainActivity` 的 Intent 并封装为 `PendingIntent`，通过 `setContentIntent(pendingIntent)` 绑定到通知上。
    *   **插件替换**: 弃用无法下载的社区插件，改用更成熟的 `cordova-plugin-background-mode`。
*   **经验总结**: 移动端原生功能的深度定制（如通知点击）往往需要直接修改 Android/iOS 原生目录下的代码，单纯依赖 Capacitor 插件可能无法覆盖所有细节。

### 10.17 移动端模型切换状态不可见 (2026-01-30)

*   **问题描述**: 移动端 App 发送切换本地模型指令后，虽然请求成功，但 UI 仍显示为云端模型，或无法确认切换成功，导致用户认为功能失效。
*   **原因分析**: 
    *   `FastAPIWebSocketAdapter.broadcast_resource_update` 在广播系统状态时，仅包含 `ResourceManager` 加载的物理模型状态，缺失了逻辑层（Settings）的当前 Provider/Model 配置。
    *   移动端依赖广播消息中的配置信息来更新 UI 状态，缺失该字段导致前端状态回滚或不更新。
*   **解决方案**: 修改广播逻辑，显式注入 `settings.model.llm` 配置信息到 `system_status` 消息中。
*   **验证**: 编写模拟脚本 `tests/diagnostics/reproduce_mobile_switch_issue.py`，确认修复后移动端能正确收到状态更新并完成切换。

### 10.16 Android WebView Mixed Content 与本地后端连接失败 (2026-01-29)

*   **问题描述**: Android App 无法连接到局域网 HTTP 后端 (`http://192.168.x.x:8000`)，即使防火墙已关闭且 IP 正确。
*   **原因分析**: Capacitor 默认配置 `androidScheme: 'https'`，导致 WebView 以 HTTPS 协议加载应用。当应用内尝试请求 HTTP 后端时，被 WebView 的 Mixed Content 安全策略拦截（HTTPS 页面禁止加载 HTTP 资源）。
*   **解决方案**: 修改 `capacitor.config.ts`，将 `androidScheme` 设置为 `'http'`，并启用 `cleartext: true`。这允许 WebView 以 HTTP 协议加载，从而合法请求 HTTP 后端接口。

### 10.65 呼吸灯在深色背景不明显的修复记录（2025-12-21）

*   **问题描述**: 在深色背景（尤其移动端深色主题）下，呼吸灯效果发光不明显甚至看起来“没亮”。
*   **复现步骤**:
    *   打开前端并切到深色背景；
    *   触发任意会导致呼吸灯变化的情绪状态；
    *   观察背景发光是否可见。
*   **预期行为**: 不论背景明暗，呼吸灯都应保持可见（至少有稳定的柔和光晕）。
*   **实际行为**: 在部分深色背景下光晕被“吃掉”，导致视觉上几乎不可见。
*   **原因分析**:
    *   发光层使用了混合模式（例如 `mix-blend-screen`）时，会与背景颜色发生非线性混合；在某些背景/透明度/叠加顺序下，反而会让发光层被压暗或被视觉吞没。
*   **解决方案**:
    *   移除会导致可见性不稳定的混合模式样式，并重新调整模糊半径与透明度，使其在深色背景下也能稳定呈现。文件：`clients/frontend/Aveline_UI/src/components/BreathingSystem.tsx`。

### 10.64 前端刷新/发消息后出现消息重复显示排查记录（2025-12-21）

*   **问题描述**: 用户反馈刷新页面后，前端会把同一条消息显示成两条；并怀疑后端历史记录是否“直接存储了重复消息”。
*   **复现步骤**:
    *   打开 `clients/frontend/Aveline_UI`（移动端 UI 或 Web UI）进入某个会话；
    *   发送一条消息并等待助手回复；
    *   刷新页面，观察消息列表是否出现重复条目（或在发送后短时间内出现重复）。
*   **预期行为**: 同一条消息在 UI 中只出现一次；历史记录与实时 WebSocket 增量消息能无缝衔接且不重复。
*   **实际行为**: 部分场景下同一条 assistant 回复会被追加两次，表现为 UI 列表中出现两条相同（或高度相似）的消息。
*   **初步结论**:
    *   后端会话历史接口更像是“如实返回最近历史”，不应主动制造重复；是否出现重复更可能来自前端把“历史拉取”和“WebSocket 增量回包”叠加后重复入队。
    *   移动端 UI 里 `handleSendWithText()` 在 `api.sendMessage(...)` 之后调用 `loadSessionHistory(currentSessionId)`，与 WebSocket 流式的 `response_chunk/response_done/response` 并行时，存在把同一条回复重复写入 `messages` 的窗口（`clients/frontend/Aveline_UI/src/MobileApp.tsx:393-420`）。
    *   `MobileApp.tsx` 的 WebSocket 消息分发里，`subtype=response` 分支直接 `append`，没有按 `message_id` 去重/覆盖更新，进一步放大了“同一 message_id 同时从两条通道到达”的重复概率（`clients/frontend/Aveline_UI/src/MobileApp.tsx:157-166`）。
*   **建议修复方向**:
    *   优先保证“单一真源”：发送后不立即强制 `loadSessionHistory`，改为以 WebSocket 流式结果为准；仅在 WebSocket 不可用/断开时再回退拉历史。
    *   `subtype=response` 分支按 `message_id` 更新已有消息（若存在则覆盖/合并），不存在才追加，避免同一 id 重复入队。
    *   `loadSessionHistory` 映射时按 `id/message_id` 做一次去重（例如 Map 覆盖），保证历史数据本身即使重复也不会污染 UI。
*   **后续定位与解决方案**:
    *   关键线索：前端 `apiService.sendMessage()` 自带重试，并且会在请求体里携带 `request_id`；但后端 `POST /api/v1/message` 会重新生成新的 `request_id`，导致同一条用户消息在网络抖动/超时后被“当成两条不同请求”重复处理，历史记录随之出现成对重复（刷新后依旧存在）。
    *   解决方案：在 `POST /api/v1/message` 增加基于请求体 `request_id` 的幂等缓存命中逻辑，重复请求直接返回首次响应，避免重复推理与重复写入历史。文件：`routers/api_router.py`
    *   兼容已产生的重复：扩展会话历史输出的去重窗口（按 `role+content` 在短时间内重复则丢弃），在不破坏正常对话的前提下隐藏“网络重试型重复”。文件：`memory/weighted_memory_manager.py`

### 10.45 Next.js 类型检查报错：缺失 `app/layout.js` / `app/page.js`（2025-12-19）

*   **问题描述**: 在 `clients/frontend` 下执行 TypeScript 检查或 Next 构建时，报错 `Cannot find module '../../app/layout.js'` / `Cannot find module '../../app/page.js'`。
*   **复现步骤**:
    *   进入目录：`clients/frontend`；
    *   执行 `npx tsc -p tsconfig.json --noEmit` 或 `npm run build`；
    *   观察 TypeScript 诊断指向 `.next/types/validator.ts`（或 `.next/dev/types/validator.ts`）中的 `import("../../app/layout.js")` / `import("../../app/page.js")`。
*   **预期行为**: 未实现业务页面时也应能通过基础构建与类型检查。
*   **实际行为**: `.next` 生成的类型校验文件会假设存在 App Router 入口（`app/layout.*`、`app/page.*`），导致类型检查失败。
*   **解决方案**: 补齐最小 App Router 入口文件（保持页面可渲染且不引入额外依赖）。文件：`clients/frontend/app/layout.tsx`、`clients/frontend/app/page.tsx`、`clients/frontend/app/globals.css`。
*   **经验总结**:
    *   Next.js 的 `.next/types/validator.ts` 会基于路由结构生成类型校验导入；如果项目选择 App Router，就必须至少存在 `app/layout.*` 与 `app/page.*`。
    *   若项目并不打算使用 App Router，应当从源头调整目录结构/配置与 `tsconfig.json` 的 `include` 策略，避免把 `.next/types` 作为“必过”的类型输入。
    *   Next.js v16 的 CLI 不包含 `next lint` 子命令；需要改用 `eslint`（例如 `npx eslint app ...`）执行 lint。

### 10.42 Ruff F841/F401 清理与 Tk GUI 组件写法（2025-12-18）

*   **问题描述**:
    *   `ruff` 报 `F841`（局部变量赋值未使用）与 `F401`（导入未使用），集中出现在 Tk GUI 的控件创建返回值、调试/占位变量、以及“预留但未实现”的代码片段中。
*   **处理方式**:
    *   对仅用于触发副作用（创建控件/注册回调）的场景：直接调用创建函数，不保存返回值。
    *   对确实无用的变量/导入：直接删除，避免留下“看似有逻辑但实际上不生效”的噪音代码。
    *   对占位的资源预处理代码：如果当前实现完全不可能被正确执行（例如同步函数里准备调用仅 async 的资源管理接口），直接移除占位块，避免误导后续维护。
*   **验证**:
    *   `python -m ruff check .` 通过；
    *   `python -m pytest -q` 通过（存在第三方 `chromadb` 的 DeprecationWarning，未影响回归）；
    *   `python -m mypy .` 通过。

### 10.2 记忆系统优化与前端渲染增强 (2025-12-13)

*   **Markdown 与 LaTeX 支持**: 前端引入 `react-markdown`, `remark-math`, `rehype-katex`，实现对数学公式和结构化文本的完美渲染，并在 Tailwind 中配置了 Typography 插件优化样式。
*   **记忆分类逻辑调优**: 将 `WeightedMemoryManager` 中进入长期记忆和权重记忆的阈值从 `2.5` 提升至 `3.0`，有效过滤了日常闲聊（权重通常约 2.3），确保只有重要信息（Importance=True）或高信息量对话（多主题+多情绪）被持久化。
*   **验证脚本**: 编写并执行了 `tests/test_memory_classification.py`，验证了不同场景下记忆的分类行为符合预期。

### AOS-0805-01 Widget 广播接收器 export=true 且接受自定义 action 风险 (2026-08-05)
*   **问题描述**: AndroidManifest 中 AvelineWidgetProvider android:exported=true，并在 intent-filter 同时注册 APPWIDGET_UPDATE 和自定义 ACTION_QUICK_SEND/ACTION_REFRESH，第三方 App 可任意指定 action 发送广播触发 widget 刷新/发消息，存在广播注入风险。
*   **复现步骤**:
    1. 安装 APK 后，通过 adb shell am broadcast -a com.aveline.ai.ACTION_WIDGET_QUICK_SEND ... 即可从任意 uid 进程触发
    2. 在安全测试工具 Drozer/Frida 中构造 pending intent 也可复用
*   **预期行为**:
    1. Widget 接收器仅接收系统级 android.appwidget.action.APPWIDGET_UPDATE 广播
    2. 自定义刷新/快速发送改为 export=false 的内部接收器、或显式通过 PendingIntent 内部 self 发送
*   **实际行为**:
    1. Widget Provider 同时处理三条 action，无权限限制
*   **根因**:
    1. 当初为了从内部发送广播到 widget，直接把自定义 action 加到了 export=true 的 provider 上，未注意权限边界
*   **修复方案**:
    1. Manifest 中 Widget 接收器 intent-filter 仅保留 APPWIDGET_UPDATE；自定义 action 由 updateAllWidgets() 显式指定 component 发送，不依赖 intent-filter 匹配
*   **验证**:
    1. `:app:compileDebugKotlin exit 0`
    2. `adb shell dumpsys package com.aveline.ai | findstr AvelineWidgetProvider 确认 export 仍为 true（系统需要），但 intentFilter 仅系统 action`

### 20260809-wellbeing-app-limits-empty 数字健康 App 限额界面刷新后仍为空 (2026-08-09)
*   **问题描述**: 数字健康界面点击刷新后仍显示无任何应用限额。
*   **复现步骤**:
    1. 打开 Aveline App 的数字健康界面
    2. 点击刷新按钮
    3. 界面仍为空，无任何应用限额展示
*   **预期行为**:
    1. 显示当天（nightly 已生成）的应用限额列表
    2. 刷新后能拉到已存在的限额数据
*   **实际行为**:
    1. 界面为空，刷新无效
    2. 后端限额文件存在（limits_2026-08-09.json，3 个应用）
*   **根因**:
    1. App 的 refresh() 调用 getAppLimits(target_date=null)，后端默认返回「明天」的限额
    2. nightly 生成的是「今天」的限额，日期错位导致 App 查询到空列表
    3. 后端 get_app_limits 注释「UI 主要管理未来那天」与 nightly 写「今天」的口径不一致
*   **修复方案**:
    1. WellbeingViewModel 统一传入 todayDate()(LocalDate.now()) 拉取/写入/删除当天限额
    2. 读/写/删三处对齐为当天日期，避免「读今天/写明天」不一致
*   **验证**:
    1. `后端按 target_date=2026-08-09 查询可返回 3 个应用限额，说明数据与字段结构无误`
    2. `App 端改为查询当天后应能正常展示`

### QR-20260813-VOCAB-SUMMARY 结算页本轮明细同词重复、正确率按重复提交算 (2026-08-13)
*   **问题描述**: Again 重排让同一词多次提交，结算页『本轮明细』同一单词显示多遍，会/不会计数与正确率也因此重复计算。
*   **复现步骤**:
    1. 复习中把某词点 Again
    2. 复习完成后打开结算页
*   **预期行为**:
    1. 每个词只出现一次，正确率基于去重后的唯一词数
*   **实际行为**:
    1. 同一词出现 N 次（Again 几次就几次），正确率被拉低
*   **根因**:
    1. submitReview 每次提交都 reviewResults + item，未按词去重
    2. accuracy 展示用后端按总提交统计的值
*   **修复方案**:
    1. StudyVocabReviewManager 增加 dedupeResults（LinkedHashMap 按词去重保留最后结果）
    2. VocabSessionSummary 正确率改为基于 reviewResults 唯一词数
*   **验证**:
    1. `Android Studio 编译验证 + 真机查看结算页不重复`

### QR-20260814-WB-001 Android 数字健康未使用应用却收到超限 active care 且强制退出失效 (2026-08-14)
*   **问题描述**: 数字健康模块在用户未使用某应用时仍发送 active care 超限关怀消息, 用量仅几分钟却被判超额, 且超限后应用未被强制退出 (无障碍权限已常驻)。
*   **复现步骤**:
    1. 配置某应用每日限额 (如 2h)
    2. 使用该应用至超限, 触发首次 active care 关怀消息
    3. 关闭该应用, 数小时后 (冷却到期) 再次收到超限关怀消息, 但实际早已不在使用
    4. 查看数字健康页面发现用量显示异常偏小 (仅几分钟)
    5. 超限后应用未被自动强制退出
*   **预期行为**:
    1. 仅在用户最近 30 分钟内仍在使用该应用时才发送超限关怀消息
    2. 用量统计应准确反映当日累计前台时长
    3. 超限后应自动强制退出应用 (需 Shizuku 运行中)
    4. 今日限额优先于明日预测限额用于判断是否超限
*   **实际行为**:
    1. 用户早已不在使用该应用仍收到超限关怀消息 (recent_active 检查失效)
    2. 用量显示仅几分钟 (同包名多个 bucket 未合并)
    3. 超限后应用未被强制退出 (Shizuku 不可用时静默失败)
    4. 明日预测限额覆盖今日实际限额导致误判超限
*   **根因**:
    1. get_exceeded_apps 未返回 last_used_time, recent_active 检查取值永远为 None
    2. sync_context 下发限额时 next_day 覆盖 today
    3. queryUsageSince 未合并同包名多个 UsageStats bucket
    4. forceStop 在 Shizuku 不可用时静默失败, 用户无感知
    5. fromisoformat 不支持 Z 后缀且 except 未 continue
*   **修复方案**:
    1. get_exceeded_apps 透传 last_used_time; 新增 _parse_last_used_time 兼容 Z 后缀, 缺失/失败时保守跳过
    2. 下发限额改为 today 优先, next_day 仅兜底
    3. queryUsageSince 先 groupBy 合并同包名 bucket
    4. forceStop 失败时发通知告知用户需 Shizuku, 并做每日通知去重
*   **验证**:
    1. `ruff check core/services/digital_wellbeing/service.py routers/v1/context_device.py`

### ANDROID-20260817-DRAWER-GESTURE Compose 侧边栏与子页面横向手势冲突 (2026-08-17)
*   **问题描述**: 侧边栏关闭时与 Pager、聊天详情面板等横向手势竞争，旧实现必须在 NavHost 上方放置透明边缘窗口才能呼出 Drawer。
*   **复现步骤**:
    1. 进入包含 HorizontalPager 或自定义 pointerInput 的子页面
    2. 从屏幕左侧向右滑尝试打开侧边栏
    3. 观察手势被页面抢走，或透明覆盖区域截断页面触摸
*   **预期行为**:
    1. 系统返回手势区域保持可用
    2. 侧边栏边缘右滑稳定触发
    3. 非侧边栏方向的点击、纵向滚动和横向 Pager 手势不受影响
*   **实际行为**:
    1. Drawer 与子页面竞争指针事件，依赖透明覆盖窗口抢占 down
*   **根因**:
    1. 关闭态 Drawer 原生手势与页面横向手势同时启用
    2. 透明边缘 Box 位于 NavHost 上层，会从命中测试层面截断子组件事件
*   **修复方案**:
    1. 关闭态禁用 Drawer 原生拖拽，打开态保留原生关闭手势
    2. 在内容根节点 Initial pass 只观察事件，越过 slop 且确认横向右滑后才消费
    3. 用 systemGestures inset 动态避开系统返回区域
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\android_frontend\verify_navigation_wellbeing_improvements.py`

### ANDROID-20260817-WELLBEING-ENFORCEMENT 数字健康超额后不会及时退出应用 (2026-08-17)
*   **问题描述**: 数字健康页面能显示接近正确的今日用量，但达到限额后应用仍可继续使用。
*   **复现步骤**:
    1. 给已安装应用设置较短的今日限额
    2. 持续使用直到页面显示已超限
    3. 继续停留或重新打开该应用
*   **预期行为**:
    1. 限额保存后立即在本机生效
    2. 达到限额的应用进入前台时立即返回桌面
    3. 页面明确提示缺失的系统授权
*   **实际行为**:
    1. 本地限额要等待 DataSyncWorker 更新
    2. WorkManager 最快每 15 分钟检查一次
    3. 没有 Shizuku 时 killBackgroundProcesses 不能结束前台应用
    4. 公开强退方法对 JSON status 的判断和降级成功语义不准确
*   **根因**:
    1. 前端保存链路与本地执行缓存未闭环
    2. 周期 Worker 不适合即时前台拦截
    3. 会话起点错误使用 daily 聚合桶统计
*   **修复方案**:
    1. Wellbeing 刷新后立即缓存每日与会话限额
    2. 使用 UsageEvents 精确累加查询区间
    3. 无障碍窗口事件触发即时检查，先回桌面再结束后台进程
    4. 页面增加执行状态卡与授权入口
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\android_frontend\verify_navigation_wellbeing_improvements.py`

### ANDROID-20260817-DRAWER-GESTURE-V2 侧边栏修复仍依赖 MainActivity 全屏 pointerInput (2026-08-17)
*   **问题描述**: 上一版表面删除透明边缘 Box，但将手势监听挂到全屏根 Box，仍是上帝窗口式触摸仲裁。
*   **复现步骤**:
    1. 检查 MainActivity 的 ModalNavigationDrawer 内容。
    2. 观察 fillMaxSize 根 Box 上的 pointerInput 和 Initial pass 事件监听。
*   **预期行为**:
    1. 侧边栏与 Pager 通过组件滚动边界协商，不存在全屏指针监听。
*   **实际行为**:
    1. 根节点观察整屏触摸事件，越过阈值后主动消费并打开 Drawer。
*   **根因**:
    1. 误把父层 Initial pass 监听当作非覆盖方案，没有从事件架构上移除全局监听。
*   **修复方案**:
    1. 改用 NestedScrollConnection 接收 Pager 未消费的边界右滑。
    2. 彻底删除 MainActivity 中的 pointerInput 与 PointerEventPass。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests/scripts/android_frontend/verify_navigation_wellbeing_improvements.py`

### ANDROID-20260817-DRAWER-PULL-ANIMATION Pager 边界侧栏只能阈值弹出而不能跟手拉动 (2026-08-17)
*   **问题描述**: 侧栏手势冲突解除后，Pager 页面右滑仍只在达到阈值时直接执行打开动画，拖动过程侧栏没有跟随手指。
*   **复现步骤**:
    1. 进入带 HorizontalPager 的侧边栏 Route。
    2. 在第一页向右缓慢拖动并停在中间位置。
    3. 观察侧栏没有实时位移，达到阈值后整体弹出。
*   **预期行为**:
    1. 侧栏和遮罩像主页一样随手指连续变化，松手后再吸附到打开或关闭状态。
*   **实际行为**:
    1. NestedScroll 只累计位移并调用 open()，没有视觉拖拽进度。
*   **根因**:
    1. Material3 DrawerState 不公开连续偏移写入，旧实现仍沿用离散 open() 状态切换。
*   **修复方案**:
    1. 以 AnchoredDraggableState 作为唯一 Drawer 运动状态。
    2. 将 NestedScroll 剩余位移实时分发到锚点状态，并绑定抽屉 translationX 与遮罩 alpha。
    3. 在 fling 结束时依据距离和速度选择目标锚点。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests/scripts/android_frontend/verify_navigation_wellbeing_improvements.py`

### ANDROID-20260817-COMPANION-PANEL-GESTURE 伴侣详情右滑仍靠全屏 pointerInput 与禁用 Pager (2026-08-17)
*   **问题描述**: 伴侣详情内部的右滑退出与 HorizontalPager 冲突，旧实现需要抢指针、禁用 Pager 并用 Channel 驱动内容偏移。
*   **复现步骤**:
    1. 从聊天页进入伴侣详情。
    2. 在第一个 Tab 缓慢右滑或在拖动中反向滑动。
    3. 观察手势偶发不响应、回弹不连贯或标题栏不随内容移动。
*   **预期行为**:
    1. 整个伴侣详情页跟随手指右移，Pager 仅在第一个 Tab 边界交出手势，松手后平滑吸附。
*   **实际行为**:
    1. CompanionScreen 全屏抢占事件并动态禁用 Pager，且只移动内部内容 Column。
*   **根因**:
    1. 手势状态位于 Pager 页面内部，没有采用父子 NestedScroll 边界接力。
*   **修复方案**:
    1. 用 PullableDismissPanel 包裹完整详情 Surface。
    2. 以 AnchoredDraggableState 和 NestedScrollConnection 替换旧 pointerInput/Channel/Animatable 方案。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests/scripts/android_frontend/verify_navigation_wellbeing_improvements.py`

### ANDROID-20260817-DRAWER-SCRIM-HITTEST 关闭态侧栏透明遮罩导致会话卡片无法点击 (2026-08-17)
*   **问题描述**: 启用自定义跟手侧栏后，消息主页点击任意会话没有反应。
*   **复现步骤**:
    1. 启动 Android 应用进入消息主页。
    2. 保持侧栏关闭并点击任意会话卡片。
    3. 观察聊天页面没有打开。
*   **预期行为**:
    1. 侧栏关闭时 NavHost 内容正常接收全部点击。
*   **实际行为**:
    1. 全屏透明遮罩位于会话列表上方，会话卡片没有收到点击事件。
*   **根因**:
    1. scrim 使用常驻 clickable(enabled=false)，关闭态仍参与全屏命中测试。
*   **修复方案**:
    1. 拆分纯绘制遮罩与点击关闭层，并仅在侧栏可见时组合点击层。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests/scripts/android_frontend/verify_navigation_wellbeing_improvements.py`

### ANDROID-20260817-DRAWER-ROUTE-THRESHOLD Route 内侧栏与伴侣详情需要拖动过长距离 (2026-08-17)
*   **问题描述**: 主页轻拉即可呼出侧栏，但含 Pager 的 Route 需要拖动很长距离；伴侣详情右滑退出也有相同体感。
*   **复现步骤**:
    1. 分别在消息主页和包含 HorizontalPager 的 Route 右滑侧栏。
    2. 比较松手后触发打开所需的拖动距离。
    3. 在伴侣详情第一个 Tab 重复右滑退出。
*   **预期行为**:
    1. 三条路径使用一致的短距离跟手吸附标准。
*   **实际行为**:
    1. Pager 消耗甩动速度后只能依赖 35% 距离阈值，明显比主页更难触发。
*   **根因**:
    1. 直接拖拽与 NestedScroll 接力获得的最终速度不同，但位置兜底阈值设置过长。
*   **修复方案**:
    1. 将侧栏和伴侣详情的直接拖拽与接力兜底统一为 12% 位置阈值。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests/scripts/android_frontend/verify_navigation_wellbeing_improvements.py`

### ANDROID-20260817-PAGER-PREFLING-VELOCITY Route 侧栏只复制距离阈值仍与主页轻甩手感不同 (2026-08-17)
*   **问题描述**: Route 内侧栏阈值改短后仍需明显拖动，主页则很短的轻甩即可打开。
*   **复现步骤**:
    1. 在主页短促右甩呼出侧栏。
    2. 在包含 HorizontalPager 的 Route 使用相同动作。
    3. 比较两者触发结果。
*   **预期行为**:
    1. Route 接力与主页同时采用相同的位置和速度判定。
*   **实际行为**:
    1. Pager 在 post-fling 前消耗速度，Route 只剩 12% 距离判断。
*   **根因**:
    1. 没有在 NestedScroll onPreFling 阶段保存原始速度。
*   **修复方案**:
    1. 保存 pre-fling 原始 X 速度并在 post-fling 复用主页 125dp/s 判定。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests/scripts/android_frontend/verify_navigation_wellbeing_improvements.py`

### ANDROID-20260817-GESTURE-MODEL-SYNC 伴侣详情退出串联侧栏且模型页误选本地模型 (2026-08-17)
*   **问题描述**: 伴侣详情右滑退出会同时呼出侧边栏，模型页显示的当前模型与后端实际模型不一致。
*   **复现步骤**:
    1. 从聊天页打开伴侣详情并在第一页向右甩动退出。
    2. 观察退出后侧边栏被同一手势打开。
    3. 进入模型页观察默认高亮项。
*   **预期行为**:
    1. 详情退出只结束详情面板，不影响外层抽屉。
    2. 模型页高亮后端当前模型。
*   **实际行为**:
    1. 外层抽屉复用了内层手势的 fling 速度。
    2. Android 在本地选择失配时回退了模型列表第一项。
*   **根因**:
    1. 抽屉没有校验自身是否发生位移就执行 fling 吸附。
    2. 模型仓库忽略 selected_model_id/path，并发送错误的切换字段。
*   **修复方案**:
    1. 增加 drawerHasMoved 门槛，实现内外层手势所有权隔离。
    2. 按后端路由解析当前模型并删除 firstOrNull 默认选择，切换消息使用 model。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\android_frontend\verify_navigation_wellbeing_improvements.py`

### ANDROID-20260817-SHOP-CACHE 商城每次进入重复刷新并在切类目时卡顿 (2026-08-17)
*   **问题描述**: 商城每次打开都重新显示加载状态，已获取的商品没有复用；快速滑动类目时还会出现响应覆盖和页面跳变。
*   **复现步骤**:
    1. 首次进入商城等待商品加载完成。
    2. 离开商城后再次进入。
    3. 连续快速左右滑动多个商品类目。
*   **预期行为**:
    1. 再次进入立即显示已有商品，必要时后台更新。
    2. 旧类目请求不能覆盖当前类目。
*   **实际行为**:
    1. ViewModel 初始化清空商品并重新请求。
    2. 并发类目请求缺少取消和归属检查。
*   **根因**:
    1. 仓库缓存未暴露给 UI，且只保存一份临时商品列表。
    2. 加载任务没有生命周期仲裁。
*   **修复方案**:
    1. 增加按类目和页保存的 ShopCacheSnapshot。
    2. 使用缓存优先与保留旧内容刷新策略。
    3. 取消过期任务并校验响应类目。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\android_frontend\verify_navigation_wellbeing_improvements.py`

### ANDROID-NAV-SETTINGS-001 Android 进入设置后侧边栏无法切换其他顶层栏目 (2026-08-17)
*   **问题描述**: 进入 Android 设置页后，从侧边栏点击学习、生活、商城、数字健康或消息，界面仍停留在设置页。
*   **复现步骤**:
    1. 从侧边栏进入学习等任一普通顶层栏目
    2. 打开侧边栏并进入设置
    3. 再次打开侧边栏并点击学习或其他顶层栏目
*   **预期行为**:
    1. 侧边栏关闭并立即显示所选顶层栏目
    2. 所有顶层栏目使用一致的返回栈保存与恢复行为
*   **实际行为**:
    1. 侧边栏关闭后仍显示设置页
    2. 只有按系统返回键先退出设置后才能正常切换
*   **根因**:
    1. 设置项通过独立 onSettingsClick 只执行 navigate(SETTINGS)，绕过统一顶层导航入口
    2. 后续 popUpTo(saveState=true) 保存了包含设置页的栈段，restoreState 恢复栏目时把设置页一并恢复为栈顶
*   **修复方案**:
    1. 移除 onSettingsClick 参数及其专用导航实现
    2. 所有 DrawerItem 点击统一调用 onNavigate(item.route)
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\android_frontend\verify_drawer_top_level_navigation.py`
    2. `gradlew.bat :app:transformDebugClassesWithAsm --no-daemon --stacktrace`

### ANDROID-HEALTH-001 三星健康同一晚多子会话导致入睡时间和时长不一致 (2026-08-18)
*   **问题描述**: Aveline Android 从 Samsung Health Data SDK 同步睡眠后，起床时间与三星健康一致，但入睡时间显示为同一晚后段子会话的开始时间，实际睡眠时长也与三星健康不同。
*   **复现步骤**:
    1. 在三星健康中确认当晚完整睡眠的起止时间和实际睡眠时长
    2. 在 Aveline Android 日程页触发三星健康同步
    3. 对比页面中的入睡时间、起床时间、阶段时长和睡眠得分
*   **预期行为**:
    1. Aveline 合并三星健康同一条睡眠记录内的全部子会话，并显示与三星健康一致的整晚起止时间
    2. 实际睡眠时长排除清醒阶段，睡眠得分与所选睡眠记录一致
*   **实际行为**:
    1. 代码先把不同睡眠记录内的子会话打平，再选择结束时间最新的单个子会话
    2. 同一晚早段子会话被遗漏，因此入睡时间偏晚，阶段和时长不完整
*   **根因**:
    1. 选择逻辑位于错误的数据层级，应选择完整睡眠数据记录而非单个 SleepSession
    2. 睡眠得分曾通过独立查询获取，存在与起止时间跨记录混用的风险
*   **修复方案**:
    1. 以 SDK 数据点为睡眠记录边界，选择最近结束的完整记录
    2. 合并所选记录的全部 SleepSession 子会话，并从相同记录读取睡眠得分
    3. 实际睡眠只累计浅睡、深睡和 REM 阶段
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\android_frontend\verify_samsung_sleep_consistency.py`

### ANDROID-COMPANION-OPEN-REGRESSION-001 聊天富文本手势仲裁导致伴侣详情无法打开 (2026-08-18)
*   **问题描述**: 接入横向表格手势仲裁后，聊天页无法通过头像或普通区域左滑进入伴侣详情。
*   **复现步骤**:
    1. 进入 Android 聊天主页
    2. 点击顶部伴侣头像，或从屏幕右半区域向左滑
    3. 观察伴侣详情是否出现
*   **预期行为**:
    1. 点击头像立即打开伴侣详情
    2. 普通区域左滑打开伴侣详情
    3. 仅表格、代码块和宽公式的内部横向滚动不打开伴侣详情
*   **实际行为**:
    1. 普通 clickable 消费事件导致左滑被拦截
    2. 面板显示前等待无锚点状态可能导致点击入口无法打开
*   **根因**:
    1. 手势消费判断粒度过粗
    2. 面板可见状态与拖拽锚点初始化顺序错误
*   **修复方案**:
    1. 只检查已消费的水平位置变化
    2. 先组合面板，再在面板内部建立锚点并恢复 Visible
*   **验证**:
    1. `verify_chat_markdown_rendering.py 静态回归检查通过`
    2. `设备交互验证由 Android Studio 安装后执行`

### ANDROID-COMPANION-GESTURE-OWNERSHIP-001 聊天页普通区域左滑仍无法进入伴侣详情 (2026-08-18)
*   **问题描述**: 富文本横向滚动接入后，设备上从聊天内容区域左滑仍可能完全不触发伴侣详情。
*   **复现步骤**:
    1. 进入 Android 聊天主页
    2. 从非表格的聊天内容区域向左滑
    3. 观察伴侣详情是否打开
*   **预期行为**:
    1. 除左边缘侧边栏保护区外，普通聊天区域均能左滑打开详情
    2. 表格、代码块和宽公式内部横滑只滚动内容
*   **实际行为**:
    1. 通用 consumed 状态可能将普通点击或列表事件误判为富文本横滑
    2. 右半屏起手限制使其他区域的左滑没有反应
*   **根因**:
    1. 父子手势使用隐式消费标志仲裁，语义不明确
    2. 页面级手势的起手区域限制过窄
*   **修复方案**:
    1. 以 CompositionLocal 下发显式手势状态
    2. 横向富文本区域在按下至抬起期间声明所有权
    3. 页面入口扩展到左侧保护区之外的整个聊天区域
*   **验证**:
    1. `verify_chat_markdown_rendering.py 静态回归检查通过`
    2. `Android Studio 安装后需确认普通区域左滑、表格横滑及重复开关面板`

### ANDROID-COMPANION-CONTROL-VISUAL-PULL-001 伴侣状态缺少操作入口且 Route 选中态与详情入场手感不统一 (2026-08-18)
*   **问题描述**: 伴侣睡觉或忙碌时只能从聊天渠道发送指令，状态页不能直接处理；生命状态和 Tab 选中颜色廉价，聊天页左滑进入详情也不会随手指移动。
*   **复现步骤**:
    1. 进入任一角色聊天并打开伴侣详情状态页
    2. 观察睡眠或忙碌活动是否有可执行操作，以及生命指标和顶部 Tab 的选中样式
    3. 返回聊天页后从非左侧边缘向左慢慢拖动
*   **预期行为**:
    1. 状态页按当前状态显示唤醒、打断或跳过活动，并操作正确角色与会话
    2. Route 使用克制的纯文字选中态且所有标签保持横向单行
    3. 详情页从右侧连续跟随手指进入，松手后自然吸附
*   **实际行为**:
    1. 状态页原先只有数值展示，没有现有控制 API 的客户端入口
    2. 顶部使用高饱和蓝色短条，Study 在窄屏下可能竖排
    3. 左滑期间页面静止，松手超过阈值后才快速播放固定入场动画
*   **根因**:
    1. 客户端状态 DTO 和领域模型没有承接后端活动与睡眠字段
    2. Route 重复使用默认蓝色 SecondaryIndicator
    3. 打开手势和详情面板的 AnchoredDraggableState 相互分离
*   **修复方案**:
    1. 接入后端活动、睡眠字段及三个既有控制端点
    2. 四个 Route 统一使用无指示条、无底色的单行文字 Tab
    3. 打开和关闭详情都由同一锚点状态实时驱动
*   **验证**:
    1. `verify_companion_controls_tabs_and_pull.py 静态回归通过`
    2. `verify_navigation_wellbeing_improvements.py 既有手势回归通过`
    3. `Android Studio 编译和真机交互待用户执行`

### QR-20260818-ANDROID-SLEEP-DURATION-SEMANTICS Android 睡眠时长与起止时间差值缺少解释 (2026-08-18)
*   **问题描述**: 实际睡眠时长不含夜间清醒，但界面只展示一个睡眠时长，看起来与入睡、起床时间矛盾。
*   **预期行为**:
    1. 将在床、实际睡眠和清醒时长分开展示并解释口径
*   **实际行为**:
    1. 只显示实际睡眠，用户无法知道时间差用在了哪里
*   **根因**:
    1. LifeScheduleTab 未渲染 sleepStageAwakeMinutes 与在床时间跨度
*   **修复方案**:
    1. 增加三种时长及计算口径说明，移除关闭状态的无效 N/A/none 行
*   **验证**:
    1. `verify_sleep_schedule_display 和 verify_samsung_sleep_consistency 通过`

### ANDROID-COMPANION-KOTLIN-COMPILE-001 伴侣状态与跟手入场实现违反 Kotlin 表达式体和受限协程规则 (2026-08-18)
*   **问题描述**: compileDebugKotlin 在 StatusRepositoryImpl 和 ChatScreen 报表达式函数体提前返回及受限协程调用普通挂起函数。
*   **复现步骤**:
    1. 在 Android Studio 编译 Debug 版本
    2. 观察 compileDebugKotlin 对 StatusRepositoryImpl 第 203 行及 ChatScreen 手势代码的错误
*   **预期行为**:
    1. 状态控制错误响应能够转换为 Result.failure
    2. 详情页保持跟手入场且遵守 Compose 指针输入协程限制
*   **实际行为**:
    1. 表达式函数体内使用 return 被 Kotlin 编译器拒绝
    2. AwaitPointerEventScope 内调用 withFrameNanos、snapTo 和 animateTo 被编译器拒绝
*   **根因**:
    1. 没有区分普通 Compose 协程与 AwaitPointerEventScope 的受限挂起上下文
    2. 面板按条件组合迫使打开手势在指针协程中等待锚点初始化
*   **修复方案**:
    1. 用异常进入既有 Result.failure 分支
    2. 让隐藏面板预先建立锚点，拖动阶段只派发同步位移
    3. 通过外层 CoroutineScope 执行松手吸附
*   **验证**:
    1. `verify_companion_controls_tabs_and_pull.py 静态回归通过`
    2. `Android Studio compileDebugKotlin 待用户复验`

### ANDROID-COMPANION-REPLY-POLICY-SCHEDULE-001 伴侣状态误用 Peer Chat 可用性且缺少分角色日程 (2026-08-18)
*   **问题描述**: 状态页使用可聊天或忙碌描述时无法说明消息是即时回复、延迟回复还是暂不回复，同时看不到当前伴侣当天的日程计划。
*   **复现步骤**:
    1. 进入任一角色聊天并打开伴侣详情状态页
    2. 观察角色处于空闲、日常活动、学习和睡眠时的状态文案
    3. 查看状态与模型之间是否有该角色的今日日程
*   **预期行为**:
    1. 状态页明确写当前活动及真实回复方式
    2. 轻活动显示实际延迟区间，学习和睡眠显示暂不回复
    3. 日程页按当前聊天角色展示当天完整时间线
*   **实际行为**:
    1. 旧实现把 activity_chat_eligible 直接解释为可以聊天
    2. 伴侣详情只有状态、模型、人设和记忆，没有日程页
*   **根因**:
    1. 混淆 Peer Chat 活动门控与用户消息 Reply Policy
    2. 未向 Android 暴露 CharacterDailyEngine 中已存在的 per-role DailyPlan
*   **修复方案**:
    1. 接口新增 reply_policy 摘要并由状态页直接展示
    2. 接口附带当前 scope 的 daily_plan，并新增独立日程 Tab
*   **验证**:
    1. `verify_companion_controls_tabs_and_pull.py 静态回归通过`
    2. `Android Studio 编译和真机切换角色验证待用户执行`

### ANDROID-COMPANION-PAGER-BOUNDARY-002 伴侣详情非首个 Tab 右滑直接退出且日程缓存误报为空 (2026-08-18)
*   **问题描述**: 在人设页右滑没有进入模型页而是直接退出到聊天；角色当前显示正在散步且持久化计划存在，日程页却提示没有生成。
*   **复现步骤**:
    1. 打开伴侣详情并切换到人设页
    2. 向右滑动一次，观察是否逐页进入模型
    3. 进入日程页并对照状态页当前活动
*   **预期行为**:
    1. 一次右滑只切换一个内层 Tab
    2. 必须稳定停在状态页后再次右滑才退出到聊天
    3. 日程页展示当前角色已存在的完整 DailyPlan
*   **实际行为**:
    1. 外层 anchoredDraggable 在人设页直接消费右滑并退出详情
    2. 旧缓存有 activity 但没有新增 daily_plan，空态错误宣称没有生成日程
*   **根因**:
    1. 外层退出手势没有根据 Pager 稳定页启停
    2. 进入详情和日程没有绕过旧生命状态缓存
*   **修复方案**:
    1. 用 settledPage 和 isScrollInProgress 锁定每次手势的层级所有权
    2. 打开详情和进入日程时调用 forceRefreshLifeStatus
    3. 修正日程同步中的空态文案
*   **验证**:
    1. `本地 daily_state.json 六个角色计划均存在`
    2. `verify_companion_controls_tabs_and_pull.py 静态回归通过`
    3. `真机手势与日程渲染待 Android Studio 构建后验证`

### ANDROID-VOCAB-20260818-SESSION-PERSISTENCE 背单词未完成强化队列在 App 重启后丢失 (2026-08-18)
*   **问题描述**: 背单词会话中标记不会的单词会在本轮最多再次出现两次，但中途强退或重启 App 后，剩余强化轮次消失；当天错词和明日复习记录仍存在。
*   **复现步骤**:
    1. 进入 Android 背单词模块并将某个词标记为 Again
    2. 在本轮尚未结束时强退 App
    3. 重启 App 并再次进入相同的背词入口
*   **预期行为**:
    1. 恢复到退出前的下一张卡片
    2. 先前标记 Again 的单词仍按剩余次数在本轮队尾再次出现
    3. 服务端长期复习记录与本地本轮强化队列各自保持原有职责
*   **实际行为**:
    1. 只要进程重启，ViewModel 中的动态队列、卡片索引和重排计数全部重置
    2. 后端虽已记录不会并安排后续日期复习，但当前会话的剩余强化轮次无法重建
*   **根因**:
    1. 本轮强化状态只存在于 VocabUiState 内存中
    2. StudyViewModel 冷启动无本地快照恢复步骤
*   **修复方案**:
    1. 用 SharedPreferences 保存可版本化的未完成会话 JSON 快照
    2. 评分后同步更新快照，完整结束或明确开始新会话时清理旧快照
    3. 冷启动先恢复，再允许用户从复习或背新词入口续背
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\study\verify_vocab_session_persistence.py`
    2. `真机执行 Again、强退、重启、续背流程`

### ANDROID-A11Y-20260818-NOTIFICATION-RESTORE 无障碍守护通知被划除后永久消失 (2026-08-18)
*   **问题描述**: Aveline 无障碍已开启且前台守护服务正在运行，但用户轻扫通知后守护通知不再出现，宿主进程随后更容易被厂商系统回收。
*   **复现步骤**:
    1. 在系统设置开启 Aveline 无障碍服务
    2. 确认 Aveline 后台守护通知已出现
    3. 在通知栏划除该通知并继续后台使用
*   **预期行为**:
    1. 守护通知被移除后立即以同一通知 ID 重新出现
    2. 恢复过程不重复响铃
    3. 用户真正关闭无障碍与常驻模式后不再恢复
*   **实际行为**:
    1. 通知只设置 ongoing，没有任何移除回调或恢复 PendingIntent
    2. 部分系统允许划除 ongoing 通知，划除后不会重新发布
*   **根因**:
    1. createForegroundNotification 未设置 deleteIntent
    2. AvelineNotificationService 未实现 onNotificationRemoved
*   **修复方案**:
    1. 用 PendingIntent.getForegroundService 绑定通知划除恢复动作
    2. 通知监听服务精确匹配本应用守护通知 ID 后兜底恢复
    3. 恢复函数统一校验无障碍系统开关与常驻模式
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\android_keepalive\verify_notification_self_restore.py`
    2. `真机划除守护通知后确认立即静默重现`

### ANDROID-ARCH-20260818-FOREGROUND-SERVICE-GOD-CLASS 前台守护 Service 累积七类职责达到 783 行 (2026-08-18)
*   **问题描述**: AvelineForegroundServiceV2 达到 783 行，通知自恢复局部修改误删了文件后半段仍需的通知渠道导入，暴露出职责耦合与变更风险。
*   **复现步骤**:
    1. 检查 AvelineForegroundServiceV2 的字段和私有方法
    2. 观察通知、WebSocket、上下文、健康、无障碍与电源逻辑全部位于同一 Service
    3. 修改主前台通知后编译整个文件
*   **预期行为**:
    1. Service 只负责系统生命周期与子组件编排
    2. 各后台子系统拥有独立文件、状态与依赖
    3. 通知或健康逻辑的局部修改不会影响其他职责的符号解析
*   **实际行为**:
    1. 七类职责共享一个 783 行文件
    2. 局部删除导入导致远端无障碍断线通知编译失败
*   **根因**:
    1. 缺少前台服务职责边界和文件规模回归约束
    2. 历史功能直接继续添加到 Service 私有方法
*   **修复方案**:
    1. 建立 services/foreground 子系统并按职责拆出七个组件
    2. 原 Service 仅保留生命周期、依赖接线和 startForeground 平台调用
    3. 新增 300 行薄壳上限、250 行子组件上限及业务实现泄漏检查
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\android_keepalive\verify_foreground_service_decomposition.py`
    2. `Android Studio Kotlin 编译与真机通知划除恢复`

### QR-20260818-ANDROID-SESSION-CROSSTALK Android ChatViewModel 聊天记录跨角色串台 (2026-08-18)
*   **问题描述**: App 端与某个角色聊天后，打开其他角色的会话窗口，显示的仍是与上一个角色的聊天记录，消息没有按角色隔离。
*   **复现步骤**:
    1. 进入角色 A 的聊天页并发送消息，产生若干条历史记录。
    2. 返回角色列表，进入角色 B 的聊天页。
    3. 观察角色 B 会话窗口中的消息列表。
*   **预期行为**:
    1. 角色 B 的会话窗口只显示与角色 B 的历史消息。
    2. 切换角色时消息列表随 session 重新加载。
*   **实际行为**:
    1. 角色 B（以及其他所有角色）的窗口都显示与角色 A 的聊天记录。
    2. 无论怎样切换角色，消息列表始终停留在首次进入 App 时的那个会话。
*   **根因**:
    1. observeCurrentSession() 中 sessionId 为一次性局部快照，Flow 建立后不再更新，上游永不发射新 session，导致 ChatViewModel 里正确写法的 flatMapLatest 永远不触发重载。
    2. 本地 session 切换被延迟到首次发消息，只读历史场景下 currentSessionId 未切换。
    3. ensureSessionForCurrentPersona 以全局 active persona 为准，会把会话冲回上一个角色。
    4. StateManager 异步恢复状态时无条件覆盖 currentSessionId，与进入聊天页的切换产生竞态。
*   **修复方案**:
    1. AppPreferences 暴露 currentSessionIdFlow，setter 同步推送；observeCurrentSession 改用 flatMapLatest 订阅该流。
    2. 新增 ChatViewModel.switchLocalSession，进入聊天页即切本地 session，并在切换前清空 flushManager。
    3. ensureSessionForCurrentPersona 优先使用 pendingSwitchFilename。
    4. flushManager 改 by lazy；StateManager.restoreState 仅在无会话时兜底恢复。
*   **验证**:
    1. `venv_core/Scripts/python.exe tests/scripts/android/verify_session_isolation.py`

### QR-20260818-ANDROID-SESSION-LIST-PREVIEW Android 会话列表预览跨角色串台 + ChatViewModel 过重 (2026-08-18)
*   **问题描述**: 修复详情页消息串台后，会话列表的『最后一条消息预览』仍串台：Aveline 预览显示卡夫卡的消息，点进去 Aveline 为空；卡夫卡预览不更新。且 ChatViewModel 膨胀到 600+ 行难以维护。
*   **复现步骤**:
    1. 与卡夫卡聊天产生历史消息。
    2. 返回会话列表，查看 Aveline 与卡夫卡的预览行。
    3. 点进 Aveline 查看详情内容，再返回。
*   **预期行为**:
    1. Aveline 预览行显示 Aveline 自己的最后一条消息（或为空）。
    2. 点进 Aveline 的内容与预览一致。
    3. 卡夫卡预览显示其最新消息。
*   **实际行为**:
    1. Aveline 预览行显示卡夫卡的消息，但点进 Aveline 为空。
    2. 卡夫卡预览不更新（不显示最新消息）。
*   **根因**:
    1. 预览归属用了后端全局 active persona（currentPersonaFilename），它只在发消息时才切换；当前查看的 session 与 active persona 不一致时，预览写错 persona。
    2. ChatViewModel 单一职责爆炸，所有跨角色/消息逻辑挤在一个类，难以定位与回归。
*   **修复方案**:
    1. ChatIncomingMessageHandler.updateLastMessagePreview 以当前 sessionId（web_{filename}）反推 persona，反推失败才回退 active persona。
    2. ChatViewModel 服务门面化拆分：ChatSessionController/ChatSessionObserver/ChatSendController/ChatIncomingMessageHandler/ChatTtsController/ChatVoiceInputController，薄壳只做转发。
*   **验证**:
    1. `venv_core/Scripts/python.exe tests/scripts/android/verify_session_isolation.py`

### QR-20260818-02 聊天页拉出侧边栏后按返回键直接退出聊天页而非收起侧边栏 (2026-08-18)
*   **问题描述**: 聊天页右滑呼出侧边栏后，按系统返回键直接退出聊天页返回消息主菜单，而不是先把侧边栏收起。
*   **复现步骤**:
    1. 进入聊天页（ChatScreen）
    2. 在聊天页通过右滑手势呼出侧边栏（PullableNavigationDrawer）
    3. 按系统返回键
*   **预期行为**:
    1. 第一次按返回键先收起侧边栏
    2. 再次按返回键才退出聊天页回消息主菜单
*   **实际行为**:
    1. 按返回键直接退出聊天页，返回消息主菜单，侧边栏未收起
*   **根因**:
    1. 仅依赖 BackHandler 组合顺序：导航到聊天页后，目的地返回回调在导航完成时才注册到 OnBackPressedDispatcher，优先级高于抽屉返回回调。
*   **修复方案**:
    1. MainActivity 中侧边栏可见时调用 navController.enableOnBackPressed(false) 禁用 NavHost 返回处理，关闭侧边栏后重新启用。

### 10.141 进入聊天页消息列表停留在最早位置而非最后聊天位置 (2026-08-18)
*   **问题描述**: 进入聊天页面时，消息列表不会自动定位到最后聊天（最新消息）的位置，而是停留在最开始（最早消息）的位置，用户需要手动下滑才能看到最新消息。
*   **复现步骤**:
    1. 在会话列表点击进入一个历史消息较多的聊天页
    2. 等待消息加载完成
    3. 观察消息列表停留在的位置
*   **预期行为**:
    1. 进入聊天页后消息列表应自动停到最后一条消息（最后聊天的位置）
    2. 切换会话时同样定位到新会话最新消息
*   **实际行为**:
    1. 消息列表停留在列表最顶端（最早的聊天位置），需手动滚动才能看到最新消息
*   **根因**:
    1. 原滚动逻辑 LaunchedEffect(uiState.messages.size) 仅当 firstVisibleIndex >= lastIndex - 1（用户已接近底部）时才滚动到底部；首次进入会话时列表位于顶端（firstVisibleIndex == 0），条件永不满足，故停留在最早消息位置
    2. 逻辑未区分「首次进入会话/消息首次加载完成」与「新消息到达」，缺少一次强制定位到最新消息的步骤
*   **修复方案**:
    1. ChatScreen.kt 新增 positionedToLatest 标记（remember(sessionId) 实现，切换会话自动重置），LaunchedEffect 以 sessionId + messages.size 为 key
    2. 首次定位用 snapshotFlow 等待 LazyColumn 布局出目标项后 scrollToItem(lastIndex) 瞬时跳到最新消息，避免长滚动动画且不受列表尚未布局影响
    3. 新消息到达保留原逻辑：仅用户接近底部时 animateScrollToItem(lastIndex) 平滑跟随，不打断向上翻看历史
*   **验证**:
    1. `进入聊天页消息加载完成后直接停到最后一条消息；切换会话定位到新会话最新消息；向上翻看历史时新消息到达不自动滚动；接近底部时新消息平滑滚动到底。编译交由用户在 Android Studio 执行。`

### 10.142 聊天页呼出侧边栏按返回键仍退出聊天页（enableOnBackPressed + BackHandler 顺序方案无效） (2026-08-18)
*   **问题描述**: 聊天页面右滑呼出侧边栏后，按系统返回键直接退出聊天页回到消息主菜单，而不是先收起侧边栏；上一轮 enableOnBackPressed(false) + BackHandler 组合顺序的修复实测无效。
*   **复现步骤**:
    1. 进入聊天页面
    2. 右滑手势呼出侧边栏
    3. 按系统返回键
*   **预期行为**:
    1. 按返回键应收起侧边栏
    2. 侧边栏关闭后再按返回键才退出聊天页
*   **实际行为**:
    1. 按返回键直接退出聊天页，返回消息主菜单，侧边栏未收起
*   **根因**:
    1. Compose NavHost（2.7.6）返回处理是自身内部的 BackHandler(currentBackStack.size > 1) { popBackStack() }，注册在 NavHost 组合作用域，不经过 NavController 的 onBackPressedCallback
    2. Compose NavHost 从不调用 NavController.setOnBackPressedDispatcher，enableOnBackPressed(false) 控制的 onBackPressedCallback 从未注册到任何 dispatcher，调用该 API 无效（@RestrictTo 隐藏 API）
    3. OnBackPressedDispatcher 纯 LIFO 无优先级，NavHost BackHandler 注册/重注册时机不可控，BackHandler 组合顺序方案不可靠
*   **修复方案**:
    1. MainActivity.kt 用 remember 创建抽屉专用 OnBackPressedCallback（handleOnBackPressed 中 close 抽屉）
    2. LaunchedEffect(drawerState.isVisible)：抽屉打开时 remove()+addCallback 排到 dispatcher 末尾并 isEnabled=true，返回键必先收起侧边栏；关闭时 remove() 放行 NavHost
    3. DisposableEffect(lifecycleOwner) 在组合销毁时移除回调防泄漏
*   **验证**:
    1. `聊天页右滑呼出侧边栏按返回键应收起侧边栏；侧边栏关闭后再按返回键正常退出聊天页。编译交由用户在 Android Studio 执行。`

### P0-38 会话切换瞬间旧角色残留消息导致预览串台与记录闪现 (2026-08-18)
*   **问题描述**: 从有聊天记录的会话切换到无聊天记录的会话时，界面先显示上一个角色的聊天记录，随后刷新才消失；同时某角色列表预览显示了另一个角色的最后一条消息，但点进该角色详情页为空，后端对应会话文件亦无该记录。
*   **复现步骤**:
    1. 进入角色 A（有聊天记录）的会话。
    2. 切换到角色 B（无聊天记录）的会话窗口。
    3. 观察切换瞬间：界面短暂显示角色 A 的聊天记录，之后才清空。
    4. 返回会话列表：角色 B 的预览显示角色 A 的最后一条消息，点进角色 B 详情页却为空。
*   **预期行为**:
    1. 切换会话时界面立即清空，不显示上一个角色的聊天记录。
    2. 列表预览只显示消息真正所属角色的最后一条消息。
*   **实际行为**:
    1. 切换瞬间显示上一个角色的聊天记录，随后刷新才消失。
    2. 角色 B 预览显示角色 A 的最后一条消息，但角色 B 详情页为空。
*   **根因**:
    1. observeMessages 的 flatMapLatest 取消旧 flow 是协作式的，切换瞬间旧会话残留消息仍到达 collect。
    2. 残留消息先写入 uiState.messages 上屏，再触发预览写入。
    3. 预览归属用 getSessionId() 反推，竞态下 currentSession 已是新角色，导致旧角色消息写到新角色预览。
*   **修复方案**:
    1. 预览归属改为优先以消息自身 sessionId 反推 persona（权威），失败才回退当前 sessionId / active persona。
    2. observeMessages 记录 expectedSessionId，切换时立即清空 messages，collect 校验归属丢弃残留消息（不上屏不写预览）。
*   **验证**:
    1. `venv_core/Scripts/python.exe tests/scripts/android/verify_session_isolation.py（39/39 通过）`

### ANDROID-CHAT-BRANCHING-001 聊天页缺少传统 AI 前端的消息编辑与回复版本分支 (2026-08-18)
*   **问题描述**: 用户无法重新生成指定 AI 回复、编辑历史请求，旧版本也无法保留和切换。
*   **复现步骤**:
    1. 进入 Android 聊天页并点击任意消息
    2. 检查消息操作按钮
    3. 尝试重新生成 AI 回复或编辑用户请求
    4. 尝试返回此前的请求或回复版本
*   **预期行为**:
    1. AI 回复可以重新生成并显示版本序号
    2. 用户请求可以编辑并形成新分支
    3. 左右切换版本时后续对话和模型上下文同步切换
*   **实际行为**:
    1. 操作区仅有播放、复制和删除
    2. 旧重新生成能力会删除旧回复且只支持最后一轮
    3. 消息存储没有分支结构
*   **根因**:
    1. 本地消息模型为单链表
    2. 客户端没有向后端传递当前选择的分支上下文
*   **修复方案**:
    1. 使用父消息和激活同级版本构建持久化消息树
    2. 增加编辑、重新生成和版本导航 UI
    3. 生成请求显式携带当前激活路径
*   **验证**:
    1. `verify_chat_message_branching.py 静态回归检查通过`
    2. `Android Studio 构建后验证 Room 3 到 4 迁移、编辑、重生成及版本切换`

### P0-Android-Image-Load Android 端聊天图片/表情包显示为破图占位 (2026-08-19)
*   **问题描述**: Android 聊天中后端下发的图片和表情包显示为带感叹号的破图占位，用户上传图片也不显示。
*   **复现步骤**:
    1. 打开 Android 应用并进入任意会话
    2. 触发 AI 发送图片/表情包，或用户主动上传图片
    3. 观察消息气泡中的图片区域
*   **预期行为**:
    1. 图片/表情包正常渲染
    2. 用户上传图片发送后能在聊天记录中显示
*   **实际行为**:
    1. 图片区域显示破图占位（灰色图片图标 + 感叹号）
*   **根因**:
    1. 后端返回相对路径 /output/image/...，Coil 无法解析缺少 host 的 URL
    2. 未配置全局 Coil ImageLoader，图片请求无统一鉴权与缓存
    3. 上传接口仅返回 file_path，Android 解析 file_url 为空
*   **修复方案**:
    1. 新增 ImageUrlResolver 统一拼接后端 base URL
    2. MessageBubble 中解析相对图片地址
    3. AvelineApplication 配置 Coil 全局 ImageLoader
    4. 后端 upload_file 同时返回 file_url
*   **验证**:
    1. `tests/scripts/android/verify_image_url_resolution.py`
    2. `ImageUrlResolverTest.kt`
