@file:Suppress("DEPRECATION")

package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.outlined.AttachFile
import androidx.compose.material.icons.outlined.KeyboardVoice
import androidx.compose.material.icons.outlined.Send
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.theme.BorderLight
import com.aveline.ai.mobile.presentation.theme.InteractivePrimary
import com.aveline.ai.mobile.presentation.theme.TextMuted
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary

/**
 * 输入区域组件（QQ/微信风格）
 *
 * 布局：
 * - 左侧：语音输入按钮
 * - 中间：自适应高度输入框
 * - 右侧：有内容时显示发送按钮，无内容时显示"+"按钮
 *
 * @param text 当前输入文本
 * @param onTextChange 文本变化回调
 * @param onSend 发送回调
 * @param onAttach 附件/更多按钮点击回调
 * @param onVoiceInput 语音输入回调
 * @param isTyping 是否正在输入
 * @param isRecording 是否正在录音
 * @param enabled 是否启用
 * @param placeholder 占位文本
 * @param modifier 修饰符
 */
@Composable
fun InputArea(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    onAttach: (() -> Unit)? = null,
    @Suppress("UNUSED_PARAMETER")
    onImagePick: (() -> Unit)? = null,
    onVoiceInput: (() -> Unit)? = null,
    isTyping: Boolean = false,
    isRecording: Boolean = false,
    enabled: Boolean = true,
    placeholder: String = "输入消息...",
    modifier: Modifier = Modifier
) {
    val interactionSource = remember { MutableInteractionSource() }

    Surface(
        modifier = modifier
            .fillMaxWidth()
            .imePadding()
            .navigationBarsPadding()
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
            // 语音按钮（左侧）
            if (onVoiceInput != null) {
                IconButton(
                    onClick = onVoiceInput,
                    enabled = enabled,
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
            
            // 输入框（中间，自适应高度）
            Box(
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = 40.dp, max = 120.dp)
                    .clip(RoundedCornerShape(20.dp))
                    .background(Color(0x1AFFFFFF))
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                contentAlignment = Alignment.CenterStart
            ) {
                BasicTextField(
                    value = text,
                    onValueChange = onTextChange,
                    enabled = enabled && !isRecording,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(
                        color = Color.White
                    ),
                    cursorBrush = SolidColor(Color.White),
                    keyboardOptions = KeyboardOptions(
                        imeAction = ImeAction.Send
                    ),
                    keyboardActions = KeyboardActions(
                        onSend = {
                            if (text.isNotBlank()) {
                                onSend()
                            }
                        }
                    ),
                    interactionSource = interactionSource,
                    maxLines = 4,
                    modifier = Modifier
                        .fillMaxWidth()
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
            
            // 右侧按钮:有内容时显示发送,无内容时显示"+"(用 AnimatedContent 平滑切换)
            AnimatedContent(
                targetState = text.isNotBlank(),
                transitionSpec = {
                    (scaleIn(tween(200)) + fadeIn(tween(200))) togetherWith
                    (scaleOut(tween(200)) + fadeOut(tween(200)))
                },
                label = "sendButtonTransition"
            ) { isSend ->
                if (isSend) {
                    // 发送按钮
                    IconButton(
                        onClick = onSend,
                        enabled = !isTyping && enabled,
                        modifier = Modifier
                            .size(40.dp)
                            .clip(CircleShape)
                            .background(Color(0x2A38BDF8))
                    ) {
                        Icon(
                            imageVector = Icons.Filled.Send,
                            contentDescription = "发送",
                            tint = Color(0xFFE2E8F0),
                            modifier = Modifier.size(20.dp)
                        )
                    }
                } else {
                    // + 号按钮
                    if (onAttach != null) {
                        IconButton(
                            onClick = onAttach,
                            enabled = enabled && !isRecording,
                            modifier = Modifier
                                .size(40.dp)
                                .clip(CircleShape)
                                .background(Color(0x1AFFFFFF))
                        ) {
                            Icon(
                                imageVector = Icons.Filled.Add,
                                contentDescription = "更多",
                                tint = Color(0x99FFFFFF),
                                modifier = Modifier.size(22.dp)
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * 录音指示器
 * 显示在输入区域上方，表示正在录音
 */
@Composable
fun RecordingIndicator(
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        // 录音动画点
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(
                    MaterialTheme.colorScheme.error,
                    CircleShape
                )
        )
        
        Spacer(modifier = Modifier.width(8.dp))
        
        Text(
            text = "正在录音...",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.error
        )
    }
}

/**
 * 紧凑型输入区域
 * 用于空间受限的场景
 */
@Composable
fun CompactInputArea(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "输入...",
    enabled: Boolean = true
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(24.dp)),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            BasicTextField(
                value = text,
                onValueChange = onTextChange,
                enabled = enabled,
                textStyle = MaterialTheme.typography.bodyMedium.copy(
                    color = TextPrimary
                ),
                cursorBrush = SolidColor(InteractivePrimary),
                keyboardOptions = KeyboardOptions(
                    imeAction = ImeAction.Send
                ),
                keyboardActions = KeyboardActions(
                    onSend = {
                        if (text.isNotBlank()) {
                            onSend()
                        }
                    }
                ),
                modifier = Modifier.weight(1f),
                decorationBox = { innerTextField ->
                    if (text.isEmpty()) {
                        Text(
                            text = placeholder,
                            style = MaterialTheme.typography.bodyMedium,
                            color = TextMuted
                        )
                    }
                    innerTextField()
                }
            )
            
            IconButton(
                onClick = {
                    if (text.isNotBlank()) {
                        onSend()
                    }
                },
                enabled = enabled && text.isNotBlank()
            ) {
                Icon(
                    imageVector = Icons.Filled.Send,
                    contentDescription = "发送",
                    tint = if (text.isNotBlank()) InteractivePrimary else TextMuted,
                    modifier = Modifier.size(20.dp)
                )
            }
        }
    }
}
