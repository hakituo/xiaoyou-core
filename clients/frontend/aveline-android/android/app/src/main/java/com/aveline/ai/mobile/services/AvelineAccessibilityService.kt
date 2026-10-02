package com.aveline.ai.mobile.services

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.services.wellbeing.SessionLimiter
import com.aveline.ai.mobile.services.wellbeing.UsageLimitEnforcer
import com.aveline.ai.mobile.utils.SelfPackageGuard
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject
import kotlin.coroutines.resume

/**
 * Aveline 无障碍服务
 *
 * 提供 UI 自动化能力: 点击/滑动/返回/桌面/找元素点击/dump 文字。
 *
 * 生命周期: 系统管理, 用户需在系统设置 > 无障碍 中开启本服务。
 * 启动后系统调 onServiceConnected, 这里把实例存到 companion object 供其他组件调用。
 *
 * 与 SystemControlExecutor 的通信:
 * - SystemControlExecutor 检查 AvelineAccessibilityService.isRunning()
 * - 通过 AvelineAccessibilityService.instance 调用具体方法
 *
 * 设计要点:
 * - dispatchGesture 是异步的, 用 suspendCancellableCoroutine 等回调
 * - AccessibilityNodeInfo 用 rootInActiveWindow 获取, 递归遍历找文字
 * - dumpVisibleText 限制深度避免 OOM
 */
@AndroidEntryPoint
class AvelineAccessibilityService : AccessibilityService() {

    @Inject
    lateinit var contextRepository: ContextRepository

    @Inject
    lateinit var sessionLimiter: SessionLimiter

    @Inject
    lateinit var usageLimitEnforcer: UsageLimitEnforcer

    private var serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /**
     * 当前前台应用包名。
     *
     * 由 [onAccessibilityEvent] 持续维护, 是"应用是否离开前台"的唯一事实来源:
     * 只有知道用户离开了哪个应用, 才能计算 sessionGap 并判断下次打开算不算"新的一次"。
     */
    @Volatile
    private var currentForegroundPackage: String? = null

    private val checksInFlight = ConcurrentHashMap.newKeySet<String>()
    private val lastCheckAt = ConcurrentHashMap<String, Long>()

    /** 前台限额轮询协程; 服务销毁 / 解绑时置空, 重连后重新拉起。 */
    @Volatile
    private var tickerJob: Job? = null

    /**
     * 主线程 Handler。无障碍的 dispatchGesture / performGlobalAction / rootInActiveWindow
     * / findAccessibilityNodeInfos* 等 API 都必须在主线程调用, 否则会抛 RuntimeException
     * 导致服务崩溃, 系统会停用本无障碍服务 (表现为"过几十分钟就被关")。
     */
    private val mainHandler = Handler(Looper.getMainLooper())

    companion object {
        private const val TAG = "AvelineA11yService"
        private const val MAX_TREE_DEPTH = 20
        private const val MAX_DUMP_TEXT_LEN = 8000
        private const val PACKAGE_CHECK_THROTTLE_MS = 2_000L

        /** 前台是受限应用时的轮询间隔。 */
        private const val TICK_ACTIVE_MS = 10_000L

        /** 前台不是受限应用 (桌面 / 未设限应用) 时的轮询间隔。 */
        private const val TICK_IDLE_MS = 30_000L

        /** 轮询间隔下限, 避免临近上限时把这层循环跑成忙等。 */
        private const val TICK_MIN_MS = 1_000L

        @Volatile
        var instance: AvelineAccessibilityService? = null
            private set

        /** 服务是否正在运行 (即用户是否已开启无障碍权限) */
        fun isRunning(): Boolean = instance != null

        /**
         * 判断 Aveline 无障碍服务是否在系统"已启用无障碍服务"列表中。
         * 与 isRunning()(进程内实例是否存在) 不同, 这是系统层面的开关状态,
         * 用于在前台保活服务启动时判断"是否值得拉起"。
         */
        fun isEnabledInSystem(context: Context): Boolean {
            return try {
                val target = ComponentName(
                    context, AvelineAccessibilityService::class.java
                ).flattenToString()
                val enabledServices = android.provider.Settings.Secure.getString(
                    context.contentResolver,
                    android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
                ) ?: return false
                val splitter = if (enabledServices.contains(":")) ":" else ";"
                enabledServices.split(splitter).any { it.equals(target, ignoreCase = true) }
            } catch (e: Exception) {
                false
            }
        }
    }

    override fun onServiceConnected() {
        try {
            super.onServiceConnected()
            instance = this
            // onUnbind / onDestroy 会取消 serviceScope; 系统重新绑定时需要重建,
            // 否则前台限额轮询在重连后永久停摆。
            if (serviceScope.coroutineContext[Job]?.isActive != true) {
                serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            }
            startForegroundTicker()
            Log.i(TAG, "无障碍服务已连接, pid=${android.os.Process.myPid()}")
            A11yDiagnosis.log(applicationContext, "A11ySvc", "onServiceConnected (服务已连接)")

            // 无条件拉起保活前台服务: 无障碍服务需要稳定的宿主进程, 否则进程被系统回收后
            // 服务会随之断开。之前依赖"常驻模式"开关才启动前台服务, 但该开关实际未生效
            // (很多机型上前台通知从未出现), 导致无障碍服务裸奔、频繁被回收。
            // 这里改为无障碍服务开启即自动拉起保活前台服务, 不再依赖常驻模式开关。
            // 整个拉起过程包在 try 内, 即使前台服务失败也绝不让无障碍服务崩溃 (避免闪退循环)。
            try {
                AvelineForegroundServiceV2.start(this)
                A11yDiagnosis.log(applicationContext, "A11ySvc", "已拉起保活前台服务")
            } catch (e: Exception) {
                Log.w(TAG, "拉起前台保活服务失败: ${e.message}")
                A11yDiagnosis.log(applicationContext, "A11ySvc", "拉起前台服务失败: ${e.message}")
            }
        } catch (e: Exception) {
            // 兜底: 任何意外都不应让无障碍服务崩溃, 否则会进入"开了就闪退"的死循环
            Log.e(TAG, "onServiceConnected 异常(已兜底, 不影响服务运行): ${e.message}", e)
        }
    }

    override fun onUnbind(intent: Intent?): Boolean {
        // 进程被系统回收 / 短暂断开时把实例置空, 但返回 true 允许系统 rebind,
        // 否则系统会判定本服务"已关闭", 用户需重新到设置里开启 (表现为十几分钟掉一次)。
        instance = null
        currentForegroundPackage = null
        tickerJob = null
        Log.w(TAG, "无障碍服务 onUnbind 被调用, pid=${android.os.Process.myPid()}, " +
                "进程是否存活=${isProcessAlive()}, intent=$intent")
        A11yDiagnosis.log(applicationContext, "A11ySvc", "onUnbind intent=$intent")
        return true
    }

    override fun onRebind(intent: Intent?) {
        super.onRebind(intent)
        // onUnbind 返回 true 时系统会在进程恢复后自动重新绑定并再次调用 onServiceConnected,
        // 这里兜底确保 instance 一定被填回。
        instance = this
        Log.i(TAG, "无障碍服务已重新绑定, pid=${android.os.Process.myPid()}")
        A11yDiagnosis.log(applicationContext, "A11ySvc", "onRebind (服务重新绑定)")
    }

    override fun onDestroy() {
        serviceScope.cancel()
        instance = null
        currentForegroundPackage = null
        tickerJob = null
        Log.e(TAG, "无障碍服务 onDestroy 被调用! pid=${android.os.Process.myPid()}, " +
                "进程是否存活=${isProcessAlive()}。这通常意味着服务被系统停用或进程被杀。")
        A11yDiagnosis.log(applicationContext, "A11ySvc", "onDestroy (服务被销毁/停用)")
        super.onDestroy()
    }

    /**
     * 粗略判断宿主进程是否还存活 (供诊断日志使用)。
     */
    private fun isProcessAlive(): Boolean = try {
        // 进程肯定"活着"才会执行到这里, 这里主要是记录到日志便于排查
        android.os.Process.myPid() > 0
    } catch (e: Exception) {
        false
    }

    /**
     * 前台应用切换时:
     * 1. 先让上一个应用"离开前台" (启动 sessionGap 计时)
     * 2. 再对刚进入前台的受限应用做一次即时判定
     *
     * 持续使用过程中的额度消耗由 [startForegroundTicker] 的秒级轮询负责,
     * 这里只负责"刚打开时是否已经不能进"的判断。
     */
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val safeEvent = event ?: return
        if (safeEvent.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
            safeEvent.eventType != AccessibilityEvent.TYPE_WINDOWS_CHANGED
        ) {
            return
        }
        val packageName = safeEvent.packageName?.toString()?.trim().orEmpty()
        if (packageName.isBlank()) return

        // 同一应用内的窗口切换 (Activity 跳转) 不算离开, 直接忽略
        val previous = currentForegroundPackage
        if (previous == packageName) return
        currentForegroundPackage = packageName

        if (previous != null && previous != packageName) {
            // 记录离开时刻: 是否算"新的一次"由下次打开时的间隔决定
            serviceScope.launch {
                runCatching { sessionLimiter.noteBackground(previous) }
                    .onFailure { Log.w(TAG, "记录离开前台失败: $previous", it) }
            }
        }

        // Aveline 自身绝不参与限额执行 (force-stop 自身会撤销无障碍授权)
        if (SelfPackageGuard.isSelf(applicationContext, packageName)) return
        // 只从轻量本地缓存判断是否受限, 避免每个窗口事件都去查 UsageStats
        if (sessionLimiter.policyFor(packageName) == null) return

        val now = System.currentTimeMillis()
        if (now - (lastCheckAt[packageName] ?: 0L) < PACKAGE_CHECK_THROTTLE_MS) return
        if (!checksInFlight.add(packageName)) return
        lastCheckAt[packageName] = now

        serviceScope.launch {
            try {
                enforceForegroundApp(packageName)
            } catch (error: Exception) {
                Log.e(TAG, "即时限额检查失败: $packageName", error)
            } finally {
                checksInFlight.remove(packageName)
            }
        }
    }

    /**
     * 受限应用进入前台时的即时判定。超限时回桌面 + 强退 + 通知。
     *
     * @return 下一次轮询的间隔 (毫秒)
     */
    private suspend fun enforceForegroundApp(packageName: String): Long {
        if (!contextRepository.hasUsageStatsPermission()) return TICK_IDLE_MS
        val decision = sessionLimiter.noteForeground(packageName)
        return when (decision) {
            is SessionLimiter.LimitDecision.Block -> {
                usageLimitEnforcer.block(packageName, decision)
                // 已经踢回桌面, 等下一个窗口事件再触发
                TICK_IDLE_MS
            }

            is SessionLimiter.LimitDecision.Allow -> {
                // 快到单次额度时把轮询间隔压到"剩余时间", 让拦截精确到秒
                if (decision.sessionLimitMs > 0) {
                    val remaining = decision.sessionLimitMs - decision.sessionUsedMs
                    if (remaining < TICK_ACTIVE_MS) {
                        return remaining.coerceIn(TICK_MIN_MS, TICK_ACTIVE_MS)
                    }
                }
                TICK_ACTIVE_MS
            }
        }
    }

    /**
     * 前台应用限额轮询: **单次额度的主要执行路径**。
     *
     * 15 分钟的 WorkManager 周期对"单次最多 10 分钟"完全不够精确 (而且周期任务
     * 本来就不是精确闹钟), 所以持续使用期间的额度判定放在这里做:
     * - 前台是受限应用时每 [TICK_ACTIVE_MS] 判定一次, 临近上限时自动缩短到剩余时间
     * - 前台不是受限应用 (或桌面) 时降到 [TICK_IDLE_MS], 几乎不产生开销
     */
    private fun startForegroundTicker() {
        // 部分 ROM 会在未 unbind 的情况下再次回调 onServiceConnected, 防重复启动
        if (tickerJob?.isActive == true) return
        tickerJob = serviceScope.launch {
            while (true) {
                val delayMs = try {
                    val pkg = currentForegroundPackage
                    if (pkg == null || SelfPackageGuard.isSelf(applicationContext, pkg)) {
                        TICK_IDLE_MS
                    } else if (sessionLimiter.policyFor(pkg) == null) {
                        TICK_IDLE_MS
                    } else if (!checksInFlight.add(pkg)) {
                        TICK_ACTIVE_MS
                    } else {
                        try {
                            enforceForegroundApp(pkg)
                        } finally {
                            checksInFlight.remove(pkg)
                        }
                    }
                } catch (e: CancellationException) {
                    throw e // 服务销毁时必须让协程真正结束, 不能被兜底 catch 吞掉
                } catch (e: Exception) {
                    Log.w(TAG, "前台限额轮询异常: ${e.message}")
                    TICK_IDLE_MS
                }
                delay(delayMs)
            }
        }
    }

    /**
     * 必须实现的 abstract 方法。服务被系统中断时调用, 留空。
     */
    override fun onInterrupt() {
        // 不处理
    }

    // ── 手势操作 ────────────────────────────────────────

    /**
     * 在指定坐标点击。
     * 用 GestureDescription 单 stroke 的 press 即可。
     */
    suspend fun click(x: Float, y: Float): Boolean = withContext(Dispatchers.Main) {
        performGesture(x, y, x, y, 50L)
    }

    /**
     * 从 (startX, startY) 滑动到 (endX, endY), 持续 durationMs 毫秒。
     */
    suspend fun swipe(
        startX: Float,
        startY: Float,
        endX: Float,
        endY: Float,
        durationMs: Long = 300L
    ): Boolean = withContext(Dispatchers.Main) {
        performGesture(startX, startY, endX, endY, durationMs)
    }

    /**
     * 执行单 stroke 手势。dispatchGesture 必须在主线程调用且是异步的,
     * 用 callback 等待完成。本方法要求在主线程执行 (由 click/swipe 用 withContext(Main) 保证)。
     */
    private suspend fun performGesture(
        startX: Float,
        startY: Float,
        endX: Float,
        endY: Float,
        durationMs: Long
    ): Boolean = suspendCancellableCoroutine { cont ->
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            // GestureDescription 从 Android N (24) 起可用, 但本应用 minSdk=26, 所以不会到这里
            if (cont.isActive) cont.resume(false)
            return@suspendCancellableCoroutine
        }

        val path = Path().apply {
            moveTo(startX, startY)
            lineTo(endX, endY)
        }
        val stroke = GestureDescription.StrokeDescription(
            path, 0L, durationMs
        )
        val gesture = GestureDescription.Builder()
            .addStroke(stroke)
            .build()

        val callback = object : AccessibilityService.GestureResultCallback() {
            override fun onCompleted(gesture: GestureDescription?) {
                if (cont.isActive) cont.resume(true)
            }

            override fun onCancelled(gesture: GestureDescription?) {
                Log.w(TAG, "手势被取消: ($startX,$startY)→($endX,$endY)")
                if (cont.isActive) cont.resume(false)
            }
        }

        val dispatched = dispatchGesture(gesture, callback, null)
        if (!dispatched) {
            if (cont.isActive) cont.resume(false)
        }
    }

    // ── 全局操作 ────────────────────────────────────────

    /**
     * 在任意线程安全执行一个需要主线程的 block, 并同步等待其返回结果。
     * performGlobalAction / rootInActiveWindow 等 API 必须在主线程调用,
     * 否则会抛 RuntimeException 导致无障碍服务崩溃被系统停用。
     */
    private fun <T> runOnMainThread(block: () -> T): T {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            return block()
        }
        var result: T? = null
        var error: Throwable? = null
        val latch = java.util.concurrent.CountDownLatch(1)
        mainHandler.post {
            try {
                result = block()
            } catch (t: Throwable) {
                error = t
            } finally {
                latch.countDown()
            }
        }
        latch.await()
        error?.let { throw it }
        @Suppress("UNCHECKED_CAST")
        return result as T
    }

    /** 模拟返回键 */
    fun goBack(): Boolean = runOnMainThread {
        performGlobalAction(GLOBAL_ACTION_BACK)
    }

    /** 模拟桌面键 */
    fun goHome(): Boolean = runOnMainThread {
        performGlobalAction(GLOBAL_ACTION_HOME)
    }

    /** 打开最近任务 */
    fun openRecents(): Boolean = runOnMainThread {
        performGlobalAction(GLOBAL_ACTION_RECENTS)
    }

    /** 打开通知栏 */
    fun openNotifications(): Boolean = runOnMainThread {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
        } else false
    }

    /** 打开快速设置 (从顶部下拉) */
    fun openQuickSettings(): Boolean = runOnMainThread {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS)
        } else false
    }

    // ── 节点查找与点击 ───────────────────────────────────

    /**
     * 查找包含指定文字的节点并点击。
     *
     * 搜索策略:
     * 1. findAccessibilityNodeInfosByText(text) 系统底层搜索
     * 2. 优先 click 父节点 (很多文字本身不能 click, 父布局才能)
     * 3. 找不到父节点则 click 自身
     *
     * @param text 要查找的精确文字 (不模糊)
     * @param clickParent 如果节点自身不可点击, 是否点击父节点
     * @return true=找到并 click 成功
     */
    suspend fun findAndClickByText(text: String, clickParent: Boolean = true): Boolean =
        withContext(Dispatchers.Main) {
            val root = rootInActiveWindow ?: return@withContext false
            try {
                val nodes = root.findAccessibilityNodeInfosByText(text)
                if (nodes.isNullOrEmpty()) return@withContext false

                // 优先找自身可点击的节点 (nodes 是 Java 集合, 元素可能为 null, 用安全调用)
                val target: AccessibilityNodeInfo? = nodes.firstOrNull { it?.isClickable == true }
                    ?: if (clickParent) {
                        nodes.firstNotNullOfOrNull { it?.parent }
                    } else null
                    ?: nodes.firstOrNull()

                target?.performAction(AccessibilityNodeInfo.ACTION_CLICK) ?: false
            } catch (e: Exception) {
                Log.w(TAG, "findAndClickByText 失败: ${e.message}")
                false
            }
        }

    /**
     * 通过 View ID 查找节点并点击。
     *
     * View ID 格式: "包名:id/id_name" (如 "com.android.settings:id/switch_widget")
     *
     * @param viewId 完整的 View ID
     * @return true=找到并 click 成功
     */
    suspend fun findAndClickById(viewId: String): Boolean =
        withContext(Dispatchers.Main) {
            val root = rootInActiveWindow ?: return@withContext false
            try {
                val nodes = root.findAccessibilityNodeInfosByViewId(viewId)
                if (nodes.isNullOrEmpty()) return@withContext false

                val target: AccessibilityNodeInfo? =
                    nodes.firstOrNull { it?.isClickable == true } ?: nodes.firstOrNull()
                target?.performAction(AccessibilityNodeInfo.ACTION_CLICK) ?: false
            } catch (e: Exception) {
                Log.w(TAG, "findAndClickById 失败: ${e.message}")
                false
            }
        }

    /**
     * 列出当前屏幕上包含指定文字的所有节点信息 (用于让 AI 知道屏幕有什么)。
     *
     * @param maxResults 最多返回的节点数
     * @return 节点信息列表: 每个 entry 包含 text/desc/class/scrollable/clickable
     */
    fun listNodesWithText(maxResults: Int = 50): List<Map<String, Any?>> = runOnMainThread {
        val root = rootInActiveWindow ?: return@runOnMainThread emptyList()
        val result = mutableListOf<Map<String, Any?>>()
        try {
            collectNodesWithText(root, result, depth = 0, maxResults = maxResults)
        } catch (e: Exception) {
            Log.w(TAG, "listNodesWithText 失败: ${e.message}")
        }
        result
    }

    private fun collectNodesWithText(
        node: AccessibilityNodeInfo,
        out: MutableList<Map<String, Any?>>,
        depth: Int,
        maxResults: Int
    ) {
        if (depth > MAX_TREE_DEPTH || out.size >= maxResults) return

        val text = node.text?.toString()?.takeIf { it.isNotBlank() }
        val desc = node.contentDescription?.toString()?.takeIf { it.isNotBlank() }
        if (text != null || desc != null) {
            out.add(mapOf(
                "text" to text,
                "description" to desc,
                "class" to (node.className?.toString() ?: ""),
                "package_name" to (node.packageName?.toString() ?: ""),
                "view_id" to (node.viewIdResourceName ?: ""),
                "clickable" to node.isClickable,
                "scrollable" to node.isScrollable
            ))
        }

        val childCount = node.childCount
        for (i in 0 until childCount) {
            val child = node.getChild(i) ?: continue
            collectNodesWithText(child, out, depth + 1, maxResults)
        }
    }

    /**
     * Dump 当前屏幕上所有可见文本 (按树形结构), 主要用于调试 / 让 AI 看屏幕内容。
     *
     * @return 多行文本, 每行带缩进表示层级
     */
    fun dumpVisibleText(): String = runOnMainThread {
        val root = rootInActiveWindow ?: return@runOnMainThread "无活动窗口"
        val sb = StringBuilder()
        try {
            dumpNode(root, 0, sb)
            val result = sb.toString()
            // 截断避免超长
            if (result.length > MAX_DUMP_TEXT_LEN) {
                result.substring(0, MAX_DUMP_TEXT_LEN) + "\n... (已截断)"
            } else {
                result
            }
        } catch (e: Exception) {
            Log.w(TAG, "dumpVisibleText 失败: ${e.message}")
            "dump 失败: ${e.message}"
        }
    }

    private fun dumpNode(node: AccessibilityNodeInfo, depth: Int, sb: StringBuilder) {
        if (depth > MAX_TREE_DEPTH) return

        val indent = "  ".repeat(depth)
        val text = node.text?.toString().orEmpty()
        val desc = node.contentDescription?.toString().orEmpty()
        val cls = node.className?.toString()?.substringAfterLast('.').orEmpty()
        val clickable = if (node.isClickable) "[click]" else ""
        val scrollable = if (node.isScrollable) "[scroll]" else ""

        // 只输出有内容的节点, 减少噪音
        if (text.isNotEmpty() || desc.isNotEmpty() || clickable.isNotEmpty() || scrollable.isNotEmpty()) {
            sb.append(indent)
            sb.append(cls)
            if (text.isNotEmpty()) sb.append(" text=\"$text\"")
            if (desc.isNotEmpty()) sb.append(" desc=\"$desc\"")
            if (clickable.isNotEmpty()) sb.append(" $clickable")
            if (scrollable.isNotEmpty()) sb.append(" $scrollable")
            sb.append("\n")
        }

        val childCount = node.childCount
        for (i in 0 until childCount) {
            val child = node.getChild(i) ?: continue
            dumpNode(child, depth + 1, sb)
        }
    }
}
