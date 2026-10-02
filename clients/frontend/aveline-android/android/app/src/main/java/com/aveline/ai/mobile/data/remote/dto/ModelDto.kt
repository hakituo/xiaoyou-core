package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * AI 模型 DTO
 */
@Serializable
data class ModelDto(
    @SerialName("id")
    val id: String,
    
    @SerialName("name")
    val name: String? = null,
    
    @SerialName("type")
    val type: String? = null,

    @SerialName("category")
    val category: String? = null,

    @SerialName("path")
    val path: String? = null,
    
    @SerialName("description")
    val description: String? = null,
    
    @SerialName("provider")
    val provider: String? = null,
    
    @SerialName("context_length")
    val contextLength: Int? = null,
    
    @SerialName("is_available")
    val isAvailable: Boolean? = null
)

/**
 * 模型列表响应
 */
@Serializable
data class ModelsResponse(
    @SerialName("models")
    val models: List<ModelDto>,
    
    @SerialName("selected_model_id")
    val selectedModelId: String? = null
)

/**
 * 切换模型请求（对应后端 POST /api/v1/models/switch）
 */
@Serializable
data class SwitchModelRequest(
    @SerialName("model_name")
    val modelName: String,
    @SerialName("provider")
    val provider: String = "local"
)

/**
 * 切换模型响应（对应后端 POST /api/v1/models/switch 返回）
 */
@Serializable
data class SwitchModelResponse(
    @SerialName("success")
    val success: Boolean = false,
    @SerialName("error")
    val error: String? = null
)
