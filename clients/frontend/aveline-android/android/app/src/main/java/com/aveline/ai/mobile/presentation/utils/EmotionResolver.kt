package com.aveline.ai.mobile.presentation.utils

import androidx.compose.ui.graphics.Color
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.presentation.theme.EmotionColorMapping

/**
 * 情绪解析工具类。
 * 
 * 用于将情绪状态映射到颜色和动画参数。
 */
object EmotionResolver {
    
    /**
     * 情绪类型枚举。
     */
    enum class EmotionType(val displayName: String, val color: Color) {
        NEUTRAL("neutral", Color(0xFF6B7280)),
        HAPPY("happy", Color(0xFFF2CE77)),
        SHY("shy", Color(0xFFF3B8C8)),
        ANGRY("angry", Color(0xFFE86A73)),
        JEALOUS("jealous", Color(0xFFA58AF8)),
        WRONGED("wronged", Color(0xFF8CB2FF)),
        COQUETRY("coquetry", Color(0xFFF6A4C6)),
        LOST("lost", Color(0xFFA3A3AD)),
        EXCITED("excited", Color(0xFF5EE3C0))
    }
    
    /**
     * 根据情绪名称获取颜色。
     * 
     * @param emotionName 情绪名称
     * @return 对应的颜色
     */
    fun getColorForEmotion(emotionName: String): Color {
        return try {
            EmotionType.values().find { 
                it.displayName.equals(emotionName, ignoreCase = true) 
            }?.color ?: Color(0xFF6B7280)
        } catch (e: Exception) {
            Color(0xFF6B7280)
        }
    }
    
    /**
     * 根据情绪名称获取颜色列表（用于呼吸背景）。
     * 返回四个颜色：与 Web 端一致的 4-color 方案。
     * 
     * @param emotionName 情绪名称
     * @return 颜色列表（4个颜色）
     */
    fun getColorsForEmotion(emotionName: String): List<Color> {
        // Use EmotionColorMapping to get 4-color scheme matching Web design
        val colorScheme = EmotionColorMapping.getColorsForEmotion(emotionName)
        return colorScheme.colors
    }
    
    /**
     * 根据情绪名称获取情绪类型。
     * 
     * @param emotionName 情绪名称
     * @return 情绪类型枚举
     */
    fun getEmotionType(emotionName: String): EmotionType {
        return EmotionType.values().find { 
            it.displayName.equals(emotionName, ignoreCase = true) 
        } ?: EmotionType.NEUTRAL
    }
    
    /**
     * 获取情绪混合颜色。
     * 
     * @param emotionMix 情绪混合比例 Map
     * @return 混合后的颜色
     */
    fun blendEmotionColors(emotionMix: Map<String, Float>): Color {
        if (emotionMix.isEmpty()) return Color(0xFF6B7280)
        
        var totalWeight = 0f
        var red = 0f
        var green = 0f
        var blue = 0f
        
        emotionMix.forEach { (emotion, weight) ->
            val color = getColorForEmotion(emotion)
            red += color.red * weight
            green += color.green * weight
            blue += color.blue * weight
            totalWeight += weight
        }
        
        if (totalWeight == 0f) return Color(0xFF6B7280)
        
        return Color(
            red = (red / totalWeight).coerceIn(0f, 1f),
            green = (green / totalWeight).coerceIn(0f, 1f),
            blue = (blue / totalWeight).coerceIn(0f, 1f)
        )
    }
    
    /**
     * 计算呼吸动画速度。
     * 
     * @param energy 能量值 (0.0 - 1.0)
     * @param isTyping 是否正在输入
     * @param breathingRate 用户设置的呼吸速率倍数 (0.5 - 2.0)
     * @return 动画速度倍数
     */
    fun calculateBreathingSpeed(
        energy: Float,
        isTyping: Boolean,
        breathingRate: Float = 1.0f
    ): Float {
        // 基础速度受能量影响
        val energyFactor = 0.5f + energy * 0.5f
        
        // 输入时加速
        val typingFactor = if (isTyping) 1.5f else 1.0f
        
        return breathingRate * energyFactor * typingFactor
    }
    
    /**
     * 获取情绪颜色强度。
     * 
     * @param emotionName 情绪名称
     * @param intensity 情绪强度 (0.0 - 1.0)
     * @return 颜色透明度
     */
    fun getEmotionAlpha(emotionName: String, intensity: Float): Float {
        val baseAlpha = when (getEmotionType(emotionName)) {
            EmotionType.NEUTRAL -> 0.4f
            EmotionType.HAPPY -> 0.6f
            EmotionType.SHY -> 0.55f
            EmotionType.ANGRY -> 0.8f
            EmotionType.JEALOUS -> 0.6f
            EmotionType.WRONGED -> 0.5f
            EmotionType.COQUETRY -> 0.65f
            EmotionType.LOST -> 0.42f
            EmotionType.EXCITED -> 0.7f
        }
        
        return baseAlpha * intensity.coerceIn(0.3f, 1.0f)
    }
    
    /**
     * 从 Emotion 域模型获取颜色列表。
     * 
     * @param emotion Emotion 域模型
     * @return 颜色列表
     */
    fun getColorsFromEmotion(emotion: Emotion): List<Color> {
        return if (emotion.colors.isNotEmpty()) {
            emotion.colors.map { parseColor(it) }
        } else {
            listOf(getColorForEmotion(emotion.primary))
        }
    }
    
    /**
     * 解析十六进制颜色字符串。
     * 
     * @param hexColor 十六进制颜色字符串 (如 "#10B981")
     * @return Color 对象
     */
    fun parseColor(hexColor: String): Color {
        return try {
            val hex = hexColor.removePrefix("#")
            val color = hex.toLong(16)
            when (hex.length) {
                // 6位hex(如"10B981")无alpha通道,需补FF避免被解析为完全透明
                6 -> Color(color or 0xFF000000L)
                8 -> Color(color)
                else -> Color(0xFF6B7280)
            }
        } catch (e: Exception) {
            Color(0xFF6B7280)
        }
    }
}
