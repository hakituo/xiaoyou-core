package com.aveline.ai.mobile.services.foreground

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.app.NotificationCompat
import com.aveline.ai.R
import com.aveline.ai.mobile.presentation.MainActivity
import com.aveline.ai.mobile.services.AvelineForegroundServiceV2
import com.aveline.ai.mobile.services.AvelineNotificationManager
import com.aveline.ai.mobile.services.AvelineNotificationManager.Companion.CHANNEL_MESSAGES
import com.aveline.ai.mobile.services.AvelineNotificationManager.Companion.CHANNEL_PROACTIVE
import java.util.concurrent.atomic.AtomicInteger

/** 前台守护服务的全部通知创建、渠道管理与发布逻辑。 */
class ForegroundNotificationController(
    private val context: Context,
    private val notificationManager: AvelineNotificationManager
) {
    private val systemManager = context.getSystemService(NotificationManager::class.java)

    /**
     * 后端推送通知的自增 ID。
     *
     * 同一会话（同一角色）的消息复用同一个 ID 以聚合卡片，不同会话各自取新 ID。
     */
    private val backendNotifyIdSeq = AtomicInteger(BACKEND_NOTIFICATION_ID)

    /**
     * 会话级聚合状态机：QQ/微信式聚合，同一角色连发多条只占通知栏里一张卡片。
     */
    private val conversationAggregator = ConversationNotificationAggregator(
        nextNotificationId = backendNotifyIdSeq,
        isNotificationActive = { notifyId ->
            systemManager.activeNotifications.any { it.id == notifyId }
        }
    )

    fun createChannels() {
        ForegroundNotificationChannels.ensureChannels(context, notificationManager)
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

        return NotificationCompat.Builder(context, ForegroundNotificationChannels.KEEPALIVE_CHANNEL_ID)
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
     *
     * 传了 [conversationKey] 时按会话聚合（QQ/微信式）：同一角色连发多条消息只占
     * 通知栏里的**一张卡片**，标题带条数（`Aveline（2条新消息）`），正文始终是最新的
     * 那一条，展开后用 InboxStyle 列出最近几条；用户不点进去就一直往上叠加。
     * 没传时退化成旧行为（每条消息一张卡）。
     *
     * @param deepLink 点击后跳转的深链(如 "aveline://chat?session_id=xxx" 或 "aveline://study")。
     *                 缺省为 null 时仅打开 App 主页。
     * @param largeIcon 角色头像（QQ/微信式"头像+昵称+内容"布局），null 时用默认样式。
     * @param cancelKeys 归属标识（persona filename / role id）；用户看完该角色消息后
     *                   用同一批 key 调用 [AvelineNotificationManager.cancelNotifications] 撤掉通知。
     * @param conversationKey 会话聚合键（一般用 role id，拿不到时退化为 persona filename）。
     */
    fun showBackendNotification(
        title: String,
        body: String,
        deepLink: String? = null,
        largeIcon: android.graphics.Bitmap? = null,
        cancelKeys: Collection<String> = emptyList(),
        conversationKey: String? = null
    ) {
        val snapshot = conversationAggregator.prepare(conversationKey, body)
        val notifyId = snapshot.notifyId
        val count = snapshot.count
        val lines = snapshot.lines
        val timestamp = snapshot.timestamp

        // 每条通知独立 PendingIntent requestCode（= notifyId）：
        // 否则所有通知共用同一个 PendingIntent，后一条的深链会覆盖前一条，
        // 点旧通知会跳到最新那条的角色页。聚合时同一会话复用同一 requestCode，
        // 配合 FLAG_UPDATE_CURRENT 让深链跟着最新消息走。
        val contentIntent = if (!deepLink.isNullOrBlank()) {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(deepLink)).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
            PendingIntent.getActivity(
                context,
                notifyId,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        } else {
            val intent = Intent(context, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
            PendingIntent.getActivity(
                context,
                notifyId,
                intent,
                PendingIntent.FLAG_IMMUTABLE
            )
        }
        // QQ 式标题：多条未点开时显示"昵称（N条新消息）"，单条就是昵称本身。
        val displayTitle = if (count > 1) "$title（${count}条新消息）" else title
        // 展开后列出最近几条（倒序无所谓，InboxStyle 自带顺序），正文仍是最新的那条。
        // 显式写类型、不用链式 apply：NotificationCompat 的 Style 子类链式调用
        // 在 Kotlin 里会被推断成平台类型（android.app.Notification.Builder!），
        // 进而 addLine / setSummaryText 解析不到。
        val style: NotificationCompat.Style = if (count > 1) {
            val inbox = NotificationCompat.InboxStyle()
            inbox.setBigContentTitle(displayTitle)
            lines.forEach { line -> inbox.addLine(line) }
            inbox.setSummaryText("共 ${count} 条新消息")
            inbox
        } else {
            NotificationCompat.BigTextStyle().bigText(body)
        }
        // 用专用"角色消息"渠道（IMPORTANCE_HIGH）：QQ/微信式横幅弹窗。
        // 不复用老渠道：渠道 importance 建好后只有用户能改，老渠道若被降级成
        // "静默"，代码改不回来。新渠道 id 保证以 HIGH 全新创建。
        val notification = NotificationCompat.Builder(context, CHANNEL_PROACTIVE)
            .setContentTitle(displayTitle)
            .setContentText(body)
            .setStyle(style)
            // 用 App 自己的通知图标替代系统 ic_dialog_info（灰色信息图标，与应用风格不符）
            .setSmallIcon(com.aveline.ai.R.drawable.ic_notification)
            .setLargeIcon(largeIcon)
            .setContentIntent(contentIntent)
            .setAutoCancel(true)
            // 不设 setOnlyAlertOnce：聚合后每次更新都要照常弹横幅，否则第二条之后就没提醒了
            // channel 已是 HIGH；priority 兜底 Android 7.1 及以下的横幅判断
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setNumber(count)
            .setWhen(timestamp)
            .setShowWhen(true)
            .build()
        systemManager.notify(notifyId, notification)
        notificationManager.registerNotificationKeys(notifyId, cancelKeys)
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
    }
}
