package com.aveline.ai.mobile.services.foreground

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.local.preferences.RoleScopedPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.presentation.chat.ChatPreviewBuilder
import com.aveline.ai.mobile.utils.AppForegroundTracker
import com.aveline.ai.mobile.utils.text.TextSegmenter
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * 角色主动消息（Active Care / 自发开口）的归档与提醒（从 WebSocketCommandCoordinator 拆出）。
 *
 * 除了弹通知，还必须把消息写进对应角色的本地会话：聊天页的消息列表来自
 * Room Flow 回流，只要落库就会自动上屏。此前只弹通知不落库，用户看到的是
 * "有通知、聊天界面里却没有这条消息"。归档的同时给该角色未读数 +1。
 *
 * 去重（重放过滤）与双角色剧本过滤留在 [WebSocketCommandCoordinator] 里做，
 * 本类只在「确认要处理这条消息」之后接手。
 */
internal class ProactiveMessageHandler(
    private val scope: CoroutineScope,
    private val preferences: AppPreferences,
    private val presenter: BackendNotificationPresenter,
    private val chatRepository: ChatRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val roleScopedPreferences: RoleScopedPreferences?,
    /** 判断"某个角色的聊天页是否正显示在屏幕上"；常驻服务外的调用方可传 null。 */
    private val replyNotifier: RoleReplyNotifier?
) {
    /** 一次主动消息的归属角色解析结果。 */
    private data class ProactiveTarget(
        val personaFilename: String,
        /** 后端下发的角色中文名（如"Aveline"），可能为 null */
        val roleName: String?,
        /** 从 conversation_id 解析出的 role id（如 aveline），可能为 null */
        val role: String?
    )

    /**
     * 处理一条已通过去重与剧本过滤的角色主动消息。
     *
     * @param body 与聊天页同一套规则清洗后的正文（剥时间戳 + 去句末句号）
     * @param messageId 后端下发的消息 id（空串表示后端未提供）
     */
    fun handle(
        message: WebSocketMessage.ProactiveMessage,
        body: String,
        messageId: String
    ) {
        // 通知标题/头像、归档目标都要查本地 meta，统一放到 IO 协程；
        // 查不到归属角色时只保留默认提醒，绝不写进错误角色的会话。
        scope.launch(Dispatchers.IO) {
            val target = resolveProactiveTarget(message)
            if (target == null) {
                Log.w(
                    TAG,
                    "主动消息无法确定归属角色，仅提醒不归档 (cid=${message.conversationId})"
                )
                presenter.showProactiveNotification(
                    title = message.roleName?.trim()?.takeIf { it.isNotEmpty() }
                        ?: DEFAULT_NOTIFY_TITLE,
                    message = message,
                    body = body,
                    largeIcon = null,
                    cancelKeys = presenter.proactiveCancelKeys(message),
                    conversationKey = NotificationDeepLink
                        .roleIdFromConversationId(message.conversationId)
                        ?: NotificationDeepLink.roleIdFromPersonaFilename(message.personaFilename)
                        ?: message.personaFilename
                )
                return@launch
            }

            // 显示名优先级与会话列表一致：本地自定义昵称 > 角色中文名 > role id
            val displayName = personaLocalMetaRepository.getMetaOnce(target.personaFilename)
                ?.customName?.takeIf { it.isNotBlank() }
                ?: target.roleName
                ?: target.role
                ?: DEFAULT_NOTIFY_TITLE

            // 前台且正看着这个角色的聊天页时，消息会随 Room Flow 直接上屏，
            // 再 +1 未读就会留下"消息就在眼前、列表徽章却怎么点都消不掉"的顽固红点。
            // 判据与下面"要不要弹通知"同源：后台或停在别的页面才计数。
            val seenOnScreen = AppForegroundTracker.isForeground &&
                replyNotifier?.isChatVisibleFor(target.role, target.personaFilename) == true
            archiveProactiveMessage(
                personaFilename = target.personaFilename,
                role = target.role,
                body = body,
                messageId = messageId,
                countUnread = !seenOnScreen
            )

            // 聊天页在前台时消息已随 Room Flow 回流直接上屏，再弹横幅属于重复打扰；
            // 退到后台（或停在别的页面）才需要通知把人叫回来。
            if (!AppForegroundTracker.isForeground) {
                presenter.showProactiveNotification(
                    title = displayName,
                    message = message,
                    body = body,
                    largeIcon = presenter.buildLargeIcon(target.personaFilename, displayName),
                    cancelKeys = presenter.proactiveCancelKeys(
                        message,
                        target.personaFilename,
                        target.role
                    ),
                    conversationKey = target.role?.trim()?.takeIf { it.isNotEmpty() }
                        ?: NotificationDeepLink.roleIdFromPersonaFilename(target.personaFilename)
                        ?: target.personaFilename
                )
            }
        }
    }

    /**
     * 解析主动消息属于哪个角色。
     *
     * 优先用后端随 payload 下发的 persona_filename（最准，见
     * core/services/active_care/core/message_dispatcher.py 的 extra_payload）；
     * 老版本后端不带该字段时，回退用 conversation_id 解析 role 再查本地已选人设。
     * 两边都拿不到就返回 null。
     */
    private suspend fun resolveProactiveTarget(
        message: WebSocketMessage.ProactiveMessage
    ): ProactiveTarget? {
        val role = NotificationDeepLink.roleIdFromConversationId(message.conversationId)
        message.personaFilename?.trim()?.takeIf { it.isNotEmpty() }?.let { filename ->
            return ProactiveTarget(
                personaFilename = filename,
                roleName = message.roleName?.trim()?.takeIf { it.isNotEmpty() },
                role = role
            )
        }
        val saved = role?.let { preferences.getSelectedPersona(it) }
            ?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        return ProactiveTarget(
            personaFilename = saved,
            roleName = message.roleName?.trim()?.takeIf { it.isNotEmpty() },
            role = role
        )
    }

    /**
     * 主动消息要落进的会话 id。
     *
     * 必须与聊天页显示的是**同一个**会话。聊天页按 role 取 session
     * （[RoleScopedPreferences.getSessionId]），只有在 role 尚未建立映射时
     * 才沿用旧的 `web_{persona}`。这里若直接写 `web_{persona}`，而聊天页
     * 显示的是 role session，消息就会落到用户永远看不到的会话里 ——
     * 表现为"会话列表有未读、点进去却什么新消息都没有"。
     */
    private fun resolveProactiveSessionId(role: String?, personaFilename: String): String {
        if (!role.isNullOrBlank()) {
            roleScopedPreferences?.getSessionId(role, personaFilename)?.let { return it }
        }
        return "web_$personaFilename"
    }

    /**
     * 把角色主动消息写进该角色的本地会话并同步会话列表预览与未读数。
     *
     * 落库放在常驻的 Service 侧而非 ChatViewModel —— WebSocketManager.messages
     * 是无 replay 的 SharedFlow，ChatViewModel 不存活时（用户在别的页面、进程在
     * 后台）消息不会补发，只有常驻组件才能保证归档不丢。
     */
    private suspend fun archiveProactiveMessage(
        personaFilename: String,
        role: String?,
        body: String,
        messageId: String,
        /** false 表示这条消息用户已经当场看到（聊天页正显示该角色），不再计未读。 */
        countUnread: Boolean = true
    ) {
        val sessionId = resolveProactiveSessionId(role, personaFilename)
        val timestamp = System.currentTimeMillis()
        // 一次主动推送可能包含多句话：按 QQ 同一套断句规则逐句成泡
        // （splitForDisplay 内含清洗），id 命名与流式气泡一致（首条用 messageId）
        val segments = TextSegmenter.splitForDisplay(body).ifEmpty { listOf(body) }
        val baseId = messageId.ifEmpty { "proactive_${UUID.randomUUID()}" }
        runCatching {
            segments.forEachIndexed { index, segment ->
                chatRepository.insertMessage(
                    Message(
                        id = if (index == 0) baseId else "$baseId-$index",
                        text = segment,
                        isUser = false,
                        timestamp = timestamp,
                        messageType = "text",
                        sessionId = sessionId
                    )
                )
            }
            personaLocalMetaRepository.updateLastMessage(
                personaFilename = personaFilename,
                preview = ChatPreviewBuilder.buildPreviewText(
                    text = segments.first(),
                    isUser = false,
                    messageType = "text"
                ),
                timestamp = timestamp
            )
            if (countUnread) personaLocalMetaRepository.incrementUnread(personaFilename)
        }.onFailure { e ->
            Log.e(TAG, "归档主动消息失败: ${e.message}", e)
        }
    }

    companion object {
        /** 与 [WebSocketCommandCoordinator] 保持同一个日志 TAG，便于按服务名过滤日志。 */
        private const val TAG = "AvelineForegroundServiceV2"
    }
}
