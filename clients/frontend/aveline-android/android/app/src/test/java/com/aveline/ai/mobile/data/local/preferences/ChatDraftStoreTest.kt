package com.aveline.ai.mobile.data.local.preferences

import android.content.Context
import android.content.SharedPreferences
import io.mockk.every
import io.mockk.mockk
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 用内存偏好验证草稿的按会话存取、清空与条数淘汰，无设备 / 网络 / 真实时间依赖。
 *
 * 之所以要单独测：SharedPreferences 的四种写（新写 / 覆盖 / 删空串 / 淘汰）
 * 全靠 key 与时间戳约定，拼错一个前缀就会表现为"草稿存了却读不回来"。
 */
class ChatDraftStoreTest {

    private fun preferences(): Pair<ChatDraftStore, MutableMap<String, Any?>> {
        val values = mutableMapOf<String, Any?>()
        val editor = mockk<SharedPreferences.Editor>(relaxed = true)
        val prefs = mockk<SharedPreferences>()
        val context = mockk<Context>()
        every { context.getSharedPreferences(any(), any()) } returns prefs
        every { prefs.edit() } returns editor
        every { prefs.all } answers { values.toMap() }
        every { prefs.getString(any(), any()) } answers {
            values[firstArg<String>()] as? String ?: secondArg<String?>()
        }
        every { prefs.getLong(any(), any()) } answers {
            values[firstArg<String>()] as? Long ?: secondArg<Long>()
        }
        every { editor.putString(any(), any()) } answers {
            values[firstArg()] = secondArg<String>()
            editor
        }
        every { editor.putLong(any(), any()) } answers {
            values[firstArg()] = secondArg<Long>()
            editor
        }
        every { editor.remove(any()) } answers {
            values.remove(firstArg<String>())
            editor
        }
        return ChatDraftStore(context) to values
    }

    @Test
    fun `草稿按会话隔离存读，互不串台`() {
        val (store, _) = preferences()

        store.writeDraft("session-a", "给 A 的话")
        store.writeDraft("session-b", "给 B 的话")

        assertEquals("给 A 的话", store.readDraft("session-a"))
        assertEquals("给 B 的话", store.readDraft("session-b"))
        assertEquals("", store.readDraft("session-c"))
    }

    @Test
    fun `写空串等于删草稿`() {
        val (store, values) = preferences()

        store.writeDraft("session-a", "要发的内容")
        assertEquals("要发的内容", store.readDraft("session-a"))

        // 发送成功后输入框被清空，草稿必须跟着删，否则重进聊天会看到已发出的内容。
        store.writeDraft("session-a", "")
        assertEquals("", store.readDraft("session-a"))
        assertEquals(false, values.containsKey("draft_session-a"))
        assertEquals(false, values.containsKey("ts_session-a"))
    }

    @Test
    fun `覆盖同一个会话只留最新内容`() {
        val (store, _) = preferences()

        store.writeDraft("session-a", "第一版")
        store.writeDraft("session-a", "第二版")

        assertEquals("第二版", store.readDraft("session-a"))
    }

    @Test
    fun `超过上限时淘汰最久没动过的草稿`() {
        val (store, _) = preferences()

        repeat(101) { index -> store.writeDraft("session-$index", "草稿-$index") }

        assertEquals(
            "超限后应删掉最早写进去的那条",
            "",
            store.readDraft("session-0")
        )
        assertEquals(
            "最近写的草稿必须还在",
            "草稿-100",
            store.readDraft("session-100")
        )
    }

    @Test
    fun `同步写用的键与异步写一致`() {
        val (store, _) = preferences()

        store.writeDraftSync("session-a", "退出前最后一句")
        assertEquals("退出前的同步写必须能按同一个会话读回来", "退出前最后一句", store.readDraft("session-a"))
    }
}
