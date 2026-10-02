package com.aveline.ai.mobile.data.local.database.entity

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Room entity for storing chat messages locally.
 * 
 * This entity stores message data including text, metadata, and media references.
 * 消息按会话长期保存；显示窗口和请求上下文的大小不能作为删除历史的依据。
 */
@Entity(
    tableName = "messages",
    indices = [Index(value = ["sessionId", "parentId", "isUser"])]
)
data class MessageEntity(
    @PrimaryKey
    val id: String,
    val text: String,
    val isUser: Boolean,
    val timestamp: Long,
    val messageType: String = "text",
    val audioBase64: String? = null,
    val imageUrl: String? = null,
    /** 视频/动图地址（后端相对路径或绝对 URL），非空即按视频消息渲染。 */
    val videoUrl: String? = null,
    val sessionId: String? = null,
    val parentId: String? = null,
    val variantIndex: Int = 0,
    val isActiveVariant: Boolean = true
)
