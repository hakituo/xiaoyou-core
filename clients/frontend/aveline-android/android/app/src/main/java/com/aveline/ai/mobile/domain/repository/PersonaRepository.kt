package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.domain.models.Persona
import com.aveline.ai.mobile.domain.models.PersonaRequest
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

/**
 * 人格仓库接口
 * 
 * 定义人格的管理操作
 * 
 * Requirements: 11.1, 11.2, 11.3, 11.4, 11.5
 */
interface PersonaRepository {
    
    /**
     * 获取所有人格
     */
    suspend fun getPersonas(): List<Persona>
    
    /**
     * 获取当前激活的人格
     */
    suspend fun getActivePersona(): Persona?
    
    /**
     * 选择人格
     */
    suspend fun selectPersona(personaId: String): Result<Unit>
    
    /**
     * 创建人格
     */
    suspend fun createPersona(request: PersonaRequest): Result<Persona>
    
    /**
     * 更新人格
     */
    suspend fun updatePersona(personaId: String, request: PersonaRequest): Result<Persona>
    
    /**
     * 删除人格
     */
    suspend fun deletePersona(personaId: String): Result<Unit>
    
    /**
     * 观察人格变化
     */
    fun observePersonas(): Flow<List<Persona>>
    
    /**
     * 观察当前激活的人格
     */
    fun observeActivePersona(): Flow<Persona?>

    // ==================== 原始 JSON 接口（用于 Web 端 UI） ====================

    /** 获取所有人格（原始 JSON 数组，含完整配置字段） */
    suspend fun getPersonasRaw(): Result<JsonArray>

    /**
     * 获取所有人格（原始 JSON 数组），带**进程级缓存**与单飞。
     *
     * 与 [getPersonasRaw] 的区别只在缓存粒度：结果缓存在单例仓库里，整个进程只真正
     * 请求一次，并发调用合并成一个请求。
     *
     * 为什么需要它：聊天页的 persona 默认值缓存（默认模型 / 默认音色 / persona -> role）
     * 挂在 `ChatSessionController` 上，而那是**每个 ChatViewModel 一份**，每次重进聊天页
     * 都会重建。于是「进入角色后的第一次发送」必然要等一次 `GET /api/v1/personas`
     * 返回才肯往下走（`consumePendingSwitchIfNeeded` → `ensurePersonaDefaults`）——
     * 后端一慢，用户看到的就是「点了发送半天没反应」，然后重复点击。
     * 发送路径上不该出现任何可以提前完成的网络请求。
     */
    suspend fun getPersonasRawCached(): Result<JsonArray>

    /** 获取当前激活的人格（原始 JSON 对象，含完整配置字段） */
    suspend fun getActivePersonaRaw(): Result<JsonObject>

    /**
     * 获取可用音色名列表（后端 voice_map 的全部键，如 Ling/Ye/Aveline/VoiceArtist）。
     *
     * 这些名字可直接作为 `/api/v1/media/tts` 的 voice 参数；
     * 客户端不维护任何"角色 -> 音色"表，候选与默认值都来自后端。
     */
    suspend fun getAvailableVoices(): Result<List<String>>
}
