package com.aveline.ai.mobile.domain.models

/**
 * Domain model for emotion state.
 * Represents the AI's emotional state with intensity and associated colors.
 */
data class Emotion(
    val primary: String,
    val intensity: Float,
    val colors: List<String>
) {
    companion object {
        val NEUTRAL = Emotion(
            primary = "neutral",
            intensity = 0.5f,
            colors = listOf("#38BDF8") // Blue
        )
        
        val HAPPY = Emotion(
            primary = "happy",
            intensity = 0.8f,
            colors = listOf("#10B981") // Green
        )
        
        val CALM = Emotion(
            primary = "calm",
            intensity = 0.6f,
            colors = listOf("#38BDF8") // Blue
        )
        
        val EXCITED = Emotion(
            primary = "excited",
            intensity = 1.0f,
            colors = listOf("#8B5CF6") // Purple
        )
        
        val SAD = Emotion(
            primary = "sad",
            intensity = 0.4f,
            colors = listOf("#38BDF8", "#8B5CF6") // Blue + Purple
        )
    }
}
