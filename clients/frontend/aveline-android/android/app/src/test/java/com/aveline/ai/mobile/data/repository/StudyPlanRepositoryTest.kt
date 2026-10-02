package com.aveline.ai.mobile.data.repository

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StudyPlanRepositoryTest {

    @Test
    fun `typed plan parser keeps stable ids planning metadata and execution facts`() {
        val raw = buildJsonObject {
            put("date", "2026-09-13")
            put("daily_goal_minutes", 420)
            put("notes", "根据 Curriculum 与当前掌握度排程")
            put("source", "algorithm_generated")
            put("revision_count", 2)
            put("generated_at", 100.0)
            put("updated_at", 120.0)
            put("checkpoint_reviews", buildJsonObject { put("2026-09-13:noon", 1.0) })
            put("items", buildJsonArray {
                add(buildJsonObject {
                    put("id", "plan_math_exp_log")
                    put("time", "09:00")
                    put("title", "数学 · 指数对数")
                    put("description", "完成中档题训练")
                    put("category", "study")
                    put("subject", "数学")
                    put("priority", "high")
                    put("estimated_duration_minutes", 90)
                    put("actual_minutes", 60.0)
                    put("status", "completed")
                    put("reminder_id", JsonNull)
                    put("end_reminder_id", JsonNull)
                    put("source_key", "curriculum:math.exp_log")
                    put("source_type", "algorithm")
                    put("score", 8.75)
                    put("carryover_count", 1)
                    put("deferred_from_date", "2026-09-12")
                    put("settlement_reason", JsonNull)
                    put("created_at", 90.0)
                    put("updated_at", 110.0)
                })
            })
        }

        val plan = raw.toStudyPlan("fallback")
        val item = plan.items.single()

        assertEquals("2026-09-13", plan.date)
        assertEquals(420, plan.dailyGoalMinutes)
        assertEquals(2, plan.revisionCount)
        assertEquals("plan_math_exp_log", item.id)
        assertEquals("数学", item.subject)
        assertEquals("90分钟", item.duration)
        assertEquals(90, item.estimatedDurationMinutes)
        assertEquals(60.0, item.actualMinutes, 0.001)
        assertEquals("completed", item.status)
        assertTrue(item.isDone)
        assertEquals("curriculum:math.exp_log", item.sourceKey)
        assertEquals(8.75, item.score, 0.001)
        assertEquals(1, item.carryoverCount)
        assertNull(item.reminderId)
        assertNull(item.settlementReason)
    }

    @Test
    fun `empty typed plan stays empty without markdown fallback`() {
        val raw = buildJsonObject {
            put("date", "2026-09-13")
            put("daily_goal_minutes", 420)
            put("items", buildJsonArray { })
            put("source", "empty")
        }

        val plan = raw.toStudyPlan("fallback")

        assertEquals("2026-09-13", plan.date)
        assertEquals(420, plan.dailyGoalMinutes)
        assertTrue(plan.items.isEmpty())
        assertEquals("empty", plan.source)
    }
}
