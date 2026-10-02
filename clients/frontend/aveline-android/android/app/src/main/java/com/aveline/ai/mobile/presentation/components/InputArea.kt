@file:Suppress("DEPRECATION")

package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp

/** 输入区域组件（QQ/微信风格）。 */
@Composable
fun InputArea(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    onAttach: (() -> Unit)? = null,
    onVoiceInput: (() -> Unit)? = null,
    onInputPressed: (() -> Unit)? = null,
    onInputFocused: (() -> Unit)? = null,
    isTyping: Boolean = false,
    isRecording: Boolean = false,
    /**
     * 当前会话是否有**本地发起的生成**在跑。
     *
     * 与 [isTyping] 分开传：isTyping 也会被 WebSocket 通道置位（角色主动关怀），
     * 那种回复没有本地任务可取消，此时不能画「停止」按钮 —— 按下去不会有任何反应。
     */
    canStopGeneration: Boolean = false,
    /** 点「停止」的回调；生成期间按钮会从纸飞机切成方块。 */
    onStopGeneration: (() -> Unit)? = null,
    // 这里曾经有个 `enabled: Boolean = true` 形参，唯一调用方 ChatBottomBar 写死传 true，
    // 于是 `enabled && ...` 全是死逻辑、还让人误以为输入栏整体可以禁用。已删掉；
    // 真正需要禁用输入框的是录音态（见下面的 `!isRecording`）。
    hasPendingAttachment: Boolean = false,
    applyBottomInsets: Boolean = true,
    placeholder: String = "输入消息...",
    modifier: Modifier = Modifier
) {
    val interactionSource = remember { MutableInteractionSource() }
    val canSend = text.isNotBlank() || hasPendingAttachment
    val bottomInsetsModifier = if (applyBottomInsets) {
        Modifier.windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))
    } else {
        Modifier
    }

    Surface(
        modifier = modifier
            .fillMaxWidth()
            .then(bottomInsetsModifier)
            .padding(horizontal = 8.dp, vertical = 6.dp),
        color = Color.Transparent,
        tonalElevation = 0.dp
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp, vertical = 4.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            if (onVoiceInput != null) {
                IconButton(
                    onClick = onVoiceInput,
                    modifier = Modifier
                        .size(40.dp)
                        .clip(CircleShape)
                        .background(if (isRecording) Color(0x1AEF4444) else Color(0x1AFFFFFF))
                ) {
                    Icon(
                        imageVector = Icons.Filled.Mic,
                        contentDescription = if (isRecording) "停止录音" else "语音输入",
                        tint = if (isRecording) Color(0xFFEF4444) else Color(0x99FFFFFF),
                        modifier = Modifier.size(22.dp)
                    )
                }
            }

            Box(
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = 40.dp, max = 120.dp)
                    .pointerInput(onInputPressed) {
                        val callback = onInputPressed ?: return@pointerInput
                        awaitEachGesture {
                            awaitFirstDown(
                                requireUnconsumed = false,
                                pass = PointerEventPass.Initial
                            )
                            callback()
                        }
                    }
                    .clip(RoundedCornerShape(20.dp))
                    .background(Color(0x1AFFFFFF))
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                contentAlignment = Alignment.CenterStart
            ) {
                BasicTextField(
                    value = text,
                    onValueChange = onTextChange,
                    enabled = !isRecording,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(color = Color.White),
                    cursorBrush = SolidColor(Color.White),
                    // 输入法自带的动作键不再发送：退回多行输入的默认行为，
                    // 回车 / 换行键只负责换行（配合 maxLines = 4），发送只由右侧纸飞机按钮触发。
                    // 之前是 ImeAction.Send + KeyboardActions(onSend = ...)，键盘上的"发送"键会
                    // 直接捅进 onSend()，用户想换行却被发了出去。
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Default),
                    interactionSource = interactionSource,
                    maxLines = 4,
                    modifier = Modifier
                        .fillMaxWidth()
                        .onFocusChanged { state ->
                            if (state.isFocused) onInputFocused?.invoke()
                        }
                        .semantics { contentDescription = "消息输入框" },
                    decorationBox = { innerTextField ->
                        if (text.isEmpty()) {
                            Text(
                                text = if (isTyping) "正在输入..." else placeholder,
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color(0x4DFFFFFF)
                            )
                        }
                        innerTextField()
                    }
                )
            }

            if (canSend || onAttach != null) {
                // 同一个按钮承担三种语义，优先级：录音 > 停止 > 发送 > 更多。
                //
                // 「停止」让位给「发送」：用户一打字，按钮就切回纸飞机且**可点**。
                // 这是 ChatGPT 的行为，也和后端一致 —— 同一会话发新请求时后端会
                // cancel 上一轮（stream_orchestrator 的 prev_task），所以"边生成边发"
                // 本来就只会有最新一轮产出。之前那个发送分支判 `!isTyping`，
                // 结果生成期间打字看到的是一个禁用发送键，等于"UI 拦掉了管线支持的动作"。
                val showStop = canStopGeneration && onStopGeneration != null && !canSend && !isRecording
                val actionEnabled = when {
                    // 录音中一切动作都停：结束录音有自己的入口（ChatVoiceTranscribingBar），
                    // 这里若可点，输入框里那段文字会在录音还没转完时被误发出去。
                    isRecording -> false
                    showStop -> true
                    // 生成期间允许再发一条，但**只对本地发起的生成**成立：
                    // WebSocket 推来的主动关怀（同样会置 isTyping）没有本地任务可取消，
                    // 此时放开会让新发送把 httpStreamingActive 抢过来，
                    // 对方还在流的那段正文会被整段丢掉。
                    canSend -> !isTyping || canStopGeneration
                    else -> onAttach != null
                }
                val containerColor by animateColorAsState(
                    targetValue = when {
                        showStop -> Color(0x1AEF4444)
                        canSend -> Color(0x2A38BDF8)
                        else -> Color(0x1AFFFFFF)
                    },
                    animationSpec = tween(durationMillis = 200),
                    label = "input_action_container"
                )
                val iconTint by animateColorAsState(
                    targetValue = when {
                        showStop -> Color(0xFFEF4444)
                        canSend -> Color(0xFFE2E8F0)
                        else -> Color(0x99FFFFFF)
                    },
                    animationSpec = tween(durationMillis = 200),
                    label = "input_action_tint"
                )
                IconButton(
                    onClick = {
                        when {
                            showStop -> onStopGeneration?.invoke()
                            canSend -> onSend()
                            else -> onAttach?.invoke()
                        }
                    },
                    enabled = actionEnabled,
                    modifier = Modifier
                        .size(40.dp)
                        .clip(CircleShape)
                        .background(containerColor)
                        // M3 的"禁用变暗"是通过 LocalContentColor 生效的，而这里每个 Icon
                        // 都显式传了 tint，把它覆盖掉了 —— 不加这层 alpha 就会出现
                        // "亮着蓝底纸飞机、点下去没反应"的假按钮（这正是最初要查的问题）。
                        .alpha(if (actionEnabled) 1f else 0.45f)
                ) {
                    if (showStop) {
                        StopIcon(tint = iconTint)
                    } else {
                        SendMoreIcon(canSend = canSend, tint = iconTint)
                    }
                }
            }
        }
    }
}

/**
 * 停止图标：实心圆角方块。
 *
 * 尺寸对齐 [SendMoreIcon] 的 22dp 画布，让两种状态切换时按钮内的视觉重量不跳。
 * 不用 `Icons.Filled.Stop`：它自带的方块只有约 14/24 的边长，铺在 22dp 画布里
 * 比纸飞机显得瘦一圈，切换时会有明显的"缩一下"。
 */
@Composable
private fun StopIcon(
    tint: Color,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
            .size(22.dp)
            .semantics { contentDescription = "停止生成" },
        contentAlignment = Alignment.Center
    ) {
        Box(
            modifier = Modifier
                .size(13.dp)
                .clip(RoundedCornerShape(3.dp))
                .background(tint)
        )
    }
}

@Composable
private fun SendMoreIcon(
    canSend: Boolean,
    tint: Color,
    modifier: Modifier = Modifier
) {
    val sendProgress by animateFloatAsState(
        targetValue = if (canSend) 1f else 0f,
        animationSpec = tween(durationMillis = 220),
        label = "send_more_progress"
    )
    val plusProgress = 1f - sendProgress

    Box(
        modifier = modifier
            .size(22.dp)
            .semantics { contentDescription = if (canSend) "发送" else "更多" },
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = Icons.Filled.Add,
            contentDescription = null,
            tint = tint,
            modifier = Modifier
                .size(22.dp)
                .graphicsLayer {
                    alpha = plusProgress
                    scaleX = 0.7f + 0.3f * plusProgress
                    scaleY = scaleX
                    rotationZ = 45f * sendProgress
                }
        )
        Icon(
            imageVector = Icons.Filled.Send,
            contentDescription = null,
            tint = tint,
            modifier = Modifier
                .size(20.dp)
                .graphicsLayer {
                    alpha = sendProgress
                    scaleX = 0.6f + 0.4f * sendProgress
                    scaleY = scaleX
                    rotationZ = -45f * plusProgress
                }
        )
    }
}

