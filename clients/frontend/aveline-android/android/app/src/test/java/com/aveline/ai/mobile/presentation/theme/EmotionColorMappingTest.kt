package com.aveline.ai.mobile.presentation.theme

import androidx.compose.ui.graphics.Color
import org.junit.Test
import org.junit.Assert.*

/**
 * Unit tests for EmotionColorMapping.
 * Validates that all emotion states have correct 4-color schemes matching Web frontend.
 */
class EmotionColorMappingTest {
    
    @Test
    fun `all emotion states have exactly 4 colors`() {
        EmotionState.values().forEach { emotionState ->
            val colorScheme = EmotionColorMapping.getColorsForEmotion(emotionState)
            assertEquals(
                "Emotion state $emotionState should have exactly 4 colors",
                4,
                colorScheme.colors.size
            )
        }
    }
    
    @Test
    fun `neutral emotion has correct colors`() {
        val colors = EmotionColorMapping.getColorsForEmotion(EmotionState.NEUTRAL).colors
        
        assertEquals(Color(0xFF6B7280), colors[0])
        assertEquals(Color(0xFFA5ADC1), colors[1])
        assertEquals(Color(0xFF1C1F24), colors[2])
        assertEquals(Color(0xFF4B5563), colors[3])
    }
    
    @Test
    fun `happy emotion has correct colors`() {
        val colors = EmotionColorMapping.getColorsForEmotion(EmotionState.HAPPY).colors
        
        assertEquals(Color(0xFFF2CE77), colors[0])
        assertEquals(Color(0xFFFFE8B2), colors[1])
        assertEquals(Color(0xFF3A2E13), colors[2])
        assertEquals(Color(0xFFD3A74F), colors[3])
    }
    
    @Test
    fun `shy emotion has correct colors`() {
        val colors = EmotionColorMapping.getColorsForEmotion(EmotionState.SHY).colors
        
        assertEquals(Color(0xFFF3B8C8), colors[0])
        assertEquals(Color(0xFFFFD8E3), colors[1])
        assertEquals(Color(0xFF3F1B29), colors[2])
        assertEquals(Color(0xFFE58AA7), colors[3])
    }
    
    @Test
    fun `angry emotion has correct colors`() {
        val colors = EmotionColorMapping.getColorsForEmotion(EmotionState.ANGRY).colors
        
        assertEquals(Color(0xFFE86A73), colors[0])
        assertEquals(Color(0xFFFFC1C4), colors[1])
        assertEquals(Color(0xFF3D0E14), colors[2])
        assertEquals(Color(0xFFC1444E), colors[3])
    }
    
    @Test
    fun `jealous emotion has correct colors`() {
        val colors = EmotionColorMapping.getColorsForEmotion(EmotionState.JEALOUS).colors
        
        assertEquals(Color(0xFFA58AF8), colors[0])
        assertEquals(Color(0xFFD3C6FF), colors[1])
        assertEquals(Color(0xFF2C2453), colors[2])
        assertEquals(Color(0xFF7E6AD9), colors[3])
    }
    
    @Test
    fun `wronged emotion has correct colors`() {
        val colors = EmotionColorMapping.getColorsForEmotion(EmotionState.WRONGED).colors
        
        assertEquals(Color(0xFF8CB2FF), colors[0])
        assertEquals(Color(0xFFCDE0FF), colors[1])
        assertEquals(Color(0xFF1B2A4C), colors[2])
        assertEquals(Color(0xFF5B8AE0), colors[3])
    }
    
    @Test
    fun `coquetry emotion has correct colors`() {
        val colors = EmotionColorMapping.getColorsForEmotion(EmotionState.COQUETRY).colors
        
        assertEquals(Color(0xFFF6A4C6), colors[0])
        assertEquals(Color(0xFFFFD6EC), colors[1])
        assertEquals(Color(0xFF381C2C), colors[2])
        assertEquals(Color(0xFFCF6D9A), colors[3])
    }
    
    @Test
    fun `lost emotion has correct colors`() {
        val colors = EmotionColorMapping.getColorsForEmotion(EmotionState.LOST).colors
        
        assertEquals(Color(0xFFA3A3AD), colors[0])
        assertEquals(Color(0xFFD8D8E2), colors[1])
        assertEquals(Color(0xFF18181B), colors[2])
        assertEquals(Color(0xFF6E6E78), colors[3])
    }
    
    @Test
    fun `excited emotion has correct colors`() {
        val colors = EmotionColorMapping.getColorsForEmotion(EmotionState.EXCITED).colors
        
        assertEquals(Color(0xFF5EE3C0), colors[0])
        assertEquals(Color(0xFFC6FFF0), colors[1])
        assertEquals(Color(0xFF0D2E25), colors[2])
        assertEquals(Color(0xFF2FB395), colors[3])
    }
    
    @Test
    fun `emotionColorMap contains all emotion states`() {
        val allStates = EmotionState.values()
        
        allStates.forEach { state ->
            assertTrue(
                "emotionColorMap should contain $state",
                EmotionColorMapping.emotionColorMap.containsKey(state)
            )
        }
        
        assertEquals(
            "emotionColorMap should have exactly ${allStates.size} entries",
            allStates.size,
            EmotionColorMapping.emotionColorMap.size
        )
    }
    
    @Test
    fun `fromString parses emotion states correctly`() {
        assertEquals(EmotionState.NEUTRAL, EmotionState.fromString("neutral"))
        assertEquals(EmotionState.HAPPY, EmotionState.fromString("happy"))
        assertEquals(EmotionState.SHY, EmotionState.fromString("shy"))
        assertEquals(EmotionState.ANGRY, EmotionState.fromString("angry"))
        assertEquals(EmotionState.JEALOUS, EmotionState.fromString("jealous"))
        assertEquals(EmotionState.WRONGED, EmotionState.fromString("wronged"))
        assertEquals(EmotionState.COQUETRY, EmotionState.fromString("coquetry"))
        assertEquals(EmotionState.LOST, EmotionState.fromString("lost"))
        assertEquals(EmotionState.EXCITED, EmotionState.fromString("excited"))
    }
    
    @Test
    fun `fromString is case insensitive`() {
        assertEquals(EmotionState.HAPPY, EmotionState.fromString("HAPPY"))
        assertEquals(EmotionState.HAPPY, EmotionState.fromString("Happy"))
        assertEquals(EmotionState.HAPPY, EmotionState.fromString("happy"))
    }
    
    @Test
    fun `fromString returns NEUTRAL for unknown emotions`() {
        assertEquals(EmotionState.NEUTRAL, EmotionState.fromString("unknown"))
        assertEquals(EmotionState.NEUTRAL, EmotionState.fromString(""))
        assertEquals(EmotionState.NEUTRAL, EmotionState.fromString("invalid"))
    }
    
    @Test
    fun `getColorsForEmotion with string parameter works correctly`() {
        val colors = EmotionColorMapping.getColorsForEmotion("happy").colors
        
        assertEquals(4, colors.size)
        assertEquals(Color(0xFFF2CE77), colors[0])
    }
    
    @Test
    fun `getColorsForEmotion returns neutral for unknown string`() {
        val colors = EmotionColorMapping.getColorsForEmotion("unknown").colors
        val neutralColors = EmotionColorMapping.getColorsForEmotion(EmotionState.NEUTRAL).colors
        
        assertEquals(neutralColors, colors)
    }
    
    @Test
    fun `EmotionColorScheme enforces exactly 4 colors`() {
        // Valid: 4 colors
        val validScheme = EmotionColorScheme(
            listOf(Color.Red, Color.Green, Color.Blue, Color.Yellow)
        )
        assertEquals(4, validScheme.colors.size)
        
        // Invalid: 3 colors should throw
        try {
            EmotionColorScheme(listOf(Color.Red, Color.Green, Color.Blue))
            fail("Should throw IllegalArgumentException for 3 colors")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message?.contains("exactly 4 colors") == true)
        }
        
        // Invalid: 5 colors should throw
        try {
            EmotionColorScheme(
                listOf(Color.Red, Color.Green, Color.Blue, Color.Yellow, Color.Cyan)
            )
            fail("Should throw IllegalArgumentException for 5 colors")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message?.contains("exactly 4 colors") == true)
        }
    }
    
    @Test
    fun `all colors are opaque (no transparency)`() {
        EmotionState.values().forEach { emotionState ->
            val colorScheme = EmotionColorMapping.getColorsForEmotion(emotionState)
            colorScheme.colors.forEachIndexed { index, color ->
                assertEquals(
                    "Color $index in $emotionState should be fully opaque",
                    1.0f,
                    color.alpha,
                    0.001f
                )
            }
        }
    }
}
