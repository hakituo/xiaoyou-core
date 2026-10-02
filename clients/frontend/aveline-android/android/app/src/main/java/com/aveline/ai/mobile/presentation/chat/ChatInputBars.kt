package com.aveline.ai.mobile.presentation.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.automirrored.outlined.InsertDriveFile
import androidx.compose.material.icons.outlined.PhotoLibrary
import androidx.compose.foundation.BorderStroke
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.aveline.ai.mobile.presentation.components.AudioWaveform
import com.aveline.ai.mobile.presentation.components.InputArea
import com.aveline.ai.mobile.presentation.theme.CardBorder
// 主题色 Surface 与 Material3 的 Surface 可组合函数同名，起别名避免解析歧义
import com.aveline.ai.mobile.presentation.theme.Surface as SurfaceColor
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.services.UploadState
import com.aveline.ai.mobile.utils.CoilImageModel

/**
 * 聊天页底部输入栏：麦克风 + 输入框 + "+"（更多）/ 发送按钮。
 *
 * "+" 不再直接打开相册，只负责切换聊天更多面板。真正的相册、文件入口在
 * [ChatMorePanel] 中，避免发送按钮切回 "+" 后误触直接弹系统选择器。
 */
@Composable
fun ChatBottomBar(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: (String) -> Unit,
    onMore: () -> Unit,
    onInputFocused: () -> Unit,
    onVoiceInput: () -> Unit,
    isTyping: Boolean,
    isRecording: Boolean,
    /**
     * 当前会话是否有本地发起的生成在跑（决定按钮是「发送」还是「停止」）。
     * 注意不要直接用 [isTyping]：WebSocket 推来的主动关怀也会置 isTyping，
     * 那种回复没有本地任务可停，画成停止键会按不动。
     */
    canStopGeneration: Boolean = false,
    onStopGeneration: (() -> Unit)? = null,
    hasPendingAttachment: Boolean = false,
    showMorePanel: Boolean = false,
    modifier: Modifier = Modifier
) {
    InputArea(
        text = text,
        onTextChange = onTextChange,
        onSend = { onSend(text) },
        onAttach = onMore,
        onVoiceInput = onVoiceInput,
        // 用 pointer down 而不是等 IME 已经开始出现后再关面板。
        // 这样用户从“更多”切回输入框时，面板会先退出，避免被 imePadding 顶上去一截。
        onInputPressed = {
            if (showMorePanel) onMore()
        },
        onInputFocused = onInputFocused,
        isTyping = isTyping,
        isRecording = isRecording,
        canStopGeneration = canStopGeneration,
        onStopGeneration = onStopGeneration,
        hasPendingAttachment = hasPendingAttachment,
        // 底部 inset 统一由聊天页 bottomBar 那一层 Column 处理（输入栏与更多面板共享）。
        // 输入栏不再随“面板是否展开”改变自己的内边距，否则开关面板时它的高度会变，
        // “+”按钮会跟着上下跳一下。
        applyBottomInsets = false,
        placeholder = "输入消息...",
        modifier = modifier
    )
}

/**
 * QQ / 微信式聊天更多面板。
 *
 * "+" 只负责显示本面板；用户在面板里再次选择“相册”或“文件”后，
 * 才真正打开系统选择器。面板高度由 ChatScreen 按最近一次 IME 高度决定，
 * 从键盘切换过来时尽量保持聊天 viewport 不突跳。
 *
 * 配色说明：这里刻意不走 `MaterialTheme.colorScheme.surface + tonalElevation`。
 * M3 的 tonal elevation 会按 primary 往底色里混一层蓝紫调，和整页中性深色
 * （Background #05060A / Surface #121214）放在一起会明显偏色。
 * 面板统一用 App 自己的 Surface 实色 + CardBorder 顶部分隔线，
 * 内部磁贴沿用输入栏那套半透明白玻璃（`Color(0x1AFFFFFF)`）语言。
 */
@Composable
fun ChatMorePanel(
    panelHeight: Dp,
    onPickImage: () -> Unit,
    onPickDocument: () -> Unit,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = SurfaceColor,
        contentColor = TextPrimary,
        tonalElevation = 0.dp,
        shadowElevation = 0.dp,
        border = BorderStroke(1.dp, CardBorder)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .height(panelHeight)
                // 导航栏 inset 由聊天页 bottomBar 那层 Column 统一处理，
                // 这里不再重复叠加，避免面板内部被多扣一段高度。
                .padding(horizontal = 20.dp, vertical = 20.dp)
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(24.dp),
                verticalAlignment = Alignment.Top
            ) {
                ChatMoreAction(
                    icon = Icons.Outlined.PhotoLibrary,
                    label = "相册",
                    onClick = onPickImage
                )
                ChatMoreAction(
                    icon = Icons.AutoMirrored.Outlined.InsertDriveFile,
                    label = "文件",
                    onClick = onPickDocument
                )
            }
        }
    }
}

@Composable
private fun ChatMoreAction(
    icon: ImageVector,
    label: String,
    onClick: () -> Unit
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Surface(
            onClick = onClick,
            modifier = Modifier.size(60.dp),
            shape = RoundedCornerShape(18.dp),
            color = Color(0x1AFFFFFF),
            contentColor = TextPrimary,
            tonalElevation = 0.dp,
            shadowElevation = 0.dp,
            border = BorderStroke(1.dp, CardBorder)
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(
                    imageVector = icon,
                    contentDescription = label,
                    tint = TextPrimary,
                    modifier = Modifier.size(26.dp)
                )
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            color = TextSecondary
        )
    }
}

/**
 * 待发送图片预览条。
 *
 * 选图上传完成后先停在这里让用户确认：输入框里的文字会作为图片文案一起发送，
 * 点取消则丢弃这张已上传的图。
 */
@Composable
fun PendingImageBar(
    imageUrl: String,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val imageModel = remember(imageUrl) { CoilImageModel.build(context, imageUrl) }
    Row(
        modifier = modifier
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        AsyncImage(
            model = imageModel,
            contentDescription = "待发送图片",
            modifier = Modifier
                .size(56.dp)
                .clip(RoundedCornerShape(8.dp)),
            contentScale = ContentScale.Crop
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = "已选好图片，点发送即可发出",
            style = MaterialTheme.typography.labelMedium,
            color = TextSecondary,
            modifier = Modifier.weight(1f)
        )
        IconButton(onClick = onCancel) {
            Icon(
                imageVector = Icons.Filled.Close,
                contentDescription = "取消发送这张图片",
                tint = TextSecondary
            )
        }
    }
}

/**
 * 图片消息发送前的视觉识别提示：后端 chat 通道只收文本，
 * 发图前要先把图片交给视觉模型转成描述。
 */
@Composable
fun ImageAnalyzingBar(modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(16.dp),
            strokeWidth = 2.dp
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = "正在识别图片…",
            style = MaterialTheme.typography.labelMedium,
            color = TextSecondary
        )
    }
}

/** 上传进度指示器：仅在上传中显示文件名与百分比。 */
@Composable
fun UploadProgressIndicator(
    uploadState: UploadState,
    modifier: Modifier = Modifier
) {
    AnimatedVisibility(
        visible = uploadState is UploadState.Uploading,
        enter = fadeIn() + slideInVertically(),
        exit = fadeOut() + slideOutVertically(),
        modifier = modifier
    ) {
        when (uploadState) {
            is UploadState.Uploading -> {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
                        .padding(horizontal = 16.dp, vertical = 8.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.primary
                        )

                        Spacer(modifier = Modifier.width(8.dp))

                        Text(
                            text = "正在上传: ${uploadState.fileName}",
                            style = MaterialTheme.typography.labelMedium,
                            color = TextSecondary
                        )

                        Spacer(modifier = Modifier.weight(1f))

                        Text(
                            text = "${(uploadState.progress * 100).toInt()}%",
                            style = MaterialTheme.typography.labelMedium,
                            color = TextSecondary
                        )
                    }

                    Spacer(modifier = Modifier.height(4.dp))

                    LinearProgressIndicator(
                        progress = { uploadState.progress },
                        modifier = Modifier.fillMaxWidth(),
                        color = MaterialTheme.colorScheme.primary,
                        trackColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                }
            }
            else -> {}
        }
    }
}

/**
 * 语音实时转写条：录音 / 收尾识别期间贴在输入栏上方，把 ASR 的流式中间结果即时上屏。
 *
 * 底层 ASR 本来就是边录边解码（sherpa-ncnn 每 32ms 出一版中间文本，系统识别走 partial results），
 * 这里把 VoiceInputManager 的 partialText 直接展示出来，用户不用等说完才看到字；
 * 右侧按钮可直接停止录音，与点麦克风是同一个动作。
 *
 * @param partialText 实时识别文本（已确认句 + 当前句）
 * @param amplitude 当前音量（0-1），驱动波形起伏
 * @param isProcessing 是否已进入收尾识别阶段（已停止录音、最终结果尚未返回）
 * @param onStop 停止录音回调
 */
@Composable
fun ChatVoiceTranscribingBar(
    partialText: String,
    amplitude: Float,
    isProcessing: Boolean,
    onStop: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
            .padding(start = 16.dp, end = 4.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // 固定高度，避免波形随音量起伏时把整条转写条撑得一跳一跳
        AudioWaveform(
            amplitude = amplitude,
            isRecording = !isProcessing,
            barCount = 4,
            modifier = Modifier.height(28.dp)
        )

        Spacer(modifier = Modifier.width(12.dp))

        Text(
            text = when {
                partialText.isNotBlank() -> partialText
                isProcessing -> "正在识别…"
                else -> "正在聆听…"
            },
            style = MaterialTheme.typography.bodyMedium,
            color = if (partialText.isNotBlank()) TextPrimary else TextSecondary,
            maxLines = 3,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f)
        )

        IconButton(
            onClick = onStop,
            modifier = Modifier.size(36.dp)
        ) {
            Icon(
                imageVector = Icons.Filled.Stop,
                contentDescription = "停止录音",
                tint = MaterialTheme.colorScheme.error,
                modifier = Modifier.size(18.dp)
            )
        }
    }
}