package com.aveline.ai.mobile.presentation.chat

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.net.Uri
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.local.preferences.ChatDraftStore
import com.aveline.ai.mobile.data.local.preferences.RoleScopedPreferences
import com.aveline.ai.mobile.data.remote.dto.MessageResponse
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.Session
import com.aveline.ai.mobile.services.AvelineNotificationManager
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.domain.repository.PluginsRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import com.aveline.ai.mobile.domain.repository.ToolsRepository
import com.aveline.ai.mobile.services.FileUploadManager
import com.aveline.ai.mobile.services.TTSEngine
import com.aveline.ai.mobile.services.UploadKind
import com.aveline.ai.mobile.services.VoiceInputManager
import com.aveline.ai.mobile.utils.ImageUrlResolver
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 聊天页 ViewModel（薄壳协调者）。
 *
 * role 级 session 与 role 级模型分别由 [ChatSessionController]、[RoleModelController]
 * 管理；persona 只作为当前角色的 prompt 版本，不再承担聊天记录或模型偏好的主键职责。
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
    private val roleScopedPreferences: RoleScopedPreferences = RoleScopedPreferences(context),
    private val personaRepository: PersonaRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val pluginsRepository: PluginsRepository? = null,
    private val toolsRepository: ToolsRepository,
    // 可空 + 默认值：单测直接构造 ViewModel 时不用传；Hilt 注入时照常提供单例。
    private val notificationManager: AvelineNotificationManager? = null,
    /**
     * 角色回复的后台通知发布器（Hilt 单例）。
     *
     * 用户主动发消息走 HTTP SSE，回复完成时 WebSocket 侧被 ChatFlushManager 抑制，
     * 因此由 ChatSendController 在 SSE 收尾时直接发通知。
     */
    private val replyNotifier: com.aveline.ai.mobile.services.foreground.RoleReplyNotifier? = null,
    /**
     * 输入框草稿的落盘通道（Hilt 单例）。
     *
     * 带默认值：单测直接构造 ViewModel 时不传也能跑，Hilt 注入时照常给同一个单例。
     */
    private val draftStore: ChatDraftStore = ChatDraftStore(context)
) : ViewModel() {

    companion object {
        private const val TAG = "ChatViewModel"
        const val FLUSH_INTERVAL_MS = 100L

        /**
         * 停止输入多久之后把草稿写盘。
         *
         * 每敲一个字就写一次 SharedPreferences 会让打字路径上多一次全量 XML 落盘，
         * 攒到停手再写既省开销又不丢内容 —— 退出页面的兜底由 [flushInputDraft] 同步补写。
         */
        private const val DRAFT_PERSIST_DEBOUNCE_MS = 400L
    }

    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    /**
     * 输入框内容当前归属的会话 id。
     *
     * inputText 是全局单字段（不是一个会话一份），所以必须记住「这段字属于谁」：
     * 否则从会话 A 切到 B 时，A 里没发的话会被存成 B 的草稿，两个会话串味。
     * 由 [rotateInputDraftOnSessionChange] 在 IO 协程写、主线程读，故标 @Volatile。
     */
    @Volatile
    private var draftSessionId: String? = null

    /** 最近一次排队等待落盘的草稿写入；新内容一来就作废前一个。 */
    @Volatile
    private var draftPersistJob: Job? = null

    private val clipboardManager: ClipboardManager by lazy {
        context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    }

    private var messageIdCounter = 0L
    private fun generateMessageId(): String {
        messageIdCounter++
        return "${System.currentTimeMillis()}-${messageIdCounter}"
    }

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

    private val sessionController = ChatSessionController(
        scope = viewModelScope,
        appPreferences = appPreferences,
        roleScopedPreferences = roleScopedPreferences,
        sessionRepository = sessionRepository,
        personaRepository = personaRepository,
        personaLocalMetaRepository = personaLocalMetaRepository,
        notificationManager = notificationManager,
        onSessionSwitched = { flushManager.clear() }
    )

    private val roleModelController = RoleModelController(
        scope = viewModelScope,
        preferences = roleScopedPreferences,
        pluginsRepository = pluginsRepository,
        getCurrentRole = { sessionController.currentRole }
    )

    private val incomingHandler = ChatIncomingMessageHandler(
        scope = viewModelScope,
        uiState = _uiState,
        chatRepository = chatRepository,
        personaLocalMetaRepository = personaLocalMetaRepository,
        generateMessageId = { generateMessageId() },
        getSessionId = { _uiState.value.currentSession?.id },
        resolvePersonaFilenameForSession = { sessionController.personaFilenameForSession(it) },
        getPersonaFilename = { sessionController.conversationPersonaFilename }
    )

    private val ttsController = ChatTtsController(
        scope = viewModelScope,
        uiState = _uiState,
        ttsEngine = ttsEngine,
        appPreferences = appPreferences,
        getPersonaVoiceOverride = { sessionController.currentPersonaVoiceOverride() },
        getPersonaDefaultVoice = { sessionController.currentPersonaDefaultVoice() }
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

    private val sendController = ChatSendController(
        scope = viewModelScope,
        uiState = _uiState,
        chatRepository = chatRepository,
        personaLocalMetaRepository = personaLocalMetaRepository,
        sessionController = sessionController,
        ttsController = ttsController,
        flushManager = flushManager,
        mapEmotion = { mapEmotion(it) },
        resolveRoleModelRoute = { roleModelController.requestModelRoute() },
        replyNotifier = replyNotifier
    )

    private val uploadHelper = ChatUploadHelper(
        scope = viewModelScope,
        uiState = _uiState,
        fileUploadManager = fileUploadManager,
        appPreferences = appPreferences,
        toolsRepository = toolsRepository,
        sendMediaMessage = { text, imageUrl, videoUrl, displayText ->
            sendController.sendMessage(
                text = text,
                imageUrl = imageUrl,
                videoUrl = videoUrl,
                displayText = displayText
            )
        }
    )

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

    // ==================== 角色 / persona / 模型状态 ====================

    val viewingPersonaFilename: StateFlow<String?> get() = sessionController.viewingPersonaFilename
    val availableRoleModels: StateFlow<List<AIModel>> get() = roleModelController.availableModels
    val selectedRoleModel: StateFlow<AIModel?> get() = roleModelController.selectedModel
    val roleModelLoading: StateFlow<Boolean> get() = roleModelController.isLoading
    val roleModelError: StateFlow<String?> get() = roleModelController.error

    fun setViewingPersona(filename: String) = sessionController.setViewingPersona(filename)

    /** 同一 role 内换 persona：只换 prompt/version，session 和角色模型偏好都保持不动。 */
    suspend fun confirmPersonaSelection(filename: String) {
        sessionController.confirmPersonaSelection(filename)
    }

    /**
     * 登记"当前聊天页显示的是这个角色"，供通知层判断复用页面与自动撤通知。
     *
     * 与 [setPendingSwitch] 分开：深链可能只带 filename、没有 role，
     * 那条路径不走 setPendingSwitch（它要求 role 非空），但仍需要登记上下文。
     */
    fun markVisibleChat(role: String?, personaFilename: String?) {
        replyNotifier?.markChatVisible(role, personaFilename)
    }

    /** 离开聊天页时清空登记（用户回到会话列表，通知不应再被当成"已看到"）。 */
    fun clearVisibleChat() {
        replyNotifier?.clearChatVisible()
    }

    /**
     * 聊天页重新可见（首次进入 / 从后台切回 / 点通知复用已有页面）时清零当前角色未读。
     *
     * 只在进页那一次清是不够的：点通知时聊天页常常已经在栈顶，深链会被吞掉，
     * 不会再走 setPendingSwitch，未读就一直挂在会话列表上（详见
     * [ChatSessionController.clearUnreadForCurrentChat]）。
     *
     * 走 IO 协程：清零要读 persona 列表并按角色聚合，不能卡住主线程首帧。
     */
    fun onChatPageResumed() {
        viewModelScope.launch(Dispatchers.IO) {
            sessionController.clearUnreadForCurrentChat()
        }
    }

    /**
     * 从会话列表进入 role：首帧先切本地 session 身份并清空旧角色 UI，
     * 后续角色归一化 / persona defaults / 未读清理仍交给 [ChatSessionController] 异步完成。
     *
     * 这里不能等 setPendingSwitch 内部的 REST 辅助请求结束才改 currentSessionId：
     * 新 ChatViewModel 初始化时 SessionObserver 会先订阅上一个角色的 currentSessionId，
     * 若继续沿用旧 id，一两秒内会把上一个角色的历史重新灌到新页面，形成明显残影。
     */
    fun setPendingSwitch(role: String, preferredFilename: String? = null) {
        if (role.isBlank()) return

        val targetFilename = preferredFilename?.takeIf { it.isNotBlank() }
        val targetSessionId = roleScopedPreferences.getSessionId(role, targetFilename)
            ?: targetFilename?.let { "web_$it" }
            ?: roleScopedPreferences.defaultSessionId(role)

        // 登记"当前聊天页正显示这个角色"：点通知时据此判断要不要复用现有页面（避免套娃），
        // 切回 App 时据此撤销该角色已看过的通知。
        replyNotifier?.markChatVisible(role, targetFilename)

        // 先同步写入目标 role/persona，让紧随其后的 Room 发射在做预览归属时
        // 已经能看到正确角色；控制器内部的网络补全仍异步执行，不阻塞首帧。
        sessionController.setPendingSwitch(role, targetFilename)

        // 再发布新的 sessionId：旧 observeMessages collect 随后即使还有残留发射，
        // 也会因 sourceSessionId != currentSessionId 被现有归属校验丢弃。
        if (appPreferences.currentSessionId != targetSessionId) {
            appPreferences.currentSessionId = targetSessionId
            flushManager.clear()
            _uiState.update {
                it.copy(
                    messages = emptyList(),
                    hasOlderMessages = false,
                    currentSession = null,
                    isTyping = false,
                    showTypingIndicator = false,
                    loadingState = LoadingState.Loading
                )
            }
        }

        // currentSessionId 已经提前切到目标值；控制器稍后看到“已经是目标 session”时
        // 可能跳过自己的 upsert。这里把目标容器先落到 Room，保证首次进入新角色也能
        // 立即由 observeCurrentSession / observeMessages 接管，不会卡在 null session。
        val now = System.currentTimeMillis()
        viewModelScope.launch(Dispatchers.IO) {
            sessionRepository.upsertLocalSession(
                Session(
                    id = targetSessionId,
                    title = role,
                    createdAt = now,
                    updatedAt = now,
                    isPinned = false
                )
            ).onFailure { e ->
                Log.w(TAG, "首帧预建 role session 失败（控制器仍会继续兜底）: ${e.message}")
            }
        }

        roleModelController.loadForRole(role)
    }

    fun selectModelForCurrentRole(modelId: String) =
        roleModelController.selectForCurrentRole(modelId)

    init {
        observeBackgroundHttpStreaming()
        sessionController.start()
        sessionObserver.start()
        voiceInputController.observeState()
        ttsController.observeState()
        uploadHelper.observeUploadState()
        uploadHelper.init()
        observeUnreadFromOthers()
        rotateInputDraftOnSessionChange()
        persistInputDraftOngoing()
    }

    /**
     * HTTP SSE 生成已提升到进程级后台作用域，因此聊天页销毁后它仍可能继续。
     * 新建 ChatViewModel 时立即继承全局流式状态，并持续同步给本页 flushManager，
     * 防止重进聊天后 WebSocket response_chunk 与仍在运行的 HTTP SSE 双通道重复上屏。
     */
    private fun observeBackgroundHttpStreaming() {
        flushManager.setHttpStreamingActive(ChatSendController.backgroundHttpStreamingActive.value)
        viewModelScope.launch {
            ChatSendController.backgroundHttpStreamingActive.collect { active ->
                flushManager.setHttpStreamingActive(active)
            }
        }
    }

    /**
     * 观察"其他角色"的主动消息未读总数：聊天页顶部返回键右上角的小圆点。
     *
     * 排除当前正在聊的 persona（它的消息直接上屏，不需要提示），
     * 其余角色有未读就亮点，让用户在聊天页里也知道有人找。
     */
    private fun observeUnreadFromOthers() {
        viewModelScope.launch {
            personaLocalMetaRepository.observeAll().collect { metas ->
                val currentFilename = sessionController.conversationPersonaFilename
                val unread = metas
                    .filter { it.personaFilename != currentFilename }
                    .sumOf { it.unreadCount }
                _uiState.update { it.copy(unreadFromOthers = unread) }
            }
        }
    }

    // ==================== 发消息 ====================

    fun sendMessage(text: String, model: String = "default") =
        sendController.sendMessage(text, model)

    fun regenerateMessage(messageId: String, model: String = "default") =
        sendController.regenerateMessage(messageId, model)

    fun editUserMessage(messageId: String, newText: String, model: String = "default") =
        sendController.editUserMessage(messageId, newText, model)

    fun selectMessageVariant(messageId: String, offset: Int) =
        sendController.selectVariant(messageId, offset)

    /**
     * 停止当前会话正在进行的生成（输入栏按钮在生成期间会切成「停止」）。
     *
     * 直接转发给 [ChatSendController]：生成跑在进程级后台作用域上，
     * 不随本 ViewModel 的生命周期存在，取消也只能由那个作用域的持有者来做。
     */
    fun stopGeneration() = sendController.stopGeneration()

    // ==================== 会话操作 ====================

    fun createNewSession(title: String = "新对话") = sessionObserver.createNewSession(title)

    fun switchSession(sessionId: String) = sessionObserver.switchSession(sessionId)

    fun clearHistory() = sessionObserver.clearHistory()

    fun loadOlderMessages() = sessionObserver.loadOlderMessages()

    // ==================== 语音输入 ====================

    fun startVoiceRecording() = voiceInputController.startRecording()

    fun stopVoiceRecording() = voiceInputController.stopRecording()

    fun cancelVoiceRecording() = voiceInputController.cancelRecording()

    fun hasRecordAudioPermission(): Boolean = voiceInputController.hasPermission()

    // ==================== TTS ====================

    fun toggleTTS(messageId: String) = ttsController.togglePlay(messageId)

    fun pauseTTS() = ttsController.pause()

    fun resumeTTS() = ttsController.resume()

    fun stopTTS() = ttsController.stop()

    // ==================== 双角色对话 ====================

    fun togglePeerChat() = peerChatHandler.togglePeerChat()

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
                Log.e(TAG, "删除消息失败", e)
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

    fun setError(message: String) {
        _uiState.update { it.copy(error = message) }
    }

    // ==================== 输入框草稿 ====================

    /**
     * 草稿的「换主」与回填都在同一个协程里串行做。
     *
     * 必须串行：会话从 A 切到 B 时，输入框里装的还是 A 没发出去的话。这里必须
     * 先把它写回 A 的草稿、再把 B 的草稿读出来，两步之间不能让自动保存那条流水线
     * （[persistInputDraftOngoing]）把 A 的内容当成 B 的草稿写进去。
     *
     * 这条链路同时覆盖了「退出聊天页再回来」的恢复：返回会话列表时 ViewModel 被清掉，
     * 重新进入时它还是一个全新的 ViewModel，靠这里从磁盘把草稿读回输入框。
     */
    private fun rotateInputDraftOnSessionChange() {
        viewModelScope.launch(Dispatchers.IO) {
            sessionRepository.observeCurrentSession()
                .map { it?.id }
                .filterNotNull()
                .distinctUntilChanged()
                .collect { sessionId ->
                    // 会话归属校验：深链 / 切角色的瞬间 id 可能不同步，
                    // 这时宁可不动草稿，也不能张冠李戴。
                    val preferred = appPreferences.currentSessionId
                    if (preferred != null && sessionId != preferred) return@collect

                    val previous = draftSessionId
                    val currentText = _uiState.value.inputText
                    if (previous != null && previous != sessionId) {
                        // 真·切会话：inputText 装的一定是上一个会话没发出去的话，先归档再让位。
                        draftStore.writeDraft(previous, currentText)
                    }
                    draftSessionId = sessionId

                    val draft = draftStore.readDraft(sessionId)
                    // previous == null 是进页（ViewModel 刚建），此时输入框里的字是用户自己刚敲的
                    // （有可能比会话 flow 先到），只能补位、不能覆盖；previous != null 才是切会话，
                    // 那份内容已经归档，无条件替换成新会话自己的草稿（没有就置空）。
                    val shouldRestore = previous != null || currentText.isBlank()
                    if (shouldRestore && draft != currentText) {
                        _uiState.update { it.copy(inputText = draft) }
                    }
                }
        }
    }

    /**
     * 打字过程中持续把草稿写盘：[DRAFT_PERSIST_DEBOUNCE_MS] 的静默之后才落笔，
     * 免得每敲一个字都触发一次 SharedPreferences 全量写。
     *
     * 挂在 uiState 而不是 updateInputText 上，是因为输入框内容的来源不止一处：
     * 语音识别回填、发送失败回填、发送后清空都会改它，只有跟着状态走才漏不掉。
     * 其中「发送后清空」尤其关键 —— 草稿必须跟着删，否则下次进来会看到已发出的内容。
     */
    private fun persistInputDraftOngoing() {
        viewModelScope.launch(Dispatchers.IO) {
            _uiState
                .map { it.inputText to (it.currentSession?.id ?: appPreferences.currentSessionId) }
                .distinctUntilChanged()
                .collect { (text, sessionId) -> scheduleDraftPersist(sessionId, text) }
        }
    }

    private fun scheduleDraftPersist(sessionId: String?, text: String) {
        draftPersistJob?.cancel()
        draftPersistJob = viewModelScope.launch(Dispatchers.IO) {
            delay(DRAFT_PERSIST_DEBOUNCE_MS)
            // 停手这段时间里会话可能已经切走：那份内容由
            // rotateInputDraftOnSessionChange 归档到它自己的会话，这里不能抢着写。
            if (sessionId == null || sessionId != draftSessionId) return@launch
            draftStore.writeDraft(sessionId, text)
        }
    }

    /**
     * 把输入框最后的内容同步写盘，供聊天页即将消失时调用。
     *
     * debounce 最多还有 400ms 没落笔，返回键一按 ViewModel 就活不了那么久，
     * 所以 Compose dispose 与 [onCleared] 各兜一层，这里一律同步 commit。
     */
    fun flushInputDraft() {
        // 已经要写了，debounce 里排着的那次就作废，避免同一个内容写两遍。
        draftPersistJob?.cancel()
        draftPersistJob = null
        val sessionId = draftSessionId ?: return
        draftStore.writeDraftSync(sessionId, _uiState.value.inputText)
    }

    // ==================== 文件上传 ====================

    fun uploadFile(uri: Uri, kind: UploadKind) = uploadHelper.uploadFile(uri, kind)
    fun uploadImage(uri: Uri) = uploadHelper.uploadImage(uri)
    fun uploadVideo(uri: Uri) = uploadHelper.uploadVideo(uri)
    fun resetUploadState() = uploadHelper.resetUploadState()
    fun sendImageMessage(imageUrl: String, caption: String = "") =
        uploadHelper.sendImageMessage(imageUrl, caption)
    fun sendVideoMessage(videoUrl: String, caption: String = "") =
        uploadHelper.sendVideoMessage(videoUrl, caption)

    fun clearPendingImage() = uploadHelper.clearPendingImage()

    fun clearPendingVideo() = uploadHelper.clearPendingVideo()

    fun sendPendingOrText(text: String) {
        val pendingImage = _uiState.value.lastUploadedImageUrl
        val pendingVideo = _uiState.value.pendingVideoUrl
        when {
            !pendingVideo.isNullOrBlank() -> sendVideoMessage(pendingVideo, text)
            !pendingImage.isNullOrBlank() -> sendImageMessage(pendingImage, text)
            else -> sendMessage(text)
        }
    }

    fun resolveImageUrl(rawUrl: String): String =
        ImageUrlResolver.resolve(appPreferences.effectiveBackendUrl, rawUrl)

    fun isSupportedImageType(mimeType: String): Boolean = uploadHelper.isSupportedImageType(mimeType)
    fun isSupportedVideoType(mimeType: String): Boolean = uploadHelper.isSupportedVideoType(mimeType)
    suspend fun getFileInfo(uri: Uri) = uploadHelper.getFileInfo(uri)

    fun extractMessageContent(response: MessageResponse): String? {
        if (!response.response.isNullOrBlank()) return response.response
        if (!response.reply.isNullOrBlank()) return response.reply
        if (response.message != null && response.message.text.isNotBlank()) return response.message.text
        if (response.data != null && response.data.text.isNotBlank()) return response.data.text
        return null
    }

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
        // 放在最前面：ViewModel 一旦开始清理，后面的协程随时可能停掉。
        // 聊天页在这里已经消失（返回会话列表 / 手势退出），输入框里没发出去的话
        // 必须此刻就同步落盘，否则用户回来看到的还是空白输入框。
        flushInputDraft()
        super.onCleared()
        voiceInputController.cancelRecording()
        ttsController.stop()
        flushManager.clear()
    }
}
