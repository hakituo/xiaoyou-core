package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardVoice
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.services.VoiceInputState

/**
 * 语音输入指示器组件
 * 
 * 显示录音状态和波形可视化。
 * 
 * @param state 语音输入状态
 * @param amplitude 当前音量幅度 (0-1)
 * @param partialText 部分识别文本
 * @param onStop 停止录音回调
 * @param modifier 修饰符
 */
@Composable
fun VoiceInputIndicator(
    state: VoiceInputState,
    amplitude: Float = 0f,
    partialText: String = "",
    onStop: () -> Unit,
    modifier: Modifier = Modifier
) {
    val isRecording = state is VoiceInputState.Recording
    val isProcessing = state is VoiceInputState.Processing
    
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .semantics { contentDescription = "语音输入指示器" },
        shape = RoundedCornerShape(24.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.9f),
        tonalElevation = 4.dp
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            when {
                isRecording -> {
                    // 录音中状态
                    RecordingAnimation(
                        amplitude = amplitude,
                        onStop = onStop
                    )
                    
                    if (partialText.isNotBlank()) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = partialText,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
                
                isProcessing -> {
                    // 处理中状态
                    ProcessingIndicator()
                }
                
                state is VoiceInputState.Error -> {
                    // 错误状态
                    Text(
                        text = state.message,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error
                    )
                }
                
                else -> {
                    // 准备状态
                    Text(
                        text = "点击麦克风开始录音",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

/**
 * 录音动画组件
 */
@Composable
private fun RecordingAnimation(
    amplitude: Float,
    onStop: () -> Unit,
    modifier: Modifier = Modifier
) {
    val infiniteTransition = rememberInfiniteTransition(label = "recording")
    
    // 脉冲动画
    val pulseScale by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = 1.2f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 500, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pulse"
    )
    
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        // 波形可视化
        AudioWaveform(
            amplitude = amplitude,
            isRecording = true,
            modifier = Modifier.height(40.dp)
        )
        
        Spacer(modifier = Modifier.height(16.dp))
        
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // 录音状态文本
            Text(
                text = "正在录音...",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.error
            )
            
            // 停止按钮
            IconButton(
                onClick = onStop,
                modifier = Modifier
                    .size(48.dp)
                    .scale(pulseScale)
                    .background(
                        color = MaterialTheme.colorScheme.error,
                        shape = CircleShape
                    )
                    .semantics { contentDescription = "停止录音" }
            ) {
                Icon(
                    imageVector = Icons.Filled.Stop,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(24.dp)
                )
            }
        }
    }
}

/**
 * 处理中指示器
 */
@Composable
private fun ProcessingIndicator(
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        // 加载动画点:共享一个 infiniteTransition,避免在 repeat 内多次创建
        val infiniteTransition = rememberInfiniteTransition(label = "processing")
        repeat(3) { index ->
            val alpha by infiniteTransition.animateFloat(
                initialValue = 0.3f,
                targetValue = 1.0f,
                animationSpec = infiniteRepeatable(
                    animation = tween(
                        durationMillis = 400,
                        delayMillis = index * 150,
                        easing = FastOutSlowInEasing
                    ),
                    repeatMode = RepeatMode.Reverse
                ),
                label = "alpha_$index"
            )

            Box(
                modifier = Modifier
                    .size(8.dp)
                    .background(
                        color = MaterialTheme.colorScheme.primary.copy(alpha = alpha),
                        shape = CircleShape
                    )
            )
        }
        
        Spacer(modifier = Modifier.width(8.dp))
        
        Text(
            text = "正在识别...",
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.primary
        )
    }
}

/**
 * 音频波形可视化组件
 * 
 * @param amplitude 当前音量幅度 (0-1)
 * @param isRecording 是否正在录音
 * @param barCount 波形条数量
 * @param modifier 修饰符
 */
@Composable
fun AudioWaveform(
    amplitude: Float,
    isRecording: Boolean,
    barCount: Int = 5,
    modifier: Modifier = Modifier
) {
    val infiniteTransition = rememberInfiniteTransition(label = "waveform")
    
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        repeat(barCount) { index ->
            // 计算每个条的动画相位偏移
            val phaseOffset = index * 100
            
            val animatedHeight by infiniteTransition.animateFloat(
                initialValue = 0.3f,
                targetValue = if (isRecording) 0.3f + amplitude * 0.7f else 0.3f,
                animationSpec = infiniteRepeatable(
                    animation = tween(
                        durationMillis = 200,
                        delayMillis = phaseOffset,
                        easing = FastOutSlowInEasing
                    ),
                    repeatMode = RepeatMode.Reverse
                ),
                label = "height_$index"
            )
            
            // 根据位置计算高度系数（中间的条更高）
            val centerFactor = 1f - kotlin.math.abs(index - barCount / 2f) / (barCount / 2f)
            val heightFactor = 0.5f + centerFactor * 0.5f
            
            Box(
                modifier = Modifier
                    .width(4.dp)
                    .height((40 * animatedHeight * heightFactor).dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(
                        color = if (isRecording) {
                            MaterialTheme.colorScheme.error
                        } else {
                            MaterialTheme.colorScheme.primary
                        }
                    )
            )
        }
    }
}

/**
 * 紧凑型录音按钮
 * 用于输入区域
 */
@Composable
fun CompactVoiceButton(
    isRecording: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val infiniteTransition = rememberInfiniteTransition(label = "voice_button")
    
    val scale by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = if (isRecording) 1.1f else 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 300, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "scale"
    )
    
    IconButton(
        onClick = onClick,
        modifier = modifier
            .size(48.dp)
            .scale(scale)
            .background(
                color = if (isRecording) {
                    MaterialTheme.colorScheme.error
                } else {
                    MaterialTheme.colorScheme.surfaceVariant
                },
                shape = CircleShape
            )
            .semantics { 
                contentDescription = if (isRecording) "停止录音" else "开始录音" 
            }
    ) {
        Icon(
            imageVector = Icons.Filled.KeyboardVoice,
            contentDescription = null,
            tint = if (isRecording) {
                Color.White
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            modifier = Modifier.size(24.dp)
        )
    }
}
