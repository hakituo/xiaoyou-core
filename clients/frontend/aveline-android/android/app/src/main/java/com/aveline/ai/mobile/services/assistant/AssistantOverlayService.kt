package com.aveline.ai.mobile.services.assistant

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.util.Log
import android.view.Gravity
import android.view.ViewTreeObserver
import android.view.WindowManager
import androidx.compose.ui.platform.ComposeView
import androidx.core.app.NotificationCompat
import androidx.lifecycle.ViewModelStore
// 注意：这三个是 **Kotlin 扩展函数**，不是类。
// 不存在 androidx.lifecycle.ViewTreeLifecycleOwner 这样的类型，
// 写 ViewTreeXxxOwner.set(view, owner) 会直接 Unresolved reference。
import androidx.lifecycle.setViewTreeLifecycleOwner
import androidx.lifecycle.setViewTreeViewModelStoreOwner
import androidx.savedstate.setViewTreeSavedStateRegistryOwner
import com.aveline.ai.R
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.presentation.assistant.AssistantCapsuleOverlay
import com.aveline.ai.mobile.presentation.assistant.AssistantCapsuleStage
import com.aveline.ai.mobile.presentation.assistant.AssistantCapsuleViewModel
import com.aveline.ai.mobile.presentation.assistant.ports.AssistantBackendPort
import com.aveline.ai.mobile.presentation.assistant.ports.AssistantSpeechPort
import com.aveline.ai.mobile.presentation.theme.AvelineTheme
import com.aveline.ai.mobile.services.VoiceInputManager
import com.aveline.ai.mobile.services.foreground.ForegroundServiceTypePolicy
import com.aveline.ai.mobile.utils.AppForegroundTracker
import com.aveline.ai.mobile.utils.HapticFeedbackManager
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlin.math.roundToInt
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * 语音助手的**跨应用悬浮窗**。
 *
 * 为什么是独立 Service 而不是挂在 Activity 上：
 * - 只有系统窗口层（[WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY]）才能出现在
 *   桌面和其它 App 之上；挂在 Activity 的 Compose 树里出了本 App 就没了；
 * - 系统窗口的 Z 序高于输入法（2038 > 2011），所以它能**盖在输入法上面**，
 *   也不会像 Activity 内容那样被输入法顶走（配合 `SOFT_INPUT_ADJUST_NOTHING`）；
 * - 位置就是窗口坐标（x/y），拖动直接改坐标 —— 想拖到哪就拖到哪，
 *   不像容器内布局那样被限制在一个矩形里。
 *
 * App 自己在前台时会**自动隐藏**：App 内有完整界面，悬浮球只会挡视野。
 * 判定复用 [AppForegroundTracker]（进程级前后台流），不需要额外权限。
 *
 * 前置条件：用户必须手动开「显示在其他应用上层」（[AssistantOverlayPermission]），
 * 没授权时本服务照常存活但不加窗口 —— 引导由 MainActivity 负责。
 *
 * **容错约定（本服务的硬要求）**：本服务是唯一会追着「App 切到后台」那一刻做动作的组件
 * （前后台流一翻成后台就挂系统窗口），所以它**不允许**任何异常逃到进程层 —— 逃出去就是
 * 「刚切出去就被杀」。三条主路径（[onCreate] 初始化、[startForegroundCompat] 挂前台、
 * [attachOverlay] 加窗口）全部有兜底，失败时降级而不是崩溃。
 */
@AndroidEntryPoint
class AssistantOverlayService : Service() {

    @Inject
    lateinit var appPreferences: AppPreferences

    @Inject
    lateinit var voiceInputManager: VoiceInputManager

    @Inject
    lateinit var backendPort: AssistantBackendPort

    @Inject
    lateinit var speechPort: AssistantSpeechPort

    @Inject
    lateinit var haptics: HapticFeedbackManager

    /**
     * 服务内部协程作用域。
     *
     * **必须挂 [CoroutineExceptionHandler]**：`SupervisorJob` 只保证「一条子协程失败不取消
     * 其它子协程」，它**不负责兜住异常** —— 没有 handler 时未捕获异常会一路交到线程默认
     * 未捕获处理器，被 `CrashHandler` 记档后**直接杀掉整个进程**。而这里跑的是
     * 「切后台 → 挂悬浮窗」这条链，异常逃出去的表现就是「刚切出去就被杀」。
     */
    private val serviceScope = CoroutineScope(
        SupervisorJob() + Dispatchers.Main.immediate + CoroutineExceptionHandler { _, error ->
            Log.e(TAG, "助手悬浮窗协程异常(已兜底, 不崩进程)", error)
        }
    )

    /**
     * 存放手工构造的胶囊 ViewModel，只为在 onDestroy 时能正常触发它的 `onCleared()`
     * （手动 new 出来的 ViewModel 不挂在任何 store 上，不清会漏掉 viewModelScope 的取消）。
     *
     * 刻意**不**和 [AssistantOverlayLifecycleOwner] 共用 store：那个 owner 会随
     * 「App 进前台隐藏 / 退后台显示」反复创建销毁，共用一个 store 就会在第一次隐藏时
     * 把胶囊 ViewModel clear 掉，之后再显示出来它已经死了（viewModelScope 已取消，
     * 状态流再也不更新）。
     */
    private val overlayViewModelStore = ViewModelStore()

    private lateinit var windowManager: WindowManager
    private lateinit var capsuleViewModel: AssistantCapsuleViewModel

    private var overlayView: ComposeView? = null
    private var overlayParams: WindowManager.LayoutParams? = null
    private var overlayLifecycleOwner: AssistantOverlayLifecycleOwner? = null

    private var lastMeasuredWidth = 0
    private var lastMeasuredHeight = 0

    /** 当前实际生效的前台服务类型，[ForegroundServiceTypePolicy.TYPE_NONE] 表示未挂上前台。 */
    private var activeFgsType: Int = ForegroundServiceTypePolicy.TYPE_NONE

    /** 是否已拿到前台身份。拿不到就 stopSelf，不留一个会被系统按超时杀掉的半死服务。 */
    private var foregroundReady = false

    /** 配额冷却结束后重新挂前台的定时任务。 */
    private var rearmJob: Job? = null

    /**
     * 内容尺寸变化后同步一次窗口。
     *
     * 窗口是 WRAP_CONTENT 的，而胶囊会在「收起的小圆柱」和「展开的声波条」之间改宽度；
     * 不主动 updateViewLayout 的话窗口还停在旧尺寸上，展开部分会被裁掉。
     */
    private val windowSizeSyncListener = ViewTreeObserver.OnGlobalLayoutListener {
        syncWindowSize()
    }

    override fun onCreate() {
        super.onCreate()

        // Service 的 onCreate 抛未捕获异常 = 整个进程崩溃。初始化失败（Hilt 注入缺失、
        // 构造 ViewModel 抛错等）时宁可不要悬浮窗，也不能把 App 带走。
        try {
            initialize()
        } catch (error: Exception) {
            Log.e(TAG, "onCreate 初始化异常(已兜底)", error)
            stopSelf()
            return
        }

        startForegroundCompat()
        if (!foregroundReady) {
            // 候选类型全被系统拒绝：不挂前台的 Service 会在数秒内被系统按
            // ForegroundServiceDidNotStartInTimeException 杀进程，所以主动停掉自己 ——
            // 只结束这个服务，App 进程与界面照常。
            Log.w(TAG, "前台身份获取失败, 主动停止服务, 避免系统按超时杀进程")
            stopSelf()
            return
        }

        // 总开关关着就不该有活着的服务。最常见的来源是升级安装后系统按 START_STICKY
        // 把上一次的服务恢复起来（那时还没有"默认关闭"这回事），既然现在默认关闭，
        // 就立刻收工，别白占一条常驻通知。
        //
        // 放在 startForegroundCompat 之后是为了先拿到前台身份再退出：本服务是从
        // startForegroundService 语境起来的，不调 startForeground 就 stopSelf，
        // Android 12+ 会抛 ForegroundServiceDidNotStartInTimeException。
        if (!appPreferences.assistantCapsuleEnabled) {
            Log.i(TAG, "助手总开关已关闭，服务立即收工")
            stopSelf()
            return
        }

        observeForegroundState()
        observeComposerFocus()
        isRunning = true
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // 通知栏动作与系统重启（START_STICKY）都会走到这里，任何异常都不能外抛。
        try {
            when (intent?.action) {
                ACTION_STOP -> {
                    Log.i(TAG, "收到停止指令，关闭悬浮助手")
                    stopSelf()
                    return START_NOT_STICKY
                }

                // onCreate 兜底走了 stopSelf 分支时 ViewModel 可能还没建出来
                ACTION_SHOW -> if (::capsuleViewModel.isInitialized) capsuleViewModel.show()

                else -> Unit
            }
        } catch (error: Exception) {
            Log.e(TAG, "onStartCommand 异常(已兜底): ${error.message}", error)
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    /**
     * Android 15+ 前台服务超时回调 (单参数版本)。
     * dataSync 类型在 24 小时内累计跑满 6 小时后由系统调用, 只有几秒宽限期。
     */
    override fun onTimeout(startId: Int) {
        handleForegroundTimeout(startId, activeFgsType)
    }

    /** Android 15+ 前台服务超时回调 (带类型版本, 系统会优先调这个)。 */
    override fun onTimeout(startId: Int, fgsType: Int) {
        handleForegroundTimeout(startId, fgsType)
    }

    override fun onDestroy() {
        isRunning = false
        rearmJob?.cancel()
        rearmJob = null
        try {
            detachOverlay()
            overlayViewModelStore.clear()
        } catch (error: Exception) {
            Log.e(TAG, "onDestroy 清理异常(已兜底): ${error.message}", error)
        }
        serviceScope.cancel()
        super.onDestroy()
    }

    // ── 初始化 ────────────────────────────────────────────────────────────────

    private fun initialize() {
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager

        // Service 里没有 Hilt 的 ViewModelProvider.Factory（那是 @AndroidEntryPoint 的
        // Activity/Fragment 才有的），hiltViewModel() 在这里构造不出来，只能手工组装后
        // 显式传给 Compose —— 这也是 AssistantCapsuleOverlay 要求传 viewModel 的原因。
        capsuleViewModel = AssistantCapsuleViewModel(
            appPreferences = appPreferences,
            voiceInputManager = voiceInputManager,
            backendPort = backendPort,
            speechPort = speechPort,
            haptics = haptics
        )
        overlayViewModelStore.put(VIEW_MODEL_KEY, capsuleViewModel)

        warnIfNotificationNotVisible()
    }

    private fun observeForegroundState() {
        // 不在这里直接 attach：交给前后台流决定（StateFlow 会立刻发射当前值）。
        // 若当下 App 正在前台，就是"不显示"，避免用户一进 App 就看到悬浮球。
        serviceScope.launch {
            AppForegroundTracker.isForegroundFlow.collect { inApp ->
                try {
                    if (inApp) detachOverlay() else attachOverlay()
                } catch (cancelled: CancellationException) {
                    // 取消是正常收尾（onDestroy 里 cancel 掉 scope），必须原样上抛，
                    // 吞掉会让上层误以为这一轮正常跑完。
                    throw cancelled
                } catch (error: Exception) {
                    // 这里再加一层兜底：即便以后有人往 attach/detach 里加了会抛的代码，
                    // 也只是这一次切换失败，不会升级成进程崩溃。
                    Log.e(TAG, "响应前后台切换失败(已兜底): ${error.message}", error)
                }
            }
        }
    }

    /**
     * 输入面板需要键盘，而窗口默认带 `FLAG_NOT_FOCUSABLE` —— 那个 flag 下系统**压根不会弹 IME**。
     *
     * 所以按阶段动态切：进输入面板时摘掉 `FLAG_NOT_FOCUSABLE`（窗口可聚焦、IME 能弹出来），
     * 离开面板立刻加回去，保住"平时绝不抢下层 App 焦点"这个前提
     * （不然用户在别的 App 里打字时，悬浮窗会把焦点抢走、输入法弹给悬浮窗）。
     */
    private fun observeComposerFocus() {
        serviceScope.launch {
            capsuleViewModel.stage.collect { stage ->
                try {
                    applyWindowFocusable(stage is AssistantCapsuleStage.Composing)
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (error: Exception) {
                    Log.e(TAG, "切换窗口可聚焦状态失败(已兜底): ${error.message}", error)
                }
            }
        }
    }

    /** 按需切换窗口是否可聚焦。窗口没挂上时静默跳过。 */
    private fun applyWindowFocusable(focusable: Boolean) {
        val view = overlayView ?: return
        val params = overlayParams ?: return

        val newFlags = if (focusable) {
            params.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
        } else {
            params.flags or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        }
        if (newFlags == params.flags) return

        params.flags = newFlags
        runCatching { windowManager.updateViewLayout(view, params) }
            .onFailure { Log.w(TAG, "切换窗口可聚焦失败: ${it.message}") }
    }

    /**
     * 通知权限只做提示，**不做拦截**。
     *
     * 前台服务的通知在 Android 13+ 是豁免 POST_NOTIFICATIONS 的：用户拒绝后只是不在通知栏
     * 显示，不会让 startForeground 抛异常。所以这里不像常驻保活服务那样把通知权限当成启动
     * 前置条件（那会让悬浮窗在没通知权限时直接不可用）；真正的防线是
     * [startForegroundCompat] 里逐类型的 try/catch。留这条日志是为了排查时能一眼分清
     * 「通知没显示」和「服务没起来」。
     */
    private fun warnIfNotificationNotVisible() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        if (!granted) {
            Log.w(TAG, "未授予通知权限：前台通知不会出现在通知栏（不影响悬浮窗与服务运行）")
        }
    }

    // ── 悬浮窗生命周期 ────────────────────────────────────────────────────────

    private fun attachOverlay() {
        if (overlayView != null) return
        if (!appPreferences.assistantCapsuleEnabled) {
            Log.i(TAG, "助手开关已关闭，不加悬浮窗")
            return
        }
        if (!AssistantOverlayPermission.canDrawOverlays(this)) {
            Log.w(TAG, "缺少「显示在其他应用上层」权限，悬浮窗不显示")
            return
        }

        var lifecycleOwner: AssistantOverlayLifecycleOwner? = null
        var addedView: ComposeView? = null
        try {
            val owner = AssistantOverlayLifecycleOwner()
            lifecycleOwner = owner
            val view = ComposeView(this).apply {
                // 三个 owner 必须在 setContent / addView 之前挂好，否则 Compose 直接抛
                // 「ViewTreeLifecycleOwner not found」。
                // 用扩展函数（setViewTreeXxxOwner）而不是 ViewTreeXxxOwner.set(...)：
                // 后者需要存在同名类，而这三者在 AndroidX 里只有扩展函数，没有类。
                setViewTreeLifecycleOwner(owner)
                setViewTreeViewModelStoreOwner(owner)
                setViewTreeSavedStateRegistryOwner(owner)
                setContent {
                    AvelineTheme {
                        AssistantCapsuleOverlay(
                            viewModel = capsuleViewModel,
                            onDrag = ::moveWindow,
                            onDragEnd = ::persistWindowPosition
                        )
                    }
                }
            }

            val params = buildLayoutParams()
            // setContent 的组合期与 addView 都可能抛（owner 缺失、ROM 拒绝该窗口类型等），
            // 所以整段都要在 try 里：这是本服务唯一追着「切到后台」跑的代码，
            // 它跑在 serviceScope 的 collector 里，抛出去就是进程级崩溃。
            windowManager.addView(view, params)
            addedView = view

            overlayView = view
            overlayParams = params
            overlayLifecycleOwner = owner
            lastMeasuredWidth = 0
            lastMeasuredHeight = 0

            owner.onCreate()
            owner.onStart()
            owner.onResume()
            view.viewTreeObserver.addOnGlobalLayoutListener(windowSizeSyncListener)

            // 重新挂窗口时按当前阶段补一次焦点状态：StateFlow 不会因为重新订阅就把旧值重发，
            // 若此刻正处在输入面板（例如 App 切前后台把窗口摘了又挂回来），
            // 不补这一次窗口就是不可聚焦的，键盘再也弹不出来。
            applyWindowFocusable(
                capsuleViewModel.stage.value is AssistantCapsuleStage.Composing
            )

            Log.i(TAG, "悬浮窗已挂载 at (${params.x}, ${params.y})")
        } catch (error: Exception) {
            Log.e(TAG, "挂载悬浮窗失败(已兜底, 不崩进程): ${error.message}", error)
            // 把半挂状态清干净：残留的 View 会让下次「切后台」时开头那句
            // `overlayView != null` 直接 return，悬浮窗从此再也出不来。
            runCatching {
                addedView?.let { if (it.isAttachedToWindow) windowManager.removeViewImmediate(it) }
            }.onFailure { Log.w(TAG, "回滚残留悬浮窗失败: ${it.message}") }
            runCatching { lifecycleOwner?.onDestroy() }
                .onFailure { Log.w(TAG, "回滚悬浮窗宿主失败: ${it.message}") }
            overlayView = null
            overlayParams = null
            overlayLifecycleOwner = null
        }
    }

    private fun detachOverlay() {
        val view = overlayView ?: return
        persistWindowPosition()

        runCatching { view.viewTreeObserver.removeOnGlobalLayoutListener(windowSizeSyncListener) }
        runCatching {
            if (view.isAttachedToWindow) windowManager.removeViewImmediate(view)
        }.onFailure { Log.w(TAG, "移除悬浮窗失败: ${it.message}") }

        overlayView = null
        overlayParams = null

        // 先摘窗口再销毁 owner：反过来的话 Compose 会在窗口还挂着的时候开始拆
        runCatching { overlayLifecycleOwner?.onDestroy() }
            .onFailure { Log.w(TAG, "销毁悬浮窗宿主失败: ${it.message}") }
        overlayLifecycleOwner = null
    }

    private fun buildLayoutParams(): WindowManager.LayoutParams {
        val flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            // 窗口**之外**的触摸直接传给下层 App；窗口内由 Compose 自己决定要不要消费
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS

        return WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            flags,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            // 关键：不让输入法把悬浮窗顶跑，它要压在输入法之上而不是被顶上去
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING
            val (initialX, initialY) = resolveInitialPosition()
            x = initialX
            y = initialY
        }
    }

    /** 拖动窗口。坐标直接加增量再夹到屏幕内，所以不存在「只能在一个矩形里移动」的限制。 */
    private fun moveWindow(deltaXPx: Float, deltaYPx: Float) {
        val view = overlayView ?: return
        val params = overlayParams ?: return

        val (targetX, targetY) = clampToScreen(
            params.x + deltaXPx.roundToInt(),
            params.y + deltaYPx.roundToInt(),
            view.width,
            view.height
        )
        if (targetX == params.x && targetY == params.y) return

        params.x = targetX
        params.y = targetY
        runCatching { windowManager.updateViewLayout(view, params) }
            .onFailure { Log.w(TAG, "移动悬浮窗失败: ${it.message}") }
    }

    /** 松手才落盘，没必要拖着的时候一直写 SharedPreferences。 */
    private fun persistWindowPosition() {
        val params = overlayParams ?: return
        // 调用方是 Compose 的手势回调（主线程）与 detachOverlay，抛出去同样会崩进程
        runCatching {
            appPreferences.assistantOverlayX = params.x
            appPreferences.assistantOverlayY = params.y
        }.onFailure { Log.w(TAG, "保存悬浮窗位置失败: ${it.message}") }
    }

    private fun syncWindowSize() {
        val view = overlayView ?: return
        val params = overlayParams ?: return

        if (view.width == lastMeasuredWidth && view.height == lastMeasuredHeight) return
        lastMeasuredWidth = view.width
        lastMeasuredHeight = view.height
        // 宽高都是 WRAP_CONTENT，让系统重新量一次即可
        runCatching { windowManager.updateViewLayout(view, params) }
            .onFailure { Log.w(TAG, "同步悬浮窗尺寸失败: ${it.message}") }
    }

    private fun resolveInitialPosition(): Pair<Int, Int> {
        val savedX = appPreferences.assistantOverlayX
        val savedY = appPreferences.assistantOverlayY
        if (savedX >= 0 && savedY >= 0) return savedX to savedY

        val metrics = resources.displayMetrics
        val defaultWidth = (DEFAULT_WIDTH_DP * metrics.density).roundToInt()
        val bottomMargin = (DEFAULT_BOTTOM_MARGIN_DP * metrics.density).roundToInt()
        return ((metrics.widthPixels - defaultWidth) / 2).coerceAtLeast(0) to
            (metrics.heightPixels - bottomMargin).coerceAtLeast(0)
    }

    private fun clampToScreen(x: Int, y: Int, viewWidth: Int, viewHeight: Int): Pair<Int, Int> {
        val metrics = resources.displayMetrics
        val maxX = (metrics.widthPixels - viewWidth).coerceAtLeast(0)
        val maxY = (metrics.heightPixels - viewHeight).coerceAtLeast(0)
        return x.coerceIn(0, maxX) to y.coerceIn(0, maxY)
    }

    // ── 前台服务与通知 ────────────────────────────────────────────────────────

    /**
     * 按 [ForegroundServiceTypePolicy] 的优先级挂前台：specialUse → dataSync → 无类型，
     * 每个类型单独 try/catch。
     *
     * 与常驻保活服务同一套写法，原因也是同一个：`startForeground` 会因为
     * 「类型没在 Manifest 声明 / 权限没申请 / 系统不允许从后台启动 / Android 13+ 通知被拒」
     * 等一堆原因抛异常，而它抛在 `onCreate` 里就是**进程级崩溃**。逐类型兜底后，
     * 某一类被系统拒绝最多是降一级，不会把 App 带走。
     *
     * 处于 dataSync 配额冷却期时只尝试无配额限制的 specialUse，拿不到就等冷却结束后由
     * [scheduleForegroundRearm] 重挂 —— 否则会「超时 → 重启 → 再超时」死循环。
     */
    private fun startForegroundCompat() {
        val now = System.currentTimeMillis()
        val resumeAt = appPreferences.fgsQuotaResumeAtMs
        val quotaCoolingDown = resumeAt > now

        val notification: Notification
        try {
            createNotificationChannel()
            notification = buildNotification()
        } catch (error: Exception) {
            Log.e(TAG, "构建前台通知失败(已兜底): ${error.message}", error)
            return
        }

        activeFgsType = ForegroundServiceTypePolicy.TYPE_NONE
        foregroundReady = false
        for (type in ForegroundServiceTypePolicy.candidates()) {
            // 冷却期内跳过受配额限制的类型，否则刚挂上就会被系统再次超时
            if (quotaCoolingDown && ForegroundServiceTypePolicy.hasRuntimeQuota(type)) continue
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
                    type != ForegroundServiceTypePolicy.TYPE_NONE
                ) {
                    startForeground(NOTIFICATION_ID, notification, type)
                } else {
                    startForeground(NOTIFICATION_ID, notification)
                }
                activeFgsType = type
                foregroundReady = true
                // 这一次挂上前台说明配额冷却已过去，清掉冷却点
                if (resumeAt != 0L) appPreferences.fgsQuotaResumeAtMs = 0L
                Log.i(TAG, "startForeground 成功 (type=${ForegroundServiceTypePolicy.name(type)})")
                return
            } catch (error: Exception) {
                Log.e(
                    TAG,
                    "startForeground 失败 (type=${ForegroundServiceTypePolicy.name(type)}): " +
                        "${error.message}",
                    error
                )
            }
        }

        // 冷却期内连 specialUse 都没挂上 → 等服务到冷却结束再试一次
        if (quotaCoolingDown) scheduleForegroundRearm(resumeAt - now)
    }

    /**
     * 优雅降级：解除前台状态但保留进程与悬浮窗。
     *
     * 配额到点后若不在数秒内自行解除前台，系统会抛 `RemoteServiceException`
     * **崩掉宿主进程**（正是 Android 15 那条 6 小时配额的限制机制）。
     *
     * 冷却点复用 `appPreferences.fgsQuotaResumeAtMs` 而不是自己记一份：Android 15 的
     * dataSync 配额是**按应用**统计的，两个前台服务共用同一个额度，冷却点也必须共享，
     * 否则这边刚记冷却、那边又把 dataSync 挂回去，照样立刻超时。
     */
    private fun handleForegroundTimeout(startId: Int, fgsType: Int) {
        val type = if (fgsType != ForegroundServiceTypePolicy.TYPE_NONE) fgsType else activeFgsType
        Log.w(TAG, "前台服务超时: startId=$startId type=${ForegroundServiceTypePolicy.name(type)}")
        releaseForegroundState()
        appPreferences.fgsQuotaResumeAtMs = System.currentTimeMillis() + FGS_QUOTA_COOLDOWN_MS
        startForegroundCompat()
    }

    /** 摘掉前台身份（保留通知），并记录当前已不在前台。 */
    private fun releaseForegroundState() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                // DETACH: 通知留在通知栏，只解除前台状态
                stopForeground(STOP_FOREGROUND_DETACH)
            } else {
                @Suppress("DEPRECATION")
                stopForeground(false)
            }
        } catch (error: Exception) {
            Log.e(TAG, "解除前台状态失败: ${error.message}", error)
        }
        activeFgsType = ForegroundServiceTypePolicy.TYPE_NONE
        foregroundReady = false
    }

    /** 冷却结束后重新尝试挂前台。 */
    private fun scheduleForegroundRearm(delayMs: Long) {
        rearmJob?.cancel()
        rearmJob = serviceScope.launch {
            delay(delayMs.coerceAtLeast(1_000L))
            startForegroundCompat()
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return

        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_LOW).apply {
                description = CHANNEL_DESC
                setShowBadge(false)
            }
        )
    }

    private fun buildNotification(): Notification {
        val showIntent = PendingIntent.getService(
            this,
            REQUEST_SHOW,
            Intent(this, AssistantOverlayService::class.java).setAction(ACTION_SHOW),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val stopIntent = PendingIntent.getService(
            this,
            REQUEST_STOP,
            Intent(this, AssistantOverlayService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(NOTIFICATION_TITLE)
            .setContentText(NOTIFICATION_TEXT)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(showIntent)
            .addAction(
                NotificationCompat.Action.Builder(0, "唤出助手", showIntent).build()
            )
            .addAction(
                NotificationCompat.Action.Builder(0, "关闭", stopIntent).build()
            )
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    companion object {
        private const val TAG = "AssistantOverlay"
        private const val CHANNEL_ID = "aveline_assistant"
        private const val CHANNEL_NAME = "助手悬浮窗"
        private const val CHANNEL_DESC = "在其他应用之上常驻的语音助手入口"
        private const val NOTIFICATION_ID = 1002
        private const val NOTIFICATION_TITLE = "小柚在待命"
        private const val NOTIFICATION_TEXT = "点一下唤出助手；不需要时点「关闭」"
        private const val REQUEST_SHOW = 1102
        private const val REQUEST_STOP = 1103
        private const val DEFAULT_WIDTH_DP = 240f
        private const val DEFAULT_BOTTOM_MARGIN_DP = 96f
        private const val VIEW_MODEL_KEY = "assistant-overlay-capsule"

        /**
         * 前台服务配额耗尽后的冷却时长。
         * Android 15 的 dataSync 配额是「24 小时滚动窗口内累计 6 小时」，等 6 小时后最早的
         * 运行记录已滚出窗口，重新挂前台才有意义；立刻重试只会再次触发 onTimeout。
         * 与常驻保活服务的同名常量保持一致。
         */
        private const val FGS_QUOTA_COOLDOWN_MS = 6 * 60 * 60 * 1000L

        const val ACTION_SHOW = "com.aveline.ai.assistant.action.SHOW"
        const val ACTION_STOP = "com.aveline.ai.assistant.action.STOP"

        /**
         * 服务当前是否在运行。
         *
         * 给调用方一个「要不要发停止指令」的依据：无条件
         * `startService(ACTION_STOP)` 会把没在跑的服务先创建出来再停掉，
         * 前台通知会跟着闪一下（用户能看见的瑕疵）。
         */
        @Volatile
        var isRunning: Boolean = false
            private set

        /** 拉起服务。没有悬浮窗权限时服务仍会启动（用于发通知/等待授权），只是不显示窗口。 */
        fun start(context: Context) {
            val intent = Intent(context, AssistantOverlayService::class.java).setAction(ACTION_SHOW)
            // 后台启动前台服务在 Android 12+ 会被拒（ForegroundServiceStartNotAllowedException），
            // 用户点开 App 属于前台场景，正常能起；起不来也只是一次失败，不影响 App 使用。
            runCatching { context.startForegroundService(intent) }
                .onFailure { Log.w(TAG, "启动助手悬浮窗服务失败: ${it.message}") }
        }

        /** 停服务并从通知栏撤下来。 */
        fun stop(context: Context) {
            runCatching {
                context.startService(
                    Intent(context, AssistantOverlayService::class.java).setAction(ACTION_STOP)
                )
            }.onFailure { Log.w(TAG, "停止助手悬浮窗服务失败: ${it.message}") }
        }
    }
}
