package com.aveline.ai.mobile.presentation.conversations

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.presentation.chat.ChatPreviewBuilder
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject

/**
 * 会话列表项：一个 persona 一行（类似 QQ 消息列表）
 *
 * @param filename 后端 persona.filename（稳定唯一标识，用于切 persona 和关联本地元数据）
 * @param displayName 显示昵称：本地 customName 优先，其次后端 name
 * @param role 角色标识（如 "Aveline"/"Ling"/"小鹿"），用于按角色分组
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
    val isActive: Boolean
)

data class ConversationListUiState(
    val items: List<ConversationItem> = emptyList(),
    val roleItems: List<RoleItem> = emptyList(),
    val activeFilename: String = "",
    val isLoading: Boolean = false,
    val isSwitching: Boolean = false,
    val error: String? = null
)

/**
 * 会话列表 ViewModel：合并后端 persona 列表 + 本地 meta（昵称/头像覆盖）。
 */
@HiltViewModel
class ConversationListViewModel @Inject constructor(
    private val personaRepository: PersonaRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val chatRepository: ChatRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(ConversationListUiState())
    val uiState: StateFlow<ConversationListUiState> = _uiState.asStateFlow()

    init {
        // 启动时拉一次
        refresh()
        // 本地 meta 变化（改昵称/改头像）→ 自动重渲染列表
        viewModelScope.launch {
            personaLocalMetaRepository.observeAll().collect {
                refresh()
            }
        }
    }

    /**
     * 重新拉 persona + 本地 meta，合并出列表。
     */
    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            runCatching {
                // 冷启动从本地聊天历史重建全部会话预览：打开 App 即自动加载，
                // 不再需要用户点进聊天后才会写入预览。
                rebuildLastMessagePreviews()

                val personas = personaRepository.getPersonasRaw().getOrThrow()
                val activeRes = personaRepository.getActivePersonaRaw().getOrThrow()
                val activeFilename = extractFilename(activeRes) ?: ""
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
                            isActive = filename == activeFilename
                        )
                    }.getOrNull()
                }.sortedWith(
                    // QQ 风格：激活 persona 始终置顶；其余按最后消息时间倒序（无消息的排最后）
                    compareByDescending<ConversationItem> { it.isActive }
                        .thenByDescending { it.lastMessageAt ?: 0L }
                )

                _uiState.update {
                    // 聚合 RoleItem：每个角色一行，显示该角色最新消息和激活 persona 的头像
                    val roleItems = items.groupBy { it.role }
                        .map { (role, list) ->
                            // 找该角色下"激活 persona"或"最新消息 persona"作为代表
                            val representative = list.firstOrNull { it.isActive }
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
                                isActive = list.any { it.isActive }
                            )
                        }.sortedWith(
                            // 激活角色优先；其余按最新消息时间倒序
                            compareByDescending<RoleItem> { it.isActive }
                                .thenByDescending { it.lastMessageAt ?: 0L }
                        )

                    it.copy(
                        items = items,
                        roleItems = roleItems,
                        activeFilename = activeFilename,
                        isLoading = false
                    )
                }
            }.onFailure { e ->
                _uiState.update {
                    it.copy(isLoading = false, error = e.message ?: "加载失败")
                }
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
    private suspend fun rebuildLastMessagePreviews() {
        val metas = personaLocalMetaRepository.observeAll().first()
        for (meta in metas) {
            // sessionId 规则：web_{personaFilename}
            val sessionId = "web_${meta.personaFilename}"
            // observeMessages 已应用 selectActiveConversationPath，返回用户实际看到的活跃消息路径，
            // 取最后一条即为最新消息。
            val lastMessage = chatRepository.observeMessages(sessionId).first().lastOrNull()
            if (lastMessage != null) {
                val preview = ChatPreviewBuilder.buildPreviewText(
                    text = lastMessage.text,
                    isUser = lastMessage.isUser,
                    messageType = lastMessage.messageType,
                    imageUrl = lastMessage.imageUrl
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
