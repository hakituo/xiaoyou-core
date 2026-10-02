package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import com.aveline.ai.mobile.presentation.theme.EmotionColorMapping
import com.aveline.ai.mobile.presentation.theme.EmotionState

/**
 * 呼吸灯背景组件
 * 
 * 采用 Web 版风格：基于 Canvas 的动态光斑效果 (Emerald/Blue/Indigo/Violet)
 * 使用平滑的颜色过渡动画，与 Web 端效果一致
 */
@Composable
fun BreathingBackground(
    modifier: Modifier = Modifier,
    emotion: String? = null,
    @Suppress("UNUSED_PARAMETER")
    emotionColors: List<String> = emptyList(),
    backgroundAlpha: Float = 1f
) {
    val infiniteTransition = rememberInfiniteTransition(label = "BreathingBackground")
    
    // Parse emotion state and get target colors from EmotionColorMapping
    val emotionState = remember(emotion) {
        EmotionState.fromString(emotion ?: "neutral")
    }
    
    val targetColorScheme = remember(emotionState) {
        EmotionColorMapping.getColorsForEmotion(emotionState)
    }
    
    // Breathing animation scales (continue to accelerate during typing state)
    val scale1 by infiniteTransition.animateFloat(
        initialValue = 0.8f,
        targetValue = 1.2f,
        animationSpec = infiniteRepeatable(
            animation = tween(5000, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "Blob1Scale"
    )
    
    val scale2 by infiniteTransition.animateFloat(
        initialValue = 1.1f,
        targetValue = 0.9f,
        animationSpec = infiniteRepeatable(
            animation = tween(5500, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "Blob2Scale"
    )

    val scale3 by infiniteTransition.animateFloat(
        initialValue = 0.95f,
        targetValue = 1.1f,
        animationSpec = infiniteRepeatable(
            animation = tween(6000, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "Blob3Scale"
    )

    Canvas(
        modifier = modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background.copy(alpha = backgroundAlpha))
    ) {
        val w = size.width
        val h = size.height
        val maxDim = maxOf(w, h)

        // Blob 1: Uses color 0 and 1
        val center1 = Offset(w * 0.2f, h * 0.3f)
        val radius1 = maxDim * 0.5f * scale1
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(targetColorScheme.colors[0].copy(alpha = 0.3f), Color.Transparent),
                center = center1,
                radius = radius1
            ),
            radius = radius1,
            center = center1
        )

        // Blob 2: Uses color 1 and 2
        val center2 = Offset(w * 0.8f, h * 0.7f)
        val radius2 = maxDim * 0.5f * scale2
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(targetColorScheme.colors[1].copy(alpha = 0.3f), Color.Transparent),
                center = center2,
                radius = radius2
            ),
            radius = radius2,
            center = center2
        )

        // Blob 3: Uses color 2 and 3
        val center3 = Offset(w * 0.55f, h * 0.45f)
        val radius3 = maxDim * 0.42f * scale3
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(targetColorScheme.colors[2].copy(alpha = 0.24f), Color.Transparent),
                center = center3,
                radius = radius3
            ),
            radius = radius3,
            center = center3
        )

        // Top blob: Uses color 3
        val topCenter = Offset(w * 0.5f, h * 0.02f)
        val topRadius = maxDim * 0.38f
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(targetColorScheme.colors[3].copy(alpha = 0.2f), Color.Transparent),
                center = topCenter,
                radius = topRadius
            ),
            radius = topRadius,
            center = topCenter
        )
    }
}
