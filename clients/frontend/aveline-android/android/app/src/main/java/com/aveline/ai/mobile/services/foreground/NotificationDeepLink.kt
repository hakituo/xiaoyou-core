package com.aveline.ai.mobile.services.foreground

import android.net.Uri
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage

/**
 * 通知点击深链与角色 id 解析（从 WebSocketCommandCoordinator 拆出）。
 *
 * 只做「从后端下发的字段推出该跳哪个页面 / 这条通知归属哪个角色」的纯计算，
 * 不持有通知发布状态，便于单测与复用。
 */
internal object NotificationDeepLink {

    /** 聊天主页深链（解析不出具体角色时的兜底）。 */
    const val CHAT_DEEP_LINK = "aveline://chat"

    /** 背单词页深链（学习页的「更多 → 词汇」）。 */
    const val VOCAB_DEEP_LINK = "aveline://study?tab=vocab"

    /**
     * 从 persona filename 反解 role id。
     *
     * 规则与后端 normalize_persona_token 一致：取文件名 → 去扩展名 →
     * 去 `core_` 前缀 → 取首个 token。仪式/自发反应只下发 persona_filename、
     * 没有 conversation_id，靠它补出 role，否则深链切不过去。
     */
    fun roleIdFromPersonaFilename(personaFilename: String?): String? {
        val raw = personaFilename?.trim().orEmpty()
        if (raw.isBlank()) return null
        val name = raw.substringAfterLast('/').substringAfterLast('\\')
        var token = name.substringBeforeLast('.').trim().lowercase()
        if (token.startsWith("core_")) token = token.removePrefix("core_")
        return token.substringBefore("_").substringBefore(".").takeIf { it.isNotBlank() }
    }

    /**
     * 从后端 conversation_id 解析角色 id。
     *
     * 后端会话 id 形如 private_10001__persona__core_aveline，persona 后缀与后端
     * get_qq_target_role_id 的解析规则保持一致（去掉 core_ 前缀后取首个 token）。
     * 解析不出角色时返回 null，由调用方回退到聊天主页深链。
     */
    fun roleIdFromConversationId(conversationId: String?): String? {
        val cid = conversationId?.trim().orEmpty()
        if (cid.isBlank()) return null
        val marker = "__persona__"
        val index = cid.indexOf(marker, ignoreCase = true)
        if (index < 0) return null
        var token = cid.substring(index + marker.length).trim().lowercase()
        if (token.startsWith("core_")) token = token.removePrefix("core_")
        token = token.substringBefore("_").substringBefore(".")
        return token.takeIf { it.isNotBlank() }
    }

    /**
     * 聊天深链：直达消息所属角色的会话，解析不出时进聊天主页。
     *
     * 后端 proactive_message 下发的是 QQ 侧会话 id（形如
     * private_10001__persona__core_aveline），与 Android 本地 sessionId
     * （web_{persona_filename}）不是一个命名空间；NavGraph 的 chat 深链没有
     * ?session_id= 参数，直接传会匹配不到路由。这里改成 role + filename：
     * - role：从 conversation_id 解析（小写 role id）；
     * - filename：直接用后端下发的 persona_filename，让聊天页打开消息真正
     *   所在的那个本地会话 —— 只带 role 时，本地没有该 role 的选择记录就
     *   切不过去，表现为"点了通知但聊天页没有这条消息"。
     */
    fun chatDeepLink(message: WebSocketMessage.ProactiveMessage): String =
        roleChatDeepLink(
            personaFilename = message.personaFilename,
            role = roleIdFromConversationId(message.conversationId)
        )

    /**
     * 角色聊天深链的通用构造：只有 filename 时也从文件名反解 role。
     *
     * 必须带上 role：聊天页只有 role 非空才会调 setPendingSwitch 切会话，
     * 只给 filename 的深链会被整段跳过，表现为"点了通知还在上一个角色"。
     */
    fun roleChatDeepLink(personaFilename: String?, role: String?): String {
        val resolvedRole = role?.trim()?.takeIf { it.isNotEmpty() }
            ?: roleIdFromPersonaFilename(personaFilename)
        val filename = personaFilename?.trim()?.takeIf { it.isNotEmpty() }
        if (resolvedRole.isNullOrBlank() && filename.isNullOrBlank()) return CHAT_DEEP_LINK
        val builder = Uri.Builder().scheme("aveline").authority("chat")
        // 与 NavArgs.ROLE / 深链 filename 同值；
        // 用字面量避免 services 层依赖 presentation 层
        resolvedRole?.let { builder.appendQueryParameter("role", it) }
        filename?.let { builder.appendQueryParameter("filename", it) }
        return builder.build().toString()
    }

    /**
     * 根据 WebSocket 通知内容计算点击跳转深链。
     * 优先使用后端下发的 target(及可选 sessionId); 未下发时按内容启发式:
     * 背单词/单词/词汇/复习/拼写/默写/记忆卡片等学习类 -> aveline://study, 其余 -> aveline://chat。
     */
    fun buildNotificationDeepLink(message: WebSocketMessage.Notification): String {
        return when (val target = message.target) {
            "study" -> "aveline://study"
            // 背单词催背/每日单词：直达背单词页，而不是学习概览页
            // （概览页还要再点两次"更多 → 词汇"才能开始背）
            "vocab" -> VOCAB_DEEP_LINK
            "life" -> "aveline://life"
            "settings" -> "aveline://settings"
            "status" -> "aveline://status"
            "conversations" -> "aveline://conversations"
            "chat" -> if (!message.sessionId.isNullOrBlank())
                Uri.Builder().scheme("aveline").authority("chat")
                    .appendQueryParameter("session_id", message.sessionId)
                    .build().toString()
            else
                "aveline://chat"
            // 后端没下发 target 时的兜底：命中背单词关键词同样直达背单词页
            else -> if (isStudyPush(message.title, message.body))
                VOCAB_DEEP_LINK
            else
                "aveline://chat"
        }
    }

    /** 启发式判断是否为背单词/学习类推送(后端未显式下发 target 时的兜底, 让其跳到背单词页)。 */
    fun isStudyPush(title: String, body: String): Boolean {
        val text = "$title $body"
        return text.contains(Regex("背单词|单词|词汇|复习|拼写|默写|记忆卡片|vocab|flashcard"))
    }
}
