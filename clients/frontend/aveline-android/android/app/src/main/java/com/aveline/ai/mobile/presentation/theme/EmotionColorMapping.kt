package com.aveline.ai.mobile.presentation.theme

import androidx.compose.ui.graphics.Color

/**
 * Emotion states supported by the breathing light system.
 * Matches the Web frontend emotion states.
 */
enum class EmotionState {
    NEUTRAL,
    HAPPY,
    SHY,
    ANGRY,
    JEALOUS,
    WRONGED,
    COQUETRY,
    LOST,
    EXCITED;
    
    companion object {
        /**
         * Parse emotion state from string.
         * Returns NEUTRAL if the emotion is not recognized.
         */
        fun fromString(emotion: String): EmotionState {
            return when (emotion.lowercase()) {
                "neutral" -> NEUTRAL
                "happy" -> HAPPY
                "shy" -> SHY
                "angry" -> ANGRY
                "jealous" -> JEALOUS
                "wronged" -> WRONGED
                "coquetry" -> COQUETRY
                "lost" -> LOST
                "excited" -> EXCITED
                else -> NEUTRAL
            }
        }
    }
}

/**
 * Color scheme for an emotion state.
 * Contains exactly 4 colors matching the Web frontend design.
 */
data class EmotionColorScheme(val colors: List<Color>) {
    init {
        require(colors.size == 4) { "EmotionColorScheme must contain exactly 4 colors" }
    }
}

/**
 * Complete emotion color mapping matching Web frontend.
 * Each emotion state has exactly 4 colors for the breathing light effect.
 * 
 * Color values are exact HEX matches from the Web implementation.
 */
object EmotionColorMapping {
    
    // Neutral: Gray tones
    private val neutralColors = EmotionColorScheme(
        colors = listOf(
            Color(0xFF6B7280),
            Color(0xFFA5ADC1),
            Color(0xFF1C1F24),
            Color(0xFF4B5563)
        )
    )
    
    // Happy: Warm yellow/gold tones
    private val happyColors = EmotionColorScheme(
        colors = listOf(
            Color(0xFFF2CE77),
            Color(0xFFFFE8B2),
            Color(0xFF3A2E13),
            Color(0xFFD3A74F)
        )
    )
    
    // Shy: Soft pink tones
    private val shyColors = EmotionColorScheme(
        colors = listOf(
            Color(0xFFF3B8C8),
            Color(0xFFFFD8E3),
            Color(0xFF3F1B29),
            Color(0xFFE58AA7)
        )
    )
    
    // Angry: Red tones
    private val angryColors = EmotionColorScheme(
        colors = listOf(
            Color(0xFFE86A73),
            Color(0xFFFFC1C4),
            Color(0xFF3D0E14),
            Color(0xFFC1444E)
        )
    )
    
    // Jealous: Purple tones
    private val jealousColors = EmotionColorScheme(
        colors = listOf(
            Color(0xFFA58AF8),
            Color(0xFFD3C6FF),
            Color(0xFF2C2453),
            Color(0xFF7E6AD9)
        )
    )
    
    // Wronged: Blue tones
    private val wrongedColors = EmotionColorScheme(
        colors = listOf(
            Color(0xFF8CB2FF),
            Color(0xFFCDE0FF),
            Color(0xFF1B2A4C),
            Color(0xFF5B8AE0)
        )
    )
    
    // Coquetry: Vibrant pink tones
    private val coquetryColors = EmotionColorScheme(
        colors = listOf(
            Color(0xFFF6A4C6),
            Color(0xFFFFD6EC),
            Color(0xFF381C2C),
            Color(0xFFCF6D9A)
        )
    )
    
    // Lost: Muted gray tones
    private val lostColors = EmotionColorScheme(
        colors = listOf(
            Color(0xFFA3A3AD),
            Color(0xFFD8D8E2),
            Color(0xFF18181B),
            Color(0xFF6E6E78)
        )
    )
    
    // Excited: Teal/cyan tones
    private val excitedColors = EmotionColorScheme(
        colors = listOf(
            Color(0xFF5EE3C0),
            Color(0xFFC6FFF0),
            Color(0xFF0D2E25),
            Color(0xFF2FB395)
        )
    )
    
    /**
     * Map of emotion states to their color schemes.
     * All emotion states use exactly 4 colors matching Web frontend.
     */
    val emotionColorMap: Map<EmotionState, EmotionColorScheme> = mapOf(
        EmotionState.NEUTRAL to neutralColors,
        EmotionState.HAPPY to happyColors,
        EmotionState.SHY to shyColors,
        EmotionState.ANGRY to angryColors,
        EmotionState.JEALOUS to jealousColors,
        EmotionState.WRONGED to wrongedColors,
        EmotionState.COQUETRY to coquetryColors,
        EmotionState.LOST to lostColors,
        EmotionState.EXCITED to excitedColors
    )
    
    /**
     * Get color scheme for an emotion state.
     * Returns neutral colors if the emotion state is not found.
     */
    fun getColorsForEmotion(emotionState: EmotionState): EmotionColorScheme {
        return emotionColorMap[emotionState] ?: neutralColors
    }
    
    /**
     * Get color scheme for an emotion string.
     * Parses the string to EmotionState and returns corresponding colors.
     */
    fun getColorsForEmotion(emotion: String): EmotionColorScheme {
        val emotionState = EmotionState.fromString(emotion)
        return getColorsForEmotion(emotionState)
    }
}
