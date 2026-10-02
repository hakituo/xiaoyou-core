package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class IntentClassifyResponse(
    val status: String? = null,
    val intent: String? = null,
    val confidence: Float? = null,
    val slots: JsonElement? = null,
    val raw: String? = null
)

@Serializable
data class SensitiveStatusResponse(
    val enabled: Boolean? = null
)

@Serializable
data class SensitiveToggleRequest(
    val enabled: Boolean,
    val user_id: String = "default"
)

@Serializable
data class SensitiveToggleResponse(
    val status: String? = null,
    val enabled: Boolean? = null,
    val mode: String? = null
)
