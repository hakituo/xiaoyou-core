package com.aveline.ai.mobile.data.local.preferences

import android.content.Context
import android.content.SharedPreferences
import io.mockk.every
import io.mockk.mockk
import org.junit.Assert.assertEquals
import org.junit.Test

/** 使用内存偏好验证真实的旧键迁移和角色改名，无设备、网络或时间依赖。 */
class RoleSessionIdentityTest {
    private fun preferences(): RoleScopedPreferences {
        val values = mutableMapOf<String, String?>()
        val editor = mockk<SharedPreferences.Editor>(relaxed = true)
        val prefs = mockk<SharedPreferences>()
        val context = mockk<Context>()
        every { context.getSharedPreferences(any(), any()) } returns prefs
        every { prefs.edit() } returns editor
        every { prefs.contains(any()) } answers { values.containsKey(firstArg()) }
        every { prefs.getString(any(), any()) } answers {
            values[firstArg<String>()] ?: secondArg<String?>()
        }
        every { editor.putString(any(), any()) } answers {
            values[firstArg()] = secondArg()
            editor
        }
        return RoleScopedPreferences(context)
    }

    @Test
    fun `角色标识改变又回滚时沿用首次绑定会话`() {
        val prefs = preferences()
        prefs.setSessionId("旧角色名", "original-session")
        assertEquals("original-session", prefs.getOrBindSessionId("旧角色名", "role.json", "fallback"))
        // 模拟异常版本已经在另一角色键下产生容器，绑定后不能静默切过去。
        prefs.setSessionId("new_scope", "other-session")
        assertEquals("original-session", prefs.getOrBindSessionId("new_scope", "role.json", "fallback"))
        assertEquals("original-session", prefs.getOrBindSessionId("旧角色名", "role.json", "fallback"))
    }

    @Test
    fun `同角色版本共享会话但其他角色保持隔离`() {
        val prefs = preferences()
        prefs.getOrBindSessionId("角色甲", "a.json", "session-a")
        prefs.bindPersonaSessionIfAbsent("a-v2.json", "session-a")
        prefs.getOrBindSessionId("角色乙", "b.json", "session-b")
        assertEquals("session-a", prefs.getSessionId("renamed-a", "a-v2.json"))
        assertEquals("session-b", prefs.getSessionId("renamed-b", "b.json"))
    }
}
