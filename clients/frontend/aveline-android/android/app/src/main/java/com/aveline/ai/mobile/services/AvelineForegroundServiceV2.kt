package com.aveline.ai.mobile.services

import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Binder
import android.os.IBinder
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.local.preferences.RoleScopedPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.data.samsung.SamsungHealthReader
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.domain.repository.HealthRepository
import com.aveline.ai.mobile.services.endpoint.EndpointResolver
import com.aveline.ai.mobile.services.foreground.AccessibilityMonitor
import com.aveline.ai.mobile.services.foreground.ContextSyncController
import com.aveline.ai.mobile.services.foreground.ForegroundNotificationController
import com.aveline.ai.mobile.services.foreground.ForegroundNotificationControllerHolder
import com.aveline.ai.mobile.services.foreground.ForegroundServiceContract
import com.aveline.ai.mobile.services.foreground.ForegroundStartCoordinator
import com.aveline.ai.mobile.services.foreground.ForegroundServiceTypePolicy
import com.aveline.ai.mobile.services.foreground.ResidentPowerController
import com.aveline.ai.mobile.services.foreground.RoleReplyNotifier
import com.aveline.ai.mobile.services.foreground.SamsungHealthSyncController
import com.aveline.ai.mobile.services.foreground.WebSocketCommandCoordinator
import dagger.hilt.android.AndroidEntryPoint
import java.lang.ref.WeakReference
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel

/**
 * Android 前台守护服务薄壳。
 *
 * 只负责 Service 生命周期、Hilt 依赖接线和子控制器编排；通知、WebSocket 指令、
 * 上下文同步、Samsung Health、无障碍监测与 WakeLock 分别由 foreground 包组件负责。
 *
 * 前台类型与配额: 由 [ForegroundServiceTypePolicy] 决定 (优先 specialUse, 回退 dataSync),
 * 并在 Android 15 的 onTimeout() 中优雅降级, 避免 6 小时配额到点把宿主进程崩掉。
 */
@AndroidEntryPoint
class AvelineForegroundServiceV2 : Service() {

    companion object {
        private const val TAG = "AvelineForegroundServiceV2"

        @Volatile
        private var instanceRef: WeakReference<AvelineForegroundServiceV2>? = null

        fun getInstance(): AvelineForegroundServiceV2? = instanceRef?.get()

        fun start(context: Context) = ForegroundServiceContract.start(context)

        fun stop(context: Context) = ForegroundServiceContract.stop(context)

        fun restoreKeepAliveNotification(context: Context, source: String) =
            ForegroundServiceContract.restoreNotification(context, source)

        fun isKeepAliveNotification(notificationId: Int): Boolean =
            ForegroundServiceContract.isKeepAliveNotification(notificationId)

        /**
         * 让服务重新裁决后端通道（局域网 / 公网）并重连 WebSocket。
         *
         * 原来是「把自动发现到的地址写进 backendUrl」，现在地址槽位的写入由
         * ServerDiscoveryManager 负责，服务这边只负责触发裁决与重连。
         */
        fun refreshEndpoint() {
            instanceRef?.get()?.refreshEndpointInternal()
        }
    }

    @Inject
    lateinit var contextRepository: ContextRepository

    @Inject
    lateinit var appPreferences: AppPreferences

    @Inject
    lateinit var webSocketManager: WebSocketManager

    @Inject
    lateinit var notificationManager: AvelineNotificationManager

    @Inject
    lateinit var phoneActionExecutor: PhoneActionExecutor

    @Inject
    lateinit var systemControlExecutor: SystemControlExecutor

    @Inject
    lateinit var samsungHealthReader: SamsungHealthReader

    @Inject
    lateinit var healthRepository: HealthRepository

    /** 主动消息归档用：把角色主动说的话写进对应角色的本地会话。 */
    @Inject
    lateinit var chatRepository: ChatRepository

    /** 主动消息归档后同步会话列表的"最后一条消息"预览。 */
    @Inject
    lateinit var personaLocalMetaRepository: PersonaLocalMetaRepository

    /** 主动消息要落到 role 级会话，而不是旧的 web_{persona}。 */
    @Inject
    lateinit var roleScopedPreferences: RoleScopedPreferences

    /** 后端通道裁决器：服务启动时先选对「局域网 or 公网」再连 WebSocket。 */
    @Inject
    lateinit var endpointResolver: EndpointResolver

    /** 判断某角色的聊天页是否正显示在屏幕上：主动消息在该页可见时不计未读。 */
    @Inject
    lateinit var replyNotifier: RoleReplyNotifier

    private lateinit var serviceScope: CoroutineScope
    private lateinit var notifications: ForegroundNotificationController
    private lateinit var powerController: ResidentPowerController
    private lateinit var contextSyncController: ContextSyncController
    private lateinit var samsungHealthSyncController: SamsungHealthSyncController
    private lateinit var accessibilityMonitor: AccessibilityMonitor
    private lateinit var webSocketCoordinator: WebSocketCommandCoordinator
    private lateinit var startCoordinator: ForegroundStartCoordinator
    private var controllersInitialized = false

    private val binder = LocalBinder()

    inner class LocalBinder : Binder() {
        fun getService(): AvelineForegroundServiceV2 = this@AvelineForegroundServiceV2
    }

    override fun onCreate() {
        super.onCreate()
        instanceRef = WeakReference(this)
        try {
            initializeControllers()
            notifications.createChannels()
            startForegroundCompat()
            A11yDiagnosis.log(applicationContext, "FgSvc", "onCreate startForeground 完成")
        } catch (error: Exception) {
            Log.e(TAG, "onCreate 异常(已兜底): ${error.message}", error)
            A11yDiagnosis.log(applicationContext, "FgSvc", "onCreate 异常兜底: ${error.message}")
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        try {
            if (!controllersInitialized) initializeControllers()
            notifications.createChannels()
            if (intent?.action == ForegroundServiceContract.ACTION_RESTORE_NOTIFICATION) {
                val source = intent.getStringExtra(ForegroundServiceContract.EXTRA_RESTORE_SOURCE)
                    ?: "unknown"
                A11yDiagnosis.log(applicationContext, "FgSvc", "收到常驻通知恢复请求: source=$source")
            }
            A11yDiagnosis.log(
                applicationContext,
                "FgSvc",
                "onStartCommand resident=${appPreferences.residentModeEnabled}"
            )
            startForegroundCompat()

            if (appPreferences.residentModeEnabled) {
                powerController.acquire()
                webSocketCoordinator.ensureConnection()
                contextSyncController.start()
                webSocketCoordinator.startObserving()
                samsungHealthSyncController.start()
            }
            accessibilityMonitor.start()
        } catch (error: Exception) {
            Log.e(TAG, "onStartCommand 编排异常: ${error.message}", error)
            A11yDiagnosis.log(applicationContext, "FgSvc", "onStartCommand 异常: ${error.message}")
        }
        return START_STICKY
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        A11yDiagnosis.log(applicationContext, "FgSvc", "onTaskRemoved (任务栈被移除, 进程可能被回收)")
        super.onTaskRemoved(rootIntent)
    }

    /**
     * Android 15+ 前台服务超时回调 (单参数版本)。
     * dataSync 类型在 24 小时内累计跑满 6 小时后由系统调用, 只有几秒宽限期。
     */
    override fun onTimeout(startId: Int) {
        startCoordinator.handleTimeout(startId)
    }

    /** Android 15+ 前台服务超时回调 (带类型版本, 系统会优先调这个)。 */
    override fun onTimeout(startId: Int, fgsType: Int) {
        startCoordinator.handleTimeout(startId, fgsType)
    }

    override fun onDestroy() {
        A11yDiagnosis.log(applicationContext, "FgSvc", "onDestroy (前台服务被销毁)")
        if (controllersInitialized) {
            contextSyncController.stop()
            samsungHealthSyncController.stop()
            accessibilityMonitor.stop()
            webSocketCoordinator.stop()
            powerController.release()
            startCoordinator.cancelRearm()
        }
        if (::serviceScope.isInitialized) serviceScope.cancel()
        controllersInitialized = false
        if (instanceRef?.get() == this) instanceRef = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent): IBinder = binder

    fun updateNotification(title: String, text: String) {
        if (controllersInitialized) notifications.updateForegroundNotification(title, text)
    }

    private fun refreshEndpointInternal() {
        if (controllersInitialized) webSocketCoordinator.refreshEndpoint()
    }

    private fun initializeControllers() {
        if (controllersInitialized) return
        serviceScope = CoroutineScope(Dispatchers.Default + SupervisorJob())
        notifications = ForegroundNotificationControllerHolder.get(applicationContext, notificationManager)
        powerController = ResidentPowerController(applicationContext)
        contextSyncController = ContextSyncController(
            serviceScope,
            contextRepository,
            appPreferences
        )
        samsungHealthSyncController = SamsungHealthSyncController(
            serviceScope,
            samsungHealthReader,
            healthRepository
        )
        accessibilityMonitor = AccessibilityMonitor(
            applicationContext,
            serviceScope,
            notifications
        )
        webSocketCoordinator = WebSocketCommandCoordinator(
            serviceScope,
            appPreferences,
            webSocketManager,
            endpointResolver,
            notifications,
            phoneActionExecutor,
            systemControlExecutor,
            chatRepository,
            personaLocalMetaRepository,
            roleScopedPreferences,
            replyNotifier
        )
        startCoordinator = ForegroundStartCoordinator(
            service = this,
            notifications = notifications,
            appPreferences = appPreferences,
            scopeProvider = { if (::serviceScope.isInitialized) serviceScope else null }
        )
        controllersInitialized = true
    }

    /**
     * 按 [ForegroundServiceTypePolicy] 的优先级挂前台: specialUse → dataSync → 无类型。
     * 处于 dataSync 配额冷却期时只尝试无配额限制的 specialUse, 拿不到就等冷却结束后由定时任务重挂。
     * 实现见 [ForegroundStartCoordinator.startForegroundCompat]。
     */
    private fun startForegroundCompat() {
        startCoordinator.startForegroundCompat()
    }
}
