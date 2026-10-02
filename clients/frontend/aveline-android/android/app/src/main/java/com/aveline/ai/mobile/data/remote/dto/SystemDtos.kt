package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class SystemPreferencesDto(
    val mode: String? = null,
    val active_care_enabled: Boolean? = null,
    val response_length: String? = null,
    val conversation_style: String? = null,
    val sensitivity: String? = null,
    val debug_visible: Boolean? = null
)

@Serializable
data class SystemPreferencesResponse(
    val status: String? = null,
    val message: String? = null,
    val data: SystemPreferencesDto? = null
)

@Serializable
data class SystemResourcesResponse(
    val status: String? = null,
    val data: JsonElement? = null,
    val timestamp: String? = null
)

@Serializable
data class SystemStatsResponse(
    val status: String? = null,
    val data: JsonElement? = null,
    val metrics: JsonElement? = null,
    val timestamp: String? = null
)
