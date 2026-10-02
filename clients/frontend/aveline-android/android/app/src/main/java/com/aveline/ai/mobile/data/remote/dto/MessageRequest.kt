package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable

@Serializable
data class HistoryOverrideMessage(
    val role: String,
    val content: String,
    /** 消息发送时间（epoch 毫秒）。后端用它补 [MM-DD HH:MM] 时间戳前缀，
     *  让模型感知每条历史消息的发生时间，避免"几小时前说的还当现在"。 */
    val timestamp: Long? = null,
    /** Android Room 消息树节点 ID；只用于后端关系记忆，不进入 LLM 正文。 */
    val message_id: String? = null,
    /** 当前节点的父消息 ID。 */
    val parent_id: String? = null,
    val variant_index: Int = 0,
    val variant_count: Int = 1,
    val is_active_variant: Boolean = true
)

/**
 * 当前请求中新写入的一对 user/assistant 节点关系。
 *
 * history_override 只描述“已经存在的当前激活路径”；当前用户消息和正在生成的 AI
 * 占位消息并不在里面，所以单独带一份 branch_metadata 给后端落 WeightedMemory。
 */
@Serializable
data class MessageBranchMetadata(
    val user_message_id: String,
    val user_parent_id: String? = null,
    val user_variant_index: Int = 0,
    val user_variant_count: Int = 1,
    val user_variant_of: String? = null,
    val assistant_message_id: String,
    val assistant_parent_id: String? = null,
    val assistant_variant_index: Int = 0,
    val assistant_variant_count: Int = 1,
    val assistant_variant_of: String? = null,
    /** 可选世界线锚点；当前实现主要依赖 parent + variant_of 恢复完整 lineage。 */
    val branch_id: String? = null
)

/**
 * Request DTO for sending a message to the backend.
 *
 * @property text The message text content
 * @property session_id Optional session ID to associate the message with
 * @property model The AI model to use for generating response
 * @property response_length Response length preference (short, normal, detailed)
 * @property context Optional context data for the message
 */
@Serializable
data class MessageRequest(
    val text: String,
    val session_id: String? = null,
    val model: String,
    val response_length: String = "normal",
    val context: Map<String, String>? = null,
    // 后端 routers/v1/chat.py 第 290 行兼容 body 里的 stream 字段, 传 true 走 SSE 流式
    val stream: Boolean = false,
    /** 当前选中的本地对话树路径；编辑或切换分支后覆盖线性服务端历史。 */
    val history_override: List<HistoryOverrideMessage>? = null,
    /** 当前新消息与待生成回复的树关系，只供后端关系记忆落库。 */
    val branch_metadata: MessageBranchMetadata? = null,
    /** 本轮稳定 ID；默认复用正在生成的 assistant 节点 ID。 */
    val message_id: String? = branch_metadata?.assistant_message_id,
    // 当前 persona filename：用于后端规范化 conversation_id 为 shared__persona__{slug}
    // 不同 persona 走不同的历史和记忆池；不传时后端 fallback 用全局 active persona
    val persona_filename: String? = null
)
