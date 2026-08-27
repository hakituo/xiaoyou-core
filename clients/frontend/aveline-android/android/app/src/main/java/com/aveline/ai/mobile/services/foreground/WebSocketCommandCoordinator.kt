package com.aveline.ai.mobile.services.foreground

import android.net.Uri
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.domain.models.PhoneAction
import com.aveline.ai.mobile.domain.models.PhoneActionResult
import com.aveline.ai.mobile.services.PhoneActionExecutor
import com.aveline.ai.mobile.services.ReplayGuard
import com.aveline.ai.mobile.services.SystemControlExecutor
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.serializer

/** 观察 WebSocket 消息并协调通知、手机动作与设备控制指令。 */
class WebSocketCommandCoordinator(
    private val scope: CoroutineScope,
    private val preferences: AppPreferences,
    private val webSocketManager: WebSocketManager,
    private val notifications: ForegroundNotificationController,
    private val phoneActionExecutor: PhoneActionExecutor,
    private val systemControlExecutor: SystemControlExecutor
) {
    private val replayGuard = ReplayGuard()
    private var observerJob: Job? = null

    fun ensureConnection() {
        if (preferences.backendUrl.isNotEmpty()) webSocketManager.connect()
    }

    fun updateBackendUrl(url: String) {
        if (url.isEmpty()) return
        preferences.backendUrl = url
        webSocketManager.connect(forceReconnect = true)
    }

    fun startObserving() {
        if (observerJob?.isActive == true) return
        observerJob = scope.launch {
            webSocketManager.messages.collect { message ->
                when (message) {
                    is WebSocketMessage.Notification -> {
                        val deepLink = buildNotificationDeepLink(message)
                        notifications.showBackendNotification(
                            title = message.title.ifEmpty { "Aveline" },
                            body = message.body,
                            deepLink = deepLink
                        )
                    }
                    is WebSocketMessage.RitualEvent -> {
                        if (message.content.isNotEmpty()) {
                            notifications.showBackendNotification("Aveline", message.content, deepLink = "aveline://chat")
                        }
                    }
                    is WebSocketMessage.SpontaneousReaction -> {
                        if (message.content.isNotEmpty()) {
                            notifications.showBackendNotification("Aveline", message.content, deepLink = "aveline://chat")
                        }
                    }
                    is WebSocketMessage.PhoneActionCommand -> handlePhoneAction(message)
                    is WebSocketMessage.DeviceCommand -> handleDeviceCommand(message)
                    else -> Unit
                }
            }
        }
    }

    fun stop() {
        observerJob?.cancel()
        observerJob = null
        webSocketManager.disconnect()
    }

    private fun handlePhoneAction(command: WebSocketMessage.PhoneActionCommand) {
        scope.launch {
            val actionId = command.actionId.trim()
            if (actionId.isNotEmpty() && replayGuard.isReplay("phone_action:$actionId")) {
                Log.w(TAG, "检测到重放的 phone_action (action_id=$actionId), 已丢弃")
                return@launch
            }
            val result = phoneActionExecutor.execute(parsePhoneAction(command))
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

    private fun parsePhoneAction(command: WebSocketMessage.PhoneActionCommand): PhoneAction {
        val params = command.params
        fun string(key: String): String = params[key]?.toString()?.trim('"') ?: ""
        fun int(key: String): Int = params[key]?.toString()?.toIntOrNull() ?: 0
        fun long(key: String): Long = params[key]?.toString()?.toLongOrNull() ?: 0L
        fun boolean(key: String): Boolean =
            params[key]?.toString()?.toBooleanStrictOrNull() ?: false

        return when (command.actionType) {
            "create_calendar_event" -> PhoneAction.CreateCalendarEvent(
                actionId = command.actionId,
                title = string("title"),
                description = string("description"),
                startTime = long("startTime"),
                endTime = long("endTime"),
                reminderMinutes = int("reminderMinutes").let { if (it == 0) 10 else it },
                allDay = boolean("allDay")
            )
            "set_alarm" -> PhoneAction.SetAlarm(
                actionId = command.actionId,
                hour = int("hour"),
                minute = int("minute"),
                message = string("message"),
                vibrate = params["vibrate"]?.toString()?.toBooleanStrictOrNull() ?: true,
                skipUi = boolean("skipUi")
            )
            "set_timer" -> PhoneAction.SetTimer(
                actionId = command.actionId,
                seconds = int("seconds"),
                message = string("message"),
                skipUi = boolean("skipUi")
            )
            "open_app" -> PhoneAction.OpenApp(
                actionId = command.actionId,
                packageName = string("packageName"),
                query = string("query")
            )
            "make_phone_call" -> PhoneAction.MakePhoneCall(
                actionId = command.actionId,
                phoneNumber = string("phoneNumber")
            )
            "send_sms" -> PhoneAction.SendSms(
                actionId = command.actionId,
                phoneNumber = string("phoneNumber"),
                message = string("message")
            )
            "open_navigation" -> PhoneAction.OpenNavigation(
                actionId = command.actionId,
                destination = string("destination"),
                mode = string("mode").ifEmpty { "driving" }
            )
            "set_dnd_mode" -> PhoneAction.SetDndMode(
                actionId = command.actionId,
                enable = params["enable"]?.toString()?.toBooleanStrictOrNull() ?: true
            )
            "media_control" -> PhoneAction.MediaControl(
                actionId = command.actionId,
                command = string("command")
            )
            "open_settings" -> PhoneAction.OpenSettings(
                actionId = command.actionId,
                settingsType = string("settingsType")
            )
            "share_content" -> PhoneAction.ShareContent(
                actionId = command.actionId,
                text = string("text"),
                title = string("title")
            )
            "set_volume" -> PhoneAction.SetVolume(
                actionId = command.actionId,
                streamType = string("streamType").ifEmpty { "music" },
                level = int("level")
            )
            "get_location" -> PhoneAction.GetLocation(actionId = command.actionId)
            else -> PhoneAction.Unknown(
                actionId = command.actionId,
                rawType = command.actionType,
                rawParams = command.params
            )
        }
    }

    /**
     * 根据 WebSocket 通知内容计算点击跳转深链。
     * 优先使用后端下发的 target(及可选 sessionId); 未下发时按内容启发式:
     * 背单词/单词/词汇/复习/拼写/默写/记忆卡片等学习类 -> aveline://study, 其余 -> aveline://chat。
     */
    private fun buildNotificationDeepLink(message: WebSocketMessage.Notification): String {
        return when (val target = message.target) {
            "study" -> "aveline://study"
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
            else -> if (isStudyPush(message.title, message.body))
                "aveline://study"
            else
                "aveline://chat"
        }
    }

    /** 启发式判断是否为背单词/学习类推送(后端未显式下发 target 时的兜底, 让其跳到背单词页)。 */
    private fun isStudyPush(title: String, body: String): Boolean {
        val text = "$title $body"
        return text.contains(Regex("背单词|单词|词汇|复习|拼写|默写|记忆卡片|vocab|flashcard"))
    }

    companion object {
        private const val TAG = "AvelineForegroundServiceV2"
    }
}
