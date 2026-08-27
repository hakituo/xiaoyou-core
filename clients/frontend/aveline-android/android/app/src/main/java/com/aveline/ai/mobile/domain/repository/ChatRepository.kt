package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.data.remote.api.StreamEvent
import com.aveline.ai.mobile.domain.models.Message
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.JsonObject

/**
 * Repository interface for chat operations.
 * Abstracts data sources for message management.
 */
interface ChatRepository {
    suspend fun sendMessage(
        text: String,
        sessionId: String?,
        model: String,
        personaFilename: String? = null
    ): Result<Message>

    /**
     * 流式发送消息, 返回 SSE 事件流
     * - Chunk: 文本增量, append 到正在生成的消息
     * - Done: 流结束, 含 emotion/messageId
     * - Error: 错误
     */
    fun sendMessageStreaming(
        text: String,
        sessionId: String?,
        model: String,
        personaFilename: String? = null,
        historyOverride: List<Message>? = null
    ): Flow<StreamEvent>

    fun observeMessages(sessionId: String): Flow<List<Message>>

    suspend fun deleteMessage(messageId: String): Result<Unit>

    suspend fun clearHistory(sessionId: String): Result<Unit>

    suspend fun insertMessage(message: Message): Result<Unit>

    /** 插入并选中一个新版本，同时保留同级旧版本。 */
    suspend fun insertMessageVariant(message: Message): Result<Unit>

    /** 切换同一父消息下当前显示的请求或回复版本。 */
    suspend fun selectMessageVariant(message: Message): Result<Unit>

    suspend fun selectSiblingVariant(message: Message, targetIndex: Int): Result<Unit>

    suspend fun updateMessageText(messageId: String, newText: String): Result<Unit>

    suspend fun loadHistoryFromApi(sessionId: String): Result<List<Message>>

    /** 获取当前角色配置 */
    suspend fun getPersona(): Result<JsonObject>

    /** 兼容旧入口：重新生成最后一条 AI 回复。 */
    suspend fun regenerateLast(sessionId: String?, model: String?): Result<Message>

    /** 联网搜索 */
    suspend fun webSearch(query: String): Result<JsonObject>
}
