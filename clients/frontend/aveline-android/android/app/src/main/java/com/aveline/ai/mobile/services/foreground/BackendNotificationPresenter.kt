package com.aveline.ai.mobile.services.foreground

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Paint
import android.graphics.Typeface
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.services.AvelineNotificationManager
import com.aveline.ai.mobile.utils.text.TextSegmenter

/** 通知标题兜底（解析不出角色名时才用）。 */
internal const val DEFAULT_NOTIFY_TITLE = "Aveline"

/**
 * 后端推送通知的展示层（从 WebSocketCommandCoordinator 拆出）。
 *
 * 覆盖三类推送：普通通知（背单词/日程/系统提醒）、角色消息（仪式与自发反应）、
 * 角色主动消息（Active Care）。只负责「文案与头像怎么算、通知怎么发」，
 * 消息去重、落库与会话未读由 [ProactiveMessageHandler] 负责。
 */
internal class BackendNotificationPresenter(
    private val notifications: ForegroundNotificationController,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository
) {

    /** 普通后端通知：按 target/关键词决定点击去哪一页。 */
    fun showNotification(message: WebSocketMessage.Notification) {
        val deepLink = NotificationDeepLink.buildNotificationDeepLink(message)
        notifications.showBackendNotification(
            title = message.title.ifEmpty { DEFAULT_NOTIFY_TITLE },
            body = message.body,
            deepLink = deepLink,
            // 背单词类通知登记到 vocab key：用户进背单词页后统一撤掉，
            // 否则从 App 内背完单词，通知栏还挂着那条催背通知。
            cancelKeys = if (deepLink == NotificationDeepLink.VOCAB_DEEP_LINK) {
                listOf(AvelineNotificationManager.KEY_VOCAB)
            } else {
                emptyList()
            }
        )
    }

    /** 仪式事件：同一角色的消息按会话聚合。 */
    fun showRitualEvent(message: WebSocketMessage.RitualEvent) {
        if (message.content.isEmpty()) return
        showRoleMessage(
            roleName = message.roleName,
            content = message.content,
            personaFilename = message.personaFilename
        )
    }

    /** 角色自发反应：与仪式事件同款展示规则。 */
    fun showSpontaneousReaction(message: WebSocketMessage.SpontaneousReaction) {
        if (message.content.isEmpty()) return
        showRoleMessage(
            roleName = message.roleName,
            content = message.content,
            personaFilename = message.personaFilename
        )
    }

    /** 仪式 / 自发反应共用：昵称作标题、正文清洗后展示，进该角色聊天页即视为已读。 */
    private fun showRoleMessage(roleName: String?, content: String, personaFilename: String?) {
        notifications.showBackendNotification(
            title = roleName?.trim()?.takeIf { it.isNotEmpty() }
                ?: DEFAULT_NOTIFY_TITLE,
            body = TextSegmenter.clean(content),
            deepLink = NotificationDeepLink.roleChatDeepLink(personaFilename, null),
            // 进该角色聊天页即视为已读，撤销它的通知
            cancelKeys = cancelKeysFor(personaFilename = personaFilename),
            conversationKey = NotificationDeepLink.roleIdFromPersonaFilename(personaFilename)
                ?: personaFilename
        )
    }

    /** QQ/微信式通知：头像 + 昵称作标题 + 正文在下方。 */
    fun showProactiveNotification(
        title: String,
        message: WebSocketMessage.ProactiveMessage,
        body: String,
        largeIcon: Bitmap?,
        cancelKeys: Collection<String> = emptyList(),
        /** 同一角色的消息叠在同一张通知卡上（QQ 式条数累加），null 表示不聚合。 */
        conversationKey: String? = null
    ) {
        notifications.showBackendNotification(
            title = title,
            body = body,
            deepLink = NotificationDeepLink.chatDeepLink(message),
            largeIcon = largeIcon,
            cancelKeys = cancelKeys,
            conversationKey = conversationKey
        )
    }

    /**
     * 这条通知归属哪些 key（persona filename / role id）。
     *
     * 用户看完该角色的消息后，聊天页会用同一批 key 把通知撤掉；解析不出归属时
     * 返回空集合，这条通知就只能靠用户手动划掉（总比误撤别的角色通知好）。
     */
    fun proactiveCancelKeys(
        message: WebSocketMessage.ProactiveMessage,
        vararg extra: String?
    ): Set<String> = cancelKeysFor(
        personaFilename = message.personaFilename,
        NotificationDeepLink.roleIdFromConversationId(message.conversationId),
        *extra
    )

    /**
     * 这条通知归属哪些 key（persona filename / role id）。
     *
     * 用户看完该角色的消息后，聊天页会用同一批 key 把通知撤掉；解析不出归属时
     * 返回空集合，这条通知就只能靠用户手动划掉（总比误撤别的角色通知好）。
     */
    fun cancelKeysFor(
        personaFilename: String?,
        vararg extra: String?
    ): Set<String> = buildSet {
        addAll(
            listOfNotNull(
                personaFilename,
                NotificationDeepLink.roleIdFromPersonaFilename(personaFilename)
            )
        )
        extra.forEach { addAll(listOfNotNull(it?.trim()?.takeIf { v -> v.isNotEmpty() })) }
    }

    /**
     * 构建通知 largeIcon：本地头像优先（方形居中裁剪），
     * 没有头像时用主题色（Primary 天蓝）画显示名首字，与聊天页首字兜底风格一致。
     * 构建失败返回 null（通知退化为默认样式）。
     */
    suspend fun buildLargeIcon(personaFilename: String, displayName: String): Bitmap? {
        val sizePx = 108
        runCatching {
            personaLocalMetaRepository.resolveAvatarFile(personaFilename)?.let { file ->
                val sampled = decodeSampledBitmap(file, sizePx) ?: return@runCatching null
                val side = minOf(sampled.width, sampled.height)
                val xOff = (sampled.width - side) / 2
                val yOff = (sampled.height - side) / 2
                return Bitmap.createBitmap(sampled, xOff, yOff, side, side)
            }
        }.getOrNull()?.let { return it }

        val initial = displayName.trim().firstOrNull() ?: return null
        return runCatching {
            val bmp = Bitmap.createBitmap(sizePx, sizePx, Bitmap.Config.ARGB_8888)
            bmp.eraseColor(PRIMARY_COLOR)
            val canvas = android.graphics.Canvas(bmp)
            val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = BACKGROUND_COLOR
                textSize = sizePx * 0.42f
                textAlign = Paint.Align.CENTER
                typeface = Typeface.DEFAULT_BOLD
            }
            val centerY = canvas.height / 2f - (paint.descent() + paint.ascent()) / 2f
            canvas.drawText(initial.toString(), canvas.width / 2f, centerY, paint)
            bmp
        }.getOrNull()
    }

    /** 采样解码本地头像，长边不超过 targetSize，避免大图直接解码进内存。 */
    private fun decodeSampledBitmap(file: java.io.File, targetSize: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= targetSize) {
            sample *= 2
        }
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        return BitmapFactory.decodeFile(file.absolutePath, options)
    }

    companion object {
        // 首字兜底头像的配色：与 theme/Color.kt 的 Primary / Background 同值，
        // 通知头像与 App 自身配色保持一致（深色字压在品牌天蓝上）。
        private const val PRIMARY_COLOR = 0xFF0EA5E9.toInt()
        private const val BACKGROUND_COLOR = 0xFF05060A.toInt()
    }
}
