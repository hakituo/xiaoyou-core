package com.aveline.ai.mobile.services

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.aveline.ai.mobile.data.local.database.dao.NotificationDao
import com.aveline.ai.mobile.data.local.database.entity.NotificationEntity
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@AndroidEntryPoint
class AvelineNotificationService : NotificationListenerService() {

    companion object {
        private val _notificationFlow = MutableSharedFlow<NotificationEvent>(
            extraBufferCapacity = 16,
            replay = 0
        )
        val notificationFlow: SharedFlow<NotificationEvent> = _notificationFlow

        private val TRACKED_PACKAGES = setOf(
            "com.tencent.mm",
            "com.tencent.mobileqq",
            "com.alibaba.android.rimet",
            "com.ss.android.lark",
            "com.sankuai.meituan",
            "me.ele",
            "com.cainiao.wireless",
            "com.android.calendar",
            "com.android.deskclock",
            "com.google.android.calendar",
            "com.samsung.android.calendar",
            "com.huawei.calendar",
            "com.xiaomi.mipicks",
            "com.taobao.taobao",
            "com.jingdong.app.mall",
            "com.sina.weibo",
            "com.ss.android.ugc.aweme",
            "com.netease.cloudmusic",
            "com.tencent.qqmusic",
            "com.eg.android.AlipayGphone",
            "com.autonavi.minimap",
            "com.baidu.BaiduMap"
        )
    }

    @Inject
    lateinit var notificationDao: NotificationDao

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    // 通知去重:同一 (packageName+title+content) 在 DEDUP_WINDOW_MS 内不重复入库
    private val recentNotificationKeys = mutableMapOf<String, Long>()
    private val dedupLock = Any()
    private val DEDUP_WINDOW_MS = 60_000L  // 60 秒去重窗口

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val packageName = sbn.packageName

        if (shouldTrack(packageName)) {
            val notification = sbn.notification
            val extras = notification.extras

            val title = extras.getString(android.app.Notification.EXTRA_TITLE)
            val text = extras.getString(android.app.Notification.EXTRA_TEXT)
            val bigText = extras.getString(android.app.Notification.EXTRA_BIG_TEXT)
            val summaryText = extras.getString(android.app.Notification.EXTRA_SUMMARY_TEXT)

            val contentText = bigText ?: text ?: summaryText

            if (title != null && contentText != null) {
                // 去重:同一内容在窗口内跳过,避免 Android 反复 post 通知导致数据库洪水
                val dedupKey = "$packageName|$title|$contentText"
                val now = sbn.postTime
                val isDuplicate = synchronized(dedupLock) {
                    val lastTime = recentNotificationKeys[dedupKey]
                    if (lastTime != null && now - lastTime < DEDUP_WINDOW_MS) {
                        true
                    } else {
                        recentNotificationKeys[dedupKey] = now
                        // 顺便清理过期条目,避免 Map 无限增长
                        if (recentNotificationKeys.size > 200) {
                            val expireBefore = now - DEDUP_WINDOW_MS
                            recentNotificationKeys.entries.removeAll { it.value < expireBefore }
                        }
                        false
                    }
                }

                if (!isDuplicate) {
                    serviceScope.launch {
                        val entity = NotificationEntity(
                            packageName = packageName,
                            title = title,
                            content = contentText,
                            timestamp = sbn.postTime
                        )
                        notificationDao.insert(entity)
                    }

                    _notificationFlow.tryEmit(
                        NotificationEvent(
                            packageName = packageName,
                            title = title,
                            text = contentText,
                            timestamp = sbn.postTime
                        )
                    )
                }
            }
        }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        super.onNotificationRemoved(sbn)
        if (
            sbn.packageName == applicationContext.packageName &&
            AvelineForegroundServiceV2.isKeepAliveNotification(sbn.id)
        ) {
            // deleteIntent 是主恢复路径；已授予通知读取权限时，这里覆盖厂商系统不触发
            // deleteIntent、清空全部通知等边缘情况。恢复函数自身会检查是否仍需保活。
            AvelineForegroundServiceV2.restoreKeepAliveNotification(
                applicationContext,
                source = "notification_listener"
            )
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        serviceScope.cancel()
    }

    private fun shouldTrack(packageName: String): Boolean {
        if (packageName == applicationContext.packageName) return false
        return TRACKED_PACKAGES.contains(packageName)
    }
}

data class NotificationEvent(
    val packageName: String,
    val title: String,
    val text: String,
    val timestamp: Long
)
