package com.aveline.ai.mobile.services.wellbeing

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * LimitNoticeTracker 判定规则单元测试。
 *
 * 覆盖: 首次放行 / 节流窗口 / 每日额度同一天只提醒一次 / 同一冷却周期只提醒一次 /
 * 新冷却周期放行 / 单次额度每日上限 / 额度被改后重新放行。
 */
class LimitNoticeTrackerTest {

    private fun record(
        day: String = "2026-09-12",
        count: Int = 1,
        lastAtMs: Long = 0L,
        dailyNotified: Boolean = false,
        dailyLimitMs: Long = DAILY_LIMIT,
        sessionKey: Long = 0L,
    ) = LimitNoticeTracker.NoticeRecord(
        packageName = PKG,
        day = day,
        count = count,
        lastAtMs = lastAtMs,
        dailyNotified = dailyNotified,
        dailyLimitMs = dailyLimitMs,
        sessionKey = sessionKey,
    )

    private fun decide(
        record: LimitNoticeTracker.NoticeRecord?,
        reason: SessionLimiter.BlockReason = SessionLimiter.BlockReason.DAILY,
        blockedUntilMs: Long = 0L,
        dailyLimitMs: Long = DAILY_LIMIT,
        nowMs: Long = NOW,
    ) = LimitNoticeTracker.decide(
        record = record,
        reason = reason,
        blockedUntilMs = blockedUntilMs,
        dailyLimitMs = dailyLimitMs,
        nowMs = nowMs,
    )

    @Test
    fun `当天没提醒过则放行`() {
        assertTrue(decide(record = null))
    }

    @Test
    fun `节流窗口内重复拦截不放行`() {
        val rec = record(lastAtMs = NOW - 5_000L)
        assertFalse(decide(record = rec))
    }

    @Test
    fun `超过节流窗口且每日额度未提醒过则放行`() {
        val rec = record(lastAtMs = NOW - 60_000L, dailyNotified = false)
        assertTrue(decide(record = rec, reason = SessionLimiter.BlockReason.DAILY))
    }

    @Test
    fun `每日额度同一天只提醒一次`() {
        val rec = record(lastAtMs = NOW - 60_000L, dailyNotified = true)
        // 用户不死心反复打开被限额的应用, 当天后续一律不再打扰
        assertFalse(decide(record = rec, reason = SessionLimiter.BlockReason.DAILY))
        assertFalse(decide(record = rec, nowMs = NOW + 3 * 60 * 60_000L))
    }

    @Test
    fun `同一冷却周期内只提醒一次`() {
        val rec = record(
            lastAtMs = NOW - 60_000L,
            sessionKey = COOLDOWN_UNTIL,
            count = 1,
            dailyNotified = true,
        )
        assertFalse(
            decide(
                record = rec,
                reason = SessionLimiter.BlockReason.SESSION,
                blockedUntilMs = COOLDOWN_UNTIL,
            )
        )
    }

    @Test
    fun `新的单次超时(不同冷却周期)可以再提醒`() {
        val rec = record(
            lastAtMs = NOW - 60_000L,
            sessionKey = COOLDOWN_UNTIL,
            count = 1,
            dailyNotified = true,
        )
        assertTrue(
            decide(
                record = rec,
                reason = SessionLimiter.BlockReason.SESSION,
                blockedUntilMs = COOLDOWN_UNTIL + 600_000L,
            )
        )
    }

    @Test
    fun `单次额度提醒达到每日上限后不再提醒`() {
        val rec = record(
            lastAtMs = NOW - 60_000L,
            count = LimitNoticeTracker.MAX_NOTICES_PER_DAY,
            dailyNotified = true,
            sessionKey = 1L,
        )
        assertFalse(
            decide(
                record = rec,
                reason = SessionLimiter.BlockReason.SESSION,
                blockedUntilMs = 2L,
            )
        )
    }

    @Test
    fun `用户改过额度后允许重新提醒一次`() {
        val rec = record(
            lastAtMs = NOW - 60_000L,
            dailyNotified = true,
            dailyLimitMs = DAILY_LIMIT,
        )
        assertTrue(
            decide(
                record = rec,
                reason = SessionLimiter.BlockReason.DAILY,
                dailyLimitMs = DAILY_LIMIT * 2,
            )
        )
    }

    private companion object {
        const val PKG = "com.bilibili.app.in"
        const val DAILY_LIMIT = 6_300_000L
        const val COOLDOWN_UNTIL = 1_800_000_000_000L
        const val NOW = 1_800_000_100_000L
    }
}
