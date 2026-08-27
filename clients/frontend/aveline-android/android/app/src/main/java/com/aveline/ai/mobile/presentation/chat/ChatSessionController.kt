package com.aveline.ai.mobile.presentation.chat

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.domain.models.Session
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * 负责"当前角色（persona）与会话（session）"的状态管理。
 *
 * 从 ChatViewModel 中拆出的原因：ChatViewModel 同时承载消息流、语音、TTS、上传等
 * 职责，角色/会话切换逻辑混杂其中，既难读也难以定位跨角色串台类问题。本类把以下
 * 逻辑内聚在一起：
 * - 当前激活的 persona filename（后端全局 active 的本地缓存）
 * - "正在查看的角色"（伴侣详情面板只读展示用）
 * - 延迟切换意图（pendingSwitch：进聊天只记意图，发消息才切后端 persona）
 * - 本地 session 切换（sessionId = "web_{persona_filename}"，按 persona 隔离消息）
 *
 * 关键设计（跨角色串台修复）：
 * 1. 进入聊天页立即切本地 session，而不是等到发消息——否则只看历史时
 *    currentSessionId 停留在上一个角色，消息列表会加载上一个角色的记录。
 * 2. 本地切换只动 Room + Preferences，不调后端 selectPersona，避免 429。
 * 3. 切换完成后通过 [onSessionSwitched] 回调通知外部清理流式残留（flushManager），
 *    防止上一个角色的流式增量串入新会话。
 *
 * @param scope ViewModel 的协程作用域（viewModelScope）
 * @param appPreferences 全局偏好，读写 currentSessionId
 * @param sessionRepository 会话仓储，用于本地 upsert session
 * @param personaRepository persona 仓储，用于读 active persona / 按 role 找 persona
 * @param onSessionSwitched 本地 session 切换完成后的回调（清理流式残留）
 */
class ChatSessionController(
    private val scope: CoroutineScope,
    private val appPreferences: AppPreferences,
    private val sessionRepository: SessionRepository,
    private val personaRepository: PersonaRepository,
    private val onSessionSwitched: () -> Unit
) {
    companion object {
        private const val TAG = "ChatSessionController"

        /**
         * 从本地 sessionId 反推 persona filename。
         *
         * 本地 sessionId 恒为 "web_{persona_filename}"，这是按角色隔离消息的约定。
         * 反推结果用于"消息列表预览归属"：预览必须写到当前正在查看的 session 对应的
         * persona 上，而不能写后端全局 active persona（两者可能不一致，是预览串台的根因）。
         *
         * @return 非 web_ 前缀或空串时返回 null（调用方应回退到 active persona）
         */
        fun personaFilenameFromSessionId(sessionId: String?): String? {
            val id = sessionId ?: return null
            if (!id.startsWith("web_")) return null
            return id.removePrefix("web_").takeIf { it.isNotBlank() }
        }
    }

    /** 当前激活的 persona filename（异步取一次缓存；切 persona 时刷新） */
    @Volatile
    var currentPersonaFilename: String? = null
        private set

    /**
     * 伴侣详情面板"正在查看的角色"对应的 persona 文件名（只读用途：状态/人设/记忆展示）。
     *
     * 与 [currentPersonaFilename]（对话实际 active persona）解耦：
     * - 进入某角色聊天时由 setPendingSwitch 预置为该角色文件（即使还没发消息、对话还没切人设）；
     * - 在面板里点同角色某个人设版本时也只改这里，纯查看，不调 switch，不影响聊天气泡头像；
     * - 真正切对话人设仍由发消息触发（consumePendingSwitch），届时 currentPersonaFilename 变化，
     *   这里同步跟随，保证两者最终一致。
     */
    private val _viewingPersonaFilename = MutableStateFlow<String?>(null)
    val viewingPersonaFilename: StateFlow<String?> = _viewingPersonaFilename.asStateFlow()

    /** 伴侣面板点击某个人设版本：只改"正在查看的角色"，纯只读，不切对话人设。 */
    fun setViewingPersona(filename: String) {
        if (filename.isBlank()) return
        _viewingPersonaFilename.value = filename
        Log.d(TAG, "setViewingPersona(只读): $filename")
    }

    /**
     * 进入 Chat 时记录"待切换意图"，但**不立即切后端人设**。
     *
     * 用户从会话列表点角色进入聊天页时，如果点进去就马上 selectPersona，会：
     * 1. 每次进聊天都打后端 API → 高频使用下容易 429
     * 2. 即使只是看看历史，也被迫切到目标 persona
     *
     * 因此改为"延迟切换"：进页面只记录 targetRole/targetFilename，
     * 真正切人设推迟到用户**首次发消息**时执行一次（见 [consumePendingSwitchIfNeeded]）。
     *
     * 但**本地 session 必须立刻切**：否则只看历史不发消息时，currentSessionId 还停在上一个
     * 角色，聊天窗口会显示上一个角色的消息（跨角色串台）。
     * 只动本地 Room + Preferences，不调后端 selectPersona，因此不会带来 429 压力。
     *
     * @param role 列表点击的角色名（兜底用）
     * @param preferredFilename 列表显示的代表 persona filename；发消息时优先切到它
     */
    fun setPendingSwitch(role: String, preferredFilename: String? = null) {
        if (role.isBlank()) return
        pendingSwitchRole = role
        pendingSwitchFilename = preferredFilename?.takeIf { it.isNotBlank() }
        pendingSwitchConsumed = false
        // 预置"正在查看的角色"：进哪个角色的聊天，详情面板就显示哪个角色，
        // 即使还没发消息、对话尚未切人设（纯只读，不调 switch）。
        preferredFilename?.takeIf { it.isNotBlank() }?.let { _viewingPersonaFilename.value = it }
        Log.d(TAG, "setPendingSwitch: role=$role preferredFilename=$pendingSwitchFilename（后端切人设延迟到发消息）")

        pendingSwitchFilename?.let { target ->
            scope.launch(Dispatchers.IO) {
                switchLocalSession(target)
            }
        }
    }

    @Volatile
    private var pendingSwitchRole: String? = null
    @Volatile
    private var pendingSwitchFilename: String? = null
    @Volatile
    private var pendingSwitchConsumed = false

    /**
     * 首次发消息时执行一次延迟切换：切到目标 role 下的目标 persona。
     * 当前已是要切的目标则跳过 selectPersona，减少后端 429。
     */
    suspend fun consumePendingSwitchIfNeeded() {
        if (pendingSwitchConsumed) return
        val role = pendingSwitchRole
        if (role.isNullOrBlank()) return
        pendingSwitchConsumed = true

        val currentFilename = currentPersonaFilename
        val target = pendingSwitchFilename

        // 当前已是要切的目标：跳过 select API，减少后端 429。
        if (target != null && currentFilename == target) {
            Log.d(TAG, "consumePendingSwitch: 当前 persona 已是目标，跳过")
            return
        }

        runCatching {
            val personas = personaRepository.getPersonasRaw().getOrThrow()
            val rolePersonas = personas.mapNotNull { p ->
                runCatching { p.jsonObject }.getOrNull()
            }.filter { obj ->
                val name = obj["name"]?.jsonPrimitive?.content ?: ""
                val pRole = obj["role"]?.jsonPrimitive?.content
                    ?: name.split("(")[0].split("（")[0].trim().ifEmpty { name }
                pRole == role
            }
            if (rolePersonas.isEmpty()) {
                Log.w(TAG, "consumePendingSwitch: role=$role 下没有 persona")
                return@runCatching
            }

            val targetFilename = if (target != null) {
                target.takeIf { t ->
                    rolePersonas.any { obj -> obj["filename"]?.jsonPrimitive?.content == t }
                } ?: rolePersonas.firstOrNull()?.get("filename")?.jsonPrimitive?.content
            } else {
                rolePersonas.firstOrNull()?.get("filename")?.jsonPrimitive?.content
            }

            if (!targetFilename.isNullOrBlank() && currentFilename != targetFilename) {
                Log.d(TAG, "consumePendingSwitch: 发消息触发切换 role=$role 的 persona=$targetFilename")
                personaRepository.selectPersona(targetFilename).getOrThrow()
                // 切好后立即刷新本地缓存，确保本条消息归属到目标 persona
                refreshCurrentPersonaFilename()
            }
        }.onFailure { e ->
            Log.w(TAG, "consumePendingSwitch 失败: ${e.message}")
        }
    }

    /** 由 ChatViewModel 在初始化时调用：加载当前 persona 并监听 persona 切换。 */
    fun start() {
        // 首次加载当前 persona filename 并确保 session
        scope.launch(Dispatchers.IO) {
            refreshCurrentPersonaFilename()
            ensureSessionForCurrentPersona()
        }
        // 监听 persona 切换：refresh filename + 切换 session（按 persona 隔离历史）
        scope.launch(Dispatchers.IO) {
            personaRepository.observeActivePersona()
                .distinctUntilChanged()
                .filterNotNull()
                .collect {
                    refreshCurrentPersonaFilename()
                    ensureSessionForCurrentPersona()
                }
        }
    }

    /**
     * 为当前查看的 persona 找到/创建一个 session，让 messages 按 persona 隔离。
     *
     * sessionId = "web_{persona_filename}"，确保每个 persona 的消息存在独立 sessionId 下。
     * 跨平台共享由后端 conversation_id 规范化（shared__persona__{slug}）处理，与 Android
     * 本地 sessionId 是不同维度：Android 端 sessionId 决定本地 DB 隔离，后端 cid 决定
     * 跨平台历史互通。
     */
    suspend fun ensureSessionForCurrentPersona() {
        // 若进入聊天页时已显式指定要看的角色（pendingSwitchFilename），以它为准。
        // 否则全局 active persona（可能还是上一个角色）会把会话冲回上一个角色。
        val filename = pendingSwitchFilename ?: currentPersonaFilename ?: return
        switchLocalSession(filename)
    }

    /**
     * 把本地会话切到指定 persona 对应的 session，实现消息按角色隔离。
     *
     * sessionId = "web_{persona_filename}"，只操作本地 Room + Preferences，不同步后端。
     * 跨平台历史互通由后端 conversation_id 规范化（shared__persona__{slug}）负责，
     * 与本地 sessionId 是两个独立维度。
     *
     * 切换后通过 [onSessionSwitched] 通知外部清空 flushManager，
     * 避免上一个角色未落盘的流式增量串到新会话里。
     */
    suspend fun switchLocalSession(personaFilename: String) {
        if (personaFilename.isBlank()) return
        val targetSessionId = "web_$personaFilename"
        if (appPreferences.currentSessionId == targetSessionId) return
        Log.d(TAG, "切换 session: ${appPreferences.currentSessionId} -> $targetSessionId")
        val session = Session(
            id = targetSessionId,
            title = personaFilename,
            createdAt = System.currentTimeMillis(),
            updatedAt = System.currentTimeMillis(),
            isPinned = false
        )
        runCatching {
            sessionRepository.upsertLocalSession(session)
        }.onFailure { e ->
            Log.w(TAG, "本地 session upsert 失败（继续）: ${e.message}")
        }
        // 先清残留流式缓冲，再改 sessionId，避免旧增量落到新会话。
        onSessionSwitched()
        appPreferences.currentSessionId = targetSessionId
    }

    /** 从后端 active persona 刷新本地 filename 缓存。 */
    suspend fun refreshCurrentPersonaFilename() {
        runCatching {
            // 直接从 Raw JSON 读 filename 字段（PersonaDto 有 filename 但没映射到 Persona 类）
            val raw = personaRepository.getActivePersonaRaw().getOrNull() ?: return@runCatching
            val filename = raw["filename"]?.jsonPrimitive?.content
                ?: raw["data"]?.jsonObject?.get("filename")?.jsonPrimitive?.content
            if (!filename.isNullOrBlank()) {
                currentPersonaFilename = filename
                // 对话真正切人设后（如发消息触发），查看角色跟随保持一致。
                // 但若查看角色已被 setPendingSwitch 显式预置（进聊天即看对应角色，尚未发消息），
                // 不覆盖——否则全局 active（此时还是上一个角色）会把查看角色冲回上一个角色。
                if (_viewingPersonaFilename.value == null) {
                    _viewingPersonaFilename.value = filename
                }
                Log.d(TAG, "当前 active persona filename: $filename (viewing=${_viewingPersonaFilename.value})")
            }
        }.onFailure { e ->
            Log.w(TAG, "获取 active persona filename 失败: ${e.message}")
        }
    }
}
