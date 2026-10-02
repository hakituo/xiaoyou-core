package com.aveline.ai.mobile.domain.models

import kotlinx.serialization.Serializable

/**
 * Domain model for a chat message.
 * Represents a message in the business logic layer, separate from DTOs and entities.
 */
@Serializable
data class Message(
    val id: String,
    val text: String,
    val isUser: Boolean,
    val timestamp: Long,
    val messageType: String = "text",
    val audioBase64: String? = null,
    val imageUrl: String? = null,
    val imageBase64: String? = null,
    /** 视频/动图地址（后端相对路径或绝对 URL），非空即按视频消息渲染。 */
    val videoUrl: String? = null,
    val emotion: String? = null,
    val sessionId: String? = null,
    /** 对话树中的父消息；同一父消息下、角色相同的消息互为版本。 */
    val parentId: String? = null,
    val variantIndex: Int = 0,
    val variantCount: Int = 1,
    val isActiveVariant: Boolean = true
)
