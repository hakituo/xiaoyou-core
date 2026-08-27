package com.aveline.ai.mobile.presentation.chat

import android.util.Log
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 处理 WebSocket 下发的"消息类"事件并维护会话列表预览。
 *
 * 从 ChatViewModel 拆出，职责：
 * - [handleTextMessage]：文本消息即时上屏 + 落库（含智能分句）
 * - [handleImageResultMessage]：图片消息即时上屏 + 落库
 * - [updateLastMessagePreview]：把当前会话最后一条消息写入 PersonaLocalMeta，
 *   供会话列表页副标题显示（QQ 风格预览）
 *
 * 预览归属的修复（跨角色串台）：
 * 预览必须写到"当前正在查看的 session"对应的 persona 上，而不是后端全局
 * active persona。本地 sessionId 恒为 "web_{persona_filename}"，可从 sessionId
 * 反推 persona filename（见 [ChatSessionController.personaFilenameFromSessionId]）。
 * 若 sessionId 不是 web_ 前缀（如老数据 "default"），才回退到 active persona。
 *
 * @param scope ViewModel 的协程作用域
 * @param uiState UI 状态流，消息即时上屏写入此流
 * @param chatRepository 聊天仓库，用于消息落库
 * @param personaLocalMetaRepository 本地 persona 元数据，用于写列表预览
 * @param generateMessageId 生成唯一消息 ID 的回调
 * @param getSessionId 获取当前会话 ID 的回调（uiState.currentSession?.id）
 * @param getPersonaFilename 获取后端 active persona filename 的回调（兜底用）
 */
class ChatIncomingMessageHandler(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val generateMessageId: () -> String,
    private val getSessionId: () -> String?,
    private val getPersonaFilename: () -> String?
) {
    companion object {
        private const val TAG = "ChatIncomingMessageHandler"
    }

    /** 处理 WebSocket 文本消息：即时上屏 + 落库。 */
    fun handleTextMessage(message: WebSocketMessage.TextMessage) {
        val text = message.text
        if (text.isBlank()) {
            uiState.update { it.copy(isTyping = false, showTypingIndicator = false) }
            return
        }

        val sessionId = getSessionId()
        val messageId = generateMessageId()
        val segments = ChatTextProcessor.smartSegmentText(text)

        if (segments.isEmpty()) {
            uiState.update { it.copy(isTyping = false, showTypingIndicator = false) }
            return
        }

        // 立即把消息加入 uiState,保证 UI 即时显示。
        // 修复 bug: 原实现只写数据库,依赖 Room Flow 异步回流更新 uiState,
        // 但 Flow 回流有延迟且依赖 currentSession 非空,在会话未就绪或 Flow
        // 未建立时消息不会显示。直接更新 uiState 保证即时反馈,Room Flow
        // 回流后会用权威版本替换(消息 id 一致,不会重复)。
        val newMessages = segments.mapIndexed { index, segment ->
            Message(
                id = if (index == 0) messageId else "${messageId}-${index}",
                text = segment.text,
                isUser = false,
                timestamp = System.currentTimeMillis(),
                messageType = if (segment.isRetraction) "retraction" else "text",
                emotion = message.emotion,
                sessionId = sessionId
            )
        }
        uiState.update { it.copy(messages = it.messages + newMessages) }

        // 同时写入数据库,Room Flow 回流后会用权威版本替换 uiState
        // 修复 P0-35: 原实现只 launch 不 catch,数据库写入失败(磁盘满/锁/约束冲突)时
        // 静默丢失,用户感知不到(UI 显示但没入库)。现在加 runCatching 打日志并提示。
        scope.launch(Dispatchers.IO) {
            runCatching {
                newMessages.forEach { msg ->
                    chatRepository.insertMessage(msg)
                }
            }.onFailure { e ->
                Log.e("ChatIncomingMessageHandler", "批量写入消息失败", e)
                uiState.update { it.copy(error = "消息保存失败: ${e.message}") }
            }
        }

        if (text.endsWith("\n\n") || text.isEmpty()) {
            uiState.update { it.copy(isTyping = false, showTypingIndicator = false) }
        }
    }

    /** 处理 WebSocket 图片消息：即时上屏 + 落库。 */
    fun handleImageResultMessage(message: WebSocketMessage.ImageResult) {
        val sessionId = getSessionId()
        val imageMessage = Message(
            id = generateMessageId(),
            text = "",
            isUser = false,
            timestamp = System.currentTimeMillis(),
            messageType = "image",
            imageUrl = message.imageUrl,
            sessionId = sessionId
        )

        // 立即加入 uiState,保证图片消息即时显示(与 handleTextMessage 同理)
        uiState.update { it.copy(messages = it.messages + imageMessage) }

        // 修复 P0-35: 单条图片消息写入加异常保护
        scope.launch(Dispatchers.IO) {
            runCatching {
                chatRepository.insertMessage(imageMessage)
            }.onFailure { e ->
                Log.e("ChatIncomingMessageHandler", "写入图片消息失败", e)
                uiState.update { it.copy(error = "图片消息保存失败: ${e.message}") }
            }
        }
    }

    /**
     * 把 messages 列表的最后一条消息写入 PersonaLocalMeta 的预览字段，
     * 供会话列表页副标题显示（QQ 风格"最后一条消息预览"）。
     *
     * 预览归属规则（跨角色串台修复）：
     * 以**消息自身的 sessionId** 为权威，而不是 getSessionId()。因为 observeMessages()
     * 用 flatMapLatest 切换会话时，旧 flow（上一个角色）的残留消息可能仍在切换瞬间
     * 到达 collect，而此刻 uiState.currentSession 已被 observeCurrentSession 更新为
     * 新角色；若用 getSessionId() 反推，会把上一个角色的最后一条消息写到新角色的
     * 预览上（Aveline 显示卡夫卡的消息、点进去却没有）。消息落库时已绑定正确的
     * sessionId（sessionId = "web_{filename}"），用它反推才准确。
     *
     * 反推失败（消息无 sessionId / 非 web_ 前缀的老数据）才回退到 getSessionId()，
     * 最后才回退到后端 active persona（仅兼容历史脏数据）。
     *
     * 预览文本规则：
     * - 文本消息：直接取 text，超长截断
     * - 图片消息：显示 "[图片]"
     * - 用户消息：前缀 "我: "
     */
    fun updateLastMessagePreview(messages: List<Message>) {
        scope.launch(Dispatchers.IO) {
            if (messages.isEmpty()) {
                // 当前没有消息：清空"当前查看角色"的预览，避免列表残留旧消息。
                // （清空动作跟随当前 session，无竞态风险。）
                val filename = ChatSessionController.personaFilenameFromSessionId(getSessionId())
                    ?: getPersonaFilename()
                    ?: return@launch
                personaLocalMetaRepository.updateLastMessage(
                    personaFilename = filename,
                    preview = null,
                    timestamp = null
                )
                return@launch
            }
            val last = messages.last()
            // 归属以"消息自身的 sessionId"反推（权威）；失败再回退当前 sessionId / active persona。
            val filename = ChatSessionController.personaFilenameFromSessionId(last.sessionId)
                ?: ChatSessionController.personaFilenameFromSessionId(getSessionId())
                ?: getPersonaFilename()
                ?: return@launch
            val preview = buildPreviewText(last)
            personaLocalMetaRepository.updateLastMessage(
                personaFilename = filename,
                preview = preview,
                timestamp = last.timestamp
            )
        }
    }

    /** 构造预览文本（带前缀/类型标签，超长截断），委托给 [ChatPreviewBuilder] 单一真源 */
    private fun buildPreviewText(msg: Message): String =
        ChatPreviewBuilder.buildPreviewText(
            text = msg.text,
            isUser = msg.isUser,
            messageType = msg.messageType,
            imageUrl = msg.imageUrl
        )
}
