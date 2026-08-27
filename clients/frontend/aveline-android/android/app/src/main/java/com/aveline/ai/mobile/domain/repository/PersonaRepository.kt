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

    /** 获取当前激活的人格（原始 JSON 对象，含完整配置字段） */
    suspend fun getActivePersonaRaw(): Result<JsonObject>
}
