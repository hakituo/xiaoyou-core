package com.aveline.ai.mobile.data.local.preferences

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import java.security.MessageDigest
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 角色级聊天偏好。
 *
 * role 是长期对话边界；persona filename 只是该角色当前使用的人设版本，不能再作为
 * session/model 的持久化键。这个类只保存真正需要按角色隔离的状态：
 * - role -> 当前聊天 sessionId
 * - role -> 用户手动选择的模型 id + 实际请求 route
 *
 * 与 [AppPreferences] 的应用级设置分开，避免再次把角色状态退化成全局状态。
 */
@Singleton
class RoleScopedPreferences @Inject constructor(
    @ApplicationContext context: Context
) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    /** 中英文名称只作别名；注册完成后内部键统一使用后端明确下发的 role_id。 */
    fun canonicalRoleId(role: String): String =
        prefs.getString("role_alias:${roleDigest(role)}", null) ?: role

    fun resolveSessionId(sessionId: String): String =
        prefs.getString("session_redirect:$sessionId", null) ?: sessionId

    fun legacySessionCandidates(roleId: String, aliases: Set<String>, filenames: Set<String>): Set<String> = buildSet {
        add("web_role_$roleId")
        (aliases + roleId).forEach { alias ->
            add(defaultSessionId(alias))
            add("web_role_${roleDigest(alias)}")
        }
        filenames.forEach { filename ->
            add("web_$filename")
        }
        // 已知 web_* 只能来自同角色的人设清单，不能把曾误指向别的角色的键也合进来。
        val verifiedWebSessions = toSet()
        val persisted = (aliases + roleId).mapNotNull { prefs.getString("session:${roleDigest(it)}", null) } +
            filenames.mapNotNull { prefs.getString("persona_session:$it", null) }
        persisted.filter { !it.startsWith("web_") || it in verifiedWebSessions }.forEach { add(it) }
    }

    /** 仅在 Room 迁移成功后发布映射；旧记录仍在，重复执行只会复用已生成的副本。 */
    @Synchronized
    fun completeRoleMigration(roleId: String, aliases: Set<String>, filenames: Set<String>, sources: Set<String>) {
        val target = "web_role_$roleId"
        val editor = prefs.edit()
        (aliases + roleId).forEach { alias ->
            editor.putString("role_alias:${roleDigest(alias)}", roleId)
            editor.putString("session:${roleDigest(alias)}", target)
        }
        filenames.forEach { editor.putString("persona_session:$it", target) }
        sources.filter { it != target }.forEach { editor.putString("session_redirect:$it", target) }
        // 模型选择也沿用旧角色键，已有稳定键的显式选择优先。
        listOf("model", "model_route").forEach { prefix ->
            val targetKey = "$prefix:${roleDigest(roleId)}"
            if (!prefs.contains(targetKey)) {
                aliases.sorted().firstNotNullOfOrNull { prefs.getString("$prefix:${roleDigest(it)}", null) }
                    ?.let { editor.putString(targetKey, it) }
            }
        }
        editor.apply()
    }

    fun getSessionId(role: String, personaFilename: String? = null): String? =
        personaFilename?.takeIf { it.isNotBlank() }
            ?.let { prefs.getString("persona_session:$it", null) }
            ?.takeIf { it.isNotBlank() }
            ?: prefs.getString(sessionKey(role), null)?.takeIf { it.isNotBlank() }

    /**
     * filename 是服务端已有的稳定人设标识。首次沿用角色原映射，随后用它抵御 role 改名。
     * 这里只建立别名，不迁移、删除或拼接消息；历史上已分裂的容器仍保留原样供恢复。
     */
    @Synchronized
    fun getOrBindSessionId(role: String, personaFilename: String?, fallback: String): String {
        val sessionId = getSessionId(role, personaFilename) ?: fallback
        val editor = prefs.edit().putString(sessionKey(role), sessionId)
        personaFilename?.takeIf { it.isNotBlank() }?.let {
            editor.putString("persona_session:$it", sessionId)
        }
        editor.apply()
        return sessionId
    }

    /** 同一角色的新版本继承既有会话；已有别名不在后台被改写。 */
    @Synchronized
    fun bindPersonaSessionIfAbsent(personaFilename: String, sessionId: String) {
        val key = "persona_session:$personaFilename"
        if (!prefs.contains(key)) prefs.edit().putString(key, sessionId).apply()
    }

    fun setSessionId(role: String, sessionId: String) {
        if (role.isBlank() || sessionId.isBlank()) return
        prefs.edit().putString(sessionKey(role), sessionId).apply()
    }

    fun getModelId(role: String): String? =
        prefs.getString(modelIdKey(role), null)?.takeIf { it.isNotBlank() }

    fun getModelRoute(role: String): String? =
        prefs.getString(modelRouteKey(role), null)?.takeIf { it.isNotBlank() }

    fun setModel(role: String, modelId: String, modelRoute: String) {
        if (role.isBlank() || modelId.isBlank() || modelRoute.isBlank()) return
        prefs.edit()
            .putString(modelIdKey(role), modelId)
            .putString(modelRouteKey(role), modelRoute)
            .apply()
    }

    /** 兼容旧调用；新代码应使用 [setModel] 同时保存实际请求 route。 */
    fun setModelId(role: String, modelId: String) {
        if (role.isBlank() || modelId.isBlank()) return
        prefs.edit().putString(modelIdKey(role), modelId).apply()
    }

    fun clearModel(role: String) {
        if (role.isBlank()) return
        prefs.edit()
            .remove(modelIdKey(role))
            .remove(modelRouteKey(role))
            .apply()
    }

    fun clearModelId(role: String) = clearModel(role)

    /**
     * 新角色首次创建本地会话时使用的稳定 ID。
     *
     * 正常升级路径会优先复用该角色当前 persona 的旧 `web_{persona}` session，保住已有
     * Room 历史；只有找不到旧会话线索时才使用这个 role 级 ID。
     *
     * 这个 ID 会被后端当作 conversation_id 反解角色归属来决定记忆目录，所以尽量带
     * 可读的角色标识：后端能识别 `web_role_<角色名>`，但识别不了 `web_role_<哈希>`，
     * 后者只能落到与角色无关的隔离目录（表现为该角色的记忆被分散、后续换设备对不上）。
     */
    fun defaultSessionId(role: String): String = "web_role_${roleSlug(role)}"

    /**
     * 角色标识转成会话 ID 可用的 ASCII slug。
     *
     * 中文等角色名没有安全的 ASCII 写法，退化为稳定哈希，避免把非 ASCII 字符塞进
     * 后端的文件名；这种情况下由后端按 `web_role_<哈希>` 走隔离目录兜底。
     */
    private fun roleSlug(role: String): String {
        val ascii = role.trim().lowercase(Locale.ROOT).mapNotNull { ch ->
            when {
                ch in 'a'..'z' || ch in '0'..'9' -> ch
                ch == '-' || ch == ' ' || ch == '.' || ch == '_' -> '_'
                else -> null
            }
        }.joinToString("").trim('_')
        return ascii.take(40).ifBlank { roleDigest(role) }
    }

    private fun sessionKey(role: String): String = "session:${roleDigest(canonicalRoleId(role))}"
    private fun modelIdKey(role: String): String = "model:${roleDigest(canonicalRoleId(role))}"
    private fun modelRouteKey(role: String): String = "model_route:${roleDigest(canonicalRoleId(role))}"

    private fun roleDigest(role: String): String {
        val normalized = role.trim().lowercase(Locale.ROOT)
        val bytes = MessageDigest.getInstance("SHA-256").digest(normalized.toByteArray(Charsets.UTF_8))
        return bytes.take(8).joinToString("") { "%02x".format(it) }
    }

    private companion object {
        const val PREFS_NAME = "aveline_role_scoped_preferences"
    }
}
