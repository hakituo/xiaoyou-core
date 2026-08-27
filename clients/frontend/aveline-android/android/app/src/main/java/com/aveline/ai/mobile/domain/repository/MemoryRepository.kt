package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemoryFilter
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import com.aveline.ai.mobile.domain.models.MemoryStats
import com.aveline.ai.mobile.domain.models.MemoryType
import kotlinx.coroutines.flow.Flow

/**
 * 记忆仓库接口
 * 
 * 定义记忆的读取和管理操作
 * 
 * Requirements: 9.1, 9.2, 9.3, 9.5, 9.6
 */
interface MemoryRepository {
    
    /**
     * 获取所有记忆
     *
     * @param persona 可选，按 persona 查询记忆：传人格文件名（如 qq/Aveline_QQ_Master.json），
     *                由后端解析成 shared__scope__{scope} 返回该角色的记忆池。
     *                不传则用后端默认 user_id（"default"）。
     */
    suspend fun getMemories(
        filter: MemoryFilter = MemoryFilter(),
        sortOrder: MemorySortOrder = MemorySortOrder.NEWEST_FIRST,
        persona: String? = null
    ): List<Memory>
    
    /**
     * 搜索记忆
     * 
     * @param query 搜索关键词
     * @param persona 可选，按 persona 文件名搜索对应记忆池
     */
    suspend fun searchMemories(query: String, persona: String? = null): List<Memory>
    
    /**
     * 获取单个记忆
     */
    suspend fun getMemory(id: String): Memory?
    
    /**
     * 删除记忆
     */
    suspend fun deleteMemory(id: String): Result<Unit>
    
    /**
     * 标记记忆为重要
     */
    suspend fun markImportant(id: String, important: Boolean): Result<Unit>
    
    /**
     * 获取记忆统计
     *
     * @param persona 可选，按 persona 文件名查询对应记忆池统计
     */
    suspend fun getMemoryStats(persona: String? = null): MemoryStats

    /**
     * 获取记忆类型列表
     */
    suspend fun getMemoryTypes(): List<MemoryType>

    /**
     * 获取标签列表
     *
     * @param persona 可选，按 persona 文件名查询对应记忆池标签
     */
    suspend fun getTags(persona: String? = null): List<String>
    
    /**
     * 观察记忆变化
     */
    fun observeMemories(): Flow<List<Memory>>

    /** 批量清除所有加权记忆 */
    suspend fun clearAll(userId: String = "default"): Result<Unit>

    /** 清除会话历史 */
    suspend fun clearSessionHistory(userId: String, mode: String): Result<Unit>
}
