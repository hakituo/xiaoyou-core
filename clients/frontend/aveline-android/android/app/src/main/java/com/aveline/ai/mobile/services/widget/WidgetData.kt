package com.aveline.ai.mobile.services.widget

/**
 * Widget 数据模型
 */
data class WidgetData(
    val aiName: String = "Aveline",
    val emotionPrimary: String = "neutral",
    val emotionIntensity: Float = 0.5f,
    val emotionText: String = "心情平静",
    val health: Float = 0.8f,
    val happiness: Float = 0.7f,
    val energy: Float = 0.6f,
    val hunger: Float = 0.5f,
    val lastMessage: String = "",
    val lastMessageTime: String = "",
    val isConnected: Boolean = false,
    val connectionState: String = "未连接"
) {
    companion object {
        /**
         * 从 SharedPreferences 读取 Widget 数据
         */
        fun fromPreferences(prefs: android.content.SharedPreferences): WidgetData {
            return WidgetData(
                aiName = prefs.getString("widget_ai_name", "Aveline") ?: "Aveline",
                emotionPrimary = prefs.getString("widget_emotion_primary", "neutral") ?: "neutral",
                emotionIntensity = prefs.getFloat("widget_emotion_intensity", 0.5f),
                emotionText = prefs.getString("widget_emotion_text", "心情平静") ?: "心情平静",
                health = prefs.getFloat("widget_health", 0.8f),
                happiness = prefs.getFloat("widget_happiness", 0.7f),
                energy = prefs.getFloat("widget_energy", 0.6f),
                hunger = prefs.getFloat("widget_hunger", 0.5f),
                lastMessage = prefs.getString("widget_last_message", "") ?: "",
                lastMessageTime = prefs.getString("widget_last_message_time", "") ?: "",
                isConnected = prefs.getBoolean("widget_is_connected", false),
                connectionState = prefs.getString("widget_connection_state", "未连接") ?: "未连接"
            )
        }
    }

    /**
     * 保存到 SharedPreferences
     */
    fun toPreferences(prefs: android.content.SharedPreferences) {
        prefs.edit().apply {
            putString("widget_ai_name", aiName)
            putString("widget_emotion_primary", emotionPrimary)
            putFloat("widget_emotion_intensity", emotionIntensity)
            putString("widget_emotion_text", emotionText)
            putFloat("widget_health", health)
            putFloat("widget_happiness", happiness)
            putFloat("widget_energy", energy)
            putFloat("widget_hunger", hunger)
            putString("widget_last_message", lastMessage)
            putString("widget_last_message_time", lastMessageTime)
            putBoolean("widget_is_connected", isConnected)
            putString("widget_connection_state", connectionState)
            apply()
        }
    }

    /**
     * 获取情绪对应的 emoji
     */
    fun getEmotionEmoji(): String {
        return when (emotionPrimary.lowercase()) {
            "happy" -> "😊"
            "sad" -> "😢"
            "excited" -> "🤩"
            "calm" -> "😌"
            "angry" -> "😠"
            "surprised" -> "😲"
            "neutral" -> "😐"
            else -> "💖"
        }
    }

    /**
     * 获取情绪对应的颜色资源
     */
    fun getEmotionColor(): String {
        return when (emotionPrimary.lowercase()) {
            "happy" -> "#4CAF50"
            "sad" -> "#2196F3"
            "excited" -> "#FF9800"
            "calm" -> "#9C27B0"
            "angry" -> "#F44336"
            "surprised" -> "#FFEB3B"
            else -> "#607D8B"
        }
    }
}
