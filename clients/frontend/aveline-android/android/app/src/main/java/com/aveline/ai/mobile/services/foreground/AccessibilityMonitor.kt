package com.aveline.ai.mobile.services.foreground

import android.content.Context
import android.util.Log
import com.aveline.ai.mobile.services.AvelineAccessibilityService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** 检测系统仍授权但进程内实例已丢失的无障碍断线状态。 */
class AccessibilityMonitor(
    private val context: Context,
    private val scope: CoroutineScope,
    private val notifications: ForegroundNotificationController
) {
    private var job: Job? = null

    fun start() {
        if (job?.isActive == true) return
        job = scope.launch {
            while (isActive) {
                try {
                    delay(MONITOR_INTERVAL_MS)
                    if (AvelineAccessibilityService.isRunning()) continue
                    if (!AvelineAccessibilityService.isEnabledInSystem(context)) continue
                    notifications.showAccessibilityDownNotification()
                } catch (error: Exception) {
                    Log.w(TAG, "无障碍断线监测异常: ${error.message}")
                }
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    companion object {
        private const val MONITOR_INTERVAL_MS = 60 * 1000L
        private const val TAG = "AvelineForegroundServiceV2"
    }
}
