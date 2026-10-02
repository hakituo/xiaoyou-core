package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.data.remote.api.StreamEvent
import com.aveline.ai.mobile.domain.models.Message
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
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
        historyOverride: List<Message>? = null,
        branchContext: ChatBranchContext? = null
    ): Flow<StreamEvent>

    fun observeMessages(sessionId: String): Flow<List<Message>>

    /** 窗口限制只影响读取，不删除持久化历史，也不改变用户选中的分支。 */
    fun observeMessageWindow(sessionId: String, limit: Int): Flow<ChatMessageWindow> =
        observeMessages(sessionId).map {
            ChatMessageWindow(it.takeLast(limit), it.size > limit)
        }

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

    /** 同一稳定角色的旧会话合并；消息副本和入口映射必须在成功后一起生效。 */
    suspend fun mergeRoleHistory(roleId: String, aliases: Set<String>, filenames: Set<String>): Result<Int>

    /** 获取当前角色配置 */
    suspend fun getPersona(): Result<JsonObject>

    /** 兼容旧入口：重新生成最后一条 AI 回复。 */
    suspend fun regenerateLast(sessionId: String?, model: String?): Result<Message>

    /**
     * 启动体检：修复因裁剪而丢失根节点的会话，重新接上消息树入口。
     *
     * @return 修复的会话数
     */
    suspend fun repairOrphanedMessageTrees(): Int

    /** 联网搜索 */
    suspend fun webSearch(query: String): Result<JsonObject>
}

data class ChatMessageWindow(val messages: List<Message>, val hasOlder: Boolean)

/**
 * 当前生成事务对应的消息树关系。
 *
 * [branchId] 是“当前世界线”锚点：没有发生过分叉时为空；一旦编辑用户消息或重新生成
 * AI 回复，就使用该激活版本节点 ID，后续普通消息继续沿用它，直到再次发生新分叉。
 */
data class ChatBranchContext(
    val userMessage: Message,
    val assistantMessage: Message,
    val branchId: String? = null,
    val userVariantOfId: String? = null,
    val assistantVariantOfId: String? = null
)
