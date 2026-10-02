package com.aveline.ai.mobile.presentation.components

import androidx.compose.ui.graphics.Color
import com.aveline.ai.mobile.presentation.utils.EmotionResolver
import org.junit.Assert.*
import org.junit.Test

/**
 * Bug Condition Exploration Test for Breathing Light Colors
 * 
 * **Validates: Requirements 2.1, 2.2, 2.3**
 * 
 * **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
 * 
 * **Property 1: Fault Condition** - 呼吸灯颜色与 Web 端不一致
 * 
 * This test encodes the EXPECTED BEHAVIOR after the fix:
 * - When emotion state is set (neutral, happy, shy, angry, jealous, wronged, coquetry, lost, excited)
 * - BreathingLight component SHALL use 4-color scheme matching Web exactly
 * - Color values SHALL match Web端的精确颜色值
 * - Color transitions SHALL be smooth (not abrupt)
 * 
 * **EXPECTED OUTCOME ON UNFIXED CODE**: Test FAILS (this proves the bug exists)
 * 
 * The test will document counterexamples that demonstrate:
 * - Current color count (likely 3 instead of 4)
 * - Current color values vs Web values
 * - Whether color transition is abrupt or smooth
 */
class BreathingLightBugConditionTest {
    
    /**
     * Web端的4色方案定义
     * 每个情绪状态对应4个颜色值
     */
    private val webEmotionColors = mapOf(
        "neutral" to listOf("#6B7280", "#A5ADC1", "#1C1F24", "#4B5563"),
        "happy" to listOf("#F2CE77", "#FFE8B2", "#3A2E13", "#D3A74F"),
        "shy" to listOf("#F3B8C8", "#FFD8E3", "#3F1B29", "#E58AA7"),
        "angry" to listOf("#E86A73", "#FFC1C4", "#3D0E14", "#C1444E"),
        "jealous" to listOf("#A58AF8", "#D3C6FF", "#2C2453", "#7E6AD9"),
        "wronged" to listOf("#8CB2FF", "#CDE0FF", "#1B2A4C", "#5B8AE0"),
        "coquetry" to listOf("#F6A4C6", "#FFD6EC", "#381C2C", "#CF6D9A"),
        "lost" to listOf("#A3A3AD", "#D8D8E2", "#18181B", "#6E6E78"),
        "excited" to listOf("#5EE3C0", "#C6FFF0", "#0D2E25", "#2FB395")
    )
    
    /**
     * Bug Condition Test 1: Neutral emotion uses 3-color scheme instead of Web's 4-color scheme
     * 
     * **Scoped PBT Approach**: Test concrete failing case - neutral emotion
     * 
     * EXPECTED ON UNFIXED CODE: Test FAILS - color count is 3, not 4
     * EXPECTED AFTER FIX: Test PASSES - color count is 4 and matches Web
     */
    @Test
    fun `bug condition - neutral emotion uses simplified 3-color scheme instead of Web 4-color scheme`() {
        // Get current Android implementation colors for neutral emotion
        val androidColors = EmotionResolver.getColorsForEmotion("neutral")
        
        // Get expected Web colors for neutral emotion
        val webColors = webEmotionColors["neutral"]!!
        val expectedColorCount = 4
        
        // COUNTEREXAMPLE DOCUMENTATION:
        println("=== BUG CONDITION EXPLORATION: Neutral Emotion ===")
        println("Android color count: ${androidColors.size}")
        println("Expected Web color count: $expectedColorCount")
        println("Android colors: ${androidColors.map { colorToHex(it) }}")
        println("Expected Web colors: $webColors")
        
        // EXPECTED BEHAVIOR (after fix): Should use 4-color scheme
        assertEquals(
            "BUG DETECTED: Breathing light uses ${androidColors.size}-color scheme instead of Web's 4-color scheme. " +
            "Android colors: ${androidColors.map { colorToHex(it) }}, " +
            "Expected Web colors: $webColors",
            expectedColorCount,
            androidColors.size
        )
        
        // Verify colors match Web values exactly
        for (i in 0 until expectedColorCount) {
            val androidColorHex = colorToHex(androidColors[i])
            val webColorHex = webColors[i]
            assertEquals(
                "BUG DETECTED: Color at index $i doesn't match Web. " +
                "Android: $androidColorHex, Web: $webColorHex",
                webColorHex.uppercase(),
                androidColorHex.uppercase()
            )
        }
    }
    
    /**
     * Bug Condition Test 2: Happy emotion colors don't match Web
     * 
     * EXPECTED ON UNFIXED CODE: Test FAILS - colors don't match Web
     * EXPECTED AFTER FIX: Test PASSES - colors match Web exactly
     */
    @Test
    fun `bug condition - happy emotion colors don't match Web 4-color scheme`() {
        val androidColors = EmotionResolver.getColorsForEmotion("happy")
        val webColors = webEmotionColors["happy"]!!
        
        println("=== BUG CONDITION EXPLORATION: Happy Emotion ===")
        println("Android color count: ${androidColors.size}")
        println("Android colors: ${androidColors.map { colorToHex(it) }}")
        println("Expected Web colors: $webColors")
        
        // This will FAIL on unfixed code
        assertEquals(
            "BUG DETECTED: Happy emotion uses ${androidColors.size} colors instead of 4",
            4,
            androidColors.size
        )
        
        // Verify each color matches
        for (i in 0 until 4) {
            assertEquals(
                "BUG DETECTED: Happy emotion color $i doesn't match Web",
                webColors[i].uppercase(),
                colorToHex(androidColors[i]).uppercase()
            )
        }
    }
    
    /**
     * Bug Condition Test 3: Shy emotion colors don't match Web
     * 
     * EXPECTED ON UNFIXED CODE: Test FAILS
     * EXPECTED AFTER FIX: Test PASSES
     */
    @Test
    fun `bug condition - shy emotion colors don't match Web 4-color scheme`() {
        val androidColors = EmotionResolver.getColorsForEmotion("shy")
        val webColors = webEmotionColors["shy"]!!
        
        println("=== BUG CONDITION EXPLORATION: Shy Emotion ===")
        println("Android color count: ${androidColors.size}")
        println("Android colors: ${androidColors.map { colorToHex(it) }}")
        println("Expected Web colors: $webColors")
        
        assertEquals(
            "BUG DETECTED: Shy emotion uses ${androidColors.size} colors instead of 4",
            4,
            androidColors.size
        )
        
        for (i in 0 until 4) {
            assertEquals(
                "BUG DETECTED: Shy emotion color $i doesn't match Web",
                webColors[i].uppercase(),
                colorToHex(androidColors[i]).uppercase()
            )
        }
    }
    
    /**
     * Bug Condition Test 4: Angry emotion colors don't match Web
     */
    @Test
    fun `bug condition - angry emotion colors don't match Web 4-color scheme`() {
        val androidColors = EmotionResolver.getColorsForEmotion("angry")
        val webColors = webEmotionColors["angry"]!!
        
        println("=== BUG CONDITION EXPLORATION: Angry Emotion ===")
        println("Android color count: ${androidColors.size}")
        println("Android colors: ${androidColors.map { colorToHex(it) }}")
        println("Expected Web colors: $webColors")
        
        assertEquals(
            "BUG DETECTED: Angry emotion uses ${androidColors.size} colors instead of 4",
            4,
            androidColors.size
        )
        
        for (i in 0 until 4) {
            assertEquals(
                "BUG DETECTED: Angry emotion color $i doesn't match Web",
                webColors[i].uppercase(),
                colorToHex(androidColors[i]).uppercase()
            )
        }
    }
    
    /**
     * Bug Condition Test 5: Jealous emotion colors don't match Web
     */
    @Test
    fun `bug condition - jealous emotion colors don't match Web 4-color scheme`() {
        val androidColors = EmotionResolver.getColorsForEmotion("jealous")
        val webColors = webEmotionColors["jealous"]!!
        
        println("=== BUG CONDITION EXPLORATION: Jealous Emotion ===")
        println("Android color count: ${androidColors.size}")
        println("Android colors: ${androidColors.map { colorToHex(it) }}")
        println("Expected Web colors: $webColors")
        
        assertEquals(
            "BUG DETECTED: Jealous emotion uses ${androidColors.size} colors instead of 4",
            4,
            androidColors.size
        )
        
        for (i in 0 until 4) {
            assertEquals(
                "BUG DETECTED: Jealous emotion color $i doesn't match Web",
                webColors[i].uppercase(),
                colorToHex(androidColors[i]).uppercase()
            )
        }
    }
    
    /**
     * Bug Condition Test 6: Wronged emotion colors don't match Web
     */
    @Test
    fun `bug condition - wronged emotion colors don't match Web 4-color scheme`() {
        val androidColors = EmotionResolver.getColorsForEmotion("wronged")
        val webColors = webEmotionColors["wronged"]!!
        
        println("=== BUG CONDITION EXPLORATION: Wronged Emotion ===")
        println("Android color count: ${androidColors.size}")
        println("Android colors: ${androidColors.map { colorToHex(it) }}")
        println("Expected Web colors: $webColors")
        
        assertEquals(
            "BUG DETECTED: Wronged emotion uses ${androidColors.size} colors instead of 4",
            4,
            androidColors.size
        )
        
        for (i in 0 until 4) {
            assertEquals(
                "BUG DETECTED: Wronged emotion color $i doesn't match Web",
                webColors[i].uppercase(),
                colorToHex(androidColors[i]).uppercase()
            )
        }
    }
    
    /**
     * Bug Condition Test 7: Coquetry emotion colors don't match Web
     */
    @Test
    fun `bug condition - coquetry emotion colors don't match Web 4-color scheme`() {
        val androidColors = EmotionResolver.getColorsForEmotion("coquetry")
        val webColors = webEmotionColors["coquetry"]!!
        
        println("=== BUG CONDITION EXPLORATION: Coquetry Emotion ===")
        println("Android color count: ${androidColors.size}")
        println("Android colors: ${androidColors.map { colorToHex(it) }}")
        println("Expected Web colors: $webColors")
        
        assertEquals(
            "BUG DETECTED: Coquetry emotion uses ${androidColors.size} colors instead of 4",
            4,
            androidColors.size
        )
        
        for (i in 0 until 4) {
            assertEquals(
                "BUG DETECTED: Coquetry emotion color $i doesn't match Web",
                webColors[i].uppercase(),
                colorToHex(androidColors[i]).uppercase()
            )
        }
    }
    
    /**
     * Bug Condition Test 8: Lost emotion colors don't match Web
     */
    @Test
    fun `bug condition - lost emotion colors don't match Web 4-color scheme`() {
        val androidColors = EmotionResolver.getColorsForEmotion("lost")
        val webColors = webEmotionColors["lost"]!!
        
        println("=== BUG CONDITION EXPLORATION: Lost Emotion ===")
        println("Android color count: ${androidColors.size}")
        println("Android colors: ${androidColors.map { colorToHex(it) }}")
        println("Expected Web colors: $webColors")
        
        assertEquals(
            "BUG DETECTED: Lost emotion uses ${androidColors.size} colors instead of 4",
            4,
            androidColors.size
        )
        
        for (i in 0 until 4) {
            assertEquals(
                "BUG DETECTED: Lost emotion color $i doesn't match Web",
                webColors[i].uppercase(),
                colorToHex(androidColors[i]).uppercase()
            )
        }
    }
    
    /**
     * Bug Condition Test 9: Excited emotion colors don't match Web
     */
    @Test
    fun `bug condition - excited emotion colors don't match Web 4-color scheme`() {
        val androidColors = EmotionResolver.getColorsForEmotion("excited")
        val webColors = webEmotionColors["excited"]!!
        
        println("=== BUG CONDITION EXPLORATION: Excited Emotion ===")
        println("Android color count: ${androidColors.size}")
        println("Android colors: ${androidColors.map { colorToHex(it) }}")
        println("Expected Web colors: $webColors")
        
        assertEquals(
            "BUG DETECTED: Excited emotion uses ${androidColors.size} colors instead of 4",
            4,
            androidColors.size
        )
        
        for (i in 0 until 4) {
            assertEquals(
                "BUG DETECTED: Excited emotion color $i doesn't match Web",
                webColors[i].uppercase(),
                colorToHex(androidColors[i]).uppercase()
            )
        }
    }
    
    /**
     * Bug Condition Test 10: All emotion states should use 4-color scheme
     * 
     * Property-based test covering all emotion states
     */
    @Test
    fun `bug condition - all emotion states should use 4-color scheme matching Web`() {
        val allEmotions = listOf(
            "neutral", "happy", "shy", "angry", "jealous", 
            "wronged", "coquetry", "lost", "excited"
        )
        
        val failures = mutableListOf<String>()
        
        for (emotion in allEmotions) {
            val androidColors = EmotionResolver.getColorsForEmotion(emotion)
            val webColors = webEmotionColors[emotion]!!
            
            if (androidColors.size != 4) {
                failures.add("$emotion: has ${androidColors.size} colors instead of 4")
            }
            
            // Check if colors match (only if we have enough colors)
            val minSize = minOf(androidColors.size, webColors.size)
            for (i in 0 until minSize) {
                val androidHex = colorToHex(androidColors[i]).uppercase()
                val webHex = webColors[i].uppercase()
                if (androidHex != webHex) {
                    failures.add("$emotion color $i: Android=$androidHex, Web=$webHex")
                }
            }
        }
        
        if (failures.isNotEmpty()) {
            println("=== BUG CONDITION EXPLORATION: All Emotions ===")
            println("Found ${failures.size} mismatches:")
            failures.forEach { println("  - $it") }
        }
        
        assertTrue(
            "BUG DETECTED: ${failures.size} emotion color mismatches found:\n" +
            failures.joinToString("\n") { "  - $it" },
            failures.isEmpty()
        )
    }
    
    /**
     * Helper function to convert Color to hex string
     */
    private fun colorToHex(color: Color): String {
        val red = (color.red * 255).toInt()
        val green = (color.green * 255).toInt()
        val blue = (color.blue * 255).toInt()
        return "#%02X%02X%02X".format(red, green, blue)
    }
}
