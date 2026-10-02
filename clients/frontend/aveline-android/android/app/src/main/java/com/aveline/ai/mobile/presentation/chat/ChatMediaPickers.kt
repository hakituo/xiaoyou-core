package com.aveline.ai.mobile.presentation.chat

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember

/**
 * 聊天页的文件/媒体选择入口集合。
 *
 * 图片、通用文件、录音权限三个 launcher 原本散落在 ChatScreen 顶部，
 * 聚合到这里后 ChatScreen 只持有"选完之后干什么"的回调。
 * 底部输入栏只保留麦克风与"+"，因此不再提供选视频入口。
 */
data class ChatMediaPickers(
    /** 打开系统文件选择器（当前输入栏未暴露入口，保留能力）。 */
    val pickDocument: () -> Unit,
    /** 打开相册选图片（底部"+"号）。 */
    val pickImage: () -> Unit,
    /** 申请录音权限。 */
    val requestRecordAudioPermission: () -> Unit
)

/**
 * 创建聊天页的媒体选择入口。
 *
 * @param onDocumentPicked 选中文件（当前未接入 UI）
 * @param onImagePicked 选中图片
 * @param onRecordPermissionResult 录音权限结果：true 已授权，false 被拒绝
 */
@Composable
fun rememberChatMediaPickers(
    onDocumentPicked: (Uri) -> Unit,
    onImagePicked: (Uri) -> Unit,
    onRecordPermissionResult: (Boolean) -> Unit
): ChatMediaPickers {
    val documentLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? -> uri?.let(onDocumentPicked) }

    val imageLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? -> uri?.let(onImagePicked) }

    val recordAudioLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted: Boolean -> onRecordPermissionResult(granted) }

    return remember(
        documentLauncher,
        imageLauncher,
        recordAudioLauncher
    ) {
        ChatMediaPickers(
            pickDocument = { documentLauncher.launch("*/*") },
            pickImage = { imageLauncher.launch("image/*") },
            requestRecordAudioPermission = {
                recordAudioLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
            }
        )
    }
}
