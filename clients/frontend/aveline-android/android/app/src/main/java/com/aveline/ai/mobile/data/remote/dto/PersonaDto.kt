package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 人格 DTO
 */
@Serializable
data class PersonaDto(
    @SerialName("id")
    val id: String,
    
    @SerialName("name")
    val name: String? = null,
    
    @SerialName("description")
    val description: String? = null,
    
    @SerialName("system_prompt")
    val systemPrompt: String? = null,
    
    @SerialName("avatar_url")
    val avatarUrl: String? = null,
    
    @SerialName("traits")
    val traits: List<String>? = null,
    
    @SerialName("is_default")
    val isDefault: Boolean? = null,
    
    @SerialName("is_custom")
    val isCustom: Boolean? = null,
    
    @SerialName("created_at")
    val createdAt: String? = null,
    
    @SerialName("updated_at")
    val updatedAt: String? = null
)

/**
 * 当前激活人格响应
 */
@Serializable
data class ActivePersonaResponse(
    @SerialName("status")
    val status: String,
    
    @SerialName("filename")
    val filename: String? = null,
    
    @SerialName("data")
    val data: PersonaDto? = null
)

/**
 * 人格创建/更新请求
 */
@Serializable
data class PersonaRequest(
    @SerialName("name")
    val name: String,
    
    @SerialName("description")
    val description: String = "",
    
    @SerialName("system_prompt")
    val systemPrompt: String = "",
    
    @SerialName("avatar_url")
    val avatarUrl: String? = null,
    
    @SerialName("traits")
    val traits: List<String> = emptyList()
)

/**
 * 选择人格请求
 */
@Serializable
data class SelectPersonaRequest(
    @SerialName("filename")
    val personaId: String
)
