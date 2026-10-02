package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 学习文件 DTO
 */
@Serializable
data class StudyFileDto(
    @SerialName("id")
    val id: String,
    
    @SerialName("name")
    val name: String,
    
    @SerialName("size")
    val size: Long? = null,
    
    @SerialName("type")
    val type: String? = null,
    
    @SerialName("status")
    val status: String? = null,
    
    @SerialName("upload_progress")
    val uploadProgress: Float? = null,
    
    @SerialName("uploaded_at")
    val uploadedAt: String? = null,
    
    @SerialName("processed_at")
    val processedAt: String? = null,
    
    @SerialName("chunk_count")
    val chunkCount: Int? = null,
    
    @SerialName("error_message")
    val errorMessage: String? = null
)

/**
 * 学习文件列表响应
 */
@Serializable
data class StudyFilesResponse(
    @SerialName("files")
    val files: List<StudyFileDto>,
    
    @SerialName("total")
    val total: Int
)

/**
 * 学习模式响应
 */
@Serializable
data class StudyModeResponse(
    @SerialName("enabled")
    val enabled: Boolean,
    
    @SerialName("active_file_ids")
    val activeFileIds: List<String>,
    
    @SerialName("total_chunks")
    val totalChunks: Int
)

/**
 * 设置学习模式请求
 */
@Serializable
data class SetStudyModeRequest(
    @SerialName("enabled")
    val enabled: Boolean
)

/**
 * 设置活跃文件请求
 */
@Serializable
data class SetActiveFilesRequest(
    @SerialName("file_ids")
    val fileIds: List<String>
)
