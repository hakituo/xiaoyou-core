package com.aveline.ai.mobile.presentation.conversations

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.local.preferences.RoleScopedPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.presentation.chat.ChatPreviewBuilder
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject

/**
 * 会话列表项：一个 persona 一行（类似 QQ 消息列表）
 *
 * @param filename 后端 persona.filename（稳定唯一标识，用于切 persona 和关联本地元数据）
 * @param displayName 显示昵称：本地 customName 优先，其次后端 name
 * @param role 角色标识（如 "Aveline"/"Ling"/"Fawn"），用于按角色分组
 * @param description 描述（用于列表副标题兜底，当无消息预览时显示）
 * @param avatarUrl 后端默认头像 URL（可为 null）
 * @param localAvatarPath 本地自定义头像文件名（存在则用本地文件显示）
 * @param lastMessagePreview 最后一条消息预览文本（QQ 风格"X 分钟前 / 我: xxx"）；为空则显示 description
 * @param lastMessageAt 最后一条消息时间戳（毫秒），用于"X 分钟前"显示
 * @param isActive 是否为当前激活的 persona
 */
data class ConversationItem(
    val filename: String,
    val displayName: String,
    val role: String,
    val description: String,
    val avatarUrl: String?,
    val localAvatarPath: String?,
    val lastMessagePreview: String?,
    val lastMessageAt: Long?,
    /** 角色主动消息未读数（进聊天页清零） */
    val unreadCount: Int,
    val isActive: Boolean
)

/**
 * 角色级别的会话列表项：每个角色一行（不展开 persona）。
 *
 * - 一个角色对应多个 persona，列表只显示角色级别（最新消息/激活 persona 的头像/角色名）
 * - 点击角色 → 进 Chat（带 role 参数），ChatScreen 内部选该角色的激活 persona
 * - 伴侣详情页的人设切换在该 role 范围内切换
 *
 * @param role 角色名（如 "Aveline"/"Ling"）
 * @param activeFilename 当前激活的 persona filename（用于点击时知道进哪个 persona）
 * @param displayName 角色显示名（用激活 persona 的 customName 或角色名）
 * @param avatarUrl 角色（激活 persona）的头像 URL
 * @param localAvatarPath 角色（激活 persona）的本地自定义头像文件名
 * @param lastMessagePreview 该角色下所有 persona 中最新一条消息预览
 * @param lastMessageAt 该角色下所有 persona 中最新一条消息时间戳
 * @param personaCount 该角色下 persona 总数（用于伴侣详情切换范围）
 * @param isActive 是否为当前激活的 persona 所属角色
 */
data class RoleItem(
    val role: String,
    val activeFilename: String,
    val displayName: String,
    val avatarUrl: String?,
    val localAvatarPath: String?,
    val lastMessagePreview: String?,
    val lastMessageAt: Long?,
    val personaCount: Int,
    /** 该角色下所有 persona 的主动消息未读总数（会话列表徽章用） */
    val unreadCount: Int,
    val isActive: Boolean
)

data class ConversationListUiState(
    val items: List<ConversationItem> = emptyList(),
    val roleItems: List<RoleItem> = emptyList(),
    val activeFilename: String = "",
    val isLoading: Boolean = false,
    val isSwitching: Boolean = false,
    val error: String? = null,
    /** 可选语音音色名（从 persona 响应的 default_voice 去重收集，后端权威源 voice_map）。 */
    val voiceNames: List<String> = emptyList(),
    /** persona filename -> 用户手选的音色名（本地覆盖，优先级高于角色默认）。 */
    val personaVoiceOverrides: Map<String, String> = emptyMap(),
    /** persona filename -> 后端下发的角色默认音色。 */
    val personaDefaultVoices: Map<String, String> = emptyMap()
)

/**
 * 会话列表 ViewModel：合并后端 persona 列表 + 本地 meta（昵称/头像覆盖）。
 */
@HiltViewModel
class ConversationListViewModel @Inject constructor(
    private val personaRepository: PersonaRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val chatRepository: ChatRepository,
    private val appPreferences: AppPreferences,
    private val roleScopedPreferences: RoleScopedPreferences,
    private val webSocketManager: WebSocketManager
) : ViewModel() {

    companion object {
        private const val TAG = "ConversationListVM"

        /**
         * 启动时 EndpointResolver 需要等待网络 onAvailable + 去抖 + 探测，
         * persona REST 可能抢先失败。这里只做有限次短退避，避免失败态永久挂死，
         * 又不在后端长期离线时无限后台轮询。
         */
        private val AUTO_RETRY_DELAYS_MS = longArrayOf(
            800L,
            1_600L,
            3_200L,
            6_400L,
            12_000L,
            30_000L
        )
    }

    private val _uiState = MutableStateFlow(ConversationListUiState())
    val uiState: StateFlow<ConversationListUiState> = _uiState.asStateFlow()

    /** 同一时刻只允许一条 persona 刷新链，避免 init/meta/网络恢复并发重复拉取。 */
    private var refreshJob: Job? = null

    /** 首次/恢复失败后的有限自动重试。 */
    private var retryJob: Job? = null
    private var autoRetryAttempt = 0

    /** 与 UI error 解耦：用户可以关闭错误条，但后台仍知道上一次真实加载失败。 */
    private var lastLoadFailed = false

    init {
        // 启动时拉一次
        refresh()

        // 本地 meta 变化（改昵称/改头像）→ 自动重渲染列表
        viewModelScope.launch {
            personaLocalMetaRepository.observeAll().collect {
                refresh()
            }
        }

        // 生效地址发生变化后，REST 会通过 baseUrlInterceptor 自动走新地址。
        // 如果列表上一轮正好失败，立刻重拉，不再等用户手点“重新加载”。
        viewModelScope.launch {
            appPreferences.effectiveBackendUrlFlow.collect { url ->
                if (url.isNotBlank() && shouldRecoverFromLoadFailure()) {
                    Log.i(TAG, "生效后端地址已更新，自动恢复会话列表: $url")
                    restartRecoveryRetries()
                    refreshFromRecovery()
                }
            }
        }

        // 常驻模式/聊天链的 WebSocket 一旦重新连通，说明后端已可达。
        // REST 与 WS 协议不同，但“后端可达”这一事实可以作为失败列表的恢复信号。
        viewModelScope.launch {
            webSocketManager.connectionState.collect { state ->
                if (
                    state == WebSocketManager.ConnectionState.CONNECTED &&
                    shouldRecoverFromLoadFailure()
                ) {
                    Log.i(TAG, "WebSocket 已恢复连接，自动重拉失败的会话列表")
                    restartRecoveryRetries()
                    refreshFromRecovery()
                }
            }
        }
    }

    /**
     * 用户/本地状态主动触发刷新：重新开启一轮有限自动恢复预算。
     */
    fun refresh() {
        if (refreshJob?.isActive == true) return
        restartRecoveryRetries()
        startRefresh()
    }

    /** 网络恢复/自动退避触发：不反复重置重试计数。 */
    private fun refreshFromRecovery() {
        if (refreshJob?.isActive == true) return
        startRefresh()
    }

    private fun startRefresh() {
        refreshJob = viewModelScope.launch {
            try {
                _uiState.update { it.copy(isLoading = true, error = null) }
                runCatching {
                    val personas = personaRepository.getPersonasRaw().getOrThrow()

                    // 冷启动从本地聊天历史重建全部会话预览：打开 App 即自动加载，
                    // 不再需要用户点进聊天后才会写入预览。
                    // 预览只是列表副标题，重建失败不应让整张列表变空，单独兜底。
                    // 需要在拿到 personas 之后跑：重建要按 persona -> role 找到
                    // 聊天页真正在用的 role session，否则读的是另一个会话。
                    runCatching { rebuildLastMessagePreviews(roleByFilename(personas)) }
                        .onFailure { Log.w(TAG, "重建会话预览失败（不阻断列表）: ${it.message}") }

                    // active persona 只用于"当前激活"角标与代表版本选择：拿不到时降级为空串，
                    // 不能因为它失败就把整张角色列表丢掉（否则主页会直接变空态）。
                    val activeFilename = runCatching {
                        extractFilename(personaRepository.getActivePersonaRaw().getOrThrow())
                    }.onFailure {
                        Log.w(TAG, "获取 active persona 失败（列表仍照常展示）: ${it.message}")
                    }.getOrNull() ?: ""
                    // 本地 meta 一次性取（Flow.first()），用于合并显示
                    val metas = personaLocalMetaRepository.observeAll().first()
                        .associateBy { it.personaFilename }

                    val items = personas.mapNotNull { element ->
                        runCatching {
                            val obj = element.jsonObject
                            val filename = obj["filename"]?.jsonPrimitive?.content ?: return@runCatching null
                            val name = obj["name"]?.jsonPrimitive?.content ?: "未命名"
                            val description = obj["description"]?.jsonPrimitive?.content ?: ""
                            val avatarUrl = obj["avatar_url"]?.jsonPrimitive?.content
                            // 后端 list_personas 返回 role 字段（基于 identity.name 去括号后缀）
                            // 例如 "Aveline (QQ)" -> "Aveline"，"Ling" -> "Ling"
                            val role = obj["role"]?.jsonPrimitive?.content
                                ?: name.split("(")[0].split("（")[0].trim().ifEmpty { name }
                            val meta = metas[filename]
                            ConversationItem(
                                filename = filename,
                                // 显示名优先级：自定义昵称 > role 角色名 > 后端 persona 名
                                // 必须用 role 而不是 name，避免把 "Ling (QQ)" 这种 persona 文件名后缀显示出来。
                                displayName = meta?.customName?.takeIf { it.isNotBlank() } ?: role,
                                role = role,
                                description = description,
                                avatarUrl = avatarUrl,
                                localAvatarPath = meta?.avatarPath,
                                lastMessagePreview = meta?.lastMessagePreview,
                                lastMessageAt = meta?.lastMessageAt,
                                unreadCount = meta?.unreadCount ?: 0,
                                isActive = filename == activeFilename
                            )
                        }.getOrNull()
                    }.sortedWith(
                        // QQ 风格：激活 persona 始终置顶；其余按最后消息时间倒序（无消息的排最后）
                        compareByDescending<ConversationItem> { it.isActive }
                            .thenByDescending { it.lastMessageAt ?: 0L }
                    )

                    // 角色默认音色：从 persona 响应的 default_voice 取
                    val personaDefaultVoices = mutableMapOf<String, String>()
                    personas.forEach { element ->
                        runCatching {
                            val obj = element.jsonObject
                            val filename = obj["filename"]?.jsonPrimitive?.contentOrNull
                                ?: return@runCatching
                            val voice = obj["default_voice"]?.jsonPrimitive?.contentOrNull.orEmpty()
                            if (voice.isNotBlank()) personaDefaultVoices[filename] = voice
                        }
                    }
                    // 候选音色用后端完整列表（含未被任何角色引用的音色）；拿不到时回落到默认值集合
                    val voiceCandidates = LinkedHashSet<String>(
                        runCatching { personaRepository.getAvailableVoices().getOrThrow() }
                            .onFailure { Log.w(TAG, "拉取音色列表失败: ${it.message}") }
                            .getOrNull().orEmpty()
                    )
                    if (voiceCandidates.isEmpty()) voiceCandidates += personaDefaultVoices.values
                    // 用户手选值（本地覆盖）单独取，TTS 里优先级高于角色默认音色
                    val personaVoiceOverrides = personaDefaultVoices.keys
                        .mapNotNull { f -> appPreferences.getPersonaVoice(f)?.let { f to it } }
                        .toMap()

                    _uiState.update {
                        // 聚合 RoleItem：每个角色一行，显示该角色最新消息和激活 persona 的头像
                        val roleItems = items.groupBy { it.role }
                            .map { (role, list) ->
                                // 先恢复该角色明确保存的版本，其他角色的全局切换不应覆盖它。
                                // 有未读时例外：优先打开未读所在的那个 persona 会话，
                                // 否则会出现"列表显示有未读、点进去是另一个版本看不到"。
                                val savedFilename = appPreferences.getSelectedPersona(role)
                                val representative =
                                    list.firstOrNull { it.filename == savedFilename && it.unreadCount > 0 }
                                        ?: list.firstOrNull { it.unreadCount > 0 }
                                        ?: list.firstOrNull { it.filename == savedFilename }
                                        ?: list.firstOrNull { it.isActive }
                                        ?: list.maxByOrNull { it.lastMessageAt ?: 0L }
                                        ?: list.first()
                                // 该角色下最新一条消息预览
                                val latestInRole = list.maxByOrNull { it.lastMessageAt ?: 0L }
                                RoleItem(
                                    role = role,
                                    activeFilename = representative.filename,
                                    displayName = representative.displayName,
                                    avatarUrl = representative.avatarUrl,
                                    localAvatarPath = representative.localAvatarPath,
                                    lastMessagePreview = latestInRole?.lastMessagePreview
                                        ?: list.firstOrNull()?.description ?: "",
                                    lastMessageAt = latestInRole?.lastMessageAt,
                                    personaCount = list.size,
                                    unreadCount = list.sumOf { it.unreadCount },
                                    isActive = list.any { it.isActive }
                                )
                            }.sortedWith(
                                // 纯按最新消息时间倒序（QQ 语义）：谁刚发消息谁浮上来。
                                // 之前"激活角色始终置顶"会导致用户正在聊的角色
                                // 压住其他角色刚发来的主动消息，新消息反而看不到。
                                // 没有消息记录的角色（lastMessageAt 为 null）排最后。
                                compareByDescending<RoleItem> { it.lastMessageAt ?: 0L }
                            )

                        it.copy(
                            items = items,
                            roleItems = roleItems,
                            activeFilename = activeFilename,
                            isLoading = false,
                            voiceNames = voiceCandidates.toList(),
                            personaVoiceOverrides = personaVoiceOverrides,
                            personaDefaultVoices = personaDefaultVoices.toMap()
                        )
                    }
                }.onSuccess {
                    lastLoadFailed = false
                    autoRetryAttempt = 0
                    retryJob?.cancel()
                    retryJob = null
                }.onFailure { e ->
                    lastLoadFailed = true
                    _uiState.update {
                        it.copy(isLoading = false, error = e.message ?: "加载失败")
                    }
                    scheduleAutoRetry()
                }
            } finally {
                refreshJob = null
            }
        }
    }

    private fun shouldRecoverFromLoadFailure(): Boolean {
        return lastLoadFailed && !_uiState.value.isLoading
    }

    private fun restartRecoveryRetries() {
        autoRetryAttempt = 0
        retryJob?.cancel()
        retryJob = null
    }

    private fun scheduleAutoRetry() {
        if (!lastLoadFailed || retryJob?.isActive == true) return
        if (autoRetryAttempt >= AUTO_RETRY_DELAYS_MS.size) return

        val delayMs = AUTO_RETRY_DELAYS_MS[autoRetryAttempt]
        autoRetryAttempt += 1
        retryJob = viewModelScope.launch {
            Log.d(TAG, "会话列表加载失败，${delayMs}ms 后自动重试（第 $autoRetryAttempt 次）")
            delay(delayMs)
            retryJob = null
            if (shouldRecoverFromLoadFailure()) {
                refreshFromRecovery()
            }
        }
    }

    /**
     * 冷启动时从本地聊天历史重建全部会话预览（lastMessagePreview / lastMessageAt）。
     *
     * 旧实现只在刷新时清空所有旧预览，导致打开 App 时列表预览空白，必须点进聊天
     * 由 ChatViewModel 写入后才会出现。这里改为直接用本地消息库回填每个 persona 的
     * 最后一条消息预览，打开 App 即自动渲染，且天然修复旧版"串台"脏数据
     * （预览以消息自身归属的 session 重建，不再可能被错误清空/错写）。
     *
     * 本地消息库已在历史加载时缓存（loadHistoryFromApi 命中本地即有缓存、跳过 API），
     * 因此冷启动无需联网即可重建。
     */
    /** persona filename -> role，与列表合并处同一套解析规则。 */
    private fun roleByFilename(personas: JsonArray): Map<String, String> {
        val map = mutableMapOf<String, String>()
        personas.forEach { element ->
            runCatching {
                val obj = element.jsonObject
                val filename = obj["filename"]?.jsonPrimitive?.contentOrNull ?: return@runCatching
                val name = obj["name"]?.jsonPrimitive?.content ?: ""
                val role = obj["role"]?.jsonPrimitive?.contentOrNull
                    ?: name.split("(")[0].split("（")[0].trim().ifEmpty { name }
                if (role.isNotBlank()) map[filename] = role
            }
        }
        return map
    }

    /**
     * 解析某个 persona 的聊天会话 id：优先 role session（聊天页显示的就是它），
     * 没有 role 映射时才退回旧的 web_{persona}。
     *
     * 直接写死 web_{persona} 会让预览去读一个聊天页根本不显示的会话，
     * 结果就是"明明聊过天，列表副标题却是空的"。
     */
    private fun sessionIdFor(filename: String, roles: Map<String, String>): String {
        val role = roles[filename]
        if (!role.isNullOrBlank()) {
            roleScopedPreferences.getSessionId(role, filename)?.let { return it }
        }
        return "web_$filename"
    }

    private suspend fun rebuildLastMessagePreviews(roles: Map<String, String> = emptyMap()) {
        val metas = personaLocalMetaRepository.observeAll().first()
        for (meta in metas) {
            val sessionId = sessionIdFor(meta.personaFilename, roles)
            // observeMessages 已应用 selectActiveConversationPath，返回用户实际看到的活跃消息路径，
            // 取最后一条即为最新消息。
            val lastMessage = chatRepository.observeMessageWindow(sessionId, 1).first().messages.lastOrNull()
            if (lastMessage != null) {
                val preview = ChatPreviewBuilder.buildPreviewText(
                    text = lastMessage.text,
                    isUser = lastMessage.isUser,
                    messageType = lastMessage.messageType,
                    imageUrl = lastMessage.imageUrl,
                    videoUrl = lastMessage.videoUrl
                )
                personaLocalMetaRepository.updateLastMessage(
                    personaFilename = meta.personaFilename,
                    preview = preview,
                    timestamp = lastMessage.timestamp
                )
            } else {
                // 本地无历史：清空预览，避免旧版串台脏数据残留
                personaLocalMetaRepository.updateLastMessage(
                    personaFilename = meta.personaFilename,
                    preview = null,
                    timestamp = null
                )
            }
        }
    }

    /**
     * 切换激活 persona（点击会话项时调用）。成功后调用 onSuccess 进入聊天页。
     */
    fun switchPersona(filename: String, onSuccess: () -> Unit) {
        if (_uiState.value.isSwitching) return
        if (filename == _uiState.value.activeFilename) {
            // 已是当前 persona，直接进聊天页
            onSuccess()
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isSwitching = true) }
            runCatching {
                personaRepository.selectPersona(filename).getOrThrow()
                _uiState.update { it.copy(isSwitching = false, activeFilename = filename) }
                onSuccess()
            }.onFailure { e ->
                _uiState.update {
                    it.copy(isSwitching = false, error = e.message ?: "切换失败")
                }
            }
        }
    }

    /**
     * 更新 persona 昵称（传 null/空 表示恢复默认）
     */
    fun selectPersonaVoice(filename: String, voiceName: String) {
        if (filename.isBlank()) return
        appPreferences.setPersonaVoice(filename, voiceName)
        // 立刻更新本地覆盖快照，人设面板上能马上看到选中态
        _uiState.update { state ->
            val updated = state.personaVoiceOverrides.toMutableMap()
            if (voiceName.isBlank()) updated.remove(filename) else updated[filename] = voiceName
            state.copy(personaVoiceOverrides = updated)
        }
    }

    /**
     * 更新 persona 昵称（传 null/空 表示恢复默认）
     */
    fun updateDisplayName(filename: String, name: String?) {
        viewModelScope.launch {
            android.util.Log.d("ConvListVM", "updateDisplayName: filename=$filename name=$name")
            runCatching { personaLocalMetaRepository.setCustomName(filename, name) }
                .onFailure { e ->
                    android.util.Log.e("ConvListVM", "setCustomName 失败", e)
                    _uiState.update { it.copy(error = "保存昵称失败: ${e.message}") }
                }
                .onSuccess {
                    android.util.Log.d("ConvListVM", "setCustomName 成功 filename=$filename")
                }
        }
    }

    /**
     * 更新 persona 头像
     */
    fun updateAvatar(filename: String, uri: android.net.Uri) {
        viewModelScope.launch {
            android.util.Log.d("ConvListVM", "updateAvatar: filename=$filename uri=$uri")
            val ok = personaLocalMetaRepository.setAvatar(filename, uri)
            if (!ok) {
                android.util.Log.e("ConvListVM", "setAvatar 返回 false filename=$filename")
                _uiState.update { it.copy(error = "头像保存失败（可能是文件读写权限问题）") }
            } else {
                android.util.Log.d("ConvListVM", "setAvatar 成功 filename=$filename")
            }
        }
    }

    /** 清空头像（恢复后端默认） */
    fun clearAvatar(filename: String) {
        viewModelScope.launch {
            runCatching { personaLocalMetaRepository.clearAvatar(filename) }
        }
    }

    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }

    private fun extractFilename(activeRes: JsonObject): String? {
        return runCatching { activeRes["filename"]?.jsonPrimitive?.content }.getOrNull()
            ?: runCatching { activeRes["data"]?.jsonObject?.get("filename")?.jsonPrimitive?.content }.getOrNull()
    }
}