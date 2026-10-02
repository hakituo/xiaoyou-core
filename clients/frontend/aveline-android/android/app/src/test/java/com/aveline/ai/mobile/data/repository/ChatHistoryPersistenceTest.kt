package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.local.database.dao.MessageDao
import com.aveline.ai.mobile.data.local.database.dao.preserveMessageBranch
import com.aveline.ai.mobile.data.local.database.entity.MessageEntity
import com.aveline.ai.mobile.data.local.database.entity.MessageTreeNode
import com.aveline.ai.mobile.data.local.preferences.RoleScopedPreferences
import com.aveline.ai.mobile.domain.models.Message
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatHistoryPersistenceTest {
    private fun repository(dao: MessageDao): ChatRepositoryImpl {
        val preferences = mockk<RoleScopedPreferences>()
        every { preferences.resolveSessionId(any()) } answers { firstArg() }
        return ChatRepositoryImpl(
            apiService = mockk(), streamingApiService = mockk(),
            messageDao = dao, appPreferences = mockk(), roleScopedPreferences = preferences
        )
    }

    @Test
    fun `迟到的回复不能重新激活已切走的版本或恢复旧父链`() {
        val snapshot = MessageEntity("reply", "", false, 10, sessionId = "s", parentId = "removed")
        val stored = snapshot.copy(parentId = null, isActiveVariant = false)
        val completed = preserveMessageBranch(snapshot.copy(text = "完成"), stored)
        assertEquals("完成", completed.text)
        assertEquals(null, completed.parentId)
        assertFalse(completed.isActiveVariant)
    }

    @Test
    fun `长会话只读取窗口正文且扩页不切换尾部`() = runTest {
        val dao = mockk<MessageDao>()
        val entities = (0 until 260).map { i ->
            MessageEntity("m$i", "内容$i", i % 2 == 0, i.toLong(),
                sessionId = "s", parentId = if (i == 0) null else "m${i - 1}")
        }
        every { dao.observeMessageTree("s") } returns flowOf(entities.map {
            MessageTreeNode(it.id, it.sessionId, it.parentId, it.timestamp,
                it.isUser, it.variantIndex, it.isActiveVariant)
        })
        coEvery { dao.getMessagesByIds("s", any()) } coAnswers {
            val ids = secondArg<List<String>>().toSet()
            entities.filter { it.id in ids }
        }
        val repo = repository(dao)
        val first = repo.observeMessageWindow("s", 50).first()
        assertEquals(entities.takeLast(50).map { it.id }, first.messages.map { it.id })
        assertTrue(first.hasOlder)
        coVerify(exactly = 1) { dao.getMessagesByIds("s", entities.takeLast(50).map { it.id }) }
        val expanded = repo.observeMessageWindow("s", 100).first()
        assertEquals(first.messages, expanded.messages.takeLast(50))
        assertFalse(repo.observeMessageWindow("s", 300).first().hasOlder)
    }

    @Test
    fun `完成消息不触发任何历史裁剪`() = runTest {
        val dao = mockk<MessageDao>(relaxed = true)
        coEvery { dao.getMessageCount("s") } returns 260
        repository(dao).insertMessage(Message(
            id = "reply", text = "完成", isUser = false, timestamp = 10,
            sessionId = "s", parentId = "user"
        )).getOrThrow()
        coVerify(exactly = 1) { dao.upsertMessageContent(any()) }
        coVerify(exactly = 0) { dao.deleteOldestMessages(any(), any()) }
        coVerify(exactly = 0) { dao.clearParent(any()) }
    }
}
