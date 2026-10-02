package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable
import kotlinx.serialization.SerialName

/**
 * Response DTO for message operations from the backend.
 * 
 * @property status Response status (success, error, etc.)
 * @property message The message object
 * @property emotion Optional emotion state from the AI
 * @property emotion_internal Optional emotion mix percentages
 */
@Serializable
data class MessageResponse(
    val status: String = "",
    val message: MessageDto? = null,
    val data: MessageDto? = null,
    val response: String? = null,
    val reply: String? = null,
    @SerialName("request_id")
    val requestId: String? = null,
    @SerialName("message_id")
    val messageId: String? = null,
    @SerialName("conversation_id")
    val conversationId: String? = null,
    val timestamp: Double? = null,
    val emotion: String? = null,
    val emotion_internal: Map<String, Float>? = null,
    val error: String? = null
)

/**
 * Message DTO representing a chat message.
 * 
 * @property id Unique message identifier
 * @property text Message text content
 * @property isUser Whether the message is from the user
 * @property timestamp Message timestamp in seconds（后端 history 接口透传存储层的
 * time.time() 浮点秒，如 1790004529.5665276；声明 Long 会在 kotlinx.serialization
 * 解析浮点字面量时直接抛错，读取聊天记录整体失败）
 * @property messageType Type of message (text, system, retraction, image_result)
 * @property audioBase64 Optional base64-encoded audio data
 * @property imageUrl Optional image URL
 * @property imageBase64 Optional base64-encoded image data
 * @property videoUrl Optional video/GIF URL
 * @property emotion Optional emotion marker
 * @property sessionId Optional session ID
 */
@Serializable
data class MessageDto(
    val id: String = "",
    val text: String = "",
    @SerialName("isUser")
    val isUser: Boolean = false,
    val timestamp: Double = 0.0,
    val messageType: String = "text",
    val audioBase64: String? = null,
    val imageUrl: String? = null,
    val imageBase64: String? = null,
    val videoUrl: String? = null,
    val emotion: String? = null,
    val sessionId: String? = null
)
