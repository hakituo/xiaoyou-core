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
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.services.TTSState

/**
 * TTS 播放控制组件
 * 
 * 显示播放按钮和进度条。
 * 
 * @param state TTS 状态
 * @param onPlay 播放回调
 * @param onPause 暂停回调
 * @param onStop 停止回调
 * @param modifier 修饰符
 */
@Composable
fun TTSControls(
    state: TTSState,
    onPlay: () -> Unit,
    onPause: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier
) {
    val isPlaying = state is TTSState.Playing
    val isPaused = state is TTSState.Paused
    val isLoading = state is TTSState.Loading
    val progress = when (state) {
        is TTSState.Playing -> state.progress
        // Paused.position 是毫秒,需除以总时长得到 0-1 进度;duration 为 0 时回退 0
        is TTSState.Paused -> if (state.duration > 0) {
            state.position.toFloat() / state.duration
        } else 0f
        else -> 0f
    }
    
    Row(
        modifier = modifier
            .padding(top = 8.dp)
            .semantics { contentDescription = "TTS 控制器" },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        // 播放/暂停按钮
        IconButton(
            onClick = {
                when {
                    isPlaying -> onPause()
                    isPaused -> onPlay()
                    else -> onPlay()
                }
            },
            modifier = Modifier.size(32.dp)
        ) {
            Icon(
                imageVector = if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                contentDescription = if (isPlaying) "暂停" else "播放",
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(20.dp)
            )
        }
        
        // 进度条
        if (isPlaying || isPaused) {
            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 4.dp),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.surfaceVariant
            )
            
            // 停止按钮
            IconButton(
                onClick = onStop,
                modifier = Modifier.size(32.dp)
            ) {
                Icon(
                    imageVector = Icons.Filled.Stop,
                    contentDescription = "停止",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(18.dp)
                )
            }
        }
        
        // 加载指示器
        if (isLoading) {
            TTSLoadingIndicator()
        }
    }
}

/**
 * TTS 加载指示器
 */
@Composable
private fun TTSLoadingIndicator(
    modifier: Modifier = Modifier
) {
    val infiniteTransition = rememberInfiniteTransition(label = "tts_loading")
    
    val alpha by infiniteTransition.animateFloat(
        initialValue = 0.3f,
        targetValue = 1.0f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 500, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "alpha"
    )
    
    Text(
        text = "加载中...",
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.primary.copy(alpha = alpha),
        modifier = modifier
    )
}

/**
 * 紧凑型 TTS 播放按钮
 * 用于消息气泡
 */
@Composable
fun CompactTTSButton(
    isPlaying: Boolean,
    isLoading: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val infiniteTransition = rememberInfiniteTransition(label = "tts_button")
    
    val scale by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = if (isPlaying) 1.1f else 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 300, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "scale"
    )
    
    IconButton(
        onClick = onClick,
        modifier = modifier
            .size(32.dp)
            .semantics { 
                contentDescription = if (isPlaying) "停止播放" else "播放语音" 
            }
    ) {
        Icon(
            imageVector = if (isPlaying) Icons.Filled.Pause else Icons.Outlined.PlayArrow,
            contentDescription = null,
            tint = if (isLoading) {
                MaterialTheme.colorScheme.primary.copy(alpha = 0.5f)
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            modifier = Modifier
                .size(18.dp)
                .then(if (isPlaying) Modifier.graphicsLayer(scaleX = scale, scaleY = scale) else Modifier)
        )
    }
}

/**
 * TTS 状态指示器
 * 显示在消息气泡旁边
 */
@Composable
fun TTSStatusIndicator(
    state: TTSState,
    messageId: String,
    modifier: Modifier = Modifier
) {
    val isPlayingThisMessage = state is TTSState.Playing && state.messageId == messageId
    val isPausedThisMessage = state is TTSState.Paused && state.messageId == messageId
    
    if (isPlayingThisMessage || isPausedThisMessage) {
        val infiniteTransition = rememberInfiniteTransition(label = "tts_status")
        
        val alpha by infiniteTransition.animateFloat(
            initialValue = 0.5f,
            targetValue = 1.0f,
            animationSpec = infiniteRepeatable(
                animation = tween(durationMillis = 500, easing = FastOutSlowInEasing),
                repeatMode = RepeatMode.Reverse
            ),
            label = "alpha"
        )
        
        Box(
            modifier = modifier
                .size(8.dp)
                .clip(CircleShape)
                .background(
                    color = if (isPlayingThisMessage) {
                        MaterialTheme.colorScheme.primary.copy(alpha = alpha)
                    } else {
                        MaterialTheme.colorScheme.outline
                    }
                )
        )
    }
}
