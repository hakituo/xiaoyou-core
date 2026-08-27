package com.aveline.ai.mobile.presentation.chat

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 负责"会话与消息流"的观察与事件分发。
 *
 * 从 ChatViewModel 拆出，职责：
 * - [observeCurrentSession]：监听当前会话变化并写入 uiState
 * - [observeMessages]：随会话切换加载对应 session 的历史消息（消息按角色隔离的关键）
 * - [observeConnectionState]：监听 WebSocket 连接状态并更新 loadingState
 * - [observeWebSocketMessages]：分发 WebSocket 消息到各子模块（文本/图片落库、
 *   flush、peer chat、emotion 等）
 * - 会话操作：createNewSession / switchSession / clearHistory
 *
 * @param scope ViewModel 的协程作用域
 * @param uiState UI 状态流，当前会话/消息/连接状态写入此流
 * @param chatRepository 聊天仓库
 * @param sessionRepository 会话仓库
 * @param webSocketManager WebSocket 管理器
 * @param appPreferences 全局偏好（switchSession 时改写 currentSessionId）
 * @param onMessagesLoaded 消息列表变化回调（供 VM 更新列表预览）
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ChatSessionObserver(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val sessionRepository: SessionRepository,
    private val webSocketManager: WebSocketManager,
    private val appPreferences: AppPreferences,
    private val onMessagesLoaded: (List<com.aveline.ai.mobile.domain.models.Message>) -> Unit,
    private val incomingHandler: ChatIncomingMessageHandler,
    private val flushManager: ChatFlushManager,
    private val peerChatHandler: ChatPeerChatHandler
) {
    companion object {
        private const val TAG = "ChatSessionObserver"
    }

    /** 开始监听：当前会话 + 消息流 + 连接状态 + WS 事件。 */
    fun start() {
        observeCurrentSession()
        observeMessages()
        observeConnectionState()
        observeWebSocketMessages()
    }

    private fun observeCurrentSession() {
        scope.launch {
            sessionRepository.observeCurrentSession()
                .catch { e ->
                    uiState.update { it.copy(error = "加载会话失败: ${e.message}") }
                }
                .collect { session ->
                    uiState.update { it.copy(currentSession = session) }
                }
        }
    }

    private fun observeMessages() {
        scope.launch {
            // 记录当前 flow 对应的 sessionId，用于 collect 归属校验：
            // flatMapLatest 取消旧 flow 是协作式的，切换瞬间旧 flow 的残留消息
            // 可能仍到达 collect，只有与当前 session 匹配的消息才允许上屏/写预览。
            var expectedSessionId: String? = null
            sessionRepository.observeCurrentSession()
                .filterNotNull()
                .distinctUntilChanged { old, new -> old.id == new.id }
                .flatMapLatest { session ->
                    expectedSessionId = session.id
                    Log.d(TAG, "observeMessages: 会话切换，加载 sessionId=${session.id}")
                    // 切换会话立即清空旧消息，避免切换瞬间显示上一个角色的聊天记录
                    // （新 flow 的数据到达后会自动填充）
                    uiState.update { it.copy(messages = emptyList()) }
                    // 使用 flow 确保取消传播，而不是嵌套 launch
                    flow {
                        chatRepository.loadHistoryFromApi(session.id)
                        emitAll(chatRepository.observeMessages(session.id))
                    }
                }
                .catch { e ->
                    Log.e(TAG, "observeMessages: 加载消息失败 - ${e.message}", e)
                    uiState.update { it.copy(error = "加载消息失败: ${e.message}") }
                }
                .collect { messages ->
                    // 竞态防护：旧 flow 的残留消息（上一个角色的记录）在切换瞬间可能
                    // 仍到达 collect。校验消息归属，不属于当前会话的一律丢弃，
                    // 既不上屏也不写预览（修复"先显示上一个人记录再刷新消失"与
                    // "Aveline 预览显示卡夫卡消息"两个串台现象）。
                    if (expectedSessionId != null && messages.any { it.sessionId != null && it.sessionId != expectedSessionId }) {
                        Log.w(TAG, "observeMessages: 丢弃不属于当前会话($expectedSessionId)的残留消息 ${messages.size} 条")
                        return@collect
                    }
                    Log.d(TAG, "observeMessages: 从数据库加载 ${messages.size} 条消息")
                    uiState.update { it.copy(messages = messages) }

                    // 写入最后一条消息预览到 PersonaLocalMeta，供会话列表页副标题使用。
                    // 预览归属以"消息自身的 sessionId"为准（见 ChatIncomingMessageHandler），
                    // 即使发生竞态，也只会写到消息真正所属的角色上。
                    onMessagesLoaded(messages)

                    if (messages.isNotEmpty()) {
                        uiState.update { it.copy(loadingState = LoadingState.Loaded(messages)) }
                    } else {
                        val connectionState = uiState.value.connectionState
                        when (connectionState) {
                            WebSocketManager.ConnectionState.CONNECTED -> {
                                uiState.update { it.copy(loadingState = LoadingState.Loaded(emptyList())) }
                            }
                            WebSocketManager.ConnectionState.CONNECTING -> {
                                uiState.update { it.copy(loadingState = LoadingState.Loading) }
                            }
                            else -> {
                                uiState.update { it.copy(loadingState = LoadingState.NotLoaded) }
                            }
                        }
                    }
                }
        }
    }

    private fun observeConnectionState() {
        scope.launch {
            webSocketManager.connectionState.collect { state ->
                uiState.update { it.copy(connectionState = state) }

                when (state) {
                    WebSocketManager.ConnectionState.CONNECTING -> {
                        uiState.update { it.copy(loadingState = LoadingState.Loading) }
                    }
                    WebSocketManager.ConnectionState.CONNECTED -> {
                        val currentMessages = uiState.value.messages
                        if (currentMessages.isNotEmpty()) {
                            uiState.update { it.copy(loadingState = LoadingState.Loaded(currentMessages)) }
                        } else {
                            uiState.update { it.copy(loadingState = LoadingState.Loaded(emptyList())) }
                        }
                    }
                    WebSocketManager.ConnectionState.DISCONNECTED -> {
                        val currentMessages = uiState.value.messages
                        if (currentMessages.isEmpty()) {
                            uiState.update { it.copy(loadingState = LoadingState.NotLoaded) }
                        }
                    }
                }
            }
        }
    }

    private fun observeWebSocketMessages() {
        scope.launch {
            webSocketManager.messages.collect { message ->
                when (message) {
                    is WebSocketMessage.TextMessage -> {
                        incomingHandler.handleTextMessage(message)
                    }
                    is WebSocketMessage.ResponseChunk -> {
                        flushManager.handleResponseChunk(message)
                    }
                    is WebSocketMessage.ResponseDone -> {
                        flushManager.onResponseDone()
                    }
                    is WebSocketMessage.ResponseReset -> {
                        // AI 开始调用工具: 清空当前正在生成的临时消息,不影响历史消息
                        flushManager.onResponseReset()
                    }
                    is WebSocketMessage.EmotionUpdate -> {
                        val emotion = Emotion(
                            primary = message.primary,
                            intensity = message.intensity,
                            colors = message.colors
                        )
                        uiState.update { it.copy(currentEmotion = emotion) }
                    }
                    is WebSocketMessage.Error -> {
                        uiState.update {
                            it.copy(
                                error = message.message,
                                isTyping = false,
                                showTypingIndicator = false
                            )
                        }
                    }
                    is WebSocketMessage.ImageResult -> {
                        incomingHandler.handleImageResultMessage(message)
                    }
                    is WebSocketMessage.LifeStatusUpdate -> {
                        // 由 StatusRepository 处理
                    }
                    is WebSocketMessage.RitualEvent -> {
                        // 仪式事件，可后续扩展
                    }
                    is WebSocketMessage.SpontaneousReaction -> {
                        // 自发反应，可后续扩展
                    }
                    is WebSocketMessage.PeerChatMessage -> {
                        peerChatHandler.handlePeerChatMessage(message)
                    }
                    is WebSocketMessage.PeerChatScriptStart -> {
                        peerChatHandler.handlePeerChatScriptStart(message)
                    }
                    is WebSocketMessage.PeerChatScriptEnd -> {
                        peerChatHandler.handlePeerChatScriptEnd(message)
                    }
                    else -> Unit
                }
            }
        }
    }

    /** 创建新会话并切换到它。 */
    fun createNewSession(title: String = "新对话") {
        scope.launch {
            uiState.update { it.copy(isLoading = true) }
            val result = sessionRepository.createSession(title)
            result.fold(
                onSuccess = { session ->
                    uiState.update {
                        it.copy(currentSession = session, messages = emptyList(), isLoading = false)
                    }
                },
                onFailure = { e ->
                    uiState.update {
                        it.copy(error = "创建会话失败: ${e.message}", isLoading = false)
                    }
                }
            )
        }
    }

    /** 切换到指定会话。 */
    fun switchSession(sessionId: String) {
        appPreferences.currentSessionId = sessionId
        flushManager.clear()
    }

    /** 清空当前会话历史。 */
    fun clearHistory() {
        val sessionId = uiState.value.currentSession?.id ?: return
        scope.launch(kotlinx.coroutines.Dispatchers.IO) {
            runCatching {
                chatRepository.clearHistory(sessionId)
            }.onFailure { e ->
                Log.e(TAG, "清空历史失败", e)
                uiState.update { it.copy(error = "清空历史失败: ${e.message}") }
            }
        }
    }
}
