package com.aveline.ai.mobile.domain.models

import kotlinx.serialization.Serializable

/**
 * 双角色对话消息
 */
@Serializable
data class PeerChatMessage(
    val id: String = "",
    val scriptId: String = "",
    val role: String = "",           // aveline / ling
    val roleName: String = "",       // Aveline / Ling
    val text: String = "",
    val emotion: String? = null,
    val roundIndex: Int = 0,
    val timestamp: Long = System.currentTimeMillis()
) {
    companion object {
        /**
         * 获取角色头像
         */
        fun getRoleAvatar(role: String): String {
            return when (role.lowercase()) {
                "aveline" -> "💜"  // Aveline
                "ling" -> "🌸"     // Ling
                else -> "🤖"
            }
        }

        /**
         * 获取角色颜色
         */
        fun getRoleColor(role: String): Long {
            return when (role.lowercase()) {
                "aveline" -> 0xFF9C27B0  // 紫色
                "ling" -> 0xFFE91E63     // 粉色
                else -> 0xFF607D8B       // 灰色
            }
        }
    }
}

/**
 * 双角色对话剧本
 */
@Serializable
data class PeerChatScript(
    val scriptId: String = "",
    val topic: String = "",
    val participants: List<String> = emptyList(),
    val messages: List<PeerChatMessage> = emptyList(),
    val totalRounds: Int = 0,
    val summary: String = "",
    val mentionedUser: Boolean = false,
    val startTime: Long = System.currentTimeMillis(),
    val endTime: Long? = null
) {
    val isActive: Boolean get() = endTime == null
    val progress: Float get() = if (totalRounds > 0) messages.size.toFloat() / totalRounds else 0f
}

/**
 * 双角色对话状态
 */
@Serializable
data class PeerChatState(
    val isEnabled: Boolean = true,
    val isScriptActive: Boolean = false,
    val currentScriptId: String? = null,
    val todayCount: Int = 0,
    val dailyLimit: Int = 6,
    val lastChatTimestamp: Long = 0,
    val recentTopics: List<String> = emptyList()
)
