package com.aveline.ai.mobile.data.samsung

import java.time.Duration
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Samsung Health 睡眠会话选择及实际睡眠时长回归测试。 */
class SamsungSleepSelectionTest {

    @Test
    fun `多条有效会话应选择结束时间最新的一条`() {
        val now = Instant.parse("2026-08-18T04:00:00Z")
        val windows = listOf(
            SleepRecordWindow(
                endTime = Instant.parse("2026-08-17T03:33:00Z"),
                durationMinutes = 553
            ),
            SleepRecordWindow(
                endTime = Instant.parse("2026-08-18T00:53:00Z"),
                durationMinutes = 461
            )
        )

        val selectedIndex = selectLatestCompletedSleepRecordIndex(windows, now)

        assertEquals(1, selectedIndex)
    }

    @Test
    fun `未来会话和短碎片不应覆盖最近完整睡眠`() {
        val now = Instant.parse("2026-08-18T04:00:00Z")
        val windows = listOf(
            SleepRecordWindow(
                endTime = Instant.parse("2026-08-18T00:53:00Z"),
                durationMinutes = 461
            ),
            SleepRecordWindow(
                endTime = Instant.parse("2026-08-18T03:30:00Z"),
                durationMinutes = 20
            ),
            SleepRecordWindow(
                endTime = Instant.parse("2026-08-18T04:05:00Z"),
                durationMinutes = 500
            )
        )

        val selectedIndex = selectLatestCompletedSleepRecordIndex(windows, now)

        assertEquals(0, selectedIndex)
    }

    @Test
    fun `实际睡眠应先合并阶段时长再按整分钟取整`() {
        val minutes = sumDurationsInWholeMinutes(
            listOf(
                Duration.ofSeconds(30),
                Duration.ofSeconds(30),
                Duration.ofMinutes(419)
            )
        )

        assertEquals(420L, minutes)
    }

    @Test
    fun `没有有效阶段时长应返回空值以触发会话时长回退`() {
        assertNull(sumDurationsInWholeMinutes(emptyList()))
    }
}
