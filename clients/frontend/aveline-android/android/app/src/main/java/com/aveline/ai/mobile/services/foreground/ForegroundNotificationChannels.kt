package com.aveline.ai.mobile.services.foreground

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import com.aveline.ai.mobile.services.AvelineNotificationManager

/**
 * 前台守护服务的通知渠道创建（从 ForegroundNotificationController 拆出）。
 *
 * 只负责「渠道是否已存在、缺哪个建哪个」，不涉及通知内容构建与发布。
 */
internal object ForegroundNotificationChannels {

    /** 后端推送通知渠道（默认重要度，不带横幅）。 */
    const val BACKEND_CHANNEL_ID = "aveline_backend_v2"

    /** 常驻守护通知渠道（高重要度 + 锁屏可见），也是前台服务的通知渠道。 */
    const val KEEPALIVE_CHANNEL_ID = "aveline_keepalive"

    fun ensureChannels(context: Context, notificationManager: AvelineNotificationManager) {
        notificationManager.createNotificationChannels()
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val systemManager = context.getSystemService(NotificationManager::class.java)
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
}
