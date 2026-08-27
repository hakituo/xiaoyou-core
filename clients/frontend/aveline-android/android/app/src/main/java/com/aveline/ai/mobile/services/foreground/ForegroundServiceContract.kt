package com.aveline.ai.mobile.services.foreground

import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.services.A11yDiagnosis
import com.aveline.ai.mobile.services.AvelineAccessibilityService
import com.aveline.ai.mobile.services.AvelineForegroundServiceV2

/** 前台服务的 Intent 协议和进程外启动入口。 */
object ForegroundServiceContract {
    const val NOTIFICATION_ID = 1001
    const val ACTION_RESTORE_NOTIFICATION =
        "com.aveline.ai.action.RESTORE_KEEPALIVE_NOTIFICATION"
    const val EXTRA_RESTORE_SOURCE = "restore_source"
    const val RESTORE_NOTIFICATION_REQUEST_CODE = 1001

    fun start(context: Context) {
        startServiceIntent(context, Intent(context, AvelineForegroundServiceV2::class.java))
    }

    fun stop(context: Context) {
        context.stopService(Intent(context, AvelineForegroundServiceV2::class.java))
    }

    fun restoreNotification(context: Context, source: String) {
        val appContext = context.applicationContext
        val shouldRestore = AvelineAccessibilityService.isEnabledInSystem(appContext) ||
            AppPreferences(appContext).residentModeEnabled
        if (!shouldRestore) {
            A11yDiagnosis.log(appContext, "FgSvc", "忽略通知恢复: source=$source")
            return
        }
        val intent = Intent(appContext, AvelineForegroundServiceV2::class.java).apply {
            action = ACTION_RESTORE_NOTIFICATION
            putExtra(EXTRA_RESTORE_SOURCE, source)
        }
        startServiceIntent(appContext, intent)
    }

    fun isKeepAliveNotification(notificationId: Int): Boolean =
        notificationId == NOTIFICATION_ID

    private fun startServiceIntent(context: Context, intent: Intent) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            try {
                context.startForegroundService(intent)
            } catch (error: Exception) {
                Log.e(TAG, "startForegroundService 失败, 降级 startService: ${error.message}")
                context.startService(intent)
            }
        } else {
            context.startService(intent)
        }
    }

    private const val TAG = "AvelineForegroundServiceV2"
}
