package com.aveline.ai.mobile.services.foreground

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Paint
import android.graphics.Typeface
import android.net.Uri
import android.util.Log
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 角色回复的后台通知发布器（QQ/微信式：头像 + 昵称作标题 + 正文在下）。
 *
 * 为什么需要它：客户端有**两条完全独立的回复通道**，此前只有一条接了通知。
 * - 主动关怀 / 仪式 / 自发反应：后端经 WebSocket 广播，由 [WebSocketCommandCoordinator]
 *   处理并弹通知 —— 这条一直是好的。
 * - 用户主动发消息后的回复：走 HTTP SSE（`ChatSendController.runAssistantGeneration`），
 *   整条链路**没有任何发通知的代码**；而且 HTTP SSE 进行中，
 *   `ChatFlushManager` 会把 WebSocket 的 chunk/done/reset 全部抑制掉
 *   （防双通道重复上屏），于是 WebSocket 侧原本能弹通知的分支也被关掉了。
 *   表现为：发完消息切到别的 App，AI 回完了却什么提示都没有。
 *
 * 后端确认（`core/interfaces/websocket/adapters/streaming.py`）HTTP SSE 请求期间
 * **不会**向 WebSocket 广播任何回复事件，所以只能由客户端在 SSE 收尾时自己发通知。
 *
 * 两条通道共用这一个实现，确保通知样式、深链规则、头像兜底逻辑完全一致；
 * 调用方负责判定"是否需要弹"（前台不弹）。
 */
@Singleton
class RoleReplyNotifier @Inject constructor(
    @ApplicationContext context: android.content.Context,
    private val notificationManager: com.aveline.ai.mobile.services.AvelineNotificationManager,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository
) {

    /**
     * 通知发布必须复用 [ForegroundNotificationController] 里那份自增通知 ID 与归属登记，
     * 否则前台服务与聊天页会各自维护一套 key → id 映射，聊天页撤销通知时撤不掉这里发的。
     * 控制器本身不是 Hilt 单例（原本只在前台服务内部 new），所以这里按 ApplicationContext
     * 惰性缓存一份，保证全局唯一。
     */
    private val notifications: ForegroundNotificationController by lazy {
        ForegroundNotificationControllerHolder.get(context, notificationManager)
    }

    /**
     * 当前正显示在聊天页上的角色 / 人设。
     *
     * 由聊天页在进入、切换、退出时更新（见 [markChatVisible] / [clearChatVisible]）。
     * 两个用途：
     * 1. **点通知不套娃**：若用户已经在和该角色聊天，点通知只需把 App 拉到前台，
     *    不能再 navigate 压一个新的聊天页（QQ/微信的行为）。
     * 2. **切回 App 自动清通知**：用户切回前台时若正停在该角色的聊天页，
     *    说明消息已经看到了，通知栏里它的横幅应当撤掉。
     */
    private val visibleChatRole = java.util.concurrent.atomic.AtomicReference<String?>(null)
    private val visibleChatFilename = java.util.concurrent.atomic.AtomicReference<String?>(null)

    /** 聊天页开始显示某角色时登记；传 null 表示退出聊天页（回会话列表等）。 */
    fun markChatVisible(role: String?, personaFilename: String?) {
        visibleChatRole.set(role?.trim()?.takeIf { it.isNotEmpty() })
        visibleChatFilename.set(personaFilename?.trim()?.takeIf { it.isNotEmpty() })
    }

    /** 离开聊天页时清空登记。 */
    fun clearChatVisible() = markChatVisible(null, null)

    /**
     * 当前聊天页是否正是这个角色 / 人设。
     *
     * 判定优先比 persona filename（更精确），filename 缺失时退化比 role
     * （大小写不敏感，role 是后端下发的 id，大小写可能不一致）。
     */
    fun isChatVisibleFor(role: String?, personaFilename: String?): Boolean {
        val targetFilename = personaFilename?.trim()?.takeIf { it.isNotEmpty() }
        val targetRole = role?.trim()?.takeIf { it.isNotEmpty() }
        if (targetFilename == null && targetRole == null) return false
        val currentFilename = visibleChatFilename.get()
        if (targetFilename != null && currentFilename != null) {
            return currentFilename == targetFilename
        }
        val currentRole = visibleChatRole.get() ?: return false
        return targetRole != null && currentRole.equals(targetRole, ignoreCase = true)
    }

    /**
     * 撤掉某个角色的通知（用户已看到该角色的消息时调用）。
     *
     * @return 实际撤销的通知条数
     */
    fun cancelNotificationsFor(role: String?, personaFilename: String?): Int {
        val keys = cancelKeysFor(personaFilename, role)
        if (keys.isEmpty()) return 0
        return runCatching { notificationManager.cancelNotifications(keys) }
            .getOrElse { e ->
                Log.w(TAG, "撤销角色通知失败: ${e.message}", e)
                0
            }
    }

    /**
     * 一条角色回复消息的通知请求。
     *
     * @param role 角色 id（如 aveline），用于深链切会话与通知归属
     * @param personaFilename 人设文件名，用于查本地昵称/头像与通知归属
     * @param fallbackTitle 查不到昵称时的兜底标题
     * @param body 已清洗过的正文
     */
    data class ReplyNotification(
        val role: String?,
        val personaFilename: String?,
        val fallbackTitle: String?,
        val body: String
    )

    /**
     * App 在后台时给这条角色回复弹通知。
     *
     * 前台时不弹：回复已经直接上屏（用户正看着聊天页），再弹横幅属于重复打扰。
     * 判断走 [com.aveline.ai.mobile.utils.AppForegroundTracker]
     * （基于 ProcessLifecycleOwner，跟踪整个进程前后台）。
     *
     * @return true 表示确实发出了通知
     */
    suspend fun notifyReplyIfBackground(reply: ReplyNotification): Boolean {
        if (reply.body.isBlank()) return false
        if (com.aveline.ai.mobile.utils.AppForegroundTracker.isForeground) return false

        val filename = reply.personaFilename?.trim()?.takeIf { it.isNotEmpty() }
        // 显示名优先级与会话列表一致：本地自定义昵称 > 后端下发昵称 > 兜底名
        val displayName = filename?.let {
            personaLocalMetaRepository.getMetaOnce(it)?.customName?.takeIf { name -> name.isNotBlank() }
        } ?: reply.fallbackTitle?.trim()?.takeIf { it.isNotEmpty() }
        ?: DEFAULT_TITLE

        val role = reply.role?.trim()?.takeIf { it.isNotEmpty() }
            ?: roleIdFromPersonaFilename(filename)

        return runCatching {
            notifications.showBackendNotification(
                title = displayName,
                body = reply.body,
                deepLink = chatDeepLink(filename, role),
                largeIcon = buildLargeIcon(filename, displayName),
                cancelKeys = cancelKeysFor(filename, role),
                // 同一角色的回复叠在同一张通知卡上（QQ 式），角色 id 优先、没有时用人设名。
                conversationKey = role ?: filename
            )
            true
        }.getOrElse { e ->
            Log.w(TAG, "后台回复通知发布失败: ${e.message}", e)
            false
        }
    }

    /**
     * 解析这条通知归属哪些 key（persona filename / role id）。
     *
     * 用户看完该角色的消息后，聊天页会用同一批 key 把通知撤掉；解析不出归属时
     * 返回空集合，这条通知就只能靠用户手动划掉（总比误撤别的角色通知好）。
     */
    fun cancelKeysFor(personaFilename: String?, vararg extra: String?): Set<String> = buildSet {
        addAll(listOfNotNull(personaFilename, roleIdFromPersonaFilename(personaFilename)))
        extra.forEach { addAll(listOfNotNull(it?.trim()?.takeIf { value -> value.isNotEmpty() })) }
    }

    /**
     * 角色聊天深链：只产出导航图**真正声明过**的 `role` + `filename` 形式。
     *
     * 踩过的坑：这里原先在拿到 sessionId 时改发 `aveline://chat?session_id=...`，
     * 但 NavGraph 的 chat 目的地只声明了 `text` / `role` / `filename` / `name`
     * 四个 argument，**没有 session_id**。于是系统把该深链匹配到最宽泛的
     * `aveline://chat`，role/filename/name 全为空 —— 表现为点通知后新开一个聊天页、
     * 且提示"找不到这个人设"。深链参数必须与 NavGraph 声明严格对齐。
     *
     * 必须带上 role：聊天页只有 role 非空才会切会话，只给 filename 的深链会被整段跳过，
     * 表现为"点了通知还停在别的角色"。
     */
    fun chatDeepLink(personaFilename: String?, role: String?): String {
        val resolvedRole = role?.trim()?.takeIf { it.isNotEmpty() }
            ?: roleIdFromPersonaFilename(personaFilename)
        val filename = personaFilename?.trim()?.takeIf { it.isNotEmpty() }
        if (resolvedRole.isNullOrBlank() && filename.isNullOrBlank()) return CHAT_DEEP_LINK
        val builder = Uri.Builder().scheme("aveline").authority("chat")
        // 与 NavArgs.ROLE / 深链 filename 同值；用字面量避免 services 层依赖 presentation 层
        resolvedRole?.let { builder.appendQueryParameter("role", it) }
        filename?.let { builder.appendQueryParameter("filename", it) }
        return builder.build().toString()
    }

    /**
     * 构建通知 largeIcon：本地头像优先（方形居中裁剪），
     * 没有头像时用主题色（Primary 天蓝）画显示名首字，与聊天页首字兜底风格一致。
     * 构建失败返回 null（通知退化为默认样式）。
     */
    private suspend fun buildLargeIcon(personaFilename: String?, displayName: String): Bitmap? {
        if (!personaFilename.isNullOrBlank()) {
            runCatching {
                personaLocalMetaRepository.resolveAvatarFile(personaFilename)?.let { file ->
                    val sampled = decodeSampledBitmap(file, ICON_SIZE_PX) ?: return@runCatching null
                    val side = minOf(sampled.width, sampled.height)
                    val xOff = (sampled.width - side) / 2
                    val yOff = (sampled.height - side) / 2
                    return Bitmap.createBitmap(sampled, xOff, yOff, side, side)
                }
            }.getOrNull()?.let { return it }
        }

        val initial = displayName.trim().firstOrNull() ?: return null
        return runCatching {
            val bmp = Bitmap.createBitmap(ICON_SIZE_PX, ICON_SIZE_PX, Bitmap.Config.ARGB_8888)
            bmp.eraseColor(PRIMARY_COLOR)
            val canvas = android.graphics.Canvas(bmp)
            val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = BACKGROUND_COLOR
                textSize = ICON_SIZE_PX * 0.42f
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
        private const val TAG = "RoleReplyNotifier"

        /** 通知标题兜底（解析不出角色名时才用）。 */
        const val DEFAULT_TITLE = "Aveline"

        const val CHAT_DEEP_LINK = "aveline://chat"

        private const val ICON_SIZE_PX = 108

        // 首字兜底头像的配色：与 theme/Color.kt 的 Primary / Background 同值，
        // 通知头像与 App 自身配色保持一致（深色字压在品牌天蓝上）。
        private const val PRIMARY_COLOR = 0xFF0EA5E9.toInt()
        private const val BACKGROUND_COLOR = 0xFF05060A.toInt()

        /**
         * 从 persona filename 反解 role id。
         *
         * 规则与后端 normalize_persona_token 一致：取文件名 → 去扩展名 →
         * 去 `core_` 前缀 → 取首个 token。
         */
        fun roleIdFromPersonaFilename(personaFilename: String?): String? {
            val raw = personaFilename?.trim().orEmpty()
            if (raw.isBlank()) return null
            val name = raw.substringAfterLast('/').substringAfterLast('\\')
            var token = name.substringBeforeLast('.').trim().lowercase()
            if (token.startsWith("core_")) token = token.removePrefix("core_")
            return token.substringBefore("_").substringBefore(".").takeIf { it.isNotBlank() }
        }

        /** 从后端 conversation_id 解析角色 id（形如 private_10001__persona__core_aveline）。 */
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
    }
}

/**
 * [ForegroundNotificationController] 持有者。
 *
 * 该控制器原本只在前台服务内部构造（`private lateinit var notifications`），
 * 但发通知的能力现在被前台服务之外的组件需要（`ChatSendController` 在进程级后台
 * 作用域里收尾 HTTP SSE 后要弹通知），而那个作用域拿不到 Service 实例。
 * 这里按 ApplicationContext 缓存一份，保证全局单实例：前台服务与聊天页共用
 * 同一份自增通知 ID 与 key → id 归属表，通知才能互相撤销。
 */
internal object ForegroundNotificationControllerHolder {
    @Volatile
    private var instance: ForegroundNotificationController? = null

    fun get(
        context: android.content.Context,
        notificationManager: com.aveline.ai.mobile.services.AvelineNotificationManager
    ): ForegroundNotificationController {
        instance?.let { return it }
        return synchronized(this) {
            instance ?: ForegroundNotificationController(
                context.applicationContext,
                notificationManager
            ).also {
                it.createChannels()
                instance = it
            }
        }
    }
}
