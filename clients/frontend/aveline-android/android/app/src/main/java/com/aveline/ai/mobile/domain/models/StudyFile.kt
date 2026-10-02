package com.aveline.ai.mobile.domain.models

import java.time.Instant

/**
 * 学习文件状态
 */
enum class FileStatus {
    UPLOADING,      // 上传中
    PROCESSING,     // 处理中
    READY,          // 就绪
    ERROR           // 错误
}

/**
 * 学习文件数据模型
 * 
 * @property id 文件 ID
 * @property name 文件名
 * @property size 文件大小 (字节)
 * @property type 文件类型 (MIME type)
 * @property status 文件状态
 * @property uploadProgress 上传进度 (0-1)
 * @property uploadedAt 上传时间
 * @property processedAt 处理完成时间
 * @property chunkCount 分块数量
 * @property errorMessage 错误信息
 */
data class StudyFile(
    val id: String,
    val name: String,
    val size: Long,
    val type: String,
    val status: FileStatus = FileStatus.UPLOADING,
    val uploadProgress: Float = 0f,
    val uploadedAt: Instant = Instant.now(),
    val processedAt: Instant? = null,
    val chunkCount: Int = 0,
    val errorMessage: String? = null
) {
    val formattedSize: String
        get() = formatFileSize(size)
    
    val isReady: Boolean
        get() = status == FileStatus.READY
    
    val isProcessing: Boolean
        get() = status == FileStatus.PROCESSING || status == FileStatus.UPLOADING
    
    val hasError: Boolean
        get() = status == FileStatus.ERROR
}

/**
 * 格式化文件大小
 */
private fun formatFileSize(bytes: Long): String {
    return when {
        bytes >= 1024 * 1024 * 1024 -> String.format("%.1f GB", bytes / (1024.0 * 1024 * 1024))
        bytes >= 1024 * 1024 -> String.format("%.1f MB", bytes / (1024.0 * 1024))
        bytes >= 1024 -> String.format("%.1f KB", bytes / 1024.0)
        else -> "$bytes B"
    }
}

/**
 * 学习模式状态
 */
data class StudyModeState(
    val isEnabled: Boolean = false,
    val activeFileIds: Set<String> = emptySet(),
    val totalChunks: Int = 0
)
