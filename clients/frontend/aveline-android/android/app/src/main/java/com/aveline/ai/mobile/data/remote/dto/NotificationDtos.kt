package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class NotificationItemDto(
    val id: String? = null,
    val type: String? = null,
    val title: String? = null,
    val content: String? = null,
    val payload: JsonElement? = null,
    val timestamp: Double? = null,
    val read: Boolean? = null
)

@Serializable
data class NotificationsResponse(
    val status: String? = null,
    val data: List<NotificationItemDto> = emptyList(),
    val timestamp: Double? = null
)
