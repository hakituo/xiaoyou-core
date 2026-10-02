package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.presentation.persona.PersonaUiState
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * 顶栏要用的 persona 展示信息。
 *
 * 替代原先的 Triple：`.first/.second/.third` 在调用处完全看不出含义，
 * 改成具名字段后无需再回来看实现。
 */
data class ActivePersonaInfo(
    /** 展示名（昵称 > 角色名）。 */
    val displayName: String,
    /** 后端下发的头像地址。 */
    val avatarUrl: String?,
    /** 本地自定义头像文件名。 */
    val localAvatarPath: String?
)

/** persona 接口还没回来时的兜底标题。 */
const val FALLBACK_CHAT_TITLE = "聊天"

/**
 * 解析顶栏要展示的 persona 信息。
 *
 * 展示名优先级：**导航传入的 [initialDisplayName] > persona 接口返回的 name > "聊天"**。
 * 会话列表算好的 displayName（自定义昵称 > 角色名）与列表完全一致，
 * 优先用它既能让首帧就有正确标题，也避免接口返回后标题跳成带括号后缀的原始名
 * （例如列表显示"Ling"、接口 name 是"Ling (QQ)"）。
 *
 * @param viewingFilename 正在查看的 persona（进哪个角色的聊天就显示哪个，纯展示，不切后端人设）
 * @param initialDisplayName 导航直接传入的展示名，首帧用它避免闪一下"聊天"
 */
fun resolveActivePersonaInfo(
    personaUiState: PersonaUiState,
    localAvatarMap: Map<String, String>,
    viewingFilename: String? = null,
    initialDisplayName: String? = null
): ActivePersonaInfo {
    val enteredName = initialDisplayName?.takeIf { it.isNotBlank() }
    val activeFilename = viewingFilename ?: personaUiState.activeFilename
    // persona 接口还没回来时不能显示"聊天"兜底文案：导航已把正确的展示名带进来了。
    if (activeFilename.isBlank()) return ActivePersonaInfo(enteredName ?: FALLBACK_CHAT_TITLE, null, null)

    // 从 personas 列表找当前 persona 的 name / avatar_url
    val personaObj = personaUiState.personas.firstOrNull { element ->
        runCatching {
            element.jsonObject["filename"]?.jsonPrimitive?.contentOrNull == activeFilename
        }.getOrDefault(false)
    }?.jsonObject

    val backendName = personaObj?.get("name")?.jsonPrimitive?.contentOrNull
        ?.takeIf { it.isNotBlank() }
    return ActivePersonaInfo(
        displayName = enteredName ?: backendName ?: FALLBACK_CHAT_TITLE,
        avatarUrl = personaObj?.get("avatar_url")?.jsonPrimitive?.contentOrNull,
        localAvatarPath = localAvatarMap[activeFilename]
    )
}

/** 取当前 persona 的角色名（role），用于编辑资料弹窗。 */
fun resolvePersonaRole(personaUiState: PersonaUiState, filename: String): String {
    return runCatching {
        personaUiState.personas.firstOrNull { el ->
            el.jsonObject["filename"]?.jsonPrimitive?.contentOrNull == filename
        }?.jsonObject?.get("role")?.jsonPrimitive?.contentOrNull
    }.getOrNull().orEmpty()
}
