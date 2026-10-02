package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.models.StudyPlanItem
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class StudyTodayLogicTest {

    @Test
    fun `in progress task wins over pending task`() {
        val pending = StudyPlanItem(id = "pending", content = "数学", status = "pending")
        val active = StudyPlanItem(id = "active", content = "物理", status = "in_progress")

        assertEquals("active", selectNextPlanItem(listOf(pending, active))?.id)
    }

    @Test
    fun `completed and skipped tasks are ignored for next task`() {
        val completed = StudyPlanItem(id = "done", content = "英语", status = "completed", isDone = true)
        val skipped = StudyPlanItem(id = "skip", content = "化学", status = "skipped")
        val next = StudyPlanItem(id = "next", content = "生物", status = "pending")

        assertEquals("next", selectNextPlanItem(listOf(completed, skipped, next))?.id)
        assertNull(selectNextPlanItem(listOf(completed, skipped)))
    }

    @Test
    fun `skipped task duration is excluded from planned minutes`() {
        val items = listOf(
            StudyPlanItem(id = "a", estimatedDurationMinutes = 90, status = "pending"),
            StudyPlanItem(id = "b", estimatedDurationMinutes = 60, status = "completed", isDone = true),
            StudyPlanItem(id = "c", estimatedDurationMinutes = 45, status = "skipped")
        )

        assertEquals(150, totalPlannedMinutes(items))
    }

    @Test
    fun `study minutes are formatted compactly`() {
        assertEquals("0min", formatStudyMinutes(0))
        assertEquals("45min", formatStudyMinutes(45))
        assertEquals("2h", formatStudyMinutes(120))
        assertEquals("2h 35min", formatStudyMinutes(155))
    }

    @Test
    fun `explicit selected plan id wins over duplicate titles and keeps plan date`() {
        StudyPlanFocusLink.replace(
            listOf(
                StudyPlanItem(id = "first", content = "同名任务"),
                StudyPlanItem(id = "second", content = "同名任务")
            ),
            planDate = "2026-09-14"
        )
        StudyPlanFocusLink.select("second")

        val target = StudyPlanFocusLink.resolveUniqueTarget("同名任务")
        assertEquals("second", target?.itemId)
        assertEquals("2026-09-14", target?.planDate)
        assertNull(StudyPlanFocusLink.resolveUniqueTarget("同名任务"))
    }

    @Test
    fun `subject progress parser preserves canonical subject order`() {
        val content = """
            ## 各科进展
            ### 物理
            - 状态：框架
            ### 数学
            - 状态：体系
            ### 英语
            - 状态：较少
            ## 其他
        """.trimIndent()

        val subjects = parseStudySubjectProgress(content)
        assertEquals(listOf("数学", "英语", "物理"), subjects.map { it.name })
        assertEquals(0.7f, subjects.first().progress)
    }
}
