package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 标记重要请求
 */
@Serializable
data class MarkImportantRequest(
    @SerialName("is_important")
    val isImportant: Boolean
)
