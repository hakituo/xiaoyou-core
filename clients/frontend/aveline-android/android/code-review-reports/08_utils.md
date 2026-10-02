# Utils 工具类代码审查报告

## 审查概览

本次审查覆盖 `clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/utils/` 目录下全部 15 个 Kotlin 文件，重点关注性能、内存泄漏、安全性、无障碍、错误处理、重试/超时、国际化、DeepLink 合法性、数据导出、状态管理、可维护性等维度。

### 问题统计

| 文件 | 🔴严重 | 🟠中等 | 🟡轻微 | 小计 |
|------|-------|-------|-------|------|
| AccessibilityExtensions.kt | 0 | 1 | 3 | 4 |
| AccessibilityManager.kt | 1 | 3 | 2 | 6 |
| CoilImageLoader.kt | 0 | 2 | 2 | 4 |
| CrashHandler.kt | 2 | 3 | 2 | 7 |
| DataExportManager.kt | 2 | 3 | 1 | 6 |
| DeepLinkHandler.kt | 1 | 2 | 1 | 4 |
| ErrorHandler.kt | 0 | 2 | 2 | 4 |
| HapticFeedbackManager.kt | 0 | 2 | 2 | 4 |
| InputValidator.kt | 1 | 3 | 2 | 6 |
| LanguageManager.kt | 0 | 2 | 2 | 4 |
| PerformanceMonitor.kt | 1 | 3 | 2 | 6 |
| RetryUtils.kt | 1 | 2 | 1 | 4 |
| SecurityManager.kt | 2 | 3 | 1 | 6 |
| ShareUtils.kt | 0 | 2 | 2 | 4 |
| StateManager.kt | 1 | 3 | 1 | 5 |
| **合计** | **12** | **36** | **26** | **74** |

---

## 逐文件审查

### AccessibilityExtensions.kt

#### 问题1: [🟠中等] 字符串硬编码严重缺失国际化
- 位置: AccessibilityExtensions.kt:69, 86, 103, 120, 161, 185, 202, 219, 255, 271, 280-299
- 问题描述: `stateDescription` 设定的 "已开启/已关闭"、"已选中/未选中"、"当前页面/切换到此页面"、"必填"、"已禁用"、"已展开/已折叠" 等字符串均为硬编码中文。LanguageManager 支持英文/中文切换，但这些无障碍文案不会随语言变化。对英文用户/TalkBack 用户来说这些字符串无法被读出正确含义。
- 建议方案: 将这些字符串提取到 `res/values/strings.xml` 和 `res/values-en/strings.xml`，由于 `Modifier.semantics {}` 是非 composable 上下文，需要在使用处通过 `stringResource(R.string.xxx)` 传入，或改为 `@Composable fun` 形式返回 `Modifier`。注意 `getAccessibilityStateDescription` 已是 @Composable 但内部仍未使用 `stringResource`。

#### 问题2: [🟡轻微] accessibilityHeading 未实现 heading 语义
- 位置: AccessibilityExtensions.kt:141-146
- 问题描述: 注释说"在 Compose 1.5+ 可以使用 heading() 语义"，但代码只设置了 `contentDescription`，未调用 `heading()` 语义。TalkBack 无法识别该元素为标题，无法用"标题导航"手势跳转，违反 WCAG 2.4.10。
- 建议方案: 在 `semantics` 块中追加 `heading()`，并要求项目使用 Compose UI 1.5+。如 `this.semantics { contentDescription = description; heading() }`。

#### 问题3: [🟡轻微] accessibilitySlider 的 valueRange 参数被忽略
- 位置: AccessibilityExtensions.kt:196-204
- 问题描述: `valueRange` 参数被 `@Suppress("UNUSED_PARAMETER")` 标记，未实际使用。无障碍描述只读出当前值 `"${value.toInt()}"`，TalkBack 用户无法知道这是 0-100 还是 0-1000，体验严重不足。
- 建议方案: 在描述中加入范围信息，例如 `"$description: ${value.toInt()}, 范围 ${valueRange.start.toInt()} 至 ${valueRange.endInclusive.toInt()}"`。同时考虑使用 `ProgressBarRangeInfo` 语义。

#### 问题4: [🟡轻微] minimumTouchTargetSize 类型语义不清
- 位置: AccessibilityExtensions.kt:170-172
- 问题描述: `minSize: Int = 48` 看似数字，实际通过 `minSize.dp` 转 Dp，但调用方很难判断单位。一旦传入 `48f` 或 `48.px` 会编译错误或运行错误。WCAG 2.5.5 标准是 48dp，但函数签名未体现。
- 建议方案: 改为 `fun Modifier.minimumTouchTargetSize(minSize: Dp = 48.dp): Modifier`，明确类型语义并避免每调用一次都做 `.dp` 转换。

---

### AccessibilityManager.kt

#### 问题1: [🔴严重] isHighContrastEnabled 逻辑错误,夜间模式 != 高对比度
- 位置: AccessibilityManager.kt:97-112
- 问题描述: 在 SDK >= R 分支中,`isHighContrastEnabled` 通过 `context.resources.configuration.isNightModeActive && (颜色反转设置==1)` 判断。但夜间模式(Night Mode)与高对比度(High Contrast)是完全不同的无障碍特性:用户可能开启了夜间模式但不需要高对比度,也可能开启了高对比度但未开夜间模式。这会导致 UI 在仅开启夜间模式时错误地启用"高对比度支持"分支,样式错乱。另外 SDK < R 分支只检查颜色反转,而 `ACCESSIBILITY_DISPLAY_DALTONIZER_ENABLED`(色彩校正)也是高对比度相关特性,未覆盖。
- 建议方案: 区分两种特性。应只通过 `Settings.Secure.ACCESSIBILITY_DISPLAY_INVERSION_ENABLED` 和 `ACCESSIBILITY_DISPLAY_DALTONIZER_ENABLED` 判断高对比度,移除 `isNightModeActive` 与运算。如果项目需要单独跟踪夜间模式,应作为独立字段 `isNightMode`,不与高对比度混用。

#### 问题2: [🟠中等] 变量名与类名同名导致 shadowing 风险
- 位置: AccessibilityManager.kt:49-53
- 问题描述: 类名为 `AccessibilityManager`,内部又声明 `private val accessibilityManager: AccessibilityManager?`(此处引用的是 `android.view.accessibility.AccessibilityManager`)。同名属性遮蔽了类名,IDE 警告,后续维护者容易混淆"accessibilityManager"指代的是类还是属性。在 `init` 或扩展函数中尤其危险。
- 建议方案: 重命名属性,例如 `private val systemAccessibilityService: android.view.accessibility.AccessibilityManager?`,并显式 import 全限定名以避免歧义。

#### 问题3: [🟠中等] isReduceMotionEnabled 浮点比较不安全且未覆盖全部动画开关
- 位置: AccessibilityManager.kt:117-123
- 问题描述: (1) `Settings.Global.ANIMATOR_DURATION_SCALE == 0.0f` 用 `==` 比较浮点数,而 `Settings.Global.getFloat` 默认值返回 1.0f,实际设备可能返回极小但不为 0 的值(如 0.0 因浮点精度问题)。应使用 `<= 0.0f` 或 `< 0.5f` 阈值。(2) Android 有三个动画缩放设置:`ANIMATOR_DURATION_SCALE`、`TRANSITION_ANIMATION_SCALE`、`WINDOW_ANIMATION_SCALE`,任一为 0 都表示用户希望减少动画,只检查第一个不全面。
- 建议方案: 改为 `animatorScale == 0f || transitionScale == 0f || windowScale == 0f`,并使用 `<= 0f` 容错。

#### 问题4: [🟠中等] getRecommendedAnimationDuration 返回 0 可能导致 Compose 崩溃
- 位置: AccessibilityManager.kt:159-165
- 问题描述: 当 `shouldReduceAnimations()` 为 true 时直接返回 0。Compose 的 `AnimationSpec`/`tween(durationMillis = ...)` 在很多 API 中要求 `durationMillis > 0`,传 0 会抛 `IllegalArgumentException: Duration must be positive`。这会让"减少动画"开关变成崩溃开关。
- 建议方案: 返回 1(1ms,几乎瞬时但合法)而非 0;或在文档中明确说明此返回值不能直接传给 Compose 动画 API,应由调用方判断后跳过动画。

#### 问题5: [🟡轻微] isTalkBackEnabled 与 isScreenReaderEnabled 逻辑重叠
- 位置: AccessibilityManager.kt:81-92
- 问题描述: 两个函数都依赖 `isTouchExplorationEnabled`,但 `isScreenReaderEnabled` 额外检查 `it.isEnabled`。实际上 TalkBack 就是 Android 的屏幕阅读器,这两个概念在 Android 上是等价的。重复字段让调用方不知道该用哪个,且 `AccessibilityState` 同时持有两个字段(`isTalkBackEnabled` 和 `isScreenReaderEnabled`)会得出矛盾的组合(例如 TalkBack=false 但 ScreenReader=true),让 `needsAccessibilitySupport` 判断混乱。
- 建议方案: 合并为单一 `isScreenReaderEnabled`,从 `AccessibilityState` 中移除 `isTalkBackEnabled` 字段,或在文档中明确两者的语义差异(如果确有差异)。

#### 问题6: [🟡轻微] calculateLuminance 使用 Math.pow 效率低
- 位置: AccessibilityManager.kt:201-215
- 问题描述: 自定义 `Float.pow` 扩展内部调用 `Math.pow(this.toDouble(), exp.toDouble()).toFloat()`,涉及 Double 装箱和双重转换。`calculateLuminance` 在每次 `calculateContrastRatio` 时被调用 2 次(对 r/g/b 各一次共 6 次),如果用在主题切换/对比度检查的热路径上开销明显。Kotlin 标准库已有 `kotlin.math.pow(Float, Float): Float`,无需自造。
- 建议方案: 删除自定义 `Float.pow` 扩展,直接 `import kotlin.math.pow` 并使用 `r.pow(2.4f)`。

---

### CoilImageLoader.kt

#### 问题1: [🟠中等] 内存缓存大小硬编码 50MB,未考虑低内存设备
- 位置: CoilImageLoader.kt:31, 47-51
- 问题描述: `MEMORY_CACHE_SIZE = 50L * 1024 * 1024` 固定 50MB。在低端 Android 设备(堆内存可能仅 192MB-256MB)上,ImageLoader 占用 50MB 堆内存会导致频繁 GC 甚至 OOM。Coil 官方推荐使用 `maxSizePercent(0.25)` 基于可用内存动态调整。同样,磁盘缓存 100MB 在存储空间紧张的小设备上也偏大。
- 建议方案: 改用 `MemoryCache.Builder(context).maxSizePercent(0.25)`;磁盘缓存可保留 100MB 但应通过 `ActivityManager.MemoryInfo` 检查低内存设备时降到 50MB。

#### 问题2: [🟠中等] clearMemoryCache/clearDiskCache 依赖外部传入 ImageLoader,职责混乱
- 位置: CoilImageLoader.kt:100-118
- 问题描述: `CoilImageLoader` 是 `@Singleton` 且唯一职责是创建/管理 ImageLoader,但 `clearMemoryCache(imageLoader)`、`clearDiskCache(imageLoader)`、`getCacheStats(imageLoader)` 都要求调用方传入 ImageLoader。这意味着调用方需要自己持有 ImageLoader 引用,与 Singleton 模式矛盾。如果调用方传入了非本类创建的 ImageLoader,行为不可预期。同时这会让缓存清理的入口分散,难以统一管理生命周期。
- 建议方案: 在 `CoilImageLoader` 内部 `by lazy` 持有创建好的 ImageLoader 实例(或通过 Hilt 提供单例 ImageLoader),所有方法直接操作该实例,无需外部传参。

#### 问题3: [🟡轻微] crossfade 重复调用,第二行覆盖第一行
- 位置: CoilImageLoader.kt:72-73
- 问题描述: `.crossfade(true)` 紧接 `.crossfade(300)`,后者会覆盖前者的开关状态并设置 300ms 时长。第一行 `.crossfade(true)` 是无用代码,造成阅读歧义(维护者会疑惑:这里到底是 300ms 还是默认时长?)。
- 建议方案: 删除 `.crossfade(true)`,只保留 `.crossfade(300)`,并加注释说明 300ms 是经过 UX 调优的过渡时长。

#### 问题4: [🟡轻微] 占位图/错误图使用系统资源,UI 不一致
- 位置: CoilImageLoader.kt:75, 77
- 问题描述: `android.R.drawable.ic_menu_report_image` 和 `android.R.drawable.ic_menu_gallery` 是系统资源,在不同 Android 版本/OEM 定制系统上外观差异巨大(MIUI、EMUI、原生 Android 完全不同),且部分系统已废弃这些 drawable。在一个有自己设计语言的产品里出现系统图标,会让用户觉得"未完成"。
- 建议方案: 在 `res/drawable/` 下提供自己的 `placeholder_image.xml` 和 `error_image.xml`(可用 vector drawable),保持品牌一致性。

---

### CrashHandler.kt

#### 问题1: [🔴严重] uncaughtException 中同步执行 IO,可能 ANR 或被默认 handler 抢先终止
- 位置: CrashHandler.kt:50-59
- 问题描述: `uncaughtException` 在崩溃线程上同步调用 `saveCrashLog(throwable)`,该函数内部执行 `FileWriter`+`PrintWriter`+`getPackageInfo` 等磁盘 IO 和 PackageManager 调用,在低端设备上可能耗时数百毫秒甚至数秒。如果崩溃发生在主线程,这段同步 IO 会变成 ANR,系统可能在日志写完前就 kill 进程。另外,`defaultHandler?.uncaughtException(...)` 之后系统会终止进程,如果 `saveCrashLog` 抛出异常(被 catch 但写入失败),日志会丢失而无任何告警。
- 建议方案: (1) 将崩溃信息先写入内存(如一个 ring buffer),由独立的崩溃恢复进程或 `ProcessLifecycleOwner` 在下次启动时落盘;(2) 或使用 `java.util.logging.FileHandler` 配合 async handler;(3) 至少应在 `saveCrashLog` 内捕获 `Throwable` 而非 `Exception`,因为磁盘 IO 可能抛 `OutOfMemoryError`。同时建议引入内存映射文件(MappedByteBuffer)写入,避免被进程终止打断。

#### 问题2: [🔴严重] saveCrashLog 的 catch 块完全静默吞异常,无任何兜底
- 位置: CrashHandler.kt:100-102
- 问题描述: `catch (e: Exception) { // 忽略保存崩溃日志时的错误 }`。崩溃日志是事后定位问题的唯一线索,如果保存失败却完全静默,开发者永远不知道日志丢失。`uncaughtException` 中即使无法写文件,也应该有兜底:例如写入 `Log.e`(会被 logcat 捕获,如果设备开启了 logcat 持久化可保留)、写入 SharedPreferences(轻量 IO 更可能成功)、或至少通过 `android.util.Log.wtf` 写一条简短记录。
- 建议方案: catch 块内调用 `Log.e("CrashHandler", "Failed to save crash log", e)` 至少保留 logcat 痕迹;并尝试 `Process.killProcess` 之前用 `System.err.println` 输出简短堆栈到 stderr。

#### 问题3: [🟠中等] SimpleDateFormat 非线程安全但被多线程使用
- 位置: CrashHandler.kt:30
- 问题描述: `private val dateFormat = SimpleDateFormat(...)` 是实例字段,而 `uncaughtException` 可能在任意线程触发(工作线程崩溃、协程崩溃等)。`SimpleDateFormat` 是非线程安全的,并发访问会导致输出乱码或 `NumberFormatException`。虽然崩溃是低频事件,但一旦在多线程同时崩溃(如协程调度器抛异常时多个协程同时挂掉)就会触发。
- 建议方案: 改为方法内局部变量 `SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.getDefault()).format(Date())`,或用 `DateTimeFormatter`(java.time,API 26+,低端用 desugaring)。每次创建开销远小于线程安全风险。

#### 问题4: [🟠中等] 没有日志数量/大小限制,可能耗尽存储
- 位置: CrashHandler.kt:36-40, 147-152
- 问题描述: `crashLogDir` 没有任何清理策略,`getCrashLogs()` 每次都重新 listFiles。如果应用有崩溃循环(启动崩溃 -> 重启 -> 再崩溃),短时间内会生成大量日志文件,每个文件包含完整设备信息+堆栈,可能数 KB 到数十 KB,日积月累会占用兆级空间,且 `getCrashLogs()` 列表越来越慢。`exportCrashLog` 也没有大小检查。
- 建议方案: 在 `init()` 或 `saveCrashLog` 末尾调用 `pruneOldLogs(maxCount = 20, maxAgeDays = 7)`,保留最近 20 条或 7 天内的日志,其余删除。同时在 `getCrashLogs()` 加缓存(由 `saveCrashLog` 失效)。

#### 问题5: [🟠中等] init() 没有防止重复调用,defaultHandler 会被覆盖
- 位置: CrashHandler.kt:42-48
- 问题描述: `init()` 直接 `defaultHandler = Thread.getDefaultUncaughtExceptionHandler()` 然后 `setDefaultUncaughtExceptionHandler(this)`。如果 `init()` 被调用两次(例如 Application.onCreate 误调 + 某些初始化库再调),第二次的 `defaultHandler` 会变成 `this`(第一次设置的 CrashHandler 自身),形成自引用。下次崩溃时 `defaultHandler.uncaughtException` 会再次进入 `this.uncaughtException`,造成无限递归。
- 建议方案: 在 `init()` 开头加 `if (defaultHandler != null) return` 或 `if (Thread.getDefaultUncaughtExceptionHandler() === this) return` 幂等保护。

#### 问题6: [🟡轻微] 异常链循环未做防护
- 位置: CrashHandler.kt:88-94
- 问题描述: `while (cause != null) { ... cause = cause.cause }` 没有深度限制。虽然标准库的 Throwable 一般不会有循环引用,但第三方库或自定义异常重写 `getCause()` 时可能引入循环(已有真实案例)。一旦循环,崩溃日志会无限增长直到 OOM,在崩溃处理路径上引发二次崩溃。
- 建议方案: 加入最大深度限制,如 `var depth = 0; while (cause != null && depth < 50) { ...; depth++; cause = cause.cause }`。

#### 问题7: [🟡轻微] readCrashLog 一次性读取整个文件,大日志可能 OOM
- 位置: CrashHandler.kt:164-170
- 问题描述: `file.readText()` 一次性把整个日志读入内存。如果某个崩溃日志因循环引用或超长堆栈达到数十 MB(完全可能,尤其是含 native crash 的日志),在 UI 线程展示时直接 OOM。`getLatestCrashLog()` 调用方很可能在 ViewModel 里调 `readCrashLog`,无法保证不在主线程。
- 建议方案: 加 `maxSize` 参数,超过阈值(如 1MB)时只读前 N 行并附"..."截断提示。或改为流式读取按行展示。

---

### DataExportManager.kt

#### 问题1: [🔴严重] 一次性加载所有会话和消息到内存,大数据量必然 OOM
- 位置: DataExportManager.kt:86-124
- 问题描述: `exportChatHistory` 通过 `sessionDao.observeSessions().first()` 取出所有会话,然后对每个 session 调用 `messageDao.getRecentMessages(session.id)`(无 limit)取出该会话全部消息,全部 map 成 `SessionExport`/`MessageExport` 对象常驻内存,再 `json.encodeToString(exportData)` 生成完整 JSON 字符串,再 `.toByteArray()` 生成完整字节数组,最后 `output.write(...)`。整个链条内存峰值 = (对象树) + (JSON 字符串) + (字节数组),约为数据原始大小的 5-10 倍。一个有 1000 条会话、每会话 100 条消息(每条 1KB)的普通用户,原始数据约 100MB,内存峰值可能达 500MB+,必然 OOM。
- 建议方案: 改用流式写入。用 `Json.encodeToStream(ExportData.serializer(), output, exportData)` 配合 kotlinx-serialization 流式 API;或更彻底地用 `BufferedWriter` 逐会话/逐消息写入,手动控制 JSON 结构。同时 `messageDao.getRecentMessages(session.id)` 应加分页 limit(如 500),并在导出 UI 上让用户选择导出范围(最近 7 天/30 天/全部)。

#### 问题2: [🔴严重] 使用已废弃的 Environment.getExternalStoragePublicDirectory,Android 10+ 无 WRITE_EXTERNAL_STORAGE 权限会失败
- 位置: DataExportManager.kt:117-120, 220-223
- 问题描述: `Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)` 在 Android 10 (API 29) 起被标记为 deprecated,Android 11+ 对外部存储做了严格限制(Scoped Storage)。在 targetSdk >= 29 的应用上,直接 `File(downloadsDir, fileName)` 写入公共 Downloads 目录会抛 `FileNotFoundException`(Permission denied),除非声明 `requestLegacyExternalStorage=true` 或申请 `WRITE_EXTERNAL_STORAGE`(Android 11+ 即使声明也无效)。当前代码完全没有权限检查,失败时只能从 `Result.failure(e)` 兜底,用户体验差。
- 建议方案: 改用 `MediaStore.Downloads` 通过 ContentResolver 插入记录获取 Uri,Android 10+ 自动处理 scoped storage;或写入 `context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)`(应用私有目录,无需权限),再用 `FileProvider` 分享给用户。

#### 问题3: [🟠中等] importData/clearAllData 大量 TODO 但函数标记为可用
- 位置: DataExportManager.kt:160-199, 256-268
- 问题描述: `importData` 第 184-193 行有 `// TODO: 清除现有会话` 和 `// TODO: 创建会话和消息`,实际逻辑未实现,但函数签名声明 `suspend fun importData(...): Result<Int>` 完整且返回 `Result.success(importedCount)`。调用方(如设置页"导入数据"按钮)会以为导入成功,实际上数据并未写入数据库,只是设置被改了。`clearAllData` 同样只有 `// TODO: 实现清除逻辑`,但 `appPreferences.clearAll()` 已执行,会话/消息仍在,用户以为"清除所有数据"成功实际只清了设置。这是数据完整性灾难。
- 建议方案: 在 TODO 完成前,函数应抛 `UnsupportedOperationException("Import not implemented")` 或返回 `Result.failure(...)`,绝不能返回 success。或者直接将函数标记为 `internal`/不暴露给 UI。

#### 问题4: [🟠中等] 时间戳用 Date(timestamp).toString(),格式不可解析且不可读
- 位置: DataExportManager.kt:95-101, 109
- 问题描述: `Date(session.createdAt).toString()` 输出类似 `Thu Oct 05 14:48:20 CST 2023`,依赖 JVM 默认时区和 locale,跨设备/跨时区导入时无法还原原始时间。导出文件作为用户备份/迁移数据的核心载体,时间格式不可解析等于数据损坏。`exportTime = Date().toString()` 同样问题。
- 建议方案: 使用 ISO 8601 格式,如 `SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date(session.createdAt))` 或 `java.time.Instant.ofEpochMilli(session.createdAt).toString()`(API 26+ 或 desugar)。同时保留 epoch 毫秒数值作为 `createdAtMs` 字段便于程序解析。

#### 问题5: [🟠中等] importSettings 未验证字段合法性,可注入非法 URL
- 位置: DataExportManager.kt:204-211
- 问题描述: `appPreferences.backendUrl = settings.backendUrl` 直接写入,未调用 `InputValidator.validateBackendUrl`。攻击者可构造恶意导出文件,将 `backendUrl` 设为内网地址(`http://192.168.1.1/admin`)或非 HTTP 协议(`file:///data/...`),用户导入后所有请求被重定向到攻击者控制的服务器(SSRF/中间人攻击)。`selectedVoiceId` 同样可注入特殊字符。
- 建议方案: 导入前对每个字段调用对应 `InputValidator.validate*`,`validateBackendUrl` 还应增加 SSRF 防护(禁止 127.0.0.1/10.x/192.168.x/172.16.x 等私有 IP,除非是 localhost 显式允许)。

#### 问题6: [🟡轻微] 版本校验过于严格,未来升级困难
- 位置: DataExportManager.kt:174-176
- 问题描述: `if (importData.version > 1) throw Exception("Unsupported export version: ${importData.version}")`。导出格式一旦迭代(增加字段、改字段类型),version 必然升到 2,旧版本应用无法打开,但代码直接抛异常不返回降级提示。更糟的是异常消息没有降级方案,用户无法理解。
- 建议方案: 改为 `if (importData.version > CURRENT_VERSION) return Result.failure(UnsupportedVersionException(importData.version, CURRENT_VERSION))`,自定义异常类提供"建议升级应用"等可读消息。同时考虑前向兼容:version 2 的文件如果能解析,允许以降级方式导入(忽略未知字段)。

---

### DeepLinkHandler.kt

#### 问题1: [🔴严重] handleIntent 未对 host/path 做白名单校验,可路由到任意 screen
- 位置: DeepLinkHandler.kt:80-107, 139-152
- 问题描述: `handleIntent` 只检查 `uri.scheme == "aveline"`,然后调用 `parseUri` 取 `host ?: path?.removePrefix("/")`,再 `determineScreen(path)` 中 `else -> "chat"`。这意味着 `aveline://anything`、`aveline:///../../etc`、`aveline://evil.com` 都会被解析为合法深链并设置到 `_pendingDeepLink`。攻击者构造恶意网页/二维码诱导用户点击 `aveline://evil`,应用会无提示地跳转到默认 chat 页面并执行 prefillText 等动作。`determineAction` 中 `params.containsKey("text") -> "prefill"` 让攻击者能预填任意文本到聊天框,可能导致用户误发送。`InputValidator.validateDeepLink` 存在,但 `DeepLinkHandler` 根本没调用它,两个类逻辑割裂。
- 建议方案: (1) 在 `parseUri` 第一步调用 `InputValidator.validateDeepLink(uri)`,校验失败返回 null;(2) `determineScreen` 中未知路径应返回 null 而非 "chat",让 `handleIntent` 拒绝;(3) 对 `prefillText` 做长度限制和 `containsDangerousContent` 检查;(4) `_pendingDeepLink` 设置前应记录来源(是否来自外部 Intent)用于审计。

#### 问题2: [🟠中等] parseUri 的 host/path 回退逻辑可被绕过
- 位置: DeepLinkHandler.kt:99
- 问题描述: `val path = uri.host ?: uri.path?.removePrefix("/") ?: ""`。这相当于"如果没 host 就用 path",但深链规范应该 `aveline://<host>/<path>`。攻击者可构造 `aveline:///chat?text=xxx`(host 为空,path 为 `/chat`),绕过基于 host 的过滤。或者 `aveline://chat/settings`(host=chat,path=settings),被解析为 path=chat,而真正的 path 段被忽略,导致路由错位。
- 建议方案: 严格区分 `host` 和 `pathSegments`,不要互相回退。规范深链格式为 `aveline://<host>`(host 即目标页面),不存在 path,只接受 query 参数。校验时 `host` 必须非空且在白名单内。

#### 问题3: [🟠中等] determineAction 的 path 参数被显式忽略,逻辑不完整
- 位置: DeepLinkHandler.kt:127-134
- 问题描述: `determineAction(@Suppress("UNUSED_PARAMETER") path: String, params: Map<String, String>)` 标记 `path` 为未使用,完全靠 params 推断 action。这导致 `aveline://shop` 和 `aveline://chat` 在没有参数时 action 都是 "navigate",无法区分"打开商店"和"打开聊天"。后续若要根据不同 screen 执行不同 action(如 shop 打开后自动加载商品列表),无法实现。
- 建议方案: action 应结合 path 判断,例如 `when(path) { PATH_CHAT -> if (params.containsKey("text")) "prefill" else "navigate"; PATH_SHOP -> if (params.containsKey("item_id")) "open_item" else "navigate"; ... }`。

#### 问题4: [🟡轻微] _pendingDeepLink 无去重/防重放机制
- 位置: DeepLinkHandler.kt:71, 88-92
- 问题描述: `handleIntent` 每次都把解析结果设到 `_pendingDeepLink.value`,即使同一个 Intent 被处理两次(如 Activity 重建时 `onNewIntent` + `onCreate` 都触发)也会重复触发。调用方消费后必须记得调 `clearPendingDeepLink()`,但 StateFlow 没有内置的"消费一次即失效"语义,容易导致一次深链被处理多次(重复跳转、重复 prefill)。
- 建议方案: 改用 `Channel<DeepLinkData>(Channel.BUFFERED)` 或 `SharedFlow` 配合 `replay = 0`,调用方 `collect` 时即消费,自动失效。或保留 StateFlow 但加入 `consume(): DeepLinkData?` 方法,内部读取后立即清空。

---

### ErrorHandler.kt

#### 问题1: [🟠中等] 429 重试未解析 Retry-After header,5xx 重试缺乏退避
- 位置: ErrorHandler.kt:101-104, 137-146, 152-159
- 问题描述: HTTP 429 (Too Many Requests) 标准上必须由服务器通过 `Retry-After` header 告诉客户端等多久,但 `parseHttpException` 中 429 直接返回固定 `retryable=false`。`isRetryable` 又对 429 强制返回 true(因为 `code in listOf(429, 500, 502, 503, 504)`),逻辑矛盾:HttpError 的 `retryable=false` 但 `isRetryable` 返回 true,调用方无所适从。`getRetryAfterSeconds` 永远返回固定的 5 秒,无论服务器要求等多久。这会导致:(1) 不尊重服务器的退避要求,可能被服务器封禁;(2) 5xx 错误也用固定 5 秒重试,没有指数退避,可能加剧服务器压力。
- 建议方案: 在 `parseHttpException` 中从 `HttpException.response().headers()` 读取 `Retry-After`,转换为秒数存入 `HttpError.retryAfterSeconds`。`isRetryable` 应直接返回 `error.retryable`,不再硬编码 429/5xx 列表。5xx 的 `retryAfterSeconds` 应由调用方配合 `RetryUtils` 做指数退避,而非固定值。

#### 问题2: [🟠中等] 错误消息硬编码中文,未国际化
- 位置: ErrorHandler.kt:67-74, 87-113, 119-130
- 问题描述: `"无法连接到服务器,请检查网络连接"`、`"请求参数错误"`、`"未授权,请重新登录"` 等消息均为硬编码中文。`LanguageManager` 支持英文,但 `ErrorHandler` 不响应语言切换,英文用户看到中文错误消息。同时 `getErrorMessage` 直接返回这些字符串给 UI 层,UI 层无法做本地化替换(因为已经定了语言)。
- 建议方案: 将消息改为 error code/枚举(如 `NetworkError(MessageCode.NETWORK_DISCONNECTED)`),由 UI 层通过 `stringResource(code.resId)` 渲染。或在 `ErrorHandler` 注入 `@ApplicationContext` 后通过 `context.getString(R.string.xxx)` 取值(但要注意 ApplicationContext 在 Configuration 变化时不会自动更新)。

#### 问题3: [🟡轻微] SecurityException -> PermissionError(permission = "unknown") 信息丢失
- 位置: ErrorHandler.kt:75-77
- 问题描述: 任何 `SecurityException` 都被映射为 `PermissionError(permission = "unknown")`,丢失了具体权限信息。`SecurityException.message` 通常包含被拒绝的具体操作(如 `"Permission Denial: ... requires android.permission.CAMERA"`),解析后可提取出权限名展示给用户("缺少相机权限")。
- 建议方案: 用正则从 `throwable.message` 中提取 `android.permission.XXX`,提取失败时回退到 "unknown"。

#### 问题4: [🟡轻微] 5xx 错误消息过于笼统,无法区分 500/502/503/504
- 位置: ErrorHandler.kt:105-108
- 问题描述: 500-599 全部返回 `"服务器错误,请稍后重试"`,但 502 (Bad Gateway) 通常是网关问题、503 (Service Unavailable) 通常是维护中、504 (Gateway Timeout) 通常是上游超时,处理方式不同(504 可重试,503 可能需要等更久)。用户和开发者都无法从消息区分真实原因。
- 建议方案: 至少区分 500/502/503/504,例如 503 显示"服务维护中,请稍后再试"、504 显示"网关超时,请检查网络"。同时保留 `code` 字段供调用方判断。

---

### HapticFeedbackManager.kt

#### 问题1: [🟠中等] performSuccess 在 SDK>=Q 用 EFFECT_TICK,语义错误
- 位置: HapticFeedbackManager.kt:193-209
- 问题描述: `performSuccess` 在 SDK >= Q 时使用 `VibrationEffect.createPredefined(VibrationEffect.EFFECT_TICK)`。但 `EFFECT_TICK` 是"滴答"反馈(用于滑块/滚动微反馈),而 `performTick()` 也用 `EFFECT_TICK`。这导致 SUCCESS 和 TICK 在 Android 10+ 上感受完全相同,失去了"成功"的语义。Android 文档建议成功反馈用 `EFFECT_HEAVY_CLICK` 或自定义 waveform(双击模式)。
- 建议方案: SUCCESS 应使用 `EFFECT_DOUBLE_CLICK`(类似"咔哒-咔哒"的成功确认感),或保留 waveform fallback 的 `longArrayOf(0, 10, 50, 10)` 作为统一行为(在 SDK >= Q 也优先用 waveform 保证一致性)。

#### 问题2: [🟠中等] 公开 API 重复,light()/medium()/... 与 performHapticFeedback(type) 职责重叠
- 位置: HapticFeedbackManager.kt:73-158
- 问题描述: `performHapticFeedback(type)` 通过 when 分发到 `performLight/Medium/...`,而 `light()/medium()/...` 8 个公开方法又直接调 `performLight()` 等。结果是一个反馈动作有两条调用路径,且 `light()` 只检查 `isHapticEnabled()` 不检查 `hasVibrator()`,而 `performHapticFeedback(type)` 检查了两者。调用方用 `light()` 时即使设备无 vibrator 也会执行后续逻辑(虽然 `vibrator?.vibrate` 安全,但多了一次状态判断)。
- 建议方案: 移除 `light()/medium()/...` 8 个公开方法,统一通过 `performHapticFeedback(HapticFeedbackType.LIGHT)` 调用。如需简短调用,可定义扩展函数 `fun HapticFeedbackManager.light() = performHapticFeedback(HapticFeedbackType.LIGHT)` 作为语法糖,但内部统一走 `performHapticFeedback` 的双重检查路径。

#### 问题3: [🟡轻微] 废弃 API 用法不一致,performWarning 未用 VibrationEffect
- 位置: HapticFeedbackManager.kt:231-243
- 问题描述: `performWarning` 在 SDK < O 时直接 `vibrator?.vibrate(longArrayOf(0, 50, 100, 50), -1)`(废弃 API),而在 SDK >= O 时用了 `VibrationEffect.createWaveform`。但 SDK >= Q 时未使用 predefined effect(如 `EFFECT_HEAVY_CLICK`)优化,所有 O+ 设备都用 waveform,与 `performTick`/`performClick` 在 Q+ 优先 predefined 的风格不一致。
- 建议方案: 统一风格,所有 `perform*` 在 SDK >= Q 优先用 `createPredefined`(WARNING 可用 `EFFECT_HEAVY_CLICK`),Q 以下用 waveform。

#### 问题4: [🟡轻微] vibrator 在构造时获取,即使 hasVibrator()=false 也持有对象
- 位置: HapticFeedbackManager.kt:40-45
- 问题描述: `vibrator` 在 init 时通过 `getSystemService` 获取,即使设备没有振动器(`hasVibrator() == false`)也会持有 Vibrator 对象引用。虽然 Vibrator 对象本身很轻,但 `performHapticFeedback` 每次都要 `if (!hasVibrator()) return` 判断,如果改为 `vibrator?.let { if (!it.hasVibrator()) return null } ?: return` 在构造时就把 `vibrator` 置 null,后续调用可省一次判断。
- 建议方案: 改为 `private val vibrator: Vibrator? = (getSystemService...)?.takeIf { it.hasVibrator() }`,后续直接 `vibrator?.vibrate(...)` 无需再判断 `hasVibrator()`。

---

### InputValidator.kt

#### 问题1: [🔴严重] containsDangerousContent 的 SQL 注入检测会误杀正常文本,且无法防真实注入
- 位置: InputValidator.kt:234-249
- 问题描述: `sqlPattern = (?i)(union|select|insert|update|delete|drop|alter)\\s+` 会把以下正常用户输入判定为"危险内容"并拒绝:
  - "Please select your preference"(含 "select ")
  - "Update your profile"(含 "Update ")
  - "Delete this message?"(含 "Delete ")
  - "I want to drop the course"(含 "drop ")
  对聊天应用来说,这类英文日常句子极其常见,导致用户体验灾难。同时,这个检测对真实 SQL 注入几乎无效:现代 ORM(SQLite + Room)使用参数化查询,根本不会被 `"union select"` 字符串注入;而如果应用自己拼 SQL(不应该),`"UNION/**/SELECT"`、`"union\x00select"`、`"union%20select"` 都能绕过这个简单正则。这是典型的"安全 theater":看起来在防护,实际既误杀又漏防。
- 建议方案: 直接删除 SQL 注入检测分支。SQL 注入防护是数据层的责任(参数化查询/PreparedStatement),不应在输入验证层做字符串匹配。XSS 检测同理,聊天应用如果用 Compose Text 渲染(非 WebView),不存在 XSS 风险;如果有 WebView,应在 WebView 层做 HTML 转义,而非在输入层。如果确需检测,改为检查具体的恶意 payload 模式(如 `'; DROP TABLE`、`<script src=`),而非单词匹配。

#### 问题2: [🟠中等] scriptPattern 的 on\w+\s*= 误报率高
- 位置: InputValidator.kt:237
- 问题描述: `on\\w+\\s*=` 试图匹配 HTML 事件处理器注入(如 `onclick=`),但会误判正常文本:
  - "on click = submit"(用户描述交互)
  - "online = true"
  - "onto = the next page"
  - 任何以 on 开头的单词后跟等号
  聊天场景下这类误报很常见。
- 建议方案: 至少要求前面是 `<` 或空白后跟属性特征,如 `(<|\\s)on\\w+\\s*=`,或干脆只检测 `<script` 和 `javascript:` 两个最明确的向量。

#### 问题3: [🟠中等] validateDeepLink 的 validPaths 与 DeepLinkHandler 常量重复且缺少 tools
- 位置: InputValidator.kt:164-166, DeepLinkHandler.kt:60-69
- 问题描述: `InputValidator.validateDeepLink` 内部硬编码 `listOf("chat", "status", "shop", "settings", "plugins", "memory", "study", "persona")`,而 `DeepLinkHandler` 定义了 `PATH_CHAT`、`PATH_STATUS`、...、`PATH_TOOLS` 等常量。两处列表:
  (1) DRY 违规:新增路径要改两处,容易遗漏;
  (2) InputValidator 的列表缺少 `"tools"`(DeepLinkHandler 有 `PATH_TOOLS`),导致 `aveline://tools?...` 通过 DeepLinkHandler 能解析,但 InputValidator 会判定为"无效路径"。两个类对同一概念不一致。
- 建议方案: 把合法路径列表提取为 `DeepLinkHandler.VALID_PATHS: Set<String>`,`InputValidator.validateDeepLink` 引用该常量;或让 `DeepLinkHandler.parseUri` 内部调用 `InputValidator.validateDeepLink`,统一校验入口。

#### 问题4: [🟠中等] validateBackendUrl 缺少 SSRF 防护
- 位置: InputValidator.kt:139-151
- 问题描述: `validateBackendUrl` 只检查是否 http(s) + 是否建议 HTTPS,但不禁止内网地址。用户可设置 `backendUrl = "http://192.168.1.1"` 或 `http://10.0.0.1"`,应用所有请求(可能携带 token)被发往内网设备。在多用户/共享设备场景下,这是 SSRF 攻击向量。同样 `http://169.254.169.254`(云元数据服务)可被用于窃取云凭证。
- 建议方案: 增加内网 IP 黑名单检查(`127.0.0.0/8`、`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16` 等),除非显式标记为开发模式允许 localhost。可用 `InetAddress.getByName(host).isSiteLocalAddress` 等标准 API。

#### 问题5: [🟡轻微] Patterns.WEB_URL 在 Android 12+ 已废弃
- 位置: InputValidator.kt:124
- 问题描述: `Patterns.WEB_URL` 自 API 31 起被标记为 deprecated,且其正则较宽松(允许 `ftp://` 等)。Android 官方推荐用 `android.webkit.URLUtil.isValidUrl` 或自定义校验。
- 建议方案: 改用 `URLUtil.isValidUrl(url)` 配合手动协议检查;或引入更严格的 URL parser(如 `java.net.URI(url).parseServerAuthority()`)。

#### 问题6: [🟡轻微] sanitizePath 不能完全防止路径遍历
- 位置: InputValidator.kt:216-220
- 问题描述: `replace(PATH_TRAVERSAL.toRegex(), "")` 中 `PATH_TRAVERSAL = "(\\.\\./)|(\\.\\\\)"`,只匹配 `../` 和 `..\`。但攻击者可构造 `....//`(替换后变成 `../`)、`%2e%2e%2f`(URL 编码)、`..%5c`(混合编码)等绕过。`sanitizePath("....//etc/passwd")` 替换 `../` 后剩余 `.../etc/passwd`,但 `.../` 在某些文件 API 中仍可能被解析。这是安全相关代码,容错率应为零。
- 建议方案: 路径遍历防护应基于规范化路径比较:`File(baseDir, sanitized).canonicalPath.startsWith(baseDir.canonicalPath)`,而非正则替换。`sanitizePath` 只能作为辅助,不能作为唯一防线。

---

### LanguageManager.kt

#### 问题1: [🟠中等] applyLanguage 用已废弃的 updateConfiguration,Android 13+ 失效
- 位置: LanguageManager.kt:102-130
- 问题描述: `context.resources.updateConfiguration(config, displayMetrics)` 自 API 25 起被标记为 deprecated,Android 13 (API 33) 起严格 scoped storage 类似地限制了运行时 Configuration 修改。在 API 33+ 上,应用语言应通过 `LocaleManager.setApplicationLocales()` 设置,该 API 会通知系统持久化语言偏好并重启 Activity。当前实现的语言切换在 Android 13+ 上不会真正生效(或只对当前 Activity 生效,新 Activity 又回退)。
- 建议方案: 用 `AppCompatDelegate.setApplicationLocales(LocaleListCompat.create(locale))`(AndroidX AppCompat 1.6+ 封装了 API 13+ 的 LocaleManager),或在 API 33+ 直接调 `context.getSystemService(LocaleManager::class.java).applicationLocales = LocaleList(locale)`。

#### 问题2: [🟠中等] requiresRestart() 永远返回 false,但 Compose 字符串不会自动随 updateConfiguration 更新
- 位置: LanguageManager.kt:162-164, 102-130
- 问题描述: 注释说"在 Compose 中,通常不需要重启,因为字符串资源会自动更新",这是错误的。`updateConfiguration` 只更新 Resources 的 Configuration,但 Compose 的 `stringResource` 只在 Composition 重组时才重新读取,而 Configuration 变化不会自动触发重组(除非用 `LocalConfiguration.current` 监听)。实际表现是:用户切换语言后,当前页面字符串不变,必须手动导航或重启 Activity 才生效。`requiresRestart()` 永远 false 会让调用方误以为无需任何处理,实际用户体验差。
- 建议方案: (1) 切换语言后调用 `Activity.recreate()`(简单粗暴但有效),此时 `requiresRestart()` 返回 true;(2) 或在 Application 注入 `currentLanguage` 的 StateFlow,Compose 通过 `LocalContext.current` 监听并触发重组;(3) 推荐 AppCompat 的 `setApplicationLocales`,系统会自动处理 Activity 重建。

#### 问题3: [🟡轻微] init 块在 @Singleton 构造时同步调用 applyLanguage,影响启动性能
- 位置: LanguageManager.kt:49-54
- 问题描述: `init` 块在 Hilt 注入时(通常是 Application.onCreate 阶段)执行 `applyLanguage`,内部调用 `Configuration(context.resources.configuration).apply { setLocales(...) }` 和 `updateConfiguration`。这些操作虽然不慢,但在启动关键路径上,且 LanguageManager 是 @Singleton 提前初始化会增加冷启动时间。`detectSystemLanguage()` 也会读 Resources。
- 建议方案: 用 `by lazy` 或在 Application.onCreate 后异步初始化,启动时只读 `appPreferences.languageCode` 决定是否需要 apply,真正 apply 推迟到首次 Activity 创建。

#### 问题4: [🟡轻微] getCurrentLocale 在 SYSTEM 分支重复调用 detectSystemLanguage
- 位置: LanguageManager.kt:135-147
- 问题描述: `getCurrentLocale()` 在 SYSTEM 分支调用 `detectSystemLanguage()`,内部又读 `context.resources.configuration.locales[0]`。每次调用都重新检测,效率低,且如果系统语言在运行时被用户更改,`detectSystemLanguage` 返回新值,但 `_currentLanguage.value` 仍是 SYSTEM,导致状态不一致(状态显示 SYSTEM 但实际 locale 是新系统语言)。
- 建议方案: 缓存系统 locale,或在 Configuration 变化时通过 `OnConfigurationChangedListener` 监听并刷新。或在 SYSTEM 模式下直接返回 `Locale.getDefault()`,无需复杂判断。

---

### PerformanceMonitor.kt

#### 问题1: [🔴严重] getThreadInfo 调用 Thread.getAllStackTraces() 会暂停所有线程,严重性能事故
- 位置: PerformanceMonitor.kt:170-173
- 问题描述: `Thread.getAllStackTraces()` 是一个极度昂贵的操作,它会对 JVM 中所有线程(包括 GC 线程、JIT 线程、Binder 线程等)发送 Safepoint 信号,等待每个线程到达 safepoint 后获取其完整堆栈。在生产环境调用一次可能造成 50-200ms 的全局暂停(所有线程 frozen),与性能监控的初衷完全相反——监控工具本身成了性能杀手。如果这个函数被开发者加到 UI 刷新路径或定期采样任务里,会引发严重卡顿。
- 建议方案: (1) 删除该函数,或改为只返回 `Thread.activeCount()`(轻量);(2) 如确需线程堆栈,用 `ThreadMXBean` 的 `dumpAllThreads(false, false)` 配合采样;(3) 至少应标注"仅 DEBUG 构建可用"并用 `if (BuildConfig.DEBUG)` 包裹。

#### 问题2: [🟠中等] measureTime 在 release 构建中仍执行 Log.d,IO 开销不小
- 位置: PerformanceMonitor.kt:185-195
- 问题描述: `measureTime` 内部 `if (elapsed > 100) Log.d(TAG, "$operation took ${elapsed}ms")`。`Log.d` 在 release 构建中虽然默认不输出到 logcat(取决于设备),但字符串拼接 `"$operation took ${elapsed}ms"` 仍会执行,如果 `operation` 是复杂对象 toString 会有额外开销。更严重的是,该函数被设计为通用耗时测量工具,可能被高频调用(如测量每帧、每条消息处理),`System.nanoTime()` 本身开销小,但 Log.d 的开销在 release 中也是浪费。
- 建议方案: 用 `if (BuildConfig.DEBUG && elapsed > 100) Log.d(...)` 包裹,release 完全跳过。或用 `androidx.core.performance.DevicePerformance` 的 API。同时建议支持 sampler 而非每调用都测。

#### 问题3: [🟠中等] updateMemoryUsage 每次创建新 MemoryInfo 对象,Debug.getMemoryInfo 开销大
- 位置: PerformanceMonitor.kt:108-120, 132-136
- 问题描述: `updateMemoryUsage` 和 `getCurrentMemoryUsage` 每次都 `val memoryInfo = Debug.MemoryInfo()` 新建对象,然后 `Debug.getMemoryInfo(memoryInfo)` 填充(该 native 调用读取 /proc/self/smaps,开销 5-20ms)。如果被定期调用(如每秒采样),CPU 和内存分配压力都不小。同时两个函数代码几乎完全重复(DRY 违规)。
- 建议方案: 复用一个 `Debug.MemoryInfo` 实例字段,通过 `synchronized` 或单线程采样复用。`getCurrentMemoryUsage` 改为读 `_metrics.value.memoryUsage` 而非重新测量。两个函数合并为一个内部 `measureMemory(): Long`。

#### 问题4: [🟠中等] cpuUsage 字段从未被设置,默认 0f 误导调用方
- 位置: PerformanceMonitor.kt:29, 24-52
- 问题描述: `PerformanceMetrics.cpuUsage: Float = 0f` 字段被定义,且 `overallScore` 等并未使用它,但没有任何 `update*` 函数会设置 `cpuUsage`。调用方读 `metrics.value.cpuUsage` 永远得到 0,可能误以为 CPU 使用率确实是 0%。这是典型的"幽灵字段"。
- 建议方案: 要么实现 CPU 使用率采样(读 `/proc/self/stat` 计算 jiffies 比例),要么删除该字段。Android 上读取 CPU 使用率比较复杂(需要两次采样 + 区分进程/系统),建议直接删除,避免误用。

#### 问题5: [🟡轻微] isMemoryLow 和 getAvailableMemory 重复获取 ActivityManager
- 位置: PerformanceMonitor.kt:141-158
- 问题描述: 两个函数都 `context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager` + `ActivityManager.MemoryInfo()` + `getMemoryInfo(memoryInfo)`。重复代码,且每次都获取系统服务(虽然系统服务是单例,getSystemService 开销小,但仍可缓存)。`getPerformanceReport` 同时调这两个函数,会执行两次相同的 MemoryInfo 获取。
- 建议方案: 缓存 `activityManager` 字段,提取 `private fun getMemoryInfo(): ActivityManager.MemoryInfo` 公共方法,两个函数复用。

#### 问题6: [🟡轻微] appStartTime 是 var 但无 @Volatile,多线程可见性问题
- 位置: PerformanceMonitor.kt:74, 79-95
- 问题描述: `private var appStartTime: Long = 0`,在 `recordAppStart` 写入,在 `recordAppStartupComplete` 读取。如果两者在不同线程调用(如启动在主线程,但某库在 IO 线程触发 recordAppStart),由于 Kotlin var 无 volatile 修饰,可能读到 0 或旧值,导致 startupTime 计算错误。
- 建议方案: 加 `@Volatile`,或用 `AtomicLong`。

---

### RetryUtils.kt

#### 问题1: [🔴严重] withCircuitBreaker 每次调用新建 CircuitBreaker,熔断状态无法跨调用保留
- 位置: RetryUtils.kt:170-176
- 问题描述: `withCircuitBreaker(failureThreshold, resetTimeMs, block)` 内部 `CircuitBreaker(failureThreshold, resetTimeMs).execute(block)` 每次都 `new CircuitBreaker`,新实例的 `failureCount=0, isOpen=false`。这意味着:
  - 调用 N 次 N 都失败,熔断器永远不打开(每次都是新实例,计数从 0 开始);
  - 熔断器形同虚设,等于没有熔断;
  - 调用方以为有熔断保护,实际没有任何保护效果。
  这是非常严重的设计错误——熔断器的核心价值就是跨调用积累失败计数,而这里完全无效。
- 建议方案: (1) 让 `CircuitBreaker` 作为 `@Singleton` 注入(每个外部服务一个实例,用 `@Named` 区分);(2) 或在 `RetryUtils` 内部维护一个 `ConcurrentHashMap<String, CircuitBreaker>`,按 key 缓存;(3) 至少应该把 `CircuitBreaker` 作为调用方持有的字段,而非每次新建。

#### 问题2: [🟠中等] 指数退避无 jitter,所有客户端同时重试造成惊群
- 位置: RetryUtils.kt:81-87, 120-125
- 问题描述: `delay(currentDelay)` 后 `currentDelay = min(currentDelay * multiplier, maxDelayMs)`,延迟完全确定。如果服务器宕机,所有客户端在 t=0 失败,t=1s 重试又同时失败,t=2s 又同时重试...形成"惊群效应",服务器恢复瞬间被打爆。生产环境的重试必须加 jitter(随机抖动),这是 AWS/Google 公认的最佳实践。
- 建议方案: 引入"full jitter"算法:`delay = random(0, currentDelay)`,或"equal jitter":`delay = currentDelay/2 + random(0, currentDelay/2)`。需要注入 `Random` 或用 `ThreadLocalRandom.current()`。

#### 问题3: [🟠中等] CircuitBreaker.execute 是同步函数,无法用于 suspend block
- 位置: RetryUtils.kt:191, 170-176
- 问题描述: `execute(block: () -> T): Result<T>` 中 `block` 是同步函数,而 `RetryUtils.retry` 是 `suspend` 的。这意味着 `withCircuitBreaker` 无法保护网络请求等 suspend 操作,调用方要么用 `runBlocking`(阻塞线程,反模式),要么不能用熔断器。这是 API 设计的严重缺陷,导致熔断器在实际异步代码中无法使用。
- 建议方案: 增加 `suspend fun <T> executeAsync(block: suspend () -> T): Result<T>`,内部 `withContext(Dispatchers.IO) { block() }` 或直接 `try { Result.success(block()) } catch (...)`。

#### 问题4: [🟡轻微] retryableExceptions 列表冗余,IOException 已涵盖其子类
- 位置: RetryUtils.kt:24-28
- 问题描述: `listOf(IOException::class.java, java.net.SocketTimeoutException::class.java, java.net.UnknownHostException::class.java)`。`SocketTimeoutException extends IOException`,`UnknownHostException extends IOException`,后两者是 `IOException` 的子类。`isInstance` 检查时 `IOException::class.java.isInstance(socketTimeoutException)` 已返回 true,后两项冗余。
- 建议方案: 只保留 `IOException::class.java`,在注释中说明涵盖所有 IO 子类。或保留显式列表作为文档,但加注释说明是为了可读性。

---

### SecurityManager.kt

#### 问题1: [🔴严重] isHardwareBackedKeyStore 实现完全错误,无法判断硬件支持
- 位置: SecurityManager.kt:184-195
- 问题描述: `entry.secretKey.algorithm == "AES"` 只检查密钥算法是 AES,但软件 keystore 也能生成 AES 密钥。判断"是否硬件支持"必须通过 `SecretKey factory.translateKey(key)` 后 cast 为 `KeyInfo`,再调 `keyInfo.isInsideSecureHardware()`。当前实现返回 true 当且仅当密钥存在且算法是 AES,这意味着所有设备都会返回 true(因为 createKey 用的就是 AES),完全不能区分硬件 vs 软件 keystore。如果调用方基于这个判断决定是否存储敏感数据,会误以为有硬件保护而存储高风险数据到软件 keystore。
- 建议方案:
  ```kotlin
  val factory = SecretKeyFactory.getInstance(key.algorithm, ANDROID_KEY_STORE)
  val keyInfo = factory.getKeySpec(secretKey, KeyInfo::class.java) as KeyInfo
  return keyInfo.isInsideSecureHardware
  ```

#### 问题2: [🔴严重] hash 用单次 SHA-256,不适合密码哈希,易被暴力破解
- 位置: SecurityManager.kt:156-168
- 问题描述: `hash(data, salt)` 用 `MessageDigest.getInstance("SHA-256")` 对 `salt + data` 做单次哈希。如果 `data` 是密码,这是极度不安全的:现代 GPU 每秒可计算数十亿次 SHA-256,一个 8 字符密码几小时内可被暴力破解。密码哈希必须用慢哈希算法(PBKDF2/bcrypt/scrypt/Argon2),迭代次数 ≥ 10000 次。即使 `data` 不是密码而是其他敏感数据(如 API key),单次 SHA-256 也容易被彩虹表攻击(如果 salt 泄露)。
- 建议方案: 用 `PBKDF2WithHmacSHA256` 至少 10000 次迭代:
  ```kotlin
  val spec = PBEKeySpec(data.toCharArray(), saltBytes, 10000, 256)
  val factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
  val hash = factory.generateSecret(spec).encoded
  ```
  或在 API 26+ 用 `Argon2`。如果是非密码数据的简单指纹,应在文档中明确说明"非密码学强度"。

#### 问题3: [🟠中等] createKey 未设置用户认证要求,锁屏密钥仍可用
- 位置: SecurityManager.kt:54-72
- 问题描述: `KeyGenParameterSpec.Builder` 没有调用 `setUserAuthenticationRequired(true)` 也没有 `setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG or AUTH_DEVICE_CREDENTIAL)`。这意味着密钥不需要用户解锁设备即可使用——如果设备被偷且未锁屏,攻击者可直接调用 `decrypt` 解密所有敏感数据。`isDeviceSecure()` 检查存在,但只在调用方主动调时生效,密钥本身无保护。
- 建议方案: 对高敏感数据(如 token、密码)的密钥,加 `setUserAuthenticationRequired(true)` 和 `setUserAuthenticationValidityDurationSeconds(30)`(30 秒内免再次认证)。同时 `setInvalidatedByBiometricEnrollment(true)` 让用户录入新指纹时旧密钥失效。

#### 问题4: [🟠中等] isDeviceSecure / hasScreenLock 在 API < 23 会 crash
- 位置: SecurityManager.kt:200-213
- 问题描述: `keyguardManager.isDeviceSecure` 是 API 23 (Android 6.0) 引入的,`isKeyguardSecure` 是 API 16 但部分 OEM 实现差异。如果项目 minSdk < 23,调用 `isDeviceSecure()` 会抛 `NoSuchMethodError`。代码没有任何 SDK_INT 检查。
- 建议方案: 加 `if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return hasScreenLock()` 兜底,或用 `ContextCompat` / `KeyguardManagerCompat`。

#### 问题5: [🟠中等] encrypt/decrypt 缺少错误处理,异常会暴露信息
- 位置: SecurityManager.kt:80-119
- 问题描述: `encrypt` 和 `decrypt` 没有任何 try-catch。`Cipher.getInstance` 可能抛 `NoSuchAlgorithmException`/`NoSuchPaddingException`(虽然 AES/GCM 是标准),`doFinal` 可能抛 `IllegalBlockSizeException`/`BadPaddingException`(密钥被删除/更换后解密旧数据)。这些异常直接抛给调用方,调用方如果不处理会 crash。更糟的是,`BadPaddingException` 的 message 可能包含密钥相关信息,泄露给 logcat。
- 建议方案: 在 encrypt/decrypt 内 try-catch 所有异常,返回 `Result<String>` 或抛自定义 `SecurityException`(注意区分 `java.lang.SecurityException`)。`decrypt` 失败时返回空字符串或 null,而不是抛异常,避免调用方处理复杂度。同时 logcat 输出只记 "decrypt failed" 不记具体异常 message。

#### 问题6: [🟡轻微] isDeviceSecure / hasScreenLock 每次获取 KeyguardManager
- 位置: SecurityManager.kt:200-213
- 问题描述: 两个函数都 `context.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager`,虽然系统服务是单例,getSystemService 开销小,但每次 cast 仍有微小开销。`isHardwareBackedKeyStore`、`hasKey`、`isDeviceSecure`、`hasScreenLock` 可能在设置页频繁调用。
- 建议方案: 缓存 `keyguardManager` 字段:`private val keyguardManager by lazy { context.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager }`。

---

### ShareUtils.kt

#### 问题1: [🟠中等] 文件名硬编码"shared_image.png",多次分享会覆盖
- 位置: ShareUtils.kt:55-56, 99-100
- 问题描述: `fileName: String = "shared_image.png"` 是固定值。如果用户连续分享两张图片,第二次会覆盖第一次的缓存文件。如果第一次分享的 Intent 还在被目标应用(如微信)异步读取,文件已被覆盖,目标应用读到的是新图片,造成"分享错图"。同时 `clearShareCache()` 会一次性删除所有图片,但用户可能正在分享中。
- 建议方案: 文件名加时间戳或 UUID:`"shared_image_${System.currentTimeMillis()}.png"`,或用 `UUID.randomUUID()`。`clearShareCache` 只清理超过一定时间(如 1 小时)的文件。

#### 问题2: [🟠中等] startActivity 可能抛 ActivityNotFoundException,未处理
- 位置: ShareUtils.kt:43, 85, 130
- 问题描述: `context.startActivity(chooserIntent)` 在没有任何应用能处理 `ACTION_SEND` intent 时(罕见但可能,如定制 ROM 禁用了所有分享)会抛 `ActivityNotFoundException`。由于 `ShareUtils` 是 @Singleton,context 是 ApplicationContext,异常会直接抛到调用方,如果调用方在 ViewModel/Compose 中未捕获会 crash。
- 建议方案: try-catch `ActivityNotFoundException`,返回 `Boolean` 表示是否成功,或抛出更友好的自定义异常。同时可调用 `intent.resolveActivity(context.packageManager)` 提前检查。

#### 问题3: [🟡轻微] shareImage 和 shareTextAndImage 代码重复
- 位置: ShareUtils.kt:53-86, 96-131
- 问题描述: 两个函数 90% 代码相同(都创建 cachePath、写文件、获取 FileProvider URI、构建 Intent)。`shareTextAndImage` 只是多了 `putExtra(Intent.EXTRA_TEXT, text)`。重复代码导致 bug 修复需改两处(如问题1的文件名修复就要改两处)。
- 建议方案: 提取 `private fun createImageShareIntent(imageBytes: ByteArray, fileName: String, text: String? = null): Intent`,两个公开函数复用。

#### 问题4: [🟡轻微] 标题硬编码中文,未国际化
- 位置: ShareUtils.kt:32, 56, 100
- 问题描述: `title: String = "分享消息"`、`"分享图片"`、`"分享内容"` 硬编码中文,英文用户看到中文标题。ShareUtils 是 @Singleton 注入 ApplicationContext,无法直接用 Compose 的 `stringResource`,但可以通过 `context.getString(R.string.share_message)` 取值(ApplicationContext 配合 Configuration)。
- 建议方案: 改为 `context.getString(R.string.share_message)` 作为默认值,或要求调用方传入 title(由 UI 层用 `stringResource` 取)。

---

### StateManager.kt

#### 问题1: [🔴严重] init 块在主线程同步执行文件 IO,且 saveState 在每次状态更新时同步写盘
- 位置: StateManager.kt:47-49, 54-61, 87-93, 98-105
- 问题描述: `init { restoreState() }` 在 @Singleton 构造时(通常是 Application.onCreate 或首次注入)执行 `stateFile.readText()` + `json.decodeFromString`,这些是磁盘 IO + JSON 解析,在主线程执行会阻塞启动。`saveState()` 在 `updateCurrentScreen` 和 `updateCurrentSession` 中被同步调用,每次都 `json.encodeToString` + `stateFile.writeText`,如果在主线程频繁调用(如导航切换、会话切换),会导致明显卡顿。`updateScrollPosition` 注释说"不立即保存,避免频繁 IO",但其他更新函数没有此优化,且 `updateScrollPosition` 修改的状态在应用被杀时丢失。
- 建议方案: (1) `restoreState` 改为 `suspend` 或在 `Dispatchers.IO` 上执行,init 中只设默认值,异步恢复;(2) `saveState` 改为 `debounce(500ms)` + `Dispatchers.IO`,通过 SharedFlow 收集状态变化批量保存;(3) 用 DataStore (Preferences DataStore) 替代手动 JSON + File,DataStore 自带异步 IO 和事务性保证。

#### 问题2: [🟠中等] updateCurrentScreen/updateCurrentSession 同步触发 IO 且无防抖
- 位置: StateManager.kt:87-93, 98-105
- 问题描述: 每次 `updateCurrentScreen` 都 `saveState()`,如果用户快速切换页面(如点击底部 tab 来回切换),每秒可能触发数次磁盘写入。每次写入 = JSON 编码 + 文件覆盖写(非原子,中途 crash 会损坏文件)。这是性能和数据安全双问题:性能上 IO 阻塞主线程;安全上 writeText 不是原子操作,中途 crash 会留下半截 JSON,下次 restoreState 解析失败只能用默认状态。
- 建议方案: (1) 引入 `MutableSharedFlow` 收集状态变更,`debounce(500)` 后批量保存;(2) 写入时用临时文件 + rename 保证原子性:`tmpFile.writeText(json); tmpFile.renameTo(stateFile)`;(3) 高频更新(如 scrollPosition)只更新内存,低频更新(如 sessionId)才保存。

#### 问题3: [🟠中等] 线程安全问题:StateFlow.value 赋值线程安全,但 saveState 与 value 读取非原子
- 位置: StateManager.kt:54-61, 87-105
- 问题描述: `MutableStateFlow.value` 的赋值是线程安全的(原子),但 `saveState()` 内部 `json.encodeToString(_appState.value)` 读取 value 后再写文件,这两步不是原子的。如果线程 A 调用 `updateCurrentScreen("a")` 后 `saveState()` 开始执行,线程 B 同时调 `updateCurrentSession("b")` 修改了 value,`saveState` 写入的可能是 B 修改后的状态,但 saveState 是 A 触发的,逻辑混乱。更严重的是 `stateFile.writeText` 与 `appPreferences.currentSessionId = sessionId` 顺序问题:如果 writeText 失败但 appPreferences 已写入,两者状态不一致。
- 建议方案: 用 `Mutex` 保护状态更新+保存的临界区,或所有更新通过单一协程顺序执行(actor 模式)。

#### 问题4: [🟠中等] restoreState 失败时丢弃旧文件,用户状态丢失
- 位置: StateManager.kt:66-82
- 问题描述: `try { ... } catch (e: Exception) { _appState.value = AppState() }`,如果 JSON 解析失败(文件损坏、版本不兼容),直接重置为默认状态,旧文件保留但不被使用。下次 saveState 会覆盖损坏文件,用户彻底丢失状态(最后访问的会话、滚动位置等)。这是数据丢失 bug。同时 catch 块完全静默,无日志,问题难以排查。
- 建议方案: catch 块内 `Log.w("StateManager", "Failed to restore state", e)` 记录失败原因,并将损坏文件备份为 `app_state.json.corrupt` 供事后分析,而不是直接覆盖。

#### 问题5: [🟡轻微] shouldRestoreState 在 lastActiveTime 为默认值时返回错误结果
- 位置: StateManager.kt:159-162
- 问题描述: `shouldRestoreState()` 计算 `elapsed = System.currentTimeMillis() - lastActiveTime`。如果 state 是新建的(默认 `lastActiveTime = System.currentTimeMillis()`),elapsed ≈ 0,函数返回 true(如果 currentSessionId != null,但默认是 null 所以返回 false)。看起来 OK,但如果 AppState 被手动构造(`AppState(currentSessionId = "xxx")` 而未设 lastActiveTime),lastActiveTime 是构造时的 now,而 elapsed 是从构造到调用的间隔,逻辑不直观。
- 建议方案: 加注释说明 `lastActiveTime = 0` 表示"从未激活",`shouldRestoreState` 在 `lastActiveTime == 0L` 时直接返回 false。

---

## 总结与优先级建议

### 🔴 严重问题(必须优先修复,共 12 个)

按"影响面 × 触发概率"排序:

1. **CrashHandler.uncaughtException 同步 IO + 静默吞异常**(CrashHandler.kt:50-59, 100-102):崩溃日志可能丢失且无任何告警,事后定位困难。**修复成本:低**。
2. **RetryUtils.withCircuitBreaker 每次新建实例,熔断形同虚设**(RetryUtils.kt:170-176):生产环境熔断保护完全无效,可能被误用导致雪崩。**修复成本:低**。
3. **DataExportManager 一次性加载所有数据到内存**(DataExportManager.kt:86-124):中等数据量用户必然 OOM。**修复成本:中**(需重构为流式)。
4. **DataExportManager 用废弃 API 写公共 Downloads**(DataExportManager.kt:117-120):Android 10+ 直接失败。**修复成本:低**(改 MediaStore)。
5. **SecurityManager.isHardwareBackedKeyStore 实现错误**(SecurityManager.kt:184-195):误判所有设备为硬件支持,可能导致敏感数据存储在软件 keystore。**修复成本:低**。
6. **SecurityManager.hash 用单次 SHA-256**(SecurityManager.kt:156-168):若用于密码,易被暴力破解。**修复成本:低**(改 PBKDF2)。
7. **PerformanceMonitor.getThreadInfo 调用 getAllStackTraces**(PerformanceMonitor.kt:170-173):监控工具本身造成全局暂停,反作用。**修复成本:低**(删除或加 DEBUG 守卫)。
8. **StateManager.init 主线程同步 IO + saveState 每次同步写盘**(StateManager.kt:47-61):启动卡顿 + 运行时卡顿 + 文件非原子写损坏风险。**修复成本:中**(改 DataStore 或 SharedFlow + debounce)。
9. **DeepLinkHandler 未对 host/path 做白名单校验**(DeepLinkHandler.kt:80-107):可被恶意深链预填文本/路由。**修复成本:低**(接入 InputValidator)。
10. **AccessibilityManager.isHighContrastEnabled 逻辑错误**(AccessibilityManager.kt:97-112):夜间模式与高对比度混淆,样式错乱。**修复成本:低**。
11. **InputValidator.containsDangerousContent SQL 注入检测误杀正常文本**(InputValidator.kt:234-249):英文用户正常对话被拒。**修复成本:低**(直接删除)。
12. **DataExportManager.importData/clearAllData 大量 TODO 但返回 success**(DataExportManager.kt:160-199, 256-268):用户以为导入/清除成功,实际未生效,数据完整性问题。**修复成本:低**(改为 failure 或 unsupported)。

### 🟠 中等问题(建议下个迭代修复,共 36 个)

集中在以下几类:
- **国际化缺失**:ErrorHandler、ShareUtils、AccessibilityExtensions 中的硬编码中文字符串,影响英文用户。
- **缓存/单例生命周期**:CoilImageLoader 的缓存大小硬编码、ImageLoader 引用未持有、HapticFeedbackManager 的 API 重复。
- **错误处理不足**:CrashHandler 无日志限制、SecurityManager encrypt/decrypt 无错误处理、ShareUtils 无 ActivityNotFoundException 处理。
- **API 废弃**:LanguageManager 用 updateConfiguration(Android 13+ 失效)、DataExportManager 用 getExternalStoragePublicDirectory。
- **重试/退避**:ErrorHandler 不解析 Retry-After、RetryUtils 无 jitter、CircuitBreaker 不支持 suspend。
- **校验缺失**:InputValidator SSRF 防护缺失、DeepLinkHandler 与 InputValidator 路径列表不一致。
- **性能**:PerformanceMonitor.updateMemoryUsage 重复创建对象、measureTime 在 release 仍 Log.d。

### 🟡 轻微问题(可在重构时清理,共 26 个)

主要是命名、重复代码、注释/文档、小型优化等,不影响功能正确性。

### 整体性建议

1. **统一国际化方案**:所有面向用户的字符串(包括无障碍 stateDescription、错误消息、分享标题)统一走 `strings.xml`,非 Compose 上下文用 `context.getString`。建议引入 lint 规则禁止硬编码中文。

2. **统一异步 IO 模式**:StateManager、CrashHandler、DataExportManager 的磁盘 IO 都应改为协程 + Dispatchers.IO。考虑引入 DataStore 替代手动 JSON+File。

3. **熔断/重试体系整合**:RetryUtils.CircuitBreaker 改为 @Singleton 注入,支持 suspend block,加入 jitter。与 ErrorHandler 的 retryAfterSeconds 整合,形成"错误分类 → 是否重试 → 退避多久"的完整链路。

4. **安全审计**:SecurityManager 应做一次完整的安全审计,包括:密钥认证要求、密码哈希算法、硬件支持检测、错误处理。建议引入 `EncryptedSharedPreferences` 替代明文 SharedPreferences 存储敏感数据。

5. **DeepLink 校验统一**:DeepLinkHandler 与 InputValidator 的路径白名单合并,所有深链入口先校验后处理。

6. **性能监控自身开销审计**:PerformanceMonitor 的所有 `update*` 方法都应评估自身开销,确保 "监控开销 < 被监控操作开销" 的 10% 原则。`getThreadInfo`/`getAllStackTraces` 必须删除或加 DEBUG 守卫。

7. **单例 Context 持有审查**:所有 @Singleton 注入 ApplicationContext 是 OK 的(Hilt 保证是 Application context),但要注意 Singleton 内的 init 块不应执行重 IO,推迟到首次使用。
