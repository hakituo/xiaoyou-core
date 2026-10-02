package com.aveline.ai.mobile.domain.models

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

@Serializable
sealed class PhoneAction {
    abstract val actionId: String

    @Serializable
    data class CreateCalendarEvent(
        override val actionId: String,
        val title: String,
        val description: String = "",
        val startTime: Long,
        val endTime: Long,
        val reminderMinutes: Int = 10,
        val allDay: Boolean = false
    ) : PhoneAction()

    @Serializable
    data class SetAlarm(
        override val actionId: String,
        val hour: Int,
        val minute: Int,
        val message: String = "",
        val vibrate: Boolean = true,
        val skipUi: Boolean = false
    ) : PhoneAction()

    @Serializable
    data class SetTimer(
        override val actionId: String,
        val seconds: Int,
        val message: String = "",
        val skipUi: Boolean = false
    ) : PhoneAction()

    @Serializable
    data class OpenApp(
        override val actionId: String,
        val packageName: String,
        val query: String = ""
    ) : PhoneAction()

    @Serializable
    data class MakePhoneCall(
        override val actionId: String,
        val phoneNumber: String
    ) : PhoneAction()

    @Serializable
    data class SendSms(
        override val actionId: String,
        val phoneNumber: String,
        val message: String
    ) : PhoneAction()

    @Serializable
    data class OpenNavigation(
        override val actionId: String,
        val destination: String,
        val mode: String = "driving"
    ) : PhoneAction()

    @Serializable
    data class SetDndMode(
        override val actionId: String,
        val enable: Boolean
    ) : PhoneAction()

    @Serializable
    data class MediaControl(
        override val actionId: String,
        val command: String
    ) : PhoneAction()

    @Serializable
    data class OpenSettings(
        override val actionId: String,
        val settingsType: String
    ) : PhoneAction()

    @Serializable
    data class ShareContent(
        override val actionId: String,
        val text: String,
        val title: String = ""
    ) : PhoneAction()

    @Serializable
    data class SetVolume(
        override val actionId: String,
        val streamType: String = "music",
        val level: Int
    ) : PhoneAction()

    @Serializable
    data class GetLocation(
        override val actionId: String
    ) : PhoneAction()

    @Serializable
    data class Unknown(
        override val actionId: String,
        val rawType: String,
        val rawParams: JsonObject
    ) : PhoneAction()
}

@Serializable
data class PhoneActionResult(
    val actionId: String,
    val success: Boolean,
    val resultType: String,
    val data: Map<String, JsonPrimitive> = emptyMap(),
    val error: String? = null
)
