package com.aveline.ai.mobile.presentation.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import com.aveline.ai.mobile.services.VoiceInputState

/**
 * 聊天页底部区域（从 ChatScreen.kt 拆出）：上传/待发/识别/转写提示条 + 输入栏 + “+”更多面板。
 *
 * 底部 inset 统一在这一层处理，输入栏与更多面板共享同一份：
 * 输入栏自己不再随“面板是否展开”改内边距，高度恒定，
 * 否则开关面板时输入栏（以及“+”按钮）会额外跳一下。
 *
 * @param morePanelHeight “+”面板高度（由 ChatScreen 按最近一次真实键盘高度算好并带下限）
 * @param resolveImageUrl 把后端返回的相对图片地址解析成可加载 URL
 */
@Composable
internal fun ChatBottomArea(
    uiState: ChatUiState,
    morePanelHeight: Dp,
    showMorePanel: Boolean,
    resolveImageUrl: (String) -> String,
    onTextChange: (String) -> Unit,
    onSend: (String) -> Unit,
    onToggleMore: () -> Unit,
    onVoiceInput: () -> Unit,
    onStopGeneration: () -> Unit,
    onCancelPendingImage: () -> Unit,
    onStopVoice: () -> Unit,
    onPickImage: () -> Unit,
    onPickDocument: () -> Unit
) {
    Column(
        modifier = Modifier.windowInsetsPadding(
            WindowInsets.ime.union(WindowInsets.navigationBars)
        )
    ) {
        UploadProgressIndicator(
            uploadState = uiState.uploadState,
            modifier = Modifier.fillMaxWidth()
        )

        uiState.lastUploadedImageUrl?.let { pendingUrl ->
            PendingImageBar(
                imageUrl = resolveImageUrl(pendingUrl),
                onCancel = onCancelPendingImage,
                modifier = Modifier.fillMaxWidth()
            )
        }

        if (uiState.isAnalyzingImage) {
            ImageAnalyzingBar(modifier = Modifier.fillMaxWidth())
        }

        if (uiState.isRecording ||
            uiState.voiceInputState is VoiceInputState.Processing
        ) {
            ChatVoiceTranscribingBar(
                partialText = uiState.voicePartialText,
                amplitude = uiState.voiceAmplitude,
                isProcessing = uiState.voiceInputState is VoiceInputState.Processing,
                onStop = onStopVoice,
                modifier = Modifier.fillMaxWidth()
            )
        }

        ChatBottomBar(
            text = uiState.inputText,
            onTextChange = onTextChange,
            onSend = onSend,
            onMore = onToggleMore,
            onInputFocused = {
                // 输入框 pointer down 已经先处理“更多 -> 键盘”的切换；
                // 这里仅保留接口，不再用 focus 事件抢 showMorePanel 状态。
            },
            onVoiceInput = onVoiceInput,
            isTyping = uiState.isTyping,
            isRecording = uiState.isRecording,
            // 只有"当前会话正在本地生成"才把按钮切成停止。
            // 不能直接用 isTyping：WebSocket 的主动关怀也会把它置起来，
            // 那种回复没有本地任务，停止键会按不动；而且生成可能发生在
            // 另一个会话（用户切走了），用会话 id 比对才不会去停错人。
            canStopGeneration = uiState.generatingSessionId != null &&
                uiState.generatingSessionId == uiState.currentSession?.id,
            onStopGeneration = onStopGeneration,
            hasPendingAttachment = uiState.lastUploadedImageUrl != null,
            showMorePanel = showMorePanel
        )

        // 用 expandVertically / shrinkVertically（从底部生长）而不是 slideInVertically：
        // slide 只改绘制位移、不改占位高度，面板一出现布局就瞬间跳满一整个面板的高度，
        // 输入栏被瞬间顶上去、面板却还在下面滑动，看起来就是一卡一卡地上下跳。
        // 让占位高度跟着动画一起长，输入栏才是被平滑推上去的。
        AnimatedVisibility(
            visible = showMorePanel,
            enter = fadeIn(tween(durationMillis = 160)) +
                expandVertically(
                    animationSpec = tween(durationMillis = 220),
                    expandFrom = Alignment.Bottom
                ),
            exit = fadeOut(tween(durationMillis = 120)) +
                shrinkVertically(
                    animationSpec = tween(durationMillis = 180),
                    shrinkTowards = Alignment.Bottom
                )
        ) {
            ChatMorePanel(
                panelHeight = morePanelHeight,
                onPickImage = onPickImage,
                onPickDocument = onPickDocument
            )
        }
    }
}
