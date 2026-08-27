package com.aveline.ai.mobile.presentation.chat

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.net.Uri
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.dto.MessageResponse
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import com.aveline.ai.mobile.services.FileUploadManager
import com.aveline.ai.mobile.services.TTSEngine
import com.aveline.ai.mobile.services.VoiceInputManager
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 聊天页 ViewModel（薄壳协调者）。
 *
 * 遵循 .trae/context/CODING_GUIDE.md「8.3 服务门面模式」：本类只保留生命周期管理、
 * 状态持有（[uiState]）与各业务子模块的组装/转发，具体业务逻辑全部委托给兄弟模块。
 * 本类核心职责：
 * 1. 通过 Hilt 注入依赖并组装各 [ChatXxxController] / [ChatXxxHandler]
 * 2. 持有单一 UI 状态源 [uiState]（各子模块共享同一 MutableStateFlow）
 * 3. 将 UI 层的点击/输入事件转发给对应子模块
 * 4. [onCleared] 统一释放子模块资源
 *
 * 业务子模块：
 * - [ChatSessionController]：角色/persona 与会话/session 切换
 * - [ChatSessionObserver]：会话与消息流观察、WS 事件分发、会话操作
 * - [ChatSendController]：发消息核心流程（HTTP SSE 流式回复）
 * - [ChatIncomingMessageHandler]：WS 消息落库 + 会话列表预览
 * - [ChatFlushManager]：流式响应批量刷新
 * - [ChatUploadHelper]：文件/图片上传
 * - [ChatPeerChatHandler]：双角色对话
 * - [ChatTtsController]：TTS 播报
 * - [ChatVoiceInputController]：语音输入
 */
@HiltViewModel
class ChatViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val chatRepository: ChatRepository,
    private val sessionRepository: SessionRepository,
    private val webSocketManager: com.aveline.ai.mobile.data.remote.api.WebSocketManager,
    private val fileUploadManager: FileUploadManager,
    private val ttsEngine: TTSEngine,
    private val voiceInputManager: VoiceInputManager,
    private val appPreferences: AppPreferences,
    private val personaRepository: PersonaRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository
) : ViewModel() {

    companion object {
        private const val TAG = "ChatViewModel"
        const val FLUSH_INTERVAL_MS = 100L  // UI更新：每100ms批量刷新一次
    }

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    // 延迟初始化:避免构造时强转系统服务,使纯 JVM 单元测试能在 mock Context 下实例化 ChatViewModel
    private val clipboardManager: ClipboardManager by lazy {
        context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    }

    private var messageIdCounter = 0L
    private fun generateMessageId(): String {
        messageIdCounter++
        return "${System.currentTimeMillis()}-${messageIdCounter}"
    }

    // ==================== 业务子模块 ====================

    /**
     * 惰性初始化：类顶部的 init 块（切换 session）会先于本属性声明执行，
     * 若用饿汉式初始化则那时 flushManager 仍为 null，会 NPE。
     */
    private val flushManager: ChatFlushManager by lazy {
        ChatFlushManager(
            scope = viewModelScope,
            uiState = _uiState,
            chatRepository = chatRepository,
            generateMessageId = { generateMessageId() },
            getCurrentSessionId = { _uiState.value.currentSession?.id },
            flushIntervalMs = FLUSH_INTERVAL_MS
        )
    }

    /** 角色/会话切换（persona 与 session 状态、延迟切换意图）。 */
    private val sessionController = ChatSessionController(
        scope = viewModelScope,
        appPreferences = appPreferences,
        sessionRepository = sessionRepository,
        personaRepository = personaRepository,
        onSessionSwitched = { flushManager.clear() }
    )

    /** WebSocket 消息落库 + 会话列表预览。 */
    private val incomingHandler = ChatIncomingMessageHandler(
        scope = viewModelScope,
        uiState = _uiState,
        chatRepository = chatRepository,
        personaLocalMetaRepository = personaLocalMetaRepository,
        generateMessageId = { generateMessageId() },
        getSessionId = { _uiState.value.currentSession?.id },
        getPersonaFilename = { sessionController.currentPersonaFilename }
    )

    private val ttsController = ChatTtsController(
        scope = viewModelScope,
        uiState = _uiState,
        ttsEngine = ttsEngine,
        appPreferences = appPreferences,
        // 按当前 persona 解析角色默认音色（与 QQ 角色聊天对齐）
        getPersonaFilename = { sessionController.currentPersonaFilename }
    )

    private val uploadHelper = ChatUploadHelper(
        scope = viewModelScope,
        uiState = _uiState,
        fileUploadManager = fileUploadManager,
        appPreferences = appPreferences,
        chatRepository = chatRepository
    )

    private val peerChatHandler = ChatPeerChatHandler(
        uiState = _uiState,
        generateMessageId = { generateMessageId() }
    )

    private val voiceInputController = ChatVoiceInputController(
        scope = viewModelScope,
        uiState = _uiState,
        voiceInputManager = voiceInputManager
    )

    /** 发消息核心流程（HTTP SSE 流式回复）。 */
    private val sendController = ChatSendController(
        scope = viewModelScope,
        uiState = _uiState,
        chatRepository = chatRepository,
        sessionController = sessionController,
        ttsController = ttsController,
        flushManager = flushManager,
        generateMessageId = { generateMessageId() },
        mapEmotion = { mapEmotion(it) }
    )

    /** 会话与消息流观察、WS 事件分发、会话操作。 */
    private val sessionObserver = ChatSessionObserver(
        scope = viewModelScope,
        uiState = _uiState,
        chatRepository = chatRepository,
        sessionRepository = sessionRepository,
        webSocketManager = webSocketManager,
        appPreferences = appPreferences,
        onMessagesLoaded = { messages -> incomingHandler.updateLastMessagePreview(messages) },
        incomingHandler = incomingHandler,
        flushManager = flushManager,
        peerChatHandler = peerChatHandler
    )

    // ==================== 对外状态（转发给 sessionController） ====================

    /** 伴侣详情面板"正在查看的角色"（只读展示用）。 */
    val viewingPersonaFilename: StateFlow<String?> get() = sessionController.viewingPersonaFilename

    /** 伴侣面板点击某个人设版本：只改"正在查看的角色"，纯只读，不切对话人设。 */
    fun setViewingPersona(filename: String) = sessionController.setViewingPersona(filename)

    /** 进入 Chat 时记录待切换意图：本地 session 立即切，后端人设延迟到发消息。 */
    fun setPendingSwitch(role: String, preferredFilename: String? = null) =
        sessionController.setPendingSwitch(role, preferredFilename)

    // ==================== 初始化 ====================

    init {
        sessionController.start()
        sessionObserver.start()
        voiceInputController.observeState()
        ttsController.observeState()
        uploadHelper.observeUploadState()
        uploadHelper.init()
    }

    // ==================== 发消息（转发给 sendController） ====================

    fun sendMessage(text: String, model: String = "default") =
        sendController.sendMessage(text, model)

    fun regenerateMessage(messageId: String, model: String = "default") =
        sendController.regenerateMessage(messageId, model)

    fun editUserMessage(messageId: String, newText: String, model: String = "default") =
        sendController.editUserMessage(messageId, newText, model)

    fun selectMessageVariant(messageId: String, offset: Int) =
        sendController.selectVariant(messageId, offset)

    // ==================== 会话操作（转发给 sessionObserver） ====================

    fun createNewSession(title: String = "新对话") = sessionObserver.createNewSession(title)

    fun switchSession(sessionId: String) = sessionObserver.switchSession(sessionId)

    fun clearHistory() = sessionObserver.clearHistory()

    // ==================== 语音输入（转发给 voiceInputController） ====================

    fun startVoiceRecording() = voiceInputController.startRecording()

    fun stopVoiceRecording() = voiceInputController.stopRecording()

    fun cancelVoiceRecording() = voiceInputController.cancelRecording()

    fun hasRecordAudioPermission(): Boolean = voiceInputController.hasPermission()

    // ==================== TTS（转发给 ttsController） ====================

    fun toggleTTS(messageId: String) = ttsController.togglePlay(messageId)

    fun pauseTTS() = ttsController.pause()

    fun resumeTTS() = ttsController.resume()

    fun stopTTS() = ttsController.stop()

    // ==================== 双角色对话（转发给 peerChatHandler） ====================

    /** 切换双角色对话显示 */
    fun togglePeerChat() = peerChatHandler.togglePeerChat()

    /** 清空双角色对话消息 */
    fun clearPeerChatMessages() = peerChatHandler.clearPeerChatMessages()

    // ==================== 消息操作 ====================

    fun updateInputText(text: String) {
        _uiState.update { it.copy(inputText = text) }
    }

    fun deleteMessage(messageId: String) {
        viewModelScope.launch(kotlinx.coroutines.Dispatchers.IO) {
            runCatching {
                chatRepository.deleteMessage(messageId)
            }.onFailure { e ->
                Log.e("ChatViewModel", "删除消息失败", e)
                _uiState.update { it.copy(error = "删除消息失败: ${e.message}") }
            }
        }
    }

    fun copyMessage(text: String) {
        val clip = ClipData.newPlainText("message", text)
        clipboardManager.setPrimaryClip(clip)
    }

    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }

    /** 设置错误消息（用于权限拒绝等场景） */
    fun setError(message: String) {
        _uiState.update { it.copy(error = message) }
    }

    // ==================== 文件上传（转发给 uploadHelper） ====================

    fun uploadFile(uri: Uri, isImage: Boolean = false) = uploadHelper.uploadFile(uri, isImage)
    fun uploadImage(uri: Uri) = uploadHelper.uploadImage(uri)
    fun resetUploadState() = uploadHelper.resetUploadState()
    fun sendImageMessage(imageUrl: String, caption: String = "") = uploadHelper.sendImageMessage(imageUrl, caption)
    fun isSupportedImageType(mimeType: String): Boolean = uploadHelper.isSupportedImageType(mimeType)
    suspend fun getFileInfo(uri: Uri) = uploadHelper.getFileInfo(uri)

    fun extractMessageContent(response: MessageResponse): String? {
        if (!response.response.isNullOrBlank()) return response.response
        if (!response.reply.isNullOrBlank()) return response.reply
        if (response.message != null && response.message.text.isNotBlank()) return response.message.text
        if (response.data != null && response.data.text.isNotBlank()) return response.data.text
        return null
    }

    // ==================== 辅助 ====================

    /** 后端 emotion 字符串映射到 Emotion 模型 */
    private fun mapEmotion(raw: String): Emotion? {
        val name = raw.trim().lowercase()
        return when (name) {
            "neutral" -> Emotion.NEUTRAL
            "happy", "joy", "pleased" -> Emotion.HAPPY
            "calm", "relaxed" -> Emotion.CALM
            "excited", "enthusiastic" -> Emotion.EXCITED
            "sad", "down" -> Emotion.SAD
            else -> null
        }
    }

    override fun onCleared() {
        super.onCleared()
        voiceInputController.stopRecording()
        ttsController.stop()
        // 清理流式响应相关资源
        flushManager.clear()
    }
}
