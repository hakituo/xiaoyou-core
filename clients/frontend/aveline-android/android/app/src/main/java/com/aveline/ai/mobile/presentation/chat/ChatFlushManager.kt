package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 流式响应批量刷新管理器
 *
 * 职责：
 * 1. 缓冲 WebSocket 流式 delta，按 [flushIntervalMs] 防抖批量更新 UI
 * 2. 流式期间累积完整 Message 到内存，响应结束（onResponseDone）时一次性写入数据库
 * 3. 管理分段打字状态（句号/括号触发的气泡切分逻辑）
 *
 * 关键设计：流式期间不写数据库。
 * 因为 Room 的 Flow 会在 INSERT 后回流，用数据库的初始字符版本覆盖 uiState 已累积的完整文本，
 * 导致文字倒退。所以新气泡创建时只更新 uiState（保证即时显示和 append 能找到），
 * 数据库写入推迟到 onResponseDone，此时 uiState 与数据库版本一致，回流不会倒退。
 *
 * 通过构造函数接收 ViewModel 的协程作用域和 UI 状态流，
 * 避免直接依赖 ViewModel 类。
 *
 * @param scope          ViewModel 的协程作用域（viewModelScope）
 * @param uiState        UI 状态流，批量更新会写入此流
 * @param chatRepository 聊天仓库，用于插入消息
 * @param generateMessageId 生成唯一消息 ID 的回调
 * @param getCurrentSessionId 获取当前会话 ID 的回调
 * @param flushIntervalMs  UI 批量刷新间隔（毫秒）
 */
class ChatFlushManager(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val generateMessageId: () -> String,
    private val getCurrentSessionId: () -> String?,
    private val flushIntervalMs: Long
) {
    /** 单条流式 delta */
    private data class StreamDelta(val messageId: String, val delta: String, val emotion: String?)

    /** 单条消息的分段打字状态 */
    private data class StreamTypingState(
        var sentenceIndex: Int = 0,
        var retractionIndex: Int = 0,
        var currentMessageId: String? = null
    )

    /** 当前流式消息 ID（跨协程访问,需 @Volatile 保证可见性） */
    @Volatile
    private var wsStreamingMessageId: String? = null

    /** 流式文本缓冲（保留用于清理） */
    private val streamingTextBuffer = mutableMapOf<String, StringBuilder>()

    /** delta 缓冲区，等待批量刷新 */
    private val deltaBuffer = mutableListOf<StreamDelta>()

    /** flush 协程 Job（跨协程访问,需 @Volatile） */
    @Volatile
    private var flushJob: Job? = null

    /** 流式期间累积的完整消息（messageId -> Message）
     *  用于在 onResponseDone 时一次性写入数据库，避免流式期间 INSERT 触发 Room Flow 回流覆盖 uiState 已累积的文本 */
    private val streamingMessages = mutableMapOf<String, Message>()

    /** 每条消息的分段打字状态（跨协程访问,用锁保护） */
    private val streamTypingStates = mutableMapOf<String, StreamTypingState>()
    private val stateLock = Any()

    /**
     * HTTP SSE 流式抑制标志（跨协程访问,需 @Volatile）
     *
     * 当用户通过 HTTP SSE（sendMessage）发消息时，流式 chunk 通过 HTTP 通道返回，
     * ChatViewModel 自己管理 aiMessageId 的 UI 更新。
     * 此时如果 WS 也收到 response_chunk（如后端双通道推送或残留状态），
     * flushManager 不应再处理，否则会创建第二条 AI 消息导致重复显示。
     *
     * true = HTTP SSE 流式进行中，抑制 WS chunk 处理
     * false = 正常模式，WS chunk 由 flushManager 处理
     */
    @Volatile
    private var httpStreamingActive: Boolean = false

    /**
     * 标记 HTTP SSE 流式开始/结束
     *
     * ChatViewModel.sendMessage() 在调用前设为 true，流式结束（完成/异常/取消）后设为 false。
     * 期间 flushManager.handleResponseChunk() 会直接 return，避免双通道冲突。
     */
    fun setHttpStreamingActive(active: Boolean) {
        httpStreamingActive = active
        if (!active) {
            // HTTP 流式结束，如果期间有被抑制的 WS 状态残留，也清理掉
            // （正常情况下不应有，因为被抑制了，但防御性清理）
        }
    }

    /**
     * 处理流式响应 chunk：将 delta 加入缓冲区并调度批量刷新
     *
     * 注意：当 HTTP SSE 流式进行中（httpStreamingActive=true）时直接 return，
     * 避免 HTTP 和 WS 双通道同时更新 UI 导致重复显示。
     */
    fun handleResponseChunk(message: WebSocketMessage.ResponseChunk) {
        // HTTP SSE 流式进行中，抑制 WS 通道的 chunk 处理，避免双通道冲突
        if (httpStreamingActive) return

        val content = message.content
        if (content.isBlank()) return

        val messageId = wsStreamingMessageId ?: generateMessageId().also { wsStreamingMessageId = it }

        // 修复中8:每 chunk 触发 uiState.update 造成不必要重组。
        // typing 指示器在流式开始时已置 true,后续 chunk 到来时无需重复 update。
        // 原实现每 chunk 都调用 update,即使值没变也会执行 lambda + equals 比对;
        // 改为先检查,仅在状态未就绪时才 update,避免高频 chunk 下无谓开销。
        if (!uiState.value.isTyping || !uiState.value.showTypingIndicator) {
            uiState.update { it.copy(isTyping = true, showTypingIndicator = true) }
        }

        // 将 delta 添加到缓冲区，使用防抖机制批量处理
        synchronized(deltaBuffer) {
            deltaBuffer.add(StreamDelta(messageId, content, message.emotion))
        }
        scheduleFlush()
    }

    /**
     * 处理 ResponseDone：清理流式状态、刷新数据库、关闭打字指示器
     *
     * 竞态修复:原实现把 streamingMessages.clear() 放在异步协程里,
     * 若期间新 chunk 到来并写入 streamingMessages,会被这次 clear 误清。
     * 现改为同步取快照并清理 streamingMessages,再异步写入数据库。
     *
     * 注意：当 HTTP SSE 流式进行中时直接 return，由 ChatViewModel 自行处理 done。
     */
    fun onResponseDone() {
        // HTTP SSE 流式进行中，抑制 WS 通道的 done 处理，避免双通道冲突
        if (httpStreamingActive) return

        val finishedMessageId = wsStreamingMessageId
        wsStreamingMessageId = null

        if (finishedMessageId != null) {
            synchronized(stateLock) {
                streamTypingStates.remove(finishedMessageId)
            }
            streamingTextBuffer.remove(finishedMessageId)
        }

        // 同步取快照并清理,避免异步清理期间新 chunk 到来被误清
        val snapshot: List<Message>
        synchronized(streamingMessages) {
            snapshot = streamingMessages.values.toList()
            streamingMessages.clear()
        }

        scope.launch(Dispatchers.IO) {
            runCatching {
                snapshot.forEach { msg ->
                    chatRepository.insertMessage(msg)
                }
            }.onFailure { e ->
                // 修复 P0-35: 流式响应结束批量写入失败会静默丢失,且 dedup Map 与 DB 不一致。
                // 打错误日志,方便排查;UI 层暂不显示(属于后台数据同步问题,不让用户感知)。
                android.util.Log.e(
                    "ChatFlushManager",
                    "流式响应批量写入消息失败 (${snapshot.size} 条)",
                    e
                )
            }
        }

        uiState.update {
            it.copy(isTyping = false, showTypingIndicator = false)
        }
    }

    /**
     * 处理 ResponseReset：AI 开始调用工具时下发，清空当前正在生成的临时消息，不影响历史消息。
     *
     * 行为与 [onResponseDone] 不同：
     * - 不写入数据库（正在生成的消息尚未完成，本就不该落库）
     * - 只移除"当前正在生成的那条消息"及其衍生分段气泡（id 前缀为 wsStreamingMessageId），
     *   历史消息保持不动
     * - 清掉残留的 delta 缓冲与分段打字状态，使后续工具完成后的回答从头逐块生成
     *
     * 注意：当 HTTP SSE 流式进行中（httpStreamingActive=true）时直接 return，
     * 由 ChatViewModel 的 HTTP 路径自行处理 reset，避免双通道冲突。
     */
    fun onResponseReset() {
        // HTTP SSE 流式进行中，抑制 WS 通道的 reset 处理，避免双通道冲突
        if (httpStreamingActive) return

        val resetMessageId = wsStreamingMessageId ?: return
        wsStreamingMessageId = null

        // 清空当前正在生成的消息气泡：主气泡 + 分段衍生气泡（id 前缀为 resetMessageId）
        uiState.update { state ->
            val kept = state.messages.filterNot { msg ->
                msg.id == resetMessageId || msg.id.startsWith("$resetMessageId-")
            }
            state.copy(messages = kept)
        }

        // 清掉残留的 delta 与分段打字状态，避免工具完成后的回答被旧状态污染
        synchronized(deltaBuffer) { deltaBuffer.clear() }
        synchronized(stateLock) {
            streamTypingStates.keys.removeAll { id ->
                id == resetMessageId || id.startsWith("$resetMessageId-")
            }
        }
        streamingTextBuffer.remove(resetMessageId)

        uiState.update {
            it.copy(isTyping = true, showTypingIndicator = true)
        }
    }

    /**
     * 调度缓冲区刷新，使用防抖机制避免频繁更新
     */
    private fun scheduleFlush() {        if (flushJob?.isActive == true) return

        flushJob = scope.launch {
            delay(flushIntervalMs)
            flushDeltaBuffer()
        }
    }

    /**
     * 批量刷新缓冲区中的所有 delta
     */
    private fun flushDeltaBuffer() {
        val deltasToProcess: List<StreamDelta>
        synchronized(deltaBuffer) {
            if (deltaBuffer.isEmpty()) return
            deltasToProcess = deltaBuffer.toList()
            deltaBuffer.clear()
        }

        // 按 messageId 分组处理
        deltasToProcess.groupBy { it.messageId }.forEach { (messageId, deltas) ->
            val combinedDelta = deltas.joinToString("") { it.delta }
            val emotion = deltas.lastOrNull { it.emotion != null }?.emotion
            enqueueStreamDelta(messageId, combinedDelta, emotion)
        }
    }

    /**
     * 将合并后的 delta 按字符逐个处理，根据标点/括号切分气泡。
     *
     * 性能优化: 用 StringBuilder 批量累积当前气泡的文本,只在气泡切换
     * (遇到标点/括号)或 delta 处理结束时才调用 [appendToCurrentMessage]。
     * 原实现逐字符调用 appendToCurrentMessage,每次都做 O(M) 的 indexOfFirst
     * + toMutableList,长响应(N 字符)总复杂度 O(N*M) ≈ O(n²)。
     * 批量后 uiState 更新次数从 O(N) 降到 O(气泡切换次数),大幅减少 StateFlow
     * 重组和列表拷贝开销。
     */
    private fun enqueueStreamDelta(messageId: String, delta: String, emotion: String?) {
        // streamTypingStates 跨协程访问(clear 可能在 switchSession 中调用),getOrPut 需加锁
        val state = synchronized(stateLock) { streamTypingStates.getOrPut(messageId) { StreamTypingState() } }
        val pendingText = StringBuilder()

        // 把累积的文本一次性追加到当前气泡,然后清空累积区
        fun flushPendingAppend() {
            if (pendingText.isNotEmpty() && state.currentMessageId != null) {
                appendToCurrentMessage(state.currentMessageId!!, pendingText.toString())
                pendingText.clear()
            }
        }

        for (ch in delta) {
            when {
                ch == '。' || ch == '.' -> {
                    // 句号结束当前气泡(不追加句号本身),先刷掉已累积文本
                    flushPendingAppend()
                    if (state.currentMessageId != null) {
                        state.currentMessageId = null
                    }
                }
                ch == '！' || ch == '？' || ch == '!' || ch == '?' -> {
                    if (state.currentMessageId != null) {
                        // 感叹/问号追加到当前气泡再结束
                        pendingText.append(ch)
                        flushPendingAppend()
                        state.currentMessageId = null
                        state.sentenceIndex += 1
                    }
                }
                ch == '(' || ch == '（' -> {
                    // 左括号结束当前气泡(不追加括号),进入回收段
                    flushPendingAppend()
                    if (state.currentMessageId != null) {
                        state.currentMessageId = null
                        state.sentenceIndex += 1
                    }
                    state.retractionIndex += 1
                }
                ch == ')' || ch == '）' -> {
                    // 右括号结束当前气泡,退出回收段
                    flushPendingAppend()
                    if (state.currentMessageId != null) {
                        state.currentMessageId = null
                        state.sentenceIndex += 1
                    }
                    state.retractionIndex = 0
                }
                ch.isWhitespace() -> {
                    // 空白字符累积到当前气泡
                    if (state.currentMessageId != null) {
                        pendingText.append(ch)
                    }
                }
                else -> {
                    if (state.currentMessageId == null) {
                        // 新气泡的第一个字符:先刷掉之前累积的文本(currentMessageId 为 null 时不会刷)
                        state.sentenceIndex += 1
                        val bubbleId = if (state.sentenceIndex == 1) messageId else "${messageId}-${state.sentenceIndex - 1}"
                        state.currentMessageId = bubbleId

                        val isRetraction = state.retractionIndex > 0
                        if (isRetraction) {
                            state.retractionIndex = 0
                        }

                        val messageType = if (isRetraction) "retraction" else "text"
                        createNewMessage(bubbleId, ch.toString(), messageType, emotion)
                    } else {
                        // 累积到当前气泡,稍后批量追加
                        pendingText.append(ch)
                    }
                }
            }
        }
        // delta 处理完毕,刷掉剩余的累积文本
        flushPendingAppend()
    }

    /**
     * 创建新消息气泡
     *
     * 关键：立即把新气泡加入 uiState.messages，保证后续 appendToCurrentMessage 能通过 id 找到该气泡
     * （否则 append 时 uiState 还没有该气泡，idx=-1，文字全部丢失）。
     *
     * 数据库写入推迟到 onResponseDone，避免流式期间 INSERT 触发 Room Flow 回流
     * 用数据库的初始字符版本覆盖 uiState 已累积的完整文本（文字倒退 bug）。
     */
    private fun createNewMessage(id: String, text: String, messageType: String, emotion: String?) {
        val sessionId = getCurrentSessionId()
        val newMessage = Message(
            id = id,
            text = text,
            isUser = false,
            timestamp = System.currentTimeMillis(),
            messageType = messageType,
            emotion = emotion,
            sessionId = sessionId
        )

        // 立即加入 uiState，让 appendToCurrentMessage 能找到该气泡
        uiState.update {
            it.copy(messages = it.messages + newMessage)
        }
        // 记录到流式累积，onResponseDone 时一次性写入数据库
        // 注意：流式期间不写数据库，避免 INSERT 触发 Room Flow 回流覆盖 uiState 已累积的文本
        synchronized(streamingMessages) {
            streamingMessages[id] = newMessage
        }
    }

    /**
     * 向当前消息气泡追加文本，同时更新流式累积的 Message（待写入数据库）
     */
    private fun appendToCurrentMessage(messageId: String, text: String) {
        val currentMessages = uiState.value.messages
        val idx = currentMessages.indexOfFirst { it.id == messageId }
        if (idx >= 0) {
            val newText = currentMessages[idx].text + text
            uiState.update {
                val updatedMessages = it.messages.toMutableList()
                updatedMessages[idx] = updatedMessages[idx].copy(text = newText)
                it.copy(messages = updatedMessages)
            }

            // 更新流式累积的 Message 文本，onResponseDone 时写入数据库
            synchronized(streamingMessages) {
                streamingMessages[messageId]?.let { existing ->
                    streamingMessages[messageId] = existing.copy(text = newText)
                }
            }
        }
    }

    /**
     * 清理所有流式状态和缓冲区（用于切换会话或 ViewModel 销毁时）
     */
    fun clear() {
        wsStreamingMessageId = null
        synchronized(stateLock) {
            streamTypingStates.clear()
        }
        streamingTextBuffer.clear()
        synchronized(deltaBuffer) {
            deltaBuffer.clear()
        }
        flushJob?.cancel()
        flushJob = null
        synchronized(streamingMessages) {
            streamingMessages.clear()
        }
    }
}
