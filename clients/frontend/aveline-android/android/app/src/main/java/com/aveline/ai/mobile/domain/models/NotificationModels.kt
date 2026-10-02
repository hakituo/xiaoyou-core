package com.aveline.ai.mobile.domain.models

import kotlinx.serialization.json.JsonElement

data class NotificationItem(
    val id: String,
    val type: String,
    val title: String,
    val content: String,
    val payload: JsonElement?,
    val timestamp: Double,
    val read: Boolean
)
