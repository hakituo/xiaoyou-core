package com.aveline.ai.mobile.domain.models

/**
 * AI 模型类型
 */
enum class ModelType {
    CLOUD,      // 云端模型
    LOCAL,      // 本地模型
    UNKNOWN
}

/**
 * AI 模型数据模型
 *
 * @property id 模型 ID
 * @property name 模型名称
 * @property type 模型类型
 * @property description 模型描述
 * @property provider 提供商
 * @property contextLength 上下文长度
 * @property isAvailable 是否可用
 * @property route 实际聊天请求使用的模型路由（如 cloud:provider:alias:model）
 */
data class AIModel(
    val id: String,
    val name: String,
    val type: ModelType = ModelType.UNKNOWN,
    val description: String = "",
    val provider: String = "",
    val contextLength: Int = 4096,
    val isAvailable: Boolean = true,
    val route: String = ""
) {
    val displayName: String
        get() = name.ifEmpty { id }

    val typeLabel: String
        get() = when (type) {
            ModelType.CLOUD -> "云端"
            ModelType.LOCAL -> "本地"
            ModelType.UNKNOWN -> "未知"
        }
}

/**
 * 响应长度设置
 */
enum class ResponseLength {
    SHORT,      // 简短
    NORMAL,     // 正常
    DETAILED;   // 详细

    val label: String
        get() = when (this) {
            SHORT -> "简短"
            NORMAL -> "正常"
            DETAILED -> "详细"
        }

    val description: String
        get() = when (this) {
            SHORT -> "回复简洁，适合快速交流"
            NORMAL -> "标准回复长度"
            DETAILED -> "回复详细，适合深入讨论"
        }
}

/**
 * 情绪类型
 */
enum class EmotionType {
    NEUTRAL,    // 中性
    HAPPY,      // 开心
    SHY,        // 害羞
    ANGRY,      // 生气
    JEALOUS,    // 嫉妒
    WRONGED,    // 委屈
    COQUETRY,   // 撒娇
    LOST,       // 难过/失落
    EXCITED;    // 兴奋

    val label: String
        get() = when (this) {
            NEUTRAL -> "中性"
            HAPPY -> "开心"
            SHY -> "害羞"
            ANGRY -> "生气"
            JEALOUS -> "嫉妒"
            WRONGED -> "委屈"
            COQUETRY -> "撒娇"
            LOST -> "难过"
            EXCITED -> "兴奋"
        }

    val emoji: String
        get() = when (this) {
            NEUTRAL -> "😐"
            HAPPY -> "😊"
            SHY -> "☺️"
            ANGRY -> "😠"
            JEALOUS -> "😒"
            WRONGED -> "🥺"
            COQUETRY -> "😳"
            LOST -> "😢"
            EXCITED -> "🤩"
        }
}

/**
 * 插件设置
 *
 * @property selectedModelId 选中的模型 ID
 * @property responseLength 响应长度
 * @property breathingRate 呼吸频率 (0.5 - 2.0)
 * @property manualEmotion 手动设置的情绪
 * @property autoEmotion 是否自动情绪
 */
data class PluginSettings(
    val selectedModelId: String = "",
    val responseLength: ResponseLength = ResponseLength.NORMAL,
    val breathingRate: Float = 1.0f,
    val manualEmotion: EmotionType? = null,
    val autoEmotion: Boolean = true
) {
    val isBreathingRateDefault: Boolean
        get() = breathingRate == 1.0f

    val breathingRateLabel: String
        get() = "${breathingRate}x"
}
