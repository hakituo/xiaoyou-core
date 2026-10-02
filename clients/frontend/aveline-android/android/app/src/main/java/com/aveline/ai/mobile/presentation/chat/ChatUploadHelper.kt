package com.aveline.ai.mobile.presentation.chat

import android.net.Uri
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.domain.repository.ToolsRepository
import com.aveline.ai.mobile.services.FileUploadManager
import com.aveline.ai.mobile.services.UploadKind
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 文件上传助手
 *
 * 负责文件/图片/视频的上传、状态观察和媒体消息发送，
 * 将上传相关逻辑从 ViewModel 中分离。
 *
 * 图片发送流程：
 * 1. 选图 → 上传 → 地址暂存在 ChatUiState.lastUploadedImageUrl（待发送）；
 * 2. 点发送 → 直接发送 `[图片: url]` 附件标记，不在 Android 端提前调用视觉模型；
 * 3. 后端把附件标记还原成标准 OpenAI `image_url` 多模态内容，再由统一视觉路由决定：
 *    当前主模型原生支持视觉时直接看原图，纯文本模型才走 VL 中转描述。
 *
 * 视频发送流程：
 * 1. 选视频 → 上传 → 地址暂存在 ChatUiState.pendingVideoUrl（待发送）；
 * 2. 点发送 → 直接以 `[视频: url]` 作为用户消息文本发出（后端暂无视频理解能力，
 *    不做视觉识别），本地气泡渲染播放器 + 用户文案。
 *
 * @param scope             ViewModel 的协程作用域
 * @param uiState           UI 状态流
 * @param fileUploadManager 文件上传管理器
 * @param appPreferences    应用偏好设置（提供后端地址和 token）
 * @param toolsRepository   保留现有构造注入兼容；图片发送不再通过它预先调用视觉接口
 * @param sendMediaMessage  把组装好的文本交给发送流程（HTTP SSE 流式回复）
 */
class ChatUploadHelper(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val fileUploadManager: FileUploadManager,
    private val appPreferences: AppPreferences,
    toolsRepository: ToolsRepository,
    private val sendMediaMessage: (text: String, imageUrl: String?, videoUrl: String?, displayText: String) -> Unit
) {
    /**
     * 初始化上传管理器：设置后端地址和访问令牌
     *
     * 地址取裁决结果（effectiveBackendUrl），上传才会跟着聊天一起在局域网/公网之间切换。
     */
    fun init() {
        fileUploadManager.setBackendUrl(appPreferences.effectiveBackendUrl)
        fileUploadManager.setAccessToken(appPreferences.accessToken)
    }

    /**
     * 观察上传状态流，同步到 UI 状态
     */
    fun observeUploadState() {
        scope.launch {
            // 只同步上传进度/结果；待发送图片由 uploadFile 在"确认是图片"时写入，
            // 避免上传文档等非图片文件也被塞进图片预览条
            fileUploadManager.uploadState.collect { state ->
                uiState.update { it.copy(uploadState = state) }
            }
        }
    }

    /**
     * 上传文件
     *
     * @param uri  文件 Uri
     * @param kind 上传用途（决定体积上限与 MIME 白名单）
     */
    fun uploadFile(uri: Uri, kind: UploadKind) {
        scope.launch {
            // getFileInfo 现在是 suspend + 内部 withContext(IO),无需再切调度器
            val fileInfo = fileUploadManager.getFileInfo(uri)
            if (fileInfo == null) {
                uiState.update { it.copy(error = "无法读取文件信息") }
                return@launch
            }
            if (!fileUploadManager.validateFileSize(fileInfo.size, kind)) {
                val limitMB = maxSizeBytes(kind) / (1024 * 1024)
                uiState.update { it.copy(error = "文件大小超过限制 (最大 ${limitMB}MB)") }
                return@launch
            }
            val result = fileUploadManager.uploadFile(uri, kind)
            if (result.success) {
                when (kind) {
                    UploadKind.IMAGE -> result.fileUrl?.let { url ->
                        uiState.update { state -> state.copy(lastUploadedImageUrl = url, error = null) }
                    }
                    UploadKind.VIDEO -> result.fileUrl?.let { url ->
                        uiState.update { state -> state.copy(pendingVideoUrl = url, error = null) }
                    }
                    UploadKind.DOCUMENT -> uiState.update { state -> state.copy(error = null) }
                }
            } else {
                uiState.update { it.copy(error = result.error ?: "上传失败") }
            }
        }
    }

    /** 上传图片（[uploadFile] 的便捷封装） */
    fun uploadImage(uri: Uri) = uploadFile(uri, UploadKind.IMAGE)

    /** 上传视频（[uploadFile] 的便捷封装） */
    fun uploadVideo(uri: Uri) = uploadFile(uri, UploadKind.VIDEO)

    /** 重置上传状态 */
    fun resetUploadState() {
        fileUploadManager.resetState()
    }

    /**
     * 发送待发送的图片消息。
     *
     * 这里只发送附件标记，不再先做一次视觉描述。这样原生多模态主模型能直接看到原图；
     * 后端统一视觉路由只会在主模型为纯文本时调用 VL 中转。
     *
     * @param imageUrl 上传得到的图片地址（相对路径，如 /output/image/uploads/x.jpg）
     * @param caption  附带文字（可选）
     */
    fun sendImageMessage(imageUrl: String, caption: String = "") {
        val url = imageUrl.trim()
        if (url.isEmpty()) return
        uiState.update {
            it.copy(
                lastUploadedImageUrl = null,
                isAnalyzingImage = false,
                isTyping = true,
                showTypingIndicator = true,
                error = null
            )
        }
        sendMediaMessage(ImageMessageText.buildAttachment(url, caption), url, null, caption)
    }

    /**
     * 发送待发送的视频消息。
     *
     * 后端 chat 通道只收文本且没有视频理解能力，所以这里不做视觉识别，
     * 直接把地址放进文本（与图片附件标记口径一致），
     * 本地气泡按 videoUrl 渲染播放器。
     *
     * @param videoUrl 上传得到的视频地址（相对路径，如 /output/video/uploads/x.mp4）
     * @param caption  附带文字（可选）
     */
    fun sendVideoMessage(videoUrl: String, caption: String = "") {
        val url = videoUrl.trim()
        if (url.isEmpty()) return
        uiState.update {
            it.copy(
                pendingVideoUrl = null,
                isTyping = true,
                showTypingIndicator = true,
                error = null
            )
        }
        sendMediaMessage(VideoMessageText.build(url, caption), null, url, caption)
    }

    /** 取消待发送的图片（选完图又不想发了）。 */
    fun clearPendingImage() {
        uiState.update { it.copy(lastUploadedImageUrl = null) }
    }

    /** 取消待发送的视频（选完视频又不想发了）。 */
    fun clearPendingVideo() {
        uiState.update { it.copy(pendingVideoUrl = null) }
    }

    /** 判断 MIME 类型是否为支持的图片类型 */
    fun isSupportedImageType(mimeType: String): Boolean =
        fileUploadManager.isSupportedImageType(mimeType)

    /** 判断 MIME 类型是否为支持的视频类型 */
    fun isSupportedVideoType(mimeType: String): Boolean =
        fileUploadManager.isSupportedVideoType(mimeType)

    /** 获取文件信息(现为 suspend 内部 IO,保持对外接口一致) */
    suspend fun getFileInfo(uri: Uri) = fileUploadManager.getFileInfo(uri)

    private fun maxSizeBytes(kind: UploadKind): Long = when (kind) {
        UploadKind.IMAGE -> FileUploadManager.MAX_IMAGE_SIZE
        UploadKind.VIDEO -> FileUploadManager.MAX_VIDEO_SIZE
        UploadKind.DOCUMENT -> FileUploadManager.MAX_FILE_SIZE
    }
}
