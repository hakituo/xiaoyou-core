package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.domain.models.EmotionType
import com.aveline.ai.mobile.domain.models.PluginSettings
import com.aveline.ai.mobile.domain.models.ResponseLength
import kotlinx.coroutines.flow.Flow

/**
 * 插件和设置仓库接口
 * 
 * 定义模型管理和设置操作
 * 
 * Requirements: 12.1, 12.2, 12.3, 12.4, 12.5
 */
interface PluginsRepository {
    
    /**
     * 获取可用模型列表
     */
    suspend fun getModels(): List<AIModel>
    
    /**
     * 获取当前选中的模型
     */
    suspend fun getSelectedModel(): AIModel?
    
    /**
     * 切换模型
     */
    suspend fun switchModel(modelId: String): Result<Unit>
    
    /**
     * 获取插件设置
     */
    suspend fun getSettings(): PluginSettings
    
    /**
     * 设置响应长度
     */
    suspend fun setResponseLength(length: ResponseLength): Result<Unit>
    
    /**
     * 设置呼吸频率
     */
    suspend fun setBreathingRate(rate: Float): Result<Unit>
    
    /**
     * 设置手动情绪
     */
    suspend fun setManualEmotion(emotion: EmotionType?): Result<Unit>
    
    /**
     * 切换自动情绪
     */
    suspend fun setAutoEmotion(enabled: Boolean): Result<Unit>
    
    /**
     * 观察模型变化
     */
    fun observeModels(): Flow<List<AIModel>>
    
    /**
     * 观察设置变化
     */
    fun observeSettings(): Flow<PluginSettings>
}
