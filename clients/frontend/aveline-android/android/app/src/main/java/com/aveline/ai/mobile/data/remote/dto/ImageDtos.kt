package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class ImageModelsResponse(
    val status: String? = null,
    val data: JsonElement? = null
)

@Serializable
data class ImageItemDto(
    val image_path: String? = null,
    val url: String? = null,
    val image_base64: String? = null
)

@Serializable
data class ImageGenerateResponse(
    val success: Boolean? = null,
    val prompt: String? = null,
    val image_path: String? = null,
    val url: String? = null,
    val image_url: String? = null,
    val images: List<ImageItemDto> = emptyList()
)
