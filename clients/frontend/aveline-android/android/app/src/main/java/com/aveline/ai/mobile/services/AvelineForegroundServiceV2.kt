package com.aveline.ai.mobile.services

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.samsung.SamsungHealthReader
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.domain.repository.HealthRepository
import com.aveline.ai.mobile.services.foreground.AccessibilityMonitor
import com.aveline.ai.mobile.services.foreground.ContextSyncController
import com.aveline.ai.mobile.services.foreground.ForegroundNotificationController
import com.aveline.ai.mobile.services.foreground.ForegroundServiceContract
import com.aveline.ai.mobile.services.foreground.ResidentPowerController
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

        fun updateBackendUrl(url: String) {
            instanceRef?.get()?.updateBackendUrlInternal(url)
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

    private lateinit var serviceScope: CoroutineScope
    private lateinit var notifications: ForegroundNotificationController
    private lateinit var powerController: ResidentPowerController
    private lateinit var contextSyncController: ContextSyncController
    private lateinit var samsungHealthSyncController: SamsungHealthSyncController
    private lateinit var accessibilityMonitor: AccessibilityMonitor
    private lateinit var webSocketCoordinator: WebSocketCommandCoordinator
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

    override fun onDestroy() {
        A11yDiagnosis.log(applicationContext, "FgSvc", "onDestroy (前台服务被销毁)")
        if (controllersInitialized) {
            contextSyncController.stop()
            samsungHealthSyncController.stop()
            accessibilityMonitor.stop()
            webSocketCoordinator.stop()
            powerController.release()
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

    private fun updateBackendUrlInternal(url: String) {
        if (controllersInitialized) webSocketCoordinator.updateBackendUrl(url)
    }

    private fun initializeControllers() {
        if (controllersInitialized) return
        serviceScope = CoroutineScope(Dispatchers.Default + SupervisorJob())
        notifications = ForegroundNotificationController(applicationContext, notificationManager)
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
            notifications,
            phoneActionExecutor,
            systemControlExecutor
        )
        controllersInitialized = true
    }

    /** 以 Manifest 声明的 dataSync 类型提交前台通知。 */
    private fun startForegroundCompat() {
        val notification = notifications.createForegroundNotification()
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        } else {
            0
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(ForegroundServiceContract.NOTIFICATION_ID, notification, type)
            } else {
                startForeground(ForegroundServiceContract.NOTIFICATION_ID, notification)
            }
            A11yDiagnosis.log(
                applicationContext,
                "FgSvc",
                "startForeground 成功 (id=${ForegroundServiceContract.NOTIFICATION_ID}, types=$type)"
            )
        } catch (error: Exception) {
            Log.e(TAG, "startForeground 失败, 兜底无类型: ${error.message}")
            try {
                startForeground(ForegroundServiceContract.NOTIFICATION_ID, notification)
                A11yDiagnosis.log(applicationContext, "FgSvc", "startForeground 无类型兜底成功")
            } catch (fallbackError: Exception) {
                Log.e(TAG, "startForeground 全部失败: ${fallbackError.message}", fallbackError)
                A11yDiagnosis.log(
                    applicationContext,
                    "FgSvc",
                    "startForeground 全部失败: ${fallbackError.message}"
                )
            }
        }
    }
}
