package com.aveline.ai.mobile.services.foreground

import android.app.Service
import android.os.Build
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.services.A11yDiagnosis
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * 前台服务「挂前台 / 配额超时降级 / 冷却后重挂」的协调器
 * （从 AvelineForegroundServiceV2 拆出）。
 *
 * 前台类型与配额策略仍由 [ForegroundServiceTypePolicy] 决定，这里只负责
 * 按优先级尝试、记录当前生效类型，并在 Android 15 配额到点后优雅降级。
 */
internal class ForegroundStartCoordinator(
    private val service: Service,
    private val notifications: ForegroundNotificationController,
    private val appPreferences: AppPreferences,
    /** 供冷却结束后重新挂前台的协程作用域；服务未初始化时返回 null。 */
    private val scopeProvider: () -> CoroutineScope?
) {
    /** 当前实际生效的前台服务类型, TYPE_NONE 表示当前处于"非前台"降级状态。 */
    var activeType: Int = ForegroundServiceTypePolicy.TYPE_NONE
        private set

    /** 配额冷却结束后重新挂前台的定时任务。 */
    private var rearmJob: Job? = null

    /**
     * 按 [ForegroundServiceTypePolicy] 的优先级挂前台: specialUse → dataSync → 无类型。
     * 处于 dataSync 配额冷却期时只尝试无配额限制的 specialUse, 拿不到就等冷却结束后由定时任务重挂。
     */
    fun startForegroundCompat() {
        val now = System.currentTimeMillis()
        val resumeAt = appPreferences.fgsQuotaResumeAtMs
        val quotaCoolingDown = resumeAt > now
        if (quotaCoolingDown) {
            A11yDiagnosis.log(
                service.applicationContext,
                "FgSvc",
                "dataSync 配额冷却中, ${(resumeAt - now) / 60_000} 分钟后重试 (期间仅尝试 specialUse)"
            )
        }

        val notification = notifications.createForegroundNotification()
        activeType = ForegroundServiceTypePolicy.TYPE_NONE
        for (type in ForegroundServiceTypePolicy.candidates()) {
            // 冷却期内跳过受配额限制的类型, 否则刚挂上就会被系统再次超时。
            if (quotaCoolingDown && ForegroundServiceTypePolicy.hasRuntimeQuota(type)) continue
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
                    type != ForegroundServiceTypePolicy.TYPE_NONE
                ) {
                    service.startForeground(
                        ForegroundServiceContract.NOTIFICATION_ID,
                        notification,
                        type
                    )
                } else {
                    service.startForeground(ForegroundServiceContract.NOTIFICATION_ID, notification)
                }
                activeType = type
                if (resumeAt != 0L) appPreferences.fgsQuotaResumeAtMs = 0L
                A11yDiagnosis.log(
                    service.applicationContext,
                    "FgSvc",
                    "startForeground 成功 (id=${ForegroundServiceContract.NOTIFICATION_ID}, " +
                        "type=${ForegroundServiceTypePolicy.name(type)})"
                )
                return
            } catch (error: Exception) {
                Log.e(
                    TAG,
                    "startForeground 失败 (type=${ForegroundServiceTypePolicy.name(type)}): " +
                        "${error.message}"
                )
                A11yDiagnosis.log(
                    service.applicationContext,
                    "FgSvc",
                    "startForeground 失败 (type=${ForegroundServiceTypePolicy.name(type)}): " +
                        "${error.message}"
                )
            }
        }
        // 冷却期内 specialUse 也没挂上 → 等服务到冷却结束再试一次。
        if (quotaCoolingDown && activeType == ForegroundServiceTypePolicy.TYPE_NONE) {
            scheduleRearm(resumeAt - now)
        }
    }

    /**
     * Android 15+ 前台服务超时的统一处理（单参数与带类型两个回调都收敛到这里）。
     *
     * 优雅降级: 解除前台状态但保留常驻通知与进程。不在数秒内停止前台状态, 系统会抛
     * RemoteServiceException 崩掉宿主进程; 而直接 stopSelf() 又会让常驻通知消失、
     * WebSocket 断开。见 [releaseForegroundState]。
     */
    fun handleTimeout(startId: Int, fgsType: Int = activeType) {
        val type = if (fgsType != ForegroundServiceTypePolicy.TYPE_NONE) fgsType else activeType
        Log.w(TAG, "前台服务超时: startId=$startId type=${ForegroundServiceTypePolicy.name(type)}")
        A11yDiagnosis.log(
            service.applicationContext,
            "FgSvc",
            "onTimeout startId=$startId type=${ForegroundServiceTypePolicy.name(type)} " +
                "(配额到点, 降级为非前台)"
        )
        releaseForegroundState()
        // 记下冷却点: 冷却期内只尝试无配额限制的类型 (specialUse), 不再挂 dataSync,
        // 否则会立刻再次超时, 变成"超时 → 重启 → 再超时"的死循环。
        appPreferences.fgsQuotaResumeAtMs = System.currentTimeMillis() + FGS_QUOTA_COOLDOWN_MS
        startForegroundCompat()
    }

    /**
     * 摘掉前台身份 (保留通知), 并记录当前已不在前台。
     *
     * 用 STOP_FOREGROUND_DETACH (API 33+) 只摘掉前台身份、保留通知: 服务继续以普通
     * 后台服务运行, 冷却结束后再重新挂前台; 通知消失会触发"通知被移除"恢复风暴。
     */
    fun releaseForegroundState() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                service.stopForeground(Service.STOP_FOREGROUND_DETACH)
            } else {
                @Suppress("DEPRECATION")
                service.stopForeground(false)
            }
        } catch (error: Exception) {
            Log.e(TAG, "解除前台状态失败: ${error.message}", error)
            A11yDiagnosis.log(
                service.applicationContext,
                "FgSvc",
                "解除前台状态失败: ${error.message}"
            )
        }
        activeType = ForegroundServiceTypePolicy.TYPE_NONE
    }

    /** 服务销毁时取消待重挂任务。 */
    fun cancelRearm() {
        rearmJob?.cancel()
        rearmJob = null
    }

    /** 冷却结束后重新尝试挂前台。 */
    private fun scheduleRearm(delayMs: Long) {
        val scope = scopeProvider() ?: return
        rearmJob?.cancel()
        rearmJob = scope.launch {
            delay(delayMs.coerceAtLeast(1_000L))
            try {
                startForegroundCompat()
            } catch (error: Exception) {
                Log.e(TAG, "重新挂前台失败: ${error.message}", error)
            }
        }
    }

    companion object {
        private const val TAG = "AvelineForegroundServiceV2"

        /**
         * 前台服务配额耗尽后的冷却时长。
         * Android 15 的 dataSync 配额是"24 小时滚动窗口内累计 6 小时", 等 6 小时后最早的
         * 运行记录已滚出窗口, 重新挂前台才有意义; 立刻重试只会再次触发 onTimeout。
         */
        private const val FGS_QUOTA_COOLDOWN_MS = 6 * 60 * 60 * 1000L
    }
}
