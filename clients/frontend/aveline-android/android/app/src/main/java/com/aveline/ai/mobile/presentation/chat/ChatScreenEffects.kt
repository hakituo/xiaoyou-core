package com.aveline.ai.mobile.presentation.chat

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.widget.Toast
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.platform.LocalContext
import com.aveline.ai.mobile.services.UploadState

/**
 * 聊天页的提示类副作用（从 ChatScreen.kt 拆出）。
 *
 * 只处理「把状态翻译成一条 Snackbar」，不持有任何界面状态；
 * 各 effect 的 key 与原实现一致，避免重复弹或漏弹。
 */

/** 显示错误信息（带"复制"按钮），弹完即通知 ViewModel 清掉错误。 */
@Composable
internal fun ChatErrorSnackbarEffect(
    error: String?,
    snackbarHostState: SnackbarHostState,
    onErrorShown: () -> Unit
) {
    val context = LocalContext.current
    LaunchedEffect(error) {
        error?.let { message ->
            val result = snackbarHostState.showSnackbar(
                message = message,
                actionLabel = "复制",
                duration = SnackbarDuration.Long
            )
            if (result == SnackbarResult.ActionPerformed) {
                copyToClipboard(context, message)
                Toast.makeText(context, "已复制错误信息", Toast.LENGTH_SHORT).show()
            }
            onErrorShown()
        }
    }
}

/** 显示上传结果提示（成功/失败提示完都清状态）。 */
@Composable
internal fun ChatUploadStateEffect(
    uploadState: UploadState,
    snackbarHostState: SnackbarHostState,
    onUploadReset: () -> Unit
) {
    LaunchedEffect(uploadState) {
        when (val state = uploadState) {
            is UploadState.Success -> {
                snackbarHostState.showSnackbar(
                    message = "文件上传成功: ${state.fileName}",
                    duration = SnackbarDuration.Short
                )
                onUploadReset()
            }
            is UploadState.Error -> {
                snackbarHostState.showSnackbar(
                    message = "上传失败: ${state.message}",
                    duration = SnackbarDuration.Short
                )
                // FileUploadManager 是单例，uploadState 常驻；失败态若不清掉，
                // 下次进聊天页 observeUploadState 会立刻收到旧 Error 重放 Snackbar
                onUploadReset()
            }
            else -> {}
        }
    }
}

/** 把文本复制到系统剪贴板。 */
internal fun copyToClipboard(context: Context, text: String) {
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText("error", text))
}
