package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable

/**
 * Response DTO for file upload operations.
 * 
 * @property status Response status
 * @property fileUrl URL of the uploaded file
 * @property fileId Unique file identifier
 * @property fileName Original file name
 * @property fileSize File size in bytes
 */
@Serializable
data class UploadResponse(
    val status: String,
    val fileUrl: String,
    val fileId: String,
    val fileName: String,
    val fileSize: Long
)
