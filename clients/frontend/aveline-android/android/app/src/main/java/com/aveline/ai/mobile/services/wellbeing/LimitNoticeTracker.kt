package com.aveline.ai.mobile.services.wellbeing

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import java.time.LocalDate
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 限额通知的抑制器 (持久化)。
 *
 * 背景: 用户反馈"手机一直弹已到 app 限额的通知"。根因是限额一旦判定成立就是一个
 * **持续状态**而不是一次事件: 每日额度用完会一直挂到次日 0 点, 用户每尝试打开一次
 * 被限额的应用, [UsageLimitEnforcer.block] 就会走一遍"回桌面 → 强退 → 通知"。
 * 原先只有 20 秒的内存节流, 且进程被回收后即失效, 于是一天能弹几十条。
 *
 * 这里把"今天已经提醒过"记到 SharedPreferences, 规则:
 *
 * - **每日额度 (DAILY)**: 同一应用同一天只弹 1 次 (次日自动重置)
 * - **单次额度 / 冷却 (SESSION / COOLDOWN)**: 同一个冷却周期只弹 1 次
 *   (以 blockedUntilMs 作为周期标识), 且每天最多 [MAX_NOTICES_PER_DAY] 次
 * - **限额被改过**: dailyLimitMs 变化视为新的意图, 允许再提醒一次
 *    (用户在数字健康页把额度调大后, 再次用完时应该再收到提醒)
 *
 * 判定与标记是同一个原子方法 [takeNoticeSlot], 避免无障碍服务与 15 分钟 Worker
 * 并发时同时拿到名额。
 */
@Singleton
class LimitNoticeTracker @Inject constructor(
    private val appPreferences: AppPreferences,
) {

    /**
     * 单个应用的通知记录。
     *
     * @property day 记录所属日期 (yyyy-MM-dd), 跨天整体失效
     * @property count 当天已弹次数
     * @property lastAtMs 最近一次弹通知的时刻, 用于短节流
     * @property dailyNotified 当天是否已经弹过"每日额度用完"
     * @property dailyLimitMs 当时的每日额度; 变化说明用户改过限额
     * @property sessionKey 上次提醒所属的冷却周期 (blockedUntilMs)
     */
    internal data class NoticeRecord(
        val packageName: String,
        val day: String,
        val count: Int,
        val lastAtMs: Long,
        val dailyNotified: Boolean,
        val dailyLimitMs: Long,
        val sessionKey: Long,
    )

    @Volatile
    private var cache: Map<String, NoticeRecord>? = null

    /**
     * 判定并占用一个通知名额。
     *
     * @param reason 拦截原因
     * @param blockedUntilMs 解禁时刻 (DAILY 为 0), 用作 SESSION/COOLDOWN 的周期标识
     * @param dailyLimitMs 当前每日额度, 用于识别"用户改过限额"
     * @return true 表示这次可以弹通知 (已记账)
     */
    @Synchronized
    fun takeNoticeSlot(
        packageName: String,
        reason: SessionLimiter.BlockReason,
        blockedUntilMs: Long,
        dailyLimitMs: Long,
        nowMs: Long = System.currentTimeMillis(),
    ): Boolean {
        val today = LocalDate.now().toString()
        val records = load().toMutableMap()
        val record = records[packageName]?.takeIf { it.day == today }

        val allowed = decide(
            record = record,
            reason = reason,
            blockedUntilMs = blockedUntilMs,
            dailyLimitMs = dailyLimitMs,
            nowMs = nowMs,
        )
        if (!allowed) {
            Log.d(TAG, "跳过限额通知: $packageName reason=$reason (今日已提醒过或在节流窗口内)")
            return false
        }

        val limitChanged = record?.dailyLimitMs != dailyLimitMs
        records[packageName] = NoticeRecord(
            packageName = packageName,
            day = today,
            count = (if (limitChanged) 0 else (record?.count ?: 0)) + 1,
            lastAtMs = nowMs,
            dailyNotified = (record?.dailyNotified == true && !limitChanged) ||
                reason == SessionLimiter.BlockReason.DAILY,
            dailyLimitMs = dailyLimitMs,
            sessionKey = blockedUntilMs,
        )
        save(records)
        return true
    }

    /** 清除单个应用的通知记录 (移除限额/手动重置时调用)。 */
    @Synchronized
    fun clear(packageName: String) {
        val records = load().toMutableMap()
        if (records.remove(packageName) == null) return
        save(records)
    }

    private fun load(): Map<String, NoticeRecord> {
        cache?.let { return it }
        val parsed = buildMap {
            appPreferences.appLimitNotices.split(',').forEach { entry ->
                val separator = entry.indexOf('=')
                if (separator <= 0) return@forEach
                val packageName = entry.substring(0, separator).trim()
                val parts = entry.substring(separator + 1).split('|')
                if (packageName.isBlank() || parts.size < NOTICE_FIELDS) return@forEach
                put(
                    packageName,
                    NoticeRecord(
                        packageName = packageName,
                        day = parts[0],
                        count = parts[1].toIntOrNull() ?: 0,
                        lastAtMs = parts[2].toLongOrNull() ?: 0L,
                        dailyNotified = parts[3] == "1",
                        dailyLimitMs = parts[4].toLongOrNull() ?: 0L,
                        sessionKey = parts[5].toLongOrNull() ?: 0L,
                    )
                )
            }
        }
        cache = parsed
        return parsed
    }

    private fun save(records: Map<String, NoticeRecord>) {
        cache = records
        appPreferences.appLimitNotices = records.values
            .filter { it.day.isNotBlank() }
            .joinToString(",") { record ->
                val notified = if (record.dailyNotified) "1" else "0"
                "${record.packageName}=${record.day}|${record.count}|${record.lastAtMs}" +
                    "|$notified|${record.dailyLimitMs}|${record.sessionKey}"
            }
    }

    companion object {
        private const val TAG = "LimitNoticeTracker"

        /** 序列化字段数: day|count|lastAtMs|dailyNotified|dailyLimitMs|sessionKey */
        private const val NOTICE_FIELDS = 6

        /** 同一应用的两次通知最小间隔, 挡无障碍事件风暴 (不等于"每天只弹一次")。 */
        internal const val MIN_INTERVAL_MS = 30_000L

        /** 单次额度类通知的每日上限 (每日额度类固定 1 次)。 */
        internal const val MAX_NOTICES_PER_DAY = 3

        /**
         * 纯判定: 给定已有记录, 这次该不该弹通知。
         *
         * 抽成不依赖 Android 的纯函数, 便于 JVM 单测覆盖各条规则
         * (见 LimitNoticeTrackerTest)。[record] 为 null 表示当天还没提醒过。
         */
        internal fun decide(
            record: NoticeRecord?,
            reason: SessionLimiter.BlockReason,
            blockedUntilMs: Long,
            dailyLimitMs: Long,
            nowMs: Long,
        ): Boolean = when {
            // 首次 / 跨天: 直接给名额
            record == null -> true

            // 无障碍窗口切换会连发事件, 短节流先挡掉
            nowMs - record.lastAtMs < MIN_INTERVAL_MS -> false

            // 用户改过额度: 视为新的限额, 重新给名额
            record.dailyLimitMs != dailyLimitMs -> true

            // 每日额度: 同一天只提醒一次
            reason == SessionLimiter.BlockReason.DAILY -> !record.dailyNotified

            // 同一冷却周期内不重复打扰; 新的单次超时(不同周期)才再提醒
            record.sessionKey == blockedUntilMs -> false

            else -> record.count < MAX_NOTICES_PER_DAY
        }
    }
}
