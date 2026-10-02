package com.aveline.ai.mobile.domain.models

data class SystemPreferences(
    val mode: String = "normal",
    val activeCareEnabled: Boolean = true,
    val responseLength: String = "normal",
    val conversationStyle: String = "natural",
    val sensitivity: String = "medium",
    val debugVisible: Boolean = false
)

data class SystemPreferencesUpdate(
    val mode: String? = null,
    val activeCareEnabled: Boolean? = null,
    val responseLength: String? = null,
    val conversationStyle: String? = null,
    val sensitivity: String? = null,
    val debugVisible: Boolean? = null
)
