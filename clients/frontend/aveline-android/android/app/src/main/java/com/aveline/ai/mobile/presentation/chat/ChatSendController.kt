package com.aveline.ai.mobile.presentation.chat

import android.util.Log
import com.aveline.ai.mobile.data.remote.api.StreamEvent
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 负责"发消息"的核心流程（HTTP SSE 流式回复）。
 *
 * 从 ChatViewModel 拆出，职责：
 * - [sendMessage]：用户发消息 → 即时上屏用户消息 → 调后端流式收集 AI 回复 →
 *   边收边更新 UI（增量文本）+ 边收边播 TTS → 流结束写库 + 更新 emotion。
 *
 * 流程中的可复用步骤：
 * - 首次发消息时按需切换到目标角色 persona（[ChatSessionController.consumePendingSwitchIfNeeded]）
 * - 流式期间通过 [ChatFlushManager.setHttpStreamingActive] 抑制 WS 双通道冲突
 * - 自动播报通过 [ChatTtsController] 的流式接口边收边播
 *
 * @param scope ViewModel 的协程作用域
 * @param uiState UI 状态流
 * @param chatRepository 聊天仓库
 * @param sessionController 会话控制器（取当前 persona / 发消息前消费 pendingSwitch）
 * @param ttsController TTS 控制器（流式边收边播）
 * @param flushManager 流式批量刷新（HTTP SSE 期间抑制 WS 通道）
 * @param generateMessageId 生成唯一消息 ID 的回调
 * @param mapEmotion 后端 emotion 字符串映射到 [Emotion] 模型
 */
class ChatSendController(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val sessionController: ChatSessionController,
    private val ttsController: ChatTtsController,
    private val flushManager: ChatFlushManager,
    private val generateMessageId: () -> String,
    private val mapEmotion: (String) -> Emotion?
) {
    companion object {
        private const val TAG = "ChatSendController"
    }

    fun sendMessage(text: String, model: String = "default") {
        if (text.isBlank()) return
        val sessionId = uiState.value.currentSession?.id
        scope.launch {
            sessionController.consumePendingSwitchIfNeeded()
            val prefixHistory = uiState.value.messages
            val userMessageId = generateMessageId()
            val userMessage = Message(
                id = userMessageId,
                text = text,
                isUser = true,
                timestamp = System.currentTimeMillis(),
                messageType = "text",
                sessionId = sessionId,
                parentId = prefixHistory.lastOrNull()?.id
            )
            chatRepository.insertMessageVariant(userMessage)
            generateAssistantVariant(userMessage, prefixHistory, model, 0)
        }
    }

    /** 编辑某个用户请求会创建同级新版本，旧请求及其后续分支不会删除。 */
    fun editUserMessage(messageId: String, newText: String, model: String = "default") {
        if (newText.isBlank()) return
        scope.launch {
            val currentPath = uiState.value.messages
            val originalIndex = currentPath.indexOfFirst { it.id == messageId && it.isUser }
            if (originalIndex < 0) return@launch
            val original = currentPath[originalIndex]
            val prefixHistory = currentPath.take(originalIndex)
            val edited = original.copy(
                id = generateMessageId(),
                text = newText.trim(),
                timestamp = System.currentTimeMillis(),
                variantIndex = original.variantCount,
                variantCount = original.variantCount + 1,
                isActiveVariant = true
            )
            chatRepository.insertMessageVariant(edited)
            generateAssistantVariant(edited, prefixHistory, model, 0)
        }
    }

    /** 对指定 AI 回复重新生成，生成结果作为同一用户请求下的新回复版本。 */
    fun regenerateMessage(messageId: String, model: String = "default") {
        scope.launch {
            val currentPath = uiState.value.messages
            val aiIndex = currentPath.indexOfFirst { it.id == messageId && !it.isUser }
            if (aiIndex < 1) return@launch
            val userMessage = currentPath[aiIndex - 1]
            if (!userMessage.isUser) return@launch
            val original = currentPath[aiIndex]
            generateAssistantVariant(
                userMessage = userMessage,
                prefixHistory = currentPath.take(aiIndex - 1),
                model = model,
                assistantVariantIndex = original.variantCount
            )
        }
    }

    fun selectVariant(messageId: String, offset: Int) {
        val message = uiState.value.messages.firstOrNull { it.id == messageId } ?: return
        val target = message.variantIndex + offset
        if (target !in 0 until message.variantCount) return
        scope.launch {
            chatRepository.selectSiblingVariant(message, target).onFailure { e ->
                uiState.update { it.copy(error = "切换消息版本失败: ${e.message}") }
            }
        }
    }

    private suspend fun generateAssistantVariant(
        userMessage: Message,
        prefixHistory: List<Message>,
        model: String,
        assistantVariantIndex: Int
    ) {
        val sessionId = userMessage.sessionId
        val aiMessageId = generateMessageId()
        val aiMessageStart = System.currentTimeMillis()
        val aiPlaceholder = Message(
            id = aiMessageId,
            text = "",
            isUser = false,
            timestamp = aiMessageStart,
            messageType = "text",
            sessionId = sessionId,
            parentId = userMessage.id,
            variantIndex = assistantVariantIndex
        )
        chatRepository.insertMessageVariant(aiPlaceholder)
        uiState.update {
            it.copy(
                messages = prefixHistory + userMessage + aiPlaceholder,
                isTyping = true,
                showTypingIndicator = true,
                inputText = "",
                error = null
            )
        }

        ttsController.startStreamingIfEnabled(aiMessageId)

        val fullText = StringBuilder()
        var finalEmotion: String? = null

        flushManager.setHttpStreamingActive(true)
        try {
            chatRepository.sendMessageStreaming(
                userMessage.text,
                sessionId,
                model,
                sessionController.currentPersonaFilename,
                prefixHistory
            ).collect { event ->
                    when (event) {
                        is StreamEvent.Chunk -> {
                            fullText.append(event.content)
                            // 边收边播: 增量文本喂给 TTS 分句合成
                            ttsController.appendStreamingChunk(event.content)
                            // 增量更新 AI 消息文本 (立即刷新 UI)
                            uiState.update { state ->
                                val updatedMessages = state.messages.map {
                                    if (it.id == aiMessageId) it.copy(text = fullText.toString())
                                    else it
                                }
                                state.copy(messages = updatedMessages)
                            }
                        }
                        is StreamEvent.Done -> {
                            finalEmotion = event.emotion
                            // 流式结束: 冲刷剩余 buffer 并关闭合成通道
                            ttsController.finishStreamingIfEnabled()
                        }
                        is StreamEvent.Error -> {
                            // 生成失败: 停止流式播放,避免半句卡住
                            ttsController.stopIfEnabled()
                            uiState.update {
                                it.copy(
                                    error = "生成失败: ${event.message}",
                                    isTyping = false,
                                    showTypingIndicator = false
                                )
                            }
                        }
                        is StreamEvent.Reset -> {
                            // AI 开始调用工具: 清空当前正在生成的临时消息文本,保留历史消息。
                            // 后续工具完成后,最终回答会从空开始重新逐块流式拼接。
                            ttsController.finishStreamingIfEnabled()
                            fullText.clear()
                            uiState.update { state ->
                                val updatedMessages = state.messages.map {
                                    if (it.id == aiMessageId) it.copy(text = "") else it
                                }
                                state.copy(
                                    messages = updatedMessages,
                                    isTyping = true,
                                    showTypingIndicator = true
                                )
                            }
                        }
                        is StreamEvent.ImageResult -> {
                            // AI 输出 [MEME] 标签时后端推送的表情包/图片: 即时上屏
                            val imageMessage = Message(
                                id = generateMessageId(),
                                text = "",
                                isUser = false,
                                timestamp = System.currentTimeMillis(),
                                messageType = "image",
                                imageUrl = event.imageUrl,
                                sessionId = sessionId,
                                parentId = aiMessageId
                            )
                            uiState.update { state ->
                                state.copy(messages = state.messages + imageMessage)
                            }
                            // 落库（与 WS 通道 handleImageResultMessage 一致）
                            scope.launch(Dispatchers.IO) {
                                runCatching {
                                    chatRepository.insertMessage(imageMessage)
                                }.onFailure { e ->
                                    Log.e(TAG, "写入图片消息失败", e)
                                }
                            }
                        }
                    }
            }
        } finally {
            flushManager.setHttpStreamingActive(false)
        }

        val finalMessage = aiPlaceholder.copy(
            text = fullText.toString(),
            emotion = finalEmotion
        )

            // 用最终 id 和完整文本替换占位消息
            uiState.update { state ->
                val updatedMessages = state.messages.map {
                    if (it.id == aiMessageId) finalMessage else it
                }
                state.copy(
                    messages = updatedMessages,
                    isTyping = false,
                    showTypingIndicator = false,
                    currentEmotion = finalEmotion?.let { emo ->
                        mapEmotion(emo)
                    } ?: state.currentEmotion
                )
            }

        scope.launch(Dispatchers.IO) {
            chatRepository.insertMessage(finalMessage).onFailure { e ->
                Log.e(TAG, "消息版本写库失败", e)
            }
        }
    }
}
