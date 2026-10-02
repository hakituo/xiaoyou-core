package com.aveline.ai.mobile.services.foreground

import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.domain.models.PhoneAction

/**
 * 后端手机动作指令 → 领域 [PhoneAction] 的解析（从 WebSocketCommandCoordinator 拆出）。
 *
 * 只做字段搬运与默认值兜底，不接触执行器与 WebSocket。
 */
internal object PhoneActionCommandParser {

    fun parse(command: WebSocketMessage.PhoneActionCommand): PhoneAction {
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
}
