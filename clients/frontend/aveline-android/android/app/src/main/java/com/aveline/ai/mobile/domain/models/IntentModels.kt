package com.aveline.ai.mobile.domain.models

import kotlinx.serialization.json.JsonElement

data class IntentResult(
    val intent: String,
    val confidence: Float,
    val slots: JsonElement?,
    val raw: String?
)
