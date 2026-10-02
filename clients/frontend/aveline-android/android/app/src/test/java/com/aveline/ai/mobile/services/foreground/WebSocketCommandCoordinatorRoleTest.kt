package com.aveline.ai.mobile.services.foreground

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 通知深链的角色解析。
 *
 * 后端 proactive_message 下发的是 QQ 侧会话 id（private_10001__persona__core_aveline），
 * 与 Android 本地 sessionId（web_{persona_filename}）不是一个命名空间，且 NavGraph 的
 * chat 深链没有 ?session_id= 参数。必须解析成 role 才能走已支持的
 * aveline://chat?role= 深链，否则点了通知没反应。
 */
class WebSocketCommandCoordinatorRoleTest {

    @Test
    fun `parses role from qq persona conversation id`() {
        assertEquals(
            "aveline",
            WebSocketCommandCoordinator.roleIdFromConversationId(
                "private_10001__persona__core_aveline"
            )
        )
    }

    @Test
    fun `parses role without core prefix`() {
        assertEquals(
            "ling",
            WebSocketCommandCoordinator.roleIdFromConversationId("shared__persona__ling")
        )
    }

    @Test
    fun `returns null when persona marker missing`() {
        assertNull(WebSocketCommandCoordinator.roleIdFromConversationId("mobile_user"))
        assertNull(WebSocketCommandCoordinator.roleIdFromConversationId(null))
        assertNull(WebSocketCommandCoordinator.roleIdFromConversationId(""))
    }
}
