package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable

@Serializable
data class VisionDescribeResponse(
    val status: String? = null,
    val description: String? = null,
    val request_id: String? = null,
    val timestamp: Double? = null,
    val message: String? = null
)
