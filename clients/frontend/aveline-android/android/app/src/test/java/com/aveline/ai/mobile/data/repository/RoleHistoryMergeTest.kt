package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.local.database.mergedMessageId
import com.aveline.ai.mobile.data.local.database.planRoleHistoryMerge
import com.aveline.ai.mobile.data.local.database.entity.MessageEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RoleHistoryMergeTest {
    private fun msg(id: String, session: String, time: Long, parent: String? = null, active: Boolean = true) =
        MessageEntity(id, id, false, time, sessionId = session, parentId = parent, isActiveVariant = active)

    @Test
    fun `两套会话按时间接续且原始记录不改动`() {
        val first = listOf(msg("a", "cn", 1), msg("b", "cn", 4, "a"))
        val second = listOf(msg("c", "en", 2), msg("d", "en", 3, "c"))
        val plan = planRoleHistoryMerge("unified", mapOf("cn" to first, "en" to second))
        assertEquals(4, plan.addedCount)
        assertEquals(listOf("a", "c", "d", "b"), selectActiveConversationPath(plan.messages).map { it.text })
        assertEquals("a", first.last().parentId)
        assertTrue(plan.messages.all { it.sessionId == "unified" })
    }

    @Test
    fun `旧回复版本保留并挂在合并后对应的同级位置`() {
        val source = listOf(msg("a", "cn", 1), msg("b1", "cn", 2, "a", false), msg("b2", "cn", 3, "a"))
        val plan = planRoleHistoryMerge("unified", mapOf("cn" to source, "en" to listOf(msg("c", "en", 2))))
        val inactive = plan.messages.first { it.text == "b1" }
        val active = plan.messages.first { it.text == "b2" }
        assertFalse(inactive.isActiveVariant)
        assertEquals(active.parentId, inactive.parentId)
        assertEquals(listOf("a", "c", "b2"), selectActiveConversationPath(plan.messages).map { it.text })
    }

    @Test
    fun `重试不重复插入或覆盖已更新的目标消息`() {
        val source = listOf(msg("a", "cn", 1))
        val first = planRoleHistoryMerge("unified", mapOf("cn" to source))
        val target = first.messages.map { it.copy(text = "已更新") }
        val repeated = planRoleHistoryMerge("unified", mapOf("cn" to source, "unified" to target))
        assertEquals(0, repeated.addedCount)
        assertTrue(repeated.messages.isEmpty())
        assertEquals(mergedMessageId("cn", "a"), target.single().id)
    }

    @Test
    fun `旧裁剪产生的多个活跃根合并后不自环也不丢最新片段`() {
        val source = listOf(msg("a", "cn", 1), msg("b", "cn", 2), msg("latest", "cn", 3, "b"))
        val plan = planRoleHistoryMerge("unified", mapOf("cn" to source))
        assertTrue(plan.messages.none { it.id == it.parentId })
        assertEquals(listOf("a", "b", "latest"), selectActiveConversationPath(plan.messages).map { it.text })
    }

    @Test(expected = IllegalArgumentException::class)
    fun `归属不一致时拒绝合并`() {
        planRoleHistoryMerge("unified", mapOf("cn" to listOf(msg("a", "other-role", 1))))
    }
}
