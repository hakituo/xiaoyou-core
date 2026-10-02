package com.aveline.ai.mobile.data.repository

import android.util.Log
import com.aveline.ai.mobile.data.local.database.selectActiveMessageEntities
import com.aveline.ai.mobile.data.local.database.mergedMessageId
import com.aveline.ai.mobile.data.local.preferences.RoleScopedPreferences
import com.aveline.ai.BuildConfig
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.local.database.dao.MessageDao
import com.aveline.ai.mobile.data.local.database.entity.MessageEntity
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.api.SseParser
import com.aveline.ai.mobile.data.remote.api.StreamEvent
import com.aveline.ai.mobile.data.remote.dto.MessageBranchMetadata
import com.aveline.ai.mobile.data.remote.dto.MessageRequest
import com.aveline.ai.mobile.data.remote.dto.MessageResponse
import com.aveline.ai.mobile.data.remote.dto.HistoryOverrideMessage
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatBranchContext
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.ChatMessageWindow
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import javax.inject.Inject
import javax.inject.Named
import javax.inject.Singleton

@Singleton
class ChatRepositoryImpl @Inject constructor(
    private val apiService: AvelineApiService,
    @Named("streaming") private val streamingApiService: AvelineApiService,
    private val messageDao: MessageDao,
    private val appPreferences: AppPreferences,
    private val roleScopedPreferences: RoleScopedPreferences
) : ChatRepository {

    companion object {
        private const val TAG = "ChatRepositoryImpl"
    }

    // 普通消息的尾节点读取与写入必须串行，避免主动消息和用户发送同时挂成兄弟分支。
    private val messageMutationMutex = Mutex()

    override suspend fun mergeRoleHistory(roleId: String, aliases: Set<String>, filenames: Set<String>): Result<Int> =
        runCatching {
            require(roleId.matches(Regex("[a-z][a-z0-9_]*"))) { "无效角色 ID" }
            messageMutationMutex.withLock {
                val target = "web_role_$roleId"
                val candidates = roleScopedPreferences.legacySessionCandidates(roleId, aliases, filenames)
                val plan = messageDao.mergeRoleHistory(target, candidates.sorted())
                roleScopedPreferences.completeRoleMigration(roleId, aliases, filenames, candidates)
                // 不在列表后台刷新时修改全局当前会话；聊天入口准备完毕后再主动切换。
                Log.i(TAG, "角色历史合并完成 role=$roleId target=$target added=${plan.addedCount}")
                plan.addedCount
            }
        }

    /** 迁移期间仍在后台完成的旧请求，按同一确定性 ID 更新目标会话。 */
    private suspend fun resolveStoredMessage(message: Message): Message {
        val source = message.sessionId ?: return message
        val target = roleScopedPreferences.resolveSessionId(source)
        if (source == target) return message
        suspend fun resolveId(id: String): String =
            if (messageDao.getMessageById(id)?.sessionId == target) id else mergedMessageId(source, id)
        return message.copy(
            id = resolveId(message.id), sessionId = target,
            parentId = message.parentId?.let { resolveId(it) }
        )
    }

    /** 迁移前已发出的编辑、删除和流式更新仍携带原 ID，必须更新目标副本。 */
    private suspend fun resolveStoredMessageId(messageId: String): String {
        val row = messageDao.getMessageById(messageId) ?: return messageId
        val session = row.sessionId ?: return messageId
        val archivePrefix = "archive_role_merge:"
        if (session.startsWith(archivePrefix)) {
            val source = session.removePrefix(archivePrefix).substringAfter(':')
            return mergedMessageId(source, messageId)
        }
        return if (roleScopedPreferences.resolveSessionId(session) != session) mergedMessageId(session, messageId) else messageId
    }

    /**
     * 决定本次请求实际使用的模型，优先级：
     * 1. 调用方显式指定的模型（非 default/auto）
     * 2. 用户手动选择的模型（跨页面和进程重建保留，覆盖角色默认模型）
     * 3. 当前 persona 的默认模型（后端 persona API 的 default_model，
     *    来自 model_routing.chat_models，与 QQ 端同源，不在 Android 侧硬编码）
     * 4. 原样下发（default/auto），交给后端兜底
     */
    private fun resolveRequestModel(model: String): String {
        if (model.isNotBlank() && model != "default" && model != "auto") return model
        appPreferences.selectedModelRoute.takeIf { it.isNotBlank() }?.let { return it }
        appPreferences.personaDefaultModelRoute.takeIf { it.isNotBlank() }?.let { return it }
        return model
    }

    private fun Message.toHistoryOverrideMessage(): HistoryOverrideMessage =
        HistoryOverrideMessage(
            role = if (isUser) "user" else "assistant",
            content = text,
            timestamp = timestamp,
            message_id = id,
            parent_id = parentId,
            variant_index = variantIndex,
            variant_count = variantCount,
            is_active_variant = isActiveVariant
        )

    private fun ChatBranchContext.toRequestMetadata(): MessageBranchMetadata =
        MessageBranchMetadata(
            user_message_id = userMessage.id,
            user_parent_id = userMessage.parentId,
            user_variant_index = userMessage.variantIndex,
            user_variant_count = userMessage.variantCount,
            user_variant_of = userVariantOfId,
            assistant_message_id = assistantMessage.id,
            assistant_parent_id = assistantMessage.parentId,
            assistant_variant_index = assistantMessage.variantIndex,
            assistant_variant_count = assistantMessage.variantCount,
            assistant_variant_of = assistantVariantOfId,
            branch_id = branchId
        )

    override suspend fun sendMessage(
        text: String,
        sessionId: String?,
        model: String,
        personaFilename: String?
    ): Result<Message> {
        return try {
            val userMessageId = System.currentTimeMillis().toString()
            val userMessage = Message(
                id = userMessageId,
                text = text,
                isUser = true,
                timestamp = System.currentTimeMillis(),
                messageType = "text",
                sessionId = sessionId ?: "default"
            )
            insertMessage(userMessage).getOrThrow()

            val request = MessageRequest(
                text = text,
                session_id = sessionId?.let { roleScopedPreferences.resolveSessionId(it) },
                model = resolveRequestModel(model),
                persona_filename = personaFilename
            )
            val response = apiService.sendMessage(request)

            // AI 回复由 WebSocket 流式推送(ChatFlushManager),不在此处插入数据库(避免重复)
            val rawMessage = response.toDomainModel(sessionId)

            Result.success(rawMessage)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override fun sendMessageStreaming(
        text: String,
        sessionId: String?,
        model: String,
        personaFilename: String?,
        historyOverride: List<Message>?,
        branchContext: ChatBranchContext?
    ): Flow<StreamEvent> = callbackFlow {
        // 流式开关：BuildConfig.STREAMING_ENABLED=false 时退化为一次性请求，
        // 把结果包装成 StreamEvent 发出，上层 ChatViewModel 无需改动。
        if (!BuildConfig.STREAMING_ENABLED) {
            runCatching {
                val request = MessageRequest(
                    text = text,
                    session_id = sessionId?.let { roleScopedPreferences.resolveSessionId(it) },
                    model = resolveRequestModel(model),
                    stream = false,
                    history_override = historyOverride?.map { it.toHistoryOverrideMessage() },
                    branch_metadata = branchContext?.toRequestMetadata(),
                    persona_filename = personaFilename
                )
                // sendMessage 直接返回 MessageResponse（suspend，非 Response<T>）
                val msg = apiService.sendMessage(request).toDomainModel(sessionId)
                val content = msg.text
                if (content.isNotEmpty()) {
                    trySend(StreamEvent.Chunk(content))
                }
                trySend(StreamEvent.Done(messageId = msg.id, emotion = msg.emotion))
            }.onFailure { e ->
                trySend(StreamEvent.Error("请求失败: ${e.message}"))
            }
            close()
            return@callbackFlow
        }

        var responseBody: okhttp3.ResponseBody? = null
        try {
            val request = MessageRequest(
                text = text,
                session_id = sessionId?.let { roleScopedPreferences.resolveSessionId(it) },
                model = resolveRequestModel(model),
                stream = true,  // 后端读 body.stream 走 SSE
                history_override = historyOverride?.map { it.toHistoryOverrideMessage() },
                branch_metadata = branchContext?.toRequestMetadata(),
                persona_filename = personaFilename
            )
            // 使用流式专用 ApiService（HEADERS 级别日志，不缓冲响应体）
            val response = streamingApiService.sendMessageStreaming(request)

            if (!response.isSuccessful) {
                trySend(StreamEvent.Error("HTTP ${response.code()}: ${response.message()}"))
                return@callbackFlow
            }

            val body = response.body() ?: run {
                trySend(StreamEvent.Error("响应体为空"))
                return@callbackFlow
            }
            responseBody = body

            // 用 source().readUtf8Line() 逐行读取 SSE
            val source = body.source()
            while (isActive) {
                val line = try {
                    source.readUtf8Line() ?: break  // 流自然结束
                } catch (e: Exception) {
                    if (isActive) {
                        trySend(StreamEvent.Error("读取流失败: ${e.message}"))
                    }
                    break
                }

                val event = SseParser.parse(line)
                if (event != null) {
                    trySend(event)
                    if (event is StreamEvent.Done || event is StreamEvent.Error) {
                        break
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "流式请求失败", e)
            trySend(StreamEvent.Error("请求失败: ${e.message}"))
        } finally {
            // 确保关闭 ResponseBody 释放连接
            try { responseBody?.close() } catch (_: Exception) {}
            close()
        }

        awaitClose {
            // 协程被取消时, callbackFlow 会关闭 channel
            // ResponseBody 在 finally 已关闭
        }
    }.flowOn(Dispatchers.IO)

    override fun observeMessages(sessionId: String): Flow<List<Message>> {
        return messageDao.observeMessages(roleScopedPreferences.resolveSessionId(sessionId))
            .map { entities ->
                selectActiveConversationPath(entities)
            }
    }

    override fun observeMessageWindow(sessionId: String, limit: Int): Flow<ChatMessageWindow> {
        require(limit > 0)
        val resolvedSessionId = roleScopedPreferences.resolveSessionId(sessionId)
        return messageDao.observeMessageTree(resolvedSessionId).map { nodes ->
            val path = selectActiveConversationPath(nodes.map { it.toPathEntity() })
            val window = path.takeLast(limit)
            // 分批避开旧版 SQLite 的绑定参数上限，只有窗口正文会进入内存。
            val stored = window.map { it.id }.chunked(500).flatMap {
                messageDao.getMessagesByIds(resolvedSessionId, it)
            }.associateBy { it.id }
            ChatMessageWindow(
                window.mapNotNull { node ->
                    stored[node.id]?.toDomainModel()?.copy(
                        variantIndex = node.variantIndex, variantCount = node.variantCount
                    )
                },
                path.size > limit
            )
        }.flowOn(Dispatchers.IO)
    }

    override suspend fun deleteMessage(messageId: String): Result<Unit> {
        return try {
            messageMutationMutex.withLock { messageDao.deleteMessage(resolveStoredMessageId(messageId)) }
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun clearHistory(sessionId: String): Result<Unit> {
        return try {
            messageMutationMutex.withLock { messageDao.clearSession(roleScopedPreferences.resolveSessionId(sessionId)) }
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun insertMessage(message: Message): Result<Unit> {
        return try {
            messageMutationMutex.withLock {
                val message = resolveStoredMessage(message)
                val normalized = if (message.parentId == null && message.sessionId != null) {
                    val existing = messageDao.getMessageTree(message.sessionId).map { it.toPathEntity() }
                    val isExistingMessage = existing.any { it.id == message.id }
                    if (!isExistingMessage && existing.isNotEmpty()) {
                        // 挂到当前活跃路径的尾部；路径本身断根时会退化成"最旧一条"，
                        // 这里再退一步取时间上最后一条，绝不能算出 null 把它变成新根
                        // （那样会把既有历史整段变成孤儿）。
                        val tailId = selectActiveConversationPath(existing).lastOrNull()?.id
                            ?: existing.maxByOrNull { it.timestamp }?.id
                        message.copy(parentId = tailId)
                    } else {
                        message
                    }
                } else {
                    message
                }
                messageDao.upsertMessageContent(normalized.toEntity())
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Log.e(TAG, "插入消息失败", e)
            Result.failure(e)
        }
    }

    override suspend fun insertMessageVariant(message: Message): Result<Unit> {
        return try {
            messageMutationMutex.withLock {
                messageDao.insertActiveVariant(resolveStoredMessage(message).toEntity())
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Log.e(TAG, "插入消息版本失败", e)
            Result.failure(e)
        }
    }

    override suspend fun selectMessageVariant(message: Message): Result<Unit> {
        val sessionId = message.sessionId
            ?: return Result.failure(IllegalArgumentException("消息缺少 sessionId"))
        return try {
            messageMutationMutex.withLock {
                val resolved = resolveStoredMessage(message)
                messageDao.selectVariant(resolved.sessionId ?: sessionId, resolved.parentId, resolved.isUser, resolved.id)
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Log.e(TAG, "切换消息版本失败", e)
            Result.failure(e)
        }
    }

    override suspend fun selectSiblingVariant(message: Message, targetIndex: Int): Result<Unit> {
        val sessionId = message.sessionId
            ?: return Result.failure(IllegalArgumentException("消息缺少 sessionId"))
        return try {
            messageMutationMutex.withLock {
                val resolved = resolveStoredMessage(message)
                val siblings = messageDao.getSiblingVariants(resolved.sessionId ?: sessionId, resolved.parentId, resolved.isUser)
                val target = siblings.getOrNull(targetIndex)
                    ?: throw IndexOutOfBoundsException("消息版本不存在")
                messageDao.selectVariant(resolved.sessionId ?: sessionId, resolved.parentId, resolved.isUser, target.id)
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Log.e(TAG, "选择相邻消息版本失败", e)
            Result.failure(e)
        }
    }

    override suspend fun updateMessageText(messageId: String, newText: String): Result<Unit> {
        return try {
            messageMutationMutex.withLock { messageDao.updateMessageText(resolveStoredMessageId(messageId), newText) }
            Result.success(Unit)
        } catch (e: Exception) {
            Log.e(TAG, "更新消息文本失败", e)
            Result.failure(e)
        }
    }

    override suspend fun loadHistoryFromApi(sessionId: String): Result<List<Message>> {
        return try {
            val sessionId = roleScopedPreferences.resolveSessionId(sessionId)
            val localCount = messageDao.getMessageCount(sessionId)
            if (localCount > 0) {
                Log.d(TAG, "本地已有 $localCount 条消息，跳过API历史加载")
                return Result.success(emptyList())
            }

            val response = apiService.getSessionHistory(sessionId)
            var previousId: String? = null
            val messages = response.messages.map { dto ->
                dto.toDomainModel(sessionId).copy(sessionId = sessionId, parentId = previousId).also {
                    previousId = it.id
                }
            }

            if (messages.isNotEmpty()) {
                // 批量插入,单事务提交,避免逐条写入的 IO 放大
                val inserted = messageMutationMutex.withLock {
                    if (roleScopedPreferences.resolveSessionId(sessionId) != sessionId) false
                    else messageDao.insertHistoryIfEmpty(sessionId, messages.map { it.toEntity() })
                }
                if (!inserted) {
                    Log.d(TAG, "历史请求期间本地已有新消息，丢弃旧历史快照: $sessionId")
                    return Result.success(emptyList())
                }
            }

            Log.d(TAG, "从API加载了 ${messages.size} 条历史消息")
            Result.success(messages)
        } catch (e: Exception) {
            Log.e(TAG, "从API加载历史消息失败", e)
            Result.failure(e)
        }
    }

    override suspend fun getPersona(): Result<JsonObject> {
        return try {
            val raw = apiService.getActivePersonaRaw()
            Result.success(raw)
        } catch (e: Exception) {
            Log.e(TAG, "获取角色配置失败", e)
            Result.failure(e)
        }
    }

    override suspend fun regenerateLast(sessionId: String?, model: String?): Result<Message> {
        return try {
            val payload = buildJsonObject {
                sessionId?.let { put("conversation_id", roleScopedPreferences.resolveSessionId(it)) }
                model?.let { put("model", it) }
            }
            val response = apiService.regenerateMessage(payload)
            val rawMessage = response.toDomainModel(sessionId)
            insertMessage(rawMessage).getOrThrow()
            Result.success(rawMessage)
        } catch (e: Exception) {
            Log.e(TAG, "重新生成失败", e)
            Result.failure(e)
        }
    }

    override suspend fun webSearch(query: String): Result<JsonObject> {
        return try {
            val payload = buildJsonObject { put("query", query) }
            val result = apiService.webSearch(payload)
            Result.success(result)
        } catch (e: Exception) {
            Log.e(TAG, "联网搜索失败", e)
            Result.failure(e)
        }
    }

    /**
     * 仅在会话只有一个明确断链入口时恢复根节点。
     *
     * 不会按时间猜测分支，也不会在已有根的情况下创建第二个根，
     * 避免正常链路下无谓地写库触发 Flow 抖动。
     *
     * @return 是否真的重新置了根
     */
    private suspend fun repairUnambiguousRoot(sessionId: String): Boolean =
        messageMutationMutex.withLock {
            val surviving = messageDao.getMessageTree(sessionId)
            // 已有根时绝不创建第二个根；多条断链无法推断用户选了哪条，保留原数据待恢复。
            if (surviving.any { it.parentId == null }) return@withLock false
            val ids = surviving.mapTo(mutableSetOf()) { it.id }
            val orphan = surviving.filter { it.parentId !in ids }.singleOrNull()
                ?: return@withLock false
            if (!orphan.isActiveVariant) return@withLock false
            messageDao.clearParent(orphan.id)
            Log.d(TAG, "会话 $sessionId 仅有一个断链入口，恢复根 ${orphan.id}")
            true
        }

    /**
     * 启动时体检：把历史上已经断根的会话重新接上。
     *
     * 老版本 `enforceMessageLimit` 删最旧消息时会把消息树的根一起删掉，
     * 仅修复没有现存根且只有一个确定入口的链；多根或多条断链不自动改写。
     * 消息本身还在库里（被删的只有超出限额的那部分），重新立根即可找回。
     *
     * @return 修复的会话数
     */
    override suspend fun repairOrphanedMessageTrees(): Int = withContext(Dispatchers.IO) {
        var repaired = 0
        runCatching {
            for (sessionId in messageDao.getAllSessionIds()) {
                if (repairUnambiguousRoot(sessionId)) repaired++
            }
        }.onFailure { e ->
            Log.w(TAG, "断根会话体检失败: ${e.message}")
        }
        if (repaired > 0) {
            Log.d(TAG, "断根体检：修复了 $repaired 个会话的消息树入口")
        }
        repaired
    }
}

private fun com.aveline.ai.mobile.data.remote.dto.MessageDto.toDomainModel(defaultSessionId: String? = null): Message {
    return Message(
        id = id,
        text = text,
        isUser = isUser,
        // DTO 是后端浮点秒，域模型统一毫秒 Long；normalizeTimestamp 兼容秒/毫秒两种量级
        timestamp = normalizeTimestamp(timestamp),
        messageType = messageType,
        audioBase64 = audioBase64,
        imageUrl = imageUrl,
        imageBase64 = imageBase64,
        videoUrl = videoUrl,
        emotion = emotion,
        sessionId = sessionId ?: defaultSessionId
    )
}

private fun MessageResponse.toDomainModel(defaultSessionId: String?): Message {
    val dto = message ?: data
    if (dto != null && dto.id.isNotBlank() && dto.text.isNotBlank()) {
        return dto.toDomainModel().copy(
            emotion = emotion ?: dto.emotion,
            sessionId = dto.sessionId ?: conversationId ?: defaultSessionId
        )
    }

    val responseText = (response ?: reply).orEmpty().trim()
    if (responseText.isEmpty()) {
        throw IllegalStateException(error ?: "后端未返回有效回复")
    }

    return Message(
        id = messageId?.takeIf { it.isNotBlank() } ?: System.currentTimeMillis().toString(),
        text = responseText,
        isUser = false,
        timestamp = normalizeTimestamp(timestamp),
        messageType = "text",
        emotion = emotion,
        sessionId = conversationId ?: defaultSessionId
    )
}

private fun normalizeTimestamp(rawTimestamp: Double?): Long {
    if (rawTimestamp == null || rawTimestamp <= 0) {
        return System.currentTimeMillis()
    }
    val value = rawTimestamp.toLong()
    return if (value < 1_000_000_000_000L) value * 1000 else value
}

private fun Message.toEntity(): MessageEntity {
    return MessageEntity(
        id = id,
        text = text,
        isUser = isUser,
        timestamp = timestamp,
        messageType = messageType,
        audioBase64 = audioBase64,
        imageUrl = imageUrl,
        videoUrl = videoUrl,
        sessionId = sessionId,
        parentId = parentId,
        variantIndex = variantIndex,
        isActiveVariant = isActiveVariant
    )
}

private fun MessageEntity.toDomainModel(): Message {
    return Message(
        id = id,
        text = text,
        isUser = isUser,
        timestamp = timestamp,
        messageType = messageType,
        audioBase64 = audioBase64,
        imageUrl = imageUrl,
        imageBase64 = null,
        videoUrl = videoUrl,
        emotion = null,
        sessionId = sessionId,
        parentId = parentId,
        variantIndex = variantIndex,
        isActiveVariant = isActiveVariant
    )
}

/**
 * 从持久化消息树中提取当前选中的单条对话路径，并补齐版本计数。
 *
 * 兜底：若整棵树找不到 parentId == NULL 的根（最旧消息被裁剪删除、或旧版本
 * 遗留的脏数据），就退而把最旧的一条当根继续往下走。
 * 缺了这个兜底，断根的会话会直接返回空列表 —— 用户看到的是"聊天记录整屏消失"。
 *
 * 标记为 internal 而非 private：这段兜底逻辑由
 * `MessageTreePathTest` 直接钉住（见 app/src/test），改动前先看那个测试。
 */
internal fun selectActiveConversationPath(entities: List<MessageEntity>): List<Message> {
    val siblingsByParent = entities.groupBy { it.parentId to it.isUser }
    return selectActiveMessageEntities(entities).map { current ->
        val siblings = siblingsByParent[current.parentId to current.isUser].orEmpty()
            .sortedWith(compareBy<MessageEntity> { it.variantIndex }.thenBy { it.timestamp }.thenBy { it.id })
        current.toDomainModel().copy(
            variantIndex = siblings.indexOfFirst { it.id == current.id }.coerceAtLeast(0),
            variantCount = siblings.size.coerceAtLeast(1)
        )
    }
}
