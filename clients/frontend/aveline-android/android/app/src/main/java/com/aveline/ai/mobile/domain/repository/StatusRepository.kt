package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.LifeStatus
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.JsonObject

/**
 * Repository interface for AI status operations.
 * Abstracts data sources for life status and emotion state.
 */
interface StatusRepository {
    /** Get the current life status from the backend.
     * @param persona 正在查看的 persona 文件名（如 qq/Aveline_QQ_Master.json），按角色返回独立生命状态；为 null 用后端默认 scope
     */
    suspend fun getLifeStatus(persona: String? = null): Result<LifeStatus>

    /** 唤醒正在查看的角色。 */
    suspend fun wakeCompanion(persona: String?, conversationId: String?): Result<String>

    /** 打断正在查看角色的当前活动。 */
    suspend fun interruptCompanion(persona: String?, conversationId: String?): Result<String>

    /** 跳过正在查看角色的当前活动。 */
    suspend fun skipCompanionActivity(persona: String?, conversationId: String?): Result<String>
    
    /** Observe emotion state changes from WebSocket. */
    fun observeEmotion(): Flow<Emotion>

    /** 检测文本情绪 */
    suspend fun detectEmotion(text: String): Result<JsonObject>

    /** 获取主动关怀运行状态 */
    suspend fun getActiveCareStatus(): Result<JsonObject>

    /** 触发主动关怀检查 */
    suspend fun triggerActiveCareCheck(): Result<JsonObject>
}
