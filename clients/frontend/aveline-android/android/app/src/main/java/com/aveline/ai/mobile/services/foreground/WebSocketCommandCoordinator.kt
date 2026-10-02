package com.aveline.ai.mobile.services.foreground

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.local.preferences.RoleScopedPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.PhoneActionResult
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.services.PhoneActionExecutor
import com.aveline.ai.mobile.services.ReplayGuard
import com.aveline.ai.mobile.services.SystemControlExecutor
import com.aveline.ai.mobile.services.endpoint.EndpointResolver
import com.aveline.ai.mobile.utils.AppForegroundTracker
import com.aveline.ai.mobile.utils.text.TextSegmenter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.serializer

/**
 * 观察 WebSocket 消息并协调通知、手机动作与设备控制指令。
 *
 * 拆分说明：本类只做「消息分发 + 生命周期」这一件事，具体能力交给同包组件：
 * - [BackendNotificationPresenter]：通知文案、头像与发布
 * - [NotificationDeepLink]：深链与角色 id 解析
 * - [ProactiveMessageHandler]：角色主动消息的归档与提醒
 * - [PhoneActionCommandParser]：手机动作指令解析
 */
class WebSocketCommandCoordinator(
    private val scope: CoroutineScope,
    private val preferences: AppPreferences,
    private val webSocketManager: WebSocketManager,
    private val endpointResolver: EndpointResolver,
    private val notifications: ForegroundNotificationController,
    private val phoneActionExecutor: PhoneActionExecutor,
    private val systemControlExecutor: SystemControlExecutor,
    private val chatRepository: ChatRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val roleScopedPreferences: RoleScopedPreferences? = null,
    /** 判断"某个角色的聊天页是否正显示在屏幕上"；常驻服务外的调用方可传 null。 */
    private val replyNotifier: RoleReplyNotifier? = null
) {
    private val replayGuard = ReplayGuard()
    private var observerJob: Job? = null

    private val presenter = BackendNotificationPresenter(
        notifications = notifications,
        personaLocalMetaRepository = personaLocalMetaRepository
    )

    private val proactiveHandler = ProactiveMessageHandler(
        scope = scope,
        preferences = preferences,
        presenter = presenter,
        chatRepository = chatRepository,
        personaLocalMetaRepository = personaLocalMetaRepository,
        roleScopedPreferences = roleScopedPreferences,
        replyNotifier = replyNotifier
    )

    /**
     * 流式回复的正文缓冲。
     *
     * ResponseDone 本身不带内容，只有 response_chunk 里才有文字，因此必须在 chunk 到达时
     * 先攒起来，结束时才能用真实正文提醒（否则后台通知只能弹一句空洞的"收到新消息"）。
     * 前台聊天时同样累积（开销可忽略），但不弹通知。
     */
    private val streamingBuffer = StringBuilder()

    fun ensureConnection() {
        if (preferences.effectiveBackendUrl.isNotEmpty()) webSocketManager.connect()
    }

    /**
     * 重新裁决后端通道（局域网 / 公网）。
     *
     * 前台服务是常驻组件：App 打开即拉起、开机也会拉起。把首次探测放在这里，
     * 保证「进程起来了但用户还没打开界面」时也能选对通道；同时也兜住
     * 「服务先于 MainActivity 启动」的场景（那时 MainActivity 的探测还没跑）。
     *
     * 这里只裁决、不主动连 WebSocket：地址真变了由 WebSocketManager 订阅
     * EndpointResolver.changes 自行重连，地址没变时是否连接由常驻模式等原有开关决定，
     * 不在这里改变既有行为。
     */
    fun refreshEndpoint() {
        scope.launch { endpointResolver.resolve("前台服务") }
    }

    fun startObserving() {
        if (observerJob?.isActive == true) return
        observerJob = scope.launch {
            webSocketManager.messages.collect { message ->
                when (message) {
                    is WebSocketMessage.Notification -> presenter.showNotification(message)
                    is WebSocketMessage.RitualEvent -> presenter.showRitualEvent(message)
                    is WebSocketMessage.SpontaneousReaction ->
                        presenter.showSpontaneousReaction(message)
                    // 角色主动消息（Active Care / 自发开口）。
                    // 后端以 type=proactive_message 广播；此前没有这个分支，整条消息落到
                    // Unknown 被静默丢弃，所以用户完全收不到 active care 提醒。
                    is WebSocketMessage.ProactiveMessage -> handleProactiveMessage(message)
                    // 流式回复：先攒正文，结束时再决定是否提醒
                    is WebSocketMessage.ResponseChunk -> streamingBuffer.append(message.content)
                    is WebSocketMessage.ResponseReset -> streamingBuffer.clear()
                    is WebSocketMessage.ResponseDone -> {
                        val reply = streamingBuffer.toString().trim()
                        streamingBuffer.clear()
                        notifyReplyIfBackground(reply)
                    }
                    // 非流式的整条回复；同时清掉可能残留的流式缓冲
                    is WebSocketMessage.TextMessage -> {
                        streamingBuffer.clear()
                        notifyReplyIfBackground(message.text)
                    }
                    is WebSocketMessage.PhoneActionCommand -> handlePhoneAction(message)
                    is WebSocketMessage.DeviceCommand -> handleDeviceCommand(message)
                    else -> Unit
                }
            }
        }
    }

    /**
     * 角色主动消息（Active Care / 自发开口）：去重与剧本过滤后交给
     * [ProactiveMessageHandler] 归档上屏 + 未读计数 + 通知。
     *
     * 双角色剧本是"角色之间的对话"，不是角色找用户，既不提醒也不归档。
     */
    private fun handleProactiveMessage(message: WebSocketMessage.ProactiveMessage) {
        if (message.isPeerScript) return
        val messageId = message.messageId.orEmpty()
        if (messageId.isNotEmpty() && replayGuard.isReplay("proactive:$messageId")) {
            Log.d(TAG, "忽略重放的 proactive_message (id=$messageId)")
            return
        }
        // 与聊天页同一套规则清洗（剥时间戳 + 去句末句号）：
        // 主动消息有通知、会话列表预览、落库三个出口，全部共用这份文本，
        // 否则通知栏/会话列表会出现"都快十点了。"这类带句末句号的文案
        val body = TextSegmenter.clean(message.content).trim()
        if (body.isEmpty()) return

        proactiveHandler.handle(message, body, messageId)
    }

    /**
     * 角色"回了消息"的提醒：仅当 App 处于后台时才弹。
     *
     * 前台时回复已经直接上屏（用户正看着聊天页），再弹横幅属于重复打扰；
     * 退到后台才需要通知把人叫回来。AppForegroundTracker 基于 ProcessLifecycleOwner
     * 跟踪整个进程的前后台，已在 AvelineApplication 注册。
     *
     * 注意：这条分支只在「客户端不经 HTTP SSE 发消息」时才可能走到（如 WS 直发场景）；
     * 用户主动发消息走 HTTP SSE，那条路径由 ChatSendController 收尾时直接调
     * [RoleReplyNotifier]。两边共用同一份通知实现，样式不会分叉。
     * WS 的 response_done / text 不带角色信息，因此这里只能给出默认标题与聊天主页深链。
     */
    private fun notifyReplyIfBackground(body: String) {
        // 通知文案与聊天页同一套清洗（时间戳/句末句号），避免通知栏带句号
        val cleaned = TextSegmenter.clean(body)
        if (cleaned.isBlank() || AppForegroundTracker.isForeground) return
        notifications.showBackendNotification(
            title = DEFAULT_NOTIFY_TITLE,
            body = cleaned,
            deepLink = NotificationDeepLink.CHAT_DEEP_LINK
        )
    }

    fun stop() {
        observerJob?.cancel()
        observerJob = null
        webSocketManager.disconnect()
    }

    private fun handlePhoneAction(command: WebSocketMessage.PhoneActionCommand) {
        scope.launch {
            val actionId = command.actionId.trim()
            // action_id 缺失时退化为"指令内容指纹"去重。
            // 原写法 `actionId.isNotEmpty() && isReplay(...)` 会让无 id 的指令完全绕过重放
            // 防护(ReplayGuard 对空 id 返回 false), 抖动重连时同一条 open_settings 会被
            // 逐条执行 —— 表现为系统无障碍设置页反复弹出。这里与 handleDeviceCommand 对齐。
            val dedupKey = if (actionId.isNotEmpty()) {
                "phone_action:$actionId"
            } else {
                "phone_action:${command.actionType}:${command.params}"
            }
            if (replayGuard.isReplay(dedupKey)) {
                Log.w(TAG, "检测到重放的 phone_action (key=$dedupKey), 已丢弃")
                return@launch
            }
            val result = phoneActionExecutor.execute(PhoneActionCommandParser.parse(command))
            val resultJson = Json.encodeToString(
                serializer<PhoneActionResult>(),
                result
            )
            webSocketManager.sendMessage(
                """{"type":"phone_action_result","data":$resultJson}"""
            )
        }
    }

    private fun handleDeviceCommand(command: WebSocketMessage.DeviceCommand) {
        scope.launch {
            val requestId = command.requestId.trim()
            if (requestId.isEmpty() || replayGuard.isReplay("device_command:$requestId")) {
                Log.w(TAG, "检测到重放的 device_command (request_id=$requestId), 已丢弃")
                return@launch
            }
            val result = systemControlExecutor.execute(command.command, command.args)
            val resultFields = result.toString().removePrefix("{").removeSuffix("}")
            webSocketManager.sendMessage(
                """{"type":"device_command_result","request_id":"${command.requestId}",$resultFields}"""
            )
        }
    }

    companion object {
        private const val TAG = "AvelineForegroundServiceV2"

        /**
         * 从 persona filename 反解 role id（实现见 [NotificationDeepLink]）。
         *
         * 保留在此仅为兼容既有调用路径；规则与后端 normalize_persona_token 一致。
         */
        internal fun roleIdFromPersonaFilename(personaFilename: String?): String? =
            NotificationDeepLink.roleIdFromPersonaFilename(personaFilename)

        /**
         * 从后端 conversation_id 解析角色 id（实现见 [NotificationDeepLink]）。
         *
         * 后端会话 id 形如 private_10001__persona__core_aveline；解析不出角色时返回 null，
         * 由调用方回退到聊天主页深链。
         */
        internal fun roleIdFromConversationId(conversationId: String?): String? =
            NotificationDeepLink.roleIdFromConversationId(conversationId)
    }
}
