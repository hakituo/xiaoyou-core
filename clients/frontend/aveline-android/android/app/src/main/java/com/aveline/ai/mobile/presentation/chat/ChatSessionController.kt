package com.aveline.ai.mobile.presentation.chat

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.local.preferences.RoleScopedPreferences
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.Session
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import com.aveline.ai.mobile.services.AvelineNotificationManager
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.isActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * 负责聊天页的「角色 / persona / session」状态。
 *
 * 这里必须严格区分三个概念：
 * - role：长期角色身份，是聊天记录和用户模型偏好的隔离边界；
 * - persona：role 当前使用的人设/prompt 版本，可以在同一聊天里热切换；
 * - session：role 对应的本地消息容器，切 persona 时绝不能跟着切。
 *
 * 旧实现把 sessionId 固定成 `web_{persona_filename}`，因此同一角色换个人设文件就会
 * 像换了一个联系人一样换掉聊天记录。现在 role -> sessionId 单独持久化；升级时第一次
 * 进入角色会优先复用当时 persona 的旧 sessionId，从而尽量保留已有 Room 历史。
 *
 * 主干已有的主动消息未读清零语义也保留：进入/停留在当前角色聊天时，当前 persona
 * 的未读计数会清零，即使 role session 本身没有发生切换也一样执行。
 */
class ChatSessionController(
    private val scope: CoroutineScope,
    private val appPreferences: AppPreferences,
    private val roleScopedPreferences: RoleScopedPreferences,
    private val sessionRepository: SessionRepository,
    private val personaRepository: PersonaRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    /** 用于进入角色会话时撤销该角色的通知；单测里可以传 null。 */
    private val notificationManager: AvelineNotificationManager? = null,
    private val onSessionSwitched: () -> Unit
) {
    companion object {
        private const val TAG = "ChatSessionController"

        /**
         * 兼容旧 `web_{persona}` session 的反向解析。
         * 新的 `web_role_*` 不能被误认为 persona filename。
         */
        fun personaFilenameFromSessionId(sessionId: String?): String? {
            val id = sessionId ?: return null
            if (!id.startsWith("web_") || id.startsWith("web_role_")) return null
            return id.removePrefix("web_").takeIf { it.isNotBlank() }
        }
    }

    /** 后端当前 active persona 的本地缓存。 */
    @Volatile
    var currentPersonaFilename: String? = null
        private set

    /** 当前聊天所属 role。role 才是长期会话边界。 */
    @Volatile
    var currentRole: String? = null
        private set

    private val _conversationRole = MutableStateFlow<String?>(null)
    val conversationRole: StateFlow<String?> = _conversationRole.asStateFlow()

    /** 请求必须显式携带当前聊天 persona，不能让后端全局 active 覆盖正在聊天的角色。 */
    val conversationPersonaFilename: String?
        get() = pendingSwitchFilename ?: currentPersonaFilename

    val conversationSessionId: String?
        get() = currentRole?.let {
            roleScopedPreferences.getSessionId(it, conversationPersonaFilename)
        } ?: appPreferences.currentSessionId

    /** session -> persona 的运行时归属，用于列表预览；同一 role 换 persona 时只更新值，不换 session。 */
    private val sessionPersonaOwners = ConcurrentHashMap<String, String>()

    fun personaFilenameForSession(sessionId: String?): String? {
        if (sessionId.isNullOrBlank()) return null
        return sessionPersonaOwners[sessionId] ?: personaFilenameFromSessionId(sessionId)
    }

    /**
     * 后端确认 persona 切换成功后的本地提交。
     *
     * 重点：这里只换 persona，不换 role session。历史仍留在原聊天里。
     */
    suspend fun confirmPersonaSelection(filename: String) {
        if (filename.isBlank()) return
        val role = pendingSwitchRole ?: currentRole ?: roleForPersona(filename)
        if (!role.isNullOrBlank()) {
            pendingSwitchRole = role
            currentRole = role
            _conversationRole.value = role
            appPreferences.setSelectedPersona(role, filename)
        }
        pendingSwitchFilename = filename
        pendingSwitchConsumed = true
        currentPersonaFilename = filename
        _viewingPersonaFilename.value = filename

        if (!role.isNullOrBlank()) {
            ensureRoleSession(role, filename)
        } else {
            // 没有 role 信息的旧深链/异常入口保持兼容，不凭空合并未知角色。
            switchLegacyPersonaSession(filename)
        }
        appPreferences.currentSessionId?.let { sessionPersonaOwners[it] = filename }

        ensurePersonaDefaults(filename)
        applyPersonaDefaultModel(filename)
    }

    /** persona filename -> 后端默认模型路由。 */
    private val personaDefaultModels = ConcurrentHashMap<String, String>()

    /** persona filename -> 后端默认音色名。 */
    private val personaDefaultVoices = ConcurrentHashMap<String, String>()

    /** persona filename -> role；来自 persona API，不在客户端硬编码角色表。 */
    private val personaRoles = ConcurrentHashMap<String, String>()

    fun currentPersonaDefaultVoice(): String? =
        conversationPersonaFilename
            ?.let { personaDefaultVoices[it] }
            ?.takeIf { it.isNotBlank() }

    fun currentPersonaVoiceOverride(): String? =
        conversationPersonaFilename?.let { appPreferences.getPersonaVoice(it) }

    private fun applyPersonaDefaultModel(filename: String) {
        val hint = personaDefaultModels[filename] ?: return
        if (appPreferences.personaDefaultModelRoute == hint) return
        appPreferences.personaDefaultModelRoute = hint
        Log.d(TAG, "persona 默认模型: $filename -> ${hint.ifBlank { "(未配置，交后端兜底)" }}")
    }

    private fun cachePersonaDefaults(personas: JsonArray) {
        personas.forEach { element ->
            val obj = runCatching { element.jsonObject }.getOrNull() ?: return@forEach
            val filename = obj["filename"]?.jsonPrimitive?.contentOrNull ?: return@forEach
            val defaultModel = obj["default_model"]?.jsonPrimitive?.contentOrNull.orEmpty()
            if (defaultModel.isNotBlank()) {
                personaDefaultModels[filename] = defaultModel
            } else {
                personaDefaultModels.putIfAbsent(filename, "")
            }
            personaDefaultVoices[filename] =
                obj["default_voice"]?.jsonPrimitive?.contentOrNull.orEmpty()

            val explicitRole = obj["role"]?.jsonPrimitive?.contentOrNull.orEmpty().trim()
            val name = obj["name"]?.jsonPrimitive?.contentOrNull.orEmpty()
            val derivedRole = explicitRole.ifBlank {
                name.split("(")[0].split("（")[0].trim().ifEmpty { name }
            }
            if (derivedRole.isNotBlank()) personaRoles[filename] = derivedRole
        }
    }

    /**
     * 补齐 persona 默认值（默认模型 / 默认音色 / persona -> role）。
     *
     * 走仓库的**进程级缓存**版本：本类的 `personaDefaultModels` / `personaRoles` 是
     * 每个 ChatViewModel 一份，重进聊天页就会清空，只用它们做判据的话「进角色后第一次
     * 发送」必然要重新等一次 `GET /api/v1/personas`（发送路径上最不该出现的网络等待）。
     * 缓存版本首次之后直接命中内存，发送不再被它拖住。
     */
    private suspend fun ensurePersonaDefaults(filename: String) {
        if (filename.isBlank()) return
        if (personaDefaultModels.containsKey(filename) && personaRoles.containsKey(filename)) return
        val personas = runCatching { personaRepository.getPersonasRawCached().getOrThrow() }
            .onFailure { e -> Log.w(TAG, "拉取 persona 默认配置失败: ${e.message}") }
            .getOrNull() ?: return
        cachePersonaDefaults(personas)
    }

    private fun roleForPersona(filename: String): String? =
        personaRoles[filename]?.takeIf { it.isNotBlank() }

    /**
     * 把外部入口带来的 role 归一化成 persona API 使用的角色键。
     *
     * Active Care 的 conversation_id 使用稳定 role id（如 ling / ye），而 Android
     * 会话列表按 persona API 的 role（如 Ling / Ye）分组。通知深链同时带着准确的
     * persona filename，因此以 filename 为权威源反查 role，避免客户端维护角色映射表。
     */
    private suspend fun resolveRoleForPersona(role: String, filename: String?): String {
        val target = filename?.trim()?.takeIf { it.isNotEmpty() } ?: return role
        ensurePersonaDefaults(target)
        return roleForPersona(target) ?: role
    }

    /** 伴侣详情面板正在查看的 persona；仅展示，不等于 session 边界。 */
    private val _viewingPersonaFilename = MutableStateFlow<String?>(null)
    val viewingPersonaFilename: StateFlow<String?> = _viewingPersonaFilename.asStateFlow()

    fun setViewingPersona(filename: String) {
        if (filename.isBlank()) return
        _viewingPersonaFilename.value = filename
        Log.d(TAG, "setViewingPersona(只读): $filename")
    }

    /**
     * 从会话列表或通知深链进入某个 role。
     *
     * 本地 role session 立即切换，因此只查看历史也不会串到上一个角色；后端 persona 仍延迟到
     * 首次发消息再切，避免仅浏览聊天时制造额外 API 请求。通知/列表显式携带的 filename
     * 比本地旧选择更准确，因此优先使用 preferredFilename。
     */
    fun setPendingSwitch(role: String, preferredFilename: String? = null) {
        if (role.isBlank()) return
        pendingSwitchRole = role
        currentRole = role
        _conversationRole.value = role
        pendingSwitchFilename = preferredFilename?.takeIf { it.isNotBlank() }
            ?: appPreferences.getSelectedPersona(role)
        pendingSwitchConsumed = false
        pendingSwitchFilename?.let { _viewingPersonaFilename.value = it }
        Log.d(
            TAG,
            "setPendingSwitch: role=$role persona=$pendingSwitchFilename（session 按 role，后端 persona 延迟切换）"
        )

        scope.launch(Dispatchers.IO) {
            val target = pendingSwitchFilename
            val resolvedRole = resolveRoleForPersona(role, target)
            // 旧任务不能在用户已经切到另一个 role 后反向覆盖当前 session。
            if (pendingSwitchRole != role) return@launch
            if (resolvedRole != role) {
                pendingSwitchRole = resolvedRole
                currentRole = resolvedRole
                _conversationRole.value = resolvedRole
                Log.d(TAG, "深链 role 归一化: $role -> $resolvedRole (persona=$target)")
            }
            ensureRoleSession(resolvedRole, target)
            target?.let {
                ensurePersonaDefaults(it)
                applyPersonaDefaultModel(it)
                appPreferences.currentSessionId?.let { sid -> sessionPersonaOwners[sid] = it }
            }
        }
    }

    @Volatile
    private var pendingSwitchRole: String? = null
    @Volatile
    private var pendingSwitchFilename: String? = null
    @Volatile
    private var pendingSwitchConsumed = false

    /** 首次发消息时真正切换后端 persona；本地 session 始终保持在当前 role。 */
    suspend fun consumePendingSwitchIfNeeded() {
        if (pendingSwitchConsumed) return
        var role = pendingSwitchRole
        if (role.isNullOrBlank()) return

        val currentFilename = currentPersonaFilename
        val target = pendingSwitchFilename

        // setPendingSwitch 的 IO 归一化可能还没跑完，用户就已经点了发送。
        // 发送路径必须再同步兜底一次，确保不会拿 ling/ye 这类 scope id 去匹配
        // persona API 返回的 Ling/Ye role，从而误报“没有可用人设”。
        val resolvedRole = resolveRoleForPersona(role, target)
        if (resolvedRole != role) {
            if (pendingSwitchRole == role) {
                pendingSwitchRole = resolvedRole
                currentRole = resolvedRole
                _conversationRole.value = resolvedRole
            }
            role = resolvedRole
            Log.d(TAG, "发送前 role 归一化: $role (persona=$target)")
        }

        if (target != null && currentFilename == target) {
            Log.d(TAG, "consumePendingSwitch: 当前 persona 已是目标，跳过后端 switch")
            ensureRoleSession(role, target)
            pendingSwitchConsumed = true
            ensurePersonaDefaults(target)
            applyPersonaDefaultModel(target)
            return
        }

        runCatching {
            val personas = personaRepository.getPersonasRawCached().getOrThrow()
            cachePersonaDefaults(personas)
            val rolePersonas = personas.mapNotNull { p ->
                runCatching { p.jsonObject }.getOrNull()
            }.filter { obj ->
                val filename = obj["filename"]?.jsonPrimitive?.contentOrNull.orEmpty()
                val mappedRole = personaRoles[filename]
                mappedRole?.equals(role, ignoreCase = true) == true
            }
            if (rolePersonas.isEmpty()) error("角色 $role 没有可用人设")

            val targetFilename = if (target != null) {
                target.takeIf { t ->
                    rolePersonas.any { obj -> obj["filename"]?.jsonPrimitive?.contentOrNull == t }
                } ?: rolePersonas.firstOrNull()?.get("filename")?.jsonPrimitive?.contentOrNull
            } else {
                rolePersonas.firstOrNull()?.get("filename")?.jsonPrimitive?.contentOrNull
            }

            check(!targetFilename.isNullOrBlank()) { "没有可用人设" }
            if (currentFilename != targetFilename) {
                Log.d(TAG, "consumePendingSwitch: 发消息触发切换 role=$role persona=$targetFilename")
                personaRepository.selectPersona(targetFilename).getOrThrow()
            }
            confirmPersonaSelection(targetFilename)
        }.onFailure { e ->
            Log.w(TAG, "consumePendingSwitch 失败: ${e.message}")
        }.getOrThrow()
    }

    /** 初始化 active persona；active persona 改变时只刷新 persona，不再把它当成换会话事件。 */
    fun start() {
        scope.launch(Dispatchers.IO) {
            refreshCurrentPersonaFilename()
            if (currentRole == null) ensureSessionForCurrentPersona()
        }
        scope.launch(Dispatchers.IO) {
            personaRepository.observeActivePersona()
                .distinctUntilChanged()
                .filterNotNull()
                .collect {
                    refreshCurrentPersonaFilename()
                    // 全局 active 通知只刷新配置。返回栈里的旧聊天页仍可能存活，
                    // 不能让它在另一角色切人设时重新抢占全局 currentSessionId。
                }
        }
    }

    /**
     * 确保当前聊天拥有 session。
     * 有 role 时只认 role->session；只有完全不知道 role 的兼容入口才退回旧 persona session。
     */
    suspend fun ensureSessionForCurrentPersona() {
        val role = pendingSwitchRole ?: currentRole
        val filename = pendingSwitchFilename ?: currentPersonaFilename
        if (!role.isNullOrBlank()) {
            ensureRoleSession(role, filename)
        } else if (!filename.isNullOrBlank()) {
            switchLegacyPersonaSession(filename)
        }
    }

    /**
     * 获取/创建 role 的唯一 session。
     *
     * 升级迁移策略：role 首次出现且还没有映射时，若知道当前 persona，则直接采用旧的
     * `web_{persona}` 作为该 role 的固定 session，这样不会把用户当前已有聊天记录丢在旧键下。
     * 从这一刻起即使 persona 再变，role 的 sessionId 也不会再变。
     */
    private suspend fun ensureRoleSession(role: String, personaFilename: String?) {
        if (role.isBlank()) return
        if (currentRole != role) return
        // 调用方没给 persona 时，先用已缓存的 role->persona 映射补一个。
        // 会话 ID 必须带上人设名，后端才能反解出角色去定位记忆目录；退化成
        // `web_role_<哈希>` 后端无法反解，只能把记忆放到与角色无关的隔离目录。
        val filename = personaFilename?.takeIf { it.isNotBlank() }
            ?: personaFilenameForRole(role)
        // 先补一次 persona  Defaults，让 personaRoles 里有该角色名下的人设清单，
        // 清未读才能覆盖到同角色的其他 persona（已缓存时直接返回，不额外发请求）。
        if (!filename.isNullOrBlank()) ensurePersonaDefaults(filename)
        if (currentRole != role) return
        clearUnreadForRole(role, filename)
        if (currentRole != role) return
        val targetSessionId = roleScopedPreferences.getOrBindSessionId(
            role, filename, filename?.let { "web_$it" } ?: roleScopedPreferences.defaultSessionId(role)
        )
        personaRoles.filterValues { it.equals(role, ignoreCase = true) }.keys.forEach {
            roleScopedPreferences.bindPersonaSessionIfAbsent(it, targetSessionId)
        }
        if (!filename.isNullOrBlank()) sessionPersonaOwners[targetSessionId] = filename
        switchLocalSessionId(targetSessionId, role, role)
    }

    /** role -> 该角色名下任意一个 persona filename；还没拉到 persona 列表时返回 null。 */
    private fun personaFilenameForRole(role: String): String? =
        personaRoles.entries.firstOrNull { it.value.equals(role, ignoreCase = true) }?.key

    /**
     * 清零"当前正显示在屏幕上的这个聊天"的未读。
     *
     * 给聊天页每次重新可见（首次进入 / 从后台切回 / 点通知复用已有页面）时调用。
     * 只在 [setPendingSwitch] 建页时清一次是不够的：点通知时聊天页往往已经在栈顶，
     * MainActivity 用 RoleReplyNotifier.isChatVisibleFor 判定后会把深链直接吞掉
     * （避免叠第二个聊天页），于是不会创建新的 ChatViewModel，
     * [ensureRoleSession] 里那条清零路径根本不会执行 ——
     * 表现为"通知点进去消息也看到了，退出聊天后会话列表徽章还在，要再点几次才消"。
     *
     * 与 [clearUnreadForRole] 一样按角色整体清零，并顺带撤掉该角色的通知。
     */
    suspend fun clearUnreadForCurrentChat() {
        val role = currentRole
        val filename = conversationPersonaFilename
        if (role.isNullOrBlank() && filename.isNullOrBlank()) return
        if (!filename.isNullOrBlank()) ensurePersonaDefaults(filename)
        clearUnreadForRole(role, filename)
    }

    /** 未知 role 的兼容路径。正常会话列表入口不会再走这里。 */
    suspend fun switchLocalSession(personaFilename: String) {
        val role = currentRole
        if (!role.isNullOrBlank()) {
            ensureRoleSession(role, personaFilename)
        } else {
            switchLegacyPersonaSession(personaFilename)
        }
    }

    private suspend fun switchLegacyPersonaSession(personaFilename: String) {
        if (personaFilename.isBlank()) return
        clearUnreadForRole(currentRole, personaFilename)
        val sessionId = "web_$personaFilename"
        sessionPersonaOwners[sessionId] = personaFilename
        switchLocalSessionId(sessionId, personaFilename, null)
    }

    /**
     * 清零未读：**按角色整体清零**，而不是只清当前打开的那一个 persona。
     *
     * 会话列表的徽章是"该角色下所有 persona 的 unreadCount 之和"。主动消息由后端
     * 指定落到哪个 persona，可能不是用户当前打开的那一个；此时只清当前 persona
     * （且它的未读本来就是 0，会被 clearUnread 的 early-return 直接跳过）就会留下
     * 一个"点进去没看到新消息、返回后徽章还在"的顽固未读。
     *
     * @param role 当前角色；为空时退化为只清 [personaFilename]
     * @param personaFilename 当前打开的 persona（一定会被清）
     */
    private suspend fun clearUnreadForRole(role: String?, personaFilename: String?) {
        val filenames = buildSet {
            personaFilename?.takeIf { it.isNotBlank() }?.let { add(it) }
            val targetRole = role?.takeIf { it.isNotBlank() } ?: return@buildSet
            personaRoles.forEach { (filename, mappedRole) ->
                if (mappedRole.equals(targetRole, ignoreCase = true)) add(filename)
            }
        }
        if (filenames.isEmpty()) return
        runCatching { personaLocalMetaRepository.clearUnreadFor(filenames) }
            .onFailure { Log.w(TAG, "清未读失败: ${it.message}") }
        // 消息都看到了，通知栏里这个角色的横幅也该撤掉。
        // 之前只清未读不动通知，用户从 App 内（而不是点通知）看完消息后，
        // 通知会一直挂在状态栏上不会消失。
        val canceled = notificationManager?.cancelNotifications(
            filenames + listOfNotNull(role?.takeIf { it.isNotBlank() })
        ) ?: 0
        if (canceled > 0) Log.d(TAG, "进入 $role 聊天页，撤销该角色通知 $canceled 条")
    }

    private suspend fun switchLocalSessionId(targetSessionId: String, title: String, expectedRole: String?) {
        if (targetSessionId.isBlank()) return
        if (appPreferences.currentSessionId == targetSessionId) return
        Log.d(TAG, "切换 role session: ${appPreferences.currentSessionId} -> $targetSessionId")
        val session = Session(
            id = targetSessionId,
            title = title,
            createdAt = System.currentTimeMillis(),
            updatedAt = System.currentTimeMillis(),
            isPinned = false
        )
        runCatching {
            sessionRepository.upsertLocalSession(session)
        }.onFailure { e ->
            Log.w(TAG, "本地 session upsert 失败（继续）: ${e.message}")
        }

        // IO 期间可能已经切到另一个 role；旧协程不得覆盖新角色。
        // 比较调用开始时的角色，而不是 IO 完成后才取角色；页面销毁后的后台请求也不能换页。
        if (!scope.isActive || currentRole != expectedRole) return
        onSessionSwitched()
        appPreferences.currentSessionId = targetSessionId
    }

    /** 从后端 active persona 刷新本地缓存；不再因为 filename 改变而切 session。 */
    suspend fun refreshCurrentPersonaFilename() {
        runCatching {
            val raw = personaRepository.getActivePersonaRaw().getOrNull() ?: return@runCatching
            val filename = raw["filename"]?.jsonPrimitive?.content
                ?: raw["data"]?.jsonObject?.get("filename")?.jsonPrimitive?.content

            if (!filename.isNullOrBlank()) {
                raw["default_model"]?.jsonPrimitive?.contentOrNull?.let {
                    personaDefaultModels[filename] = it
                }
                raw["default_voice"]?.jsonPrimitive?.contentOrNull?.let {
                    personaDefaultVoices[filename] = it
                }
                currentPersonaFilename = filename

                if (_viewingPersonaFilename.value == null) {
                    _viewingPersonaFilename.value = filename
                }
                appPreferences.currentSessionId?.let { sessionPersonaOwners[it] = filename }
                Log.d(
                    TAG,
                    "当前 active persona: $filename role=${currentRole ?: "(unknown)"} session=${appPreferences.currentSessionId}"
                )
                if (pendingSwitchFilename == null) applyPersonaDefaultModel(filename)
            }
        }.onFailure { e ->
            Log.w(TAG, "获取 active persona filename 失败: ${e.message}")
        }
    }
}
