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
import java.util.concurrent.ConcurrentHashMap
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

        /**
         * 角色主动消息（Active Care / 仪式 / 自发反应）专用渠道。
         *
         * 单独开一个渠道而不是复用 CHANNEL_MESSAGES 的原因：Android 的渠道
         * importance 一旦创建就只有用户能改，代码再改也无效。老渠道可能在
         * 用户设备上被降级成"静默"，导致横幅再也弹不出来；新渠道 id 能保证
         * 以 IMPORTANCE_HIGH 全新创建（横幅弹窗）。
         * 注意：不能改 CHANNEL_MESSAGES 的值 —— AndroidManifest 里 FCM 的
         * default_notification_channel_id 指向它，改动会让推送落到不存在的渠道。
         */
        const val CHANNEL_PROACTIVE = "aveline_proactive"

        /**
         * 通知归属 key：背单词类通知（每日单词 / 生词测验 / 催背）。
         *
         * 用户进入背单词页后用它把这类通知撤掉，避免"单词都背完了通知还挂着"。
         * 定义在 Manager 里，services 与 presentation 都引用同一份，不会出现
         * 一边写 "vocab" 一边写 "study" 导致撤销不到的情况。
         */
        const val KEY_VOCAB = "vocab"

        // 通知 ID
        const val NOTIFICATION_MESSAGE = 2001
        const val NOTIFICATION_WARNING = 2002
        const val NOTIFICATION_SYSTEM = 2003
        
        // 渠道名称
        private const val CHANNEL_MESSAGES_NAME = "消息通知"
        private const val CHANNEL_WARNINGS_NAME = "警告通知"
        private const val CHANNEL_SYSTEM_NAME = "系统通知"
        private const val CHANNEL_PROACTIVE_NAME = "角色消息"

        // 渠道描述
        private const val CHANNEL_MESSAGES_DESC = "AI 消息和回复通知"
        private const val CHANNEL_WARNINGS_DESC = "生命状态警告通知"
        private const val CHANNEL_SYSTEM_DESC = "系统更新和状态通知"
        private const val CHANNEL_PROACTIVE_DESC = "角色主动发来的关心与问候"
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

            // 角色消息渠道 - 高优先级（横幅弹窗，QQ/微信式提醒）
            val proactiveChannel = NotificationChannel(
                CHANNEL_PROACTIVE,
                CHANNEL_PROACTIVE_NAME,
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = CHANNEL_PROACTIVE_DESC
                enableLights(true)
                enableVibration(true)
                setShowBadge(true)
                lockscreenVisibility = Notification.VISIBILITY_PRIVATE
            }

            notificationManager.createNotificationChannels(
                listOf(messagesChannel, warningsChannel, systemChannel, proactiveChannel)
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
        notificationIdsByKey.clear()
        notificationManager.cancelAll()
    }

    /**
     * 角色 -> 该角色名下已弹出的通知 ID。
     *
     * 主动消息通知每条都自增 ID（否则同 ID 更新不会弹横幅），事后想按"角色"撤掉
     * 就必须记住 ID 与角色的对应关系：用户看完消息（进入该角色聊天页）时，
     * 才能只撤掉这个角色的通知，不影响别的角色。
     * key 同时登记 persona filename 与 role id，两者任一匹配即可命中。
     */
    private val notificationIdsByKey = ConcurrentHashMap<String, MutableSet<Int>>()

    /**
     * 登记一条通知的归属 key（persona filename / role id）。
     *
     * @param notifyId 通知 ID
     * @param keys 归属标识；空集合表示无法归属，不做登记（该通知只能靠用户手动划掉）
     */
    fun registerNotificationKeys(notifyId: Int, keys: Collection<String>) {
        keys.map { it.trim() }.filter { it.isNotEmpty() }.forEach { key ->
            notificationIdsByKey.getOrPut(key) { ConcurrentHashMap.newKeySet() }.add(notifyId)
        }
    }

    /**
     * 取消属于这些 key（persona filename / role id）的通知。
     *
     * 用于"用户已经看完这个角色的消息"时撤掉通知栏里对应的横幅——
     * 不点通知直接打开 App 看消息时，此前没有任何地方会取消通知，
     * 表现就是消息都读完了通知还一直挂着。
     *
     * @return 实际取消掉的通知数量
     */
    fun cancelNotifications(keys: Collection<String>): Int {
        val ids = linkedSetOf<Int>()
        keys.map { it.trim() }.filter { it.isNotEmpty() }.forEach { key ->
            notificationIdsByKey.remove(key)?.let { ids.addAll(it) }
        }
        if (ids.isEmpty()) return 0
        ids.forEach { id ->
            runCatching { notificationManager.cancel(id) }
                .onFailure { Log.w(TAG, "取消通知 id=$id 失败", it) }
        }
        return ids.size
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
