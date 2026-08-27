package com.aveline.ai.mobile.presentation.chat

import android.net.Uri
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.services.FileUploadManager
import com.aveline.ai.mobile.services.UploadState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 文件上传助手
 *
 * 负责文件/图片的上传、状态观察和图片消息发送，
 * 将上传相关逻辑从 ViewModel 中分离。
 *
 * @param scope             ViewModel 的协程作用域
 * @param uiState           UI 状态流
 * @param fileUploadManager 文件上传管理器
 * @param appPreferences    应用偏好设置（提供后端地址和 token）
 * @param chatRepository    聊天仓库（用于发送图片消息）
 */
class ChatUploadHelper(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val fileUploadManager: FileUploadManager,
    private val appPreferences: AppPreferences,
    private val chatRepository: ChatRepository
) {
    /**
     * 初始化上传管理器：设置后端地址和访问令牌
     */
    fun init() {
        fileUploadManager.setBackendUrl(appPreferences.backendUrl)
        fileUploadManager.setAccessToken(appPreferences.accessToken)
    }

    /**
     * 观察上传状态流，同步到 UI 状态
     */
    fun observeUploadState() {
        scope.launch {
            fileUploadManager.uploadState.collect { state ->
                uiState.update { it.copy(uploadState = state) }
                if (state is UploadState.Success) {
                    uiState.update { it.copy(lastUploadedImageUrl = state.fileUrl) }
                }
            }
        }
    }

    /**
     * 上传文件
     *
     * @param uri     文件 Uri
     * @param isImage 是否为图片
     */
    fun uploadFile(uri: Uri, isImage: Boolean = false) {
        scope.launch {
            // getFileInfo 现在是 suspend + 内部 withContext(IO),无需再切调度器
            val fileInfo = fileUploadManager.getFileInfo(uri)
            if (fileInfo == null) {
                uiState.update { it.copy(error = "无法读取文件信息") }
                return@launch
            }
            if (!fileUploadManager.validateFileSize(fileInfo.size, isImage)) {
                uiState.update { it.copy(error = "文件大小超过限制 (最大 10MB)") }
                return@launch
            }
            val result = fileUploadManager.uploadFile(uri, isImage)
            if (result.success) {
                if (isImage && result.fileUrl != null) {
                    uiState.update { it.copy(lastUploadedImageUrl = result.fileUrl, error = null) }
                }
            } else {
                uiState.update { it.copy(error = result.error ?: "上传失败") }
            }
        }
    }

    /** 上传图片（[uploadFile] 的便捷封装） */
    fun uploadImage(uri: Uri) {
        uploadFile(uri, isImage = true)
    }

    /** 重置上传状态 */
    fun resetUploadState() {
        fileUploadManager.resetState()
    }

    /**
     * 发送图片消息
     *
     * @param imageUrl 图片 URL
     * @param caption  附带文字（可选）
     */
    fun sendImageMessage(imageUrl: String, caption: String = "") {
        val sessionId = uiState.value.currentSession?.id
        scope.launch {
            uiState.update { it.copy(isTyping = true, showTypingIndicator = true, error = null) }
            val messageText = if (caption.isNotBlank()) "[图片: $imageUrl]\n$caption" else "[图片: $imageUrl]"
            val result = chatRepository.sendMessage(messageText, sessionId, "default")
            result.fold(
                onSuccess = {
                    uiState.update {
                        it.copy(
                            lastUploadedImageUrl = null,
                            // 成功后也要清除 typing 状态,否则指示器会永久停留
                            isTyping = false,
                            showTypingIndicator = false
                        )
                    }
                },
                onFailure = { e ->
                    uiState.update { it.copy(error = "发送失败: ${e.message}", isTyping = false, showTypingIndicator = false) }
                }
            )
        }
    }

    /** 判断 MIME 类型是否为支持的图片类型 */
    fun isSupportedImageType(mimeType: String): Boolean =
        fileUploadManager.isSupportedImageType(mimeType)

    /** 获取文件信息(现为 suspend 内部 IO,保持对外接口一致) */
    suspend fun getFileInfo(uri: Uri) = fileUploadManager.getFileInfo(uri)
}
