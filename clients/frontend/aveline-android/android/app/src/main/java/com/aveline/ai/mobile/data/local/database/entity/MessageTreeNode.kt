package com.aveline.ai.mobile.data.local.database.entity

/** 路径索引不携带正文和媒体，长期历史只按需读取当前窗口的消息内容。 */
data class MessageTreeNode(
    val id: String,
    val sessionId: String?,
    val parentId: String?,
    val timestamp: Long,
    val isUser: Boolean,
    val variantIndex: Int,
    val isActiveVariant: Boolean
) {
    fun toPathEntity() = MessageEntity(
        id = id, text = "", sessionId = sessionId, parentId = parentId,
        timestamp = timestamp, isUser = isUser,
        variantIndex = variantIndex, isActiveVariant = isActiveVariant
    )
}
