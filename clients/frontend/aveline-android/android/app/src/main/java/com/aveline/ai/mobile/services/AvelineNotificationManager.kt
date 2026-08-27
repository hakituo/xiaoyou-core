package com.aveline.ai.mobile.services

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.aveline.ai.R
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 通知管理器
 * 
 * 管理应用的所有通知：
 * - 消息通知
 * - 警告通知
 * - 系统通知
 * 
 * Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7
 */
@Singleton
class AvelineNotificationManager @Inject constructor(
    @ApplicationContext private val context: Context
) {
    
    companion object {
        private const val TAG = "AvelineNotifManager"

        // 通知渠道 ID
        const val CHANNEL_MESSAGES = "aveline_messages"
        const val CHANNEL_WARNINGS = "aveline_warnings"
        const val CHANNEL_SYSTEM = "aveline_system"

        // 通知 ID
        const val NOTIFICATION_MESSAGE = 2001
        const val NOTIFICATION_WARNING = 2002
        const val NOTIFICATION_SYSTEM = 2003
        
        // 渠道名称
        private const val CHANNEL_MESSAGES_NAME = "消息通知"
        private const val CHANNEL_WARNINGS_NAME = "警告通知"
        private const val CHANNEL_SYSTEM_NAME = "系统通知"
        
        // 渠道描述
        private const val CHANNEL_MESSAGES_DESC = "AI 消息和回复通知"
        private const val CHANNEL_WARNINGS_DESC = "生命状态警告通知"
        private const val CHANNEL_SYSTEM_DESC = "系统更新和状态通知"
    }
    
    private val notificationManager: NotificationManagerCompat = 
        NotificationManagerCompat.from(context)
    
    /**
     * 创建通知渠道
     * Android 8.0+ 需要
     */
    fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            // 消息渠道 - 高优先级
            val messagesChannel = NotificationChannel(
                CHANNEL_MESSAGES,
                CHANNEL_MESSAGES_NAME,
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = CHANNEL_MESSAGES_DESC
                enableLights(true)
                enableVibration(true)
                setShowBadge(true)
            }
            
            // 警告渠道 - 高优先级
            val warningsChannel = NotificationChannel(
                CHANNEL_WARNINGS,
                CHANNEL_WARNINGS_NAME,
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = CHANNEL_WARNINGS_DESC
                enableLights(true)
                enableVibration(true)
                setShowBadge(true)
            }
            
            // 系统渠道 - 默认优先级
            val systemChannel = NotificationChannel(
                CHANNEL_SYSTEM,
                CHANNEL_SYSTEM_NAME,
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                description = CHANNEL_SYSTEM_DESC
                enableLights(true)
                setShowBadge(false)
            }
            
            notificationManager.createNotificationChannels(
                listOf(messagesChannel, warningsChannel, systemChannel)
            )
        }
    }
    
    /**
     * 检查是否有通知权限
     */
    fun hasNotificationPermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ContextCompat.checkSelfPermission(
                context,
                android.Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
        } else {
            true
        }
    }
    
    /**
     * 显示消息通知
     * 
     * @param title 通知标题
     * @param message 消息内容（截取前50字符）
     * @param sessionId 会话 ID（可选，用于点击跳转）
     */
    fun showMessageNotification(
        title: String = "Aveline",
        message: String,
        sessionId: String? = null
    ) {
        if (!hasNotificationPermission()) return
        
        val truncatedMessage = if (message.length > 50) {
            message.take(50) + "..."
        } else {
            message
        }
        
        val notification = createMessageNotification(
            title = title,
            message = truncatedMessage,
            sessionId = sessionId
        )
        
        try {
            notificationManager.notify(NOTIFICATION_MESSAGE, notification)
        } catch (e: SecurityException) {
            Log.w(TAG, "消息通知显示被拒绝(权限缺失或被撤销)", e)
        }
    }
    
    /**
     * 显示生命状态警告通知
     * 
     * @param statusName 状态名称
     * @param value 状态值
     */
    fun showLifeStatusWarning(
        statusName: String,
        value: Float
    ) {
        if (!hasNotificationPermission()) return
        
        val percentage = (value * 100).toInt()
        val message = "$statusName 值过低 ($percentage%)，请关注 AI 的状态"
        
        val notification = createWarningNotification(
            title = "状态警告",
            message = message
        )
        
        try {
            notificationManager.notify(NOTIFICATION_WARNING, notification)
        } catch (e: SecurityException) {
            Log.w(TAG, "警告通知显示被拒绝(权限缺失或被撤销)", e)
        }
    }
    
    /**
     * 显示系统通知
     * 
     * @param title 通知标题
     * @param message 通知内容
     */
    fun showSystemNotification(
        title: String,
        message: String
    ) {
        if (!hasNotificationPermission()) return
        
        val notification = createSystemNotification(
            title = title,
            message = message
        )
        
        try {
            notificationManager.notify(NOTIFICATION_SYSTEM, notification)
        } catch (e: SecurityException) {
            Log.w(TAG, "系统通知显示被拒绝(权限缺失或被撤销)", e)
        }
    }
    
    /**
     * 取消消息通知
     */
    fun cancelMessageNotification() {
        notificationManager.cancel(NOTIFICATION_MESSAGE)
    }
    
    /**
     * 取消警告通知
     */
    fun cancelWarningNotification() {
        notificationManager.cancel(NOTIFICATION_WARNING)
    }
    
    /**
     * 取消所有通知
     */
    fun cancelAllNotifications() {
        notificationManager.cancelAll()
    }
    
    /**
     * 构造带 aveline:// 深链的 PendingIntent。点击通知后由 MainActivity.handleDeepLink
     * 解析 intent.data 并跳转到对应页面 (chat/study/life/settings 等)。
     * 之前只往 Intent 塞 navigate_to extra, 而 handleDeepLink 只读 intent.data,
     * 导致点击通知永远只进主页、不跳转。
     */
    private fun buildDeepLinkPendingIntent(deepLink: String, requestCode: Int): PendingIntent {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(deepLink)).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        return PendingIntent.getActivity(
            context,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    /**
     * 创建消息通知
     */
    private fun createMessageNotification(
        title: String,
        message: String,
        sessionId: String?
    ): Notification {
        // 点击跳转到与角色聊天页: 带 session_id 时直接进入该角色会话, 否则进聊天主页
        val deepLink = if (!sessionId.isNullOrBlank()) {
            Uri.Builder().scheme("aveline").authority("chat")
                .appendQueryParameter("session_id", sessionId)
                .build().toString()
        } else {
            "aveline://chat"
        }
        val pendingIntent = buildDeepLinkPendingIntent(deepLink, NOTIFICATION_MESSAGE)

        return NotificationCompat.Builder(context, CHANNEL_MESSAGES)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(message)
            .setStyle(
                NotificationCompat.BigTextStyle()
                    .bigText(message)
            )
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setShowWhen(true)
            .build()
    }
    
    /**
     * 创建警告通知
     */
    private fun createWarningNotification(
        title: String,
        message: String
    ): Notification {
        // 生命状态警告 -> 日常生活页(健康/饮水/餐食等)
        val pendingIntent = buildDeepLinkPendingIntent("aveline://life", NOTIFICATION_WARNING)

        return NotificationCompat.Builder(context, CHANNEL_WARNINGS)
            .setSmallIcon(R.drawable.ic_notification_warning)
            .setContentTitle(title)
            .setContentText(message)
            .setStyle(
                NotificationCompat.BigTextStyle()
                    .bigText(message)
            )
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setShowWhen(true)
            .build()
    }
    
    /**
     * 创建系统通知
     */
    private fun createSystemNotification(
        title: String,
        message: String
    ): Notification {
        // 系统通知 -> 打开 App 主页(会话列表)
        val pendingIntent = buildDeepLinkPendingIntent("aveline://conversations", NOTIFICATION_SYSTEM)

        return NotificationCompat.Builder(context, CHANNEL_SYSTEM)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(message)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setShowWhen(true)
            .build()
    }
}
