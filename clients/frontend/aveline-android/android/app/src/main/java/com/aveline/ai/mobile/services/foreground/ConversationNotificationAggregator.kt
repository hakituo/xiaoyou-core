package com.aveline.ai.mobile.services.foreground

import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * 会话级通知聚合状态机（从 ForegroundNotificationController 拆出）。
 *
 * QQ/微信式聚合：同一个角色连发多条消息，通知栏里始终只有**一张卡片**，
 * 标题带条数，正文是最新一条；用户点进去看完（通知被撤掉）后计数归零。
 *
 * 只负责「这条通知该用哪个 ID、累计第几条、展开显示哪几行」这类状态推进，
 * 通知怎么构建、怎么发仍由 [ForegroundNotificationController] 负责。
 */
internal class ConversationNotificationAggregator(
    /** 后端推送通知的自增 ID 来源（同一会话复用同一个 ID 以聚合卡片）。 */
    private val nextNotificationId: AtomicInteger,
    /** 判断某个通知 ID 是否还挂在通知栏上（通知被撤掉后计数必须重新从 1 开始）。 */
    private val isNotificationActive: (Int) -> Boolean
) {
    /** 一次聚合快照：通知 ID、条数、展开后的正文行、时间戳。 */
    data class Snapshot(
        val notifyId: Int,
        val count: Int,
        val lines: List<String>,
        val timestamp: Long
    )

    /**
     * 会话 key（role id / persona filename）-> 该会话当前那张通知卡的状态。
     */
    private data class ConversationNotification(
        val notifyId: Int,
        var count: Int,
        val lines: ArrayDeque<String>,
        var updatedAt: Long
    )

    private val conversationNotifications = ConcurrentHashMap<String, ConversationNotification>()

    /** 按会话推进聚合状态；传 null / 空 key 时退化成「每条消息一张卡」。 */
    fun prepare(conversationKey: String?, body: String): Snapshot {
        val key = conversationKey?.trim()?.takeIf { it.isNotEmpty() }
        val existing = key?.let { conversationNotifications[it] }
            ?.takeIf { isNotificationActive(it.notifyId) }

        val notifyId: Int
        val count: Int
        val lines: List<String>
        val timestamp: Long
        if (existing != null) {
            // 同一会话的新消息：复用通知 ID，只更新内容与条数。
            // 不设 FLAG_ONLY_ALERT_ONCE，所以每次更新仍会照常弹横幅。
            notifyId = existing.notifyId
            existing.count += 1
            existing.lines.addLast(body)
            while (existing.lines.size > MAX_CONVERSATION_LINES) existing.lines.removeFirst()
            existing.updatedAt = System.currentTimeMillis()
            count = existing.count
            lines = existing.lines.toList()
            timestamp = existing.updatedAt
        } else {
            notifyId = nextNotificationId.incrementAndGet()
            count = 1
            lines = listOf(body)
            timestamp = System.currentTimeMillis()
            if (key != null) {
                conversationNotifications[key] = ConversationNotification(
                    notifyId = notifyId,
                    count = 1,
                    lines = ArrayDeque(listOf(body)),
                    updatedAt = timestamp
                )
            }
        }
        return Snapshot(notifyId = notifyId, count = count, lines = lines, timestamp = timestamp)
    }

    companion object {
        /** 聚合卡片展开后最多保留几条正文（超出丢最旧的，条数仍按真实条数累计）。 */
        private const val MAX_CONVERSATION_LINES = 6
    }
}
