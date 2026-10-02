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
 * 处理 WebSocket 下发的消息并维护会话列表预览。
 *
 * session 现在按 role 固定，不再能永远通过 `web_{persona}` 字符串反推当前人设；预览归属
 * 由 ChatSessionController 的 session->persona 运行时映射解析，兼容旧 session 的同时避免
 * 同一角色换 persona 后把预览继续写到旧 persona 文件名。
 */
class ChatIncomingMessageHandler(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val generateMessageId: () -> String,
    private val getSessionId: () -> String?,
    private val resolvePersonaFilenameForSession: (String?) -> String?,
    private val getPersonaFilename: () -> String?
) {
    companion object {
        private const val TAG = "ChatIncomingMessageHandler"
    }

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

        scope.launch(Dispatchers.IO) {
            runCatching {
                newMessages.forEach { msg -> chatRepository.insertMessage(msg) }
            }.onFailure { e ->
                Log.e(TAG, "批量写入消息失败", e)
                uiState.update { it.copy(error = "消息保存失败: ${e.message}") }
            }
        }

        if (text.endsWith("\n\n") || text.isEmpty()) {
            uiState.update { it.copy(isTyping = false, showTypingIndicator = false) }
        }
    }

    fun handleImageResultMessage(message: WebSocketMessage.ImageResult) {
        val imageUrl = message.imageUrl.takeIf { it.isNotBlank() } ?: run {
            Log.w(TAG, "收到空白图片地址，忽略本次 image_result")
            return
        }
        val sessionId = getSessionId()
        val imageMessage = Message(
            id = generateMessageId(),
            text = "",
            isUser = false,
            timestamp = System.currentTimeMillis(),
            messageType = "image",
            imageUrl = imageUrl,
            sessionId = sessionId
        )

        uiState.update { it.copy(messages = it.messages + imageMessage) }
        scope.launch(Dispatchers.IO) {
            runCatching { chatRepository.insertMessage(imageMessage) }
                .onFailure { e ->
                    Log.e(TAG, "写入图片消息失败", e)
                    uiState.update { it.copy(error = "图片消息保存失败: ${e.message}") }
                }
        }
    }

    fun handleVideoResultMessage(message: WebSocketMessage.VideoResult) {
        val videoUrl = message.videoUrl.takeIf { it.isNotBlank() } ?: run {
            Log.w(TAG, "收到空白视频地址，忽略本次 video_result")
            return
        }
        val sessionId = getSessionId()
        val videoMessage = Message(
            id = generateMessageId(),
            text = "",
            isUser = false,
            timestamp = System.currentTimeMillis(),
            messageType = "video",
            videoUrl = videoUrl,
            sessionId = sessionId
        )
        uiState.update { it.copy(messages = it.messages + videoMessage) }

        scope.launch(Dispatchers.IO) {
            runCatching { chatRepository.insertMessage(videoMessage) }
                .onFailure { e ->
                    Log.e(TAG, "写入视频消息失败", e)
                    uiState.update { it.copy(error = "视频消息保存失败: ${e.message}") }
                }
        }
    }

    /**
     * 把当前会话最后一条消息写入 PersonaLocalMeta。
     *
     * 归属优先使用消息自身 sessionId，经 controller 的映射解析；这样 flatMapLatest 切角色时
     * 即使旧 flow 最后一帧晚到，也仍然能落回旧 session 对应 persona，而不会串到新角色。
     */
    fun updateLastMessagePreview(messages: List<Message>) {
        scope.launch(Dispatchers.IO) {
            if (messages.isEmpty()) {
                val filename = resolvePersonaFilenameForSession(getSessionId())
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
            val filename = resolvePersonaFilenameForSession(last.sessionId)
                ?: resolvePersonaFilenameForSession(getSessionId())
                ?: getPersonaFilename()
                ?: return@launch
            personaLocalMetaRepository.updateLastMessage(
                personaFilename = filename,
                preview = buildPreviewText(last),
                timestamp = last.timestamp
            )
        }
    }

    private fun buildPreviewText(msg: Message): String =
        ChatPreviewBuilder.buildPreviewText(
            text = msg.text,
            isUser = msg.isUser,
            messageType = msg.messageType,
            imageUrl = msg.imageUrl,
            videoUrl = msg.videoUrl
        )
}
