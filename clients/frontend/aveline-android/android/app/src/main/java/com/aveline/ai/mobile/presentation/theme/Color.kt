package com.aveline.ai.mobile.presentation.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * Aveline app color palette.
 * Matches the Web frontend design system.
 */

// Background colors
val Background = Color(0xFF05060A) // Web: bg-900
val Surface = Color(0xFF121214) // Web: dark.surface
val SurfaceVariant = Color(0xFF18181B) // Web: dark.card
val SurfaceLight = Color(0xFF27272A) // Web: dark.border

// Text colors
val TextPrimary = Color(0xFFE2E8F0)
val TextSecondary = Color(0xFF94A3B8)
val TextTertiary = Color(0xFF64748B)
val TextMuted = Color(0xFF475569)
val TitleText = TextSecondary

// Brand colors
val Primary = Color(0xFF0EA5E9) // Web: primary-500
val PrimaryVariant = Color(0xFF38BDF8) // Web: primary-400

// Emotion colors
val EmotionGreen = Color(0xFF10B981)
val EmotionBlue = Color(0xFF38BDF8)
val EmotionPurple = Color(0xFF8B5CF6)
val EmotionYellow = Color(0xFFFBBF24)
val EmotionRed = Color(0xFFEF4444)
val EmotionPink = Color(0xFFEC4899)

// Status colors
val StatusOnline = Color(0xFF10B981)
val StatusOffline = Color(0xFFEF4444)
val StatusConnecting = Color(0xFFFBBF24)

// UI colors
val BorderColor = Color(0xFF27272A) // Web: dark.border
val BorderLight = Color(0x1A000000)
val DividerColor = Color(0x1A000000)
val CardBackground = Color(0x33000000) // 统一卡片背景色(半透明黑)
val CardBorder = Color(0x14FFFFFF) // 统一卡片边框色(半透明白)
val CardRadius = 16.dp // 统一卡片圆角

// Overlay colors
val OverlayLight = Color(0x0D000000)
val OverlayMedium = Color(0x1A000000)
val OverlayDark = Color(0x66000000) // Web: black/40

// Message bubble colors
val BubbleUser = Color(0x0D000000)
val BubbleAI = Color(0x66000000) // Web: black/40 (Glass panel)
val BubbleSystem = Color(0x1A000000)

// Interactive colors
val InteractivePrimary = Primary
val InteractiveSecondary = EmotionPurple
val InteractiveHover = Color(0x1A000000)
val InteractivePressed = Color(0x0D000000)

// 低饱和界面强调色：用于选中态与生命面板，避免高亮蓝和多组霓虹色抢视觉。
val SelectionSurface = Color(0x14FFFFFF)
val SelectionContent = Color(0xFFF1F3F5)
val LifeHealth = Color(0xFF86A99A) // 鼠尾草绿
val LifeHunger = Color(0xFFC0A36E) // 柔和沙金
val LifeHappiness = Color(0xFFB18FA2) // 灰粉
val LifeEnergy = Color(0xFF809EAE) // 雾蓝

// Gradient colors for breathing background
val GradientGreenStart = Color(0xFF10B981)
val GradientGreenEnd = Color(0x0010B981)
val GradientBlueStart = Color(0xFF38BDF8)
val GradientBlueEnd = Color(0x0038BDF8)
val GradientPurpleStart = Color(0xFF8B5CF6)
val GradientPurpleEnd = Color(0x008B5CF6)

/**
 * Emotion color mapping.
 * Maps emotion states to their corresponding colors.
 */
object EmotionColors {
    val happy = EmotionGreen
    val calm = EmotionBlue
    val excited = EmotionPurple
    val sad = listOf(EmotionBlue, EmotionPurple)
    val neutral = EmotionBlue
    val love = EmotionPink
    val angry = EmotionRed
    val fearful = EmotionPurple
    val surprised = EmotionYellow
    val disgusted = EmotionGreen
    
    /**
     * Get color for emotion state.
     */
    fun getColorForEmotion(emotion: String): Color {
        return when (emotion.lowercase()) {
            "happy", "joy" -> happy
            "calm", "peaceful" -> calm
            "excited", "enthusiastic" -> excited
            "sad", "melancholy" -> sad.first()
            "love", "affectionate" -> love
            "angry", "frustrated" -> angry
            "fearful", "anxious" -> fearful
            "surprised", "amazed" -> surprised
            "disgusted" -> disgusted
            else -> neutral
        }
    }
    
    /**
     * Get gradient colors for emotion state.
     */
    fun getGradientForEmotion(emotion: String): List<Color> {
        return when (emotion.lowercase()) {
            "happy", "joy" -> listOf(GradientGreenStart, GradientGreenEnd)
            "calm", "peaceful" -> listOf(GradientBlueStart, GradientBlueEnd)
            "excited", "enthusiastic" -> listOf(GradientPurpleStart, GradientPurpleEnd)
            "sad", "melancholy" -> listOf(GradientBlueStart, GradientPurpleStart)
            "love", "affectionate" -> listOf(EmotionPink, GradientPurpleEnd)
            else -> listOf(GradientBlueStart, GradientBlueEnd)
        }
    }
}
