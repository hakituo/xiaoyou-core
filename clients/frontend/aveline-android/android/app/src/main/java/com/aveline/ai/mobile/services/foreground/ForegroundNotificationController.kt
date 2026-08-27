package com.aveline.ai.mobile.services.foreground

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.net.Uri
import android.provider.Settings
import androidx.core.app.NotificationCompat
import com.aveline.ai.R
import com.aveline.ai.mobile.presentation.MainActivity
import com.aveline.ai.mobile.services.AvelineForegroundServiceV2
import com.aveline.ai.mobile.services.AvelineNotificationManager
import com.aveline.ai.mobile.services.AvelineNotificationManager.Companion.CHANNEL_MESSAGES

/** 前台守护服务的全部通知创建、渠道管理与发布逻辑。 */
class ForegroundNotificationController(
    private val context: Context,
    private val notificationManager: AvelineNotificationManager
) {
    private val systemManager = context.getSystemService(NotificationManager::class.java)

    fun createChannels() {
        notificationManager.createNotificationChannels()
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        if (systemManager.getNotificationChannel(BACKEND_CHANNEL_ID) == null) {
            systemManager.createNotificationChannel(
                NotificationChannel(
                    BACKEND_CHANNEL_ID,
                    "Aveline Backend Notifications",
                    NotificationManager.IMPORTANCE_DEFAULT
                )
            )
        }
        if (systemManager.getNotificationChannel(KEEPALIVE_CHANNEL_ID) == null) {
            systemManager.createNotificationChannel(
                NotificationChannel(
                    KEEPALIVE_CHANNEL_ID,
                    "Aveline 保活通知",
                    NotificationManager.IMPORTANCE_HIGH
                ).apply {
                    description = "后台守护常驻通知, 用于保持连接与无障碍保活"
                    setShowBadge(false)
                    lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                }
            )
        }
    }

    fun createForegroundNotification(
        title: String = "Aveline 正在后台守护",
        text: String = "保持连接以提供实时关怀"
    ): Notification {
        val openAppIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val openAppPendingIntent = PendingIntent.getActivity(
            context,
            0,
            openAppIntent,
            PendingIntent.FLAG_IMMUTABLE
        )
        val restoreIntent = Intent(context, AvelineForegroundServiceV2::class.java).apply {
            action = ForegroundServiceContract.ACTION_RESTORE_NOTIFICATION
            putExtra(ForegroundServiceContract.EXTRA_RESTORE_SOURCE, "delete_intent")
        }
        val restorePendingIntent = PendingIntent.getForegroundService(
            context,
            ForegroundServiceContract.RESTORE_NOTIFICATION_REQUEST_CODE,
            restoreIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val iconRes = if (R.drawable.ic_notification != 0) {
            R.drawable.ic_notification
        } else {
            android.R.drawable.ic_menu_info_details
        }

        return NotificationCompat.Builder(context, KEEPALIVE_CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(iconRes)
            .setContentIntent(openAppPendingIntent)
            .setDeleteIntent(restorePendingIntent)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setTicker("Aveline 正在后台守护")
            .build()
    }

    fun updateForegroundNotification(title: String, text: String) {
        systemManager.notify(
            ForegroundServiceContract.NOTIFICATION_ID,
            createForegroundNotification(title, text)
        )
    }

    /**
     * 显示来自后端的推送通知 (active care / 仪式 / 自发反应 / 背单词推送等)。
     * @param deepLink 点击后跳转的深链(如 "aveline://chat?session_id=xxx" 或 "aveline://study")。
     *                 缺省为 null 时仅打开 App 主页。
     */
    fun showBackendNotification(title: String, body: String, deepLink: String? = null) {
        val contentIntent = if (!deepLink.isNullOrBlank()) {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(deepLink)).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
            PendingIntent.getActivity(
                context,
                BACKEND_NOTIFICATION_ID,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        } else {
            val intent = Intent(context, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
            PendingIntent.getActivity(
                context,
                BACKEND_NOTIFICATION_ID,
                intent,
                PendingIntent.FLAG_IMMUTABLE
            )
        }
        val notification = NotificationCompat.Builder(context, BACKEND_CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(body)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(contentIntent)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
        systemManager.notify(BACKEND_NOTIFICATION_ID, notification)
    }

    fun showAccessibilityDownNotification() {
        val settingsIntent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        val pendingIntent = PendingIntent.getActivity(
            context,
            A11Y_DOWN_NOTIFICATION_ID,
            settingsIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_MESSAGES)
            .setContentTitle("无障碍服务已断开")
            .setContentText("点击重新开启, 否则 AI 无法执行点击/滑动等操作")
            .setSmallIcon(android.R.drawable.ic_menu_manage)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        systemManager.notify(A11Y_DOWN_NOTIFICATION_ID, notification)
    }

    companion object {
        private const val BACKEND_NOTIFICATION_ID = 1002
        private const val A11Y_DOWN_NOTIFICATION_ID = 2003
        private const val BACKEND_CHANNEL_ID = "aveline_backend_v2"
        private const val KEEPALIVE_CHANNEL_ID = "aveline_keepalive"
    }
}
