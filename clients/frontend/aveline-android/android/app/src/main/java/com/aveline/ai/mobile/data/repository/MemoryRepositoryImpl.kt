package com.aveline.ai.mobile.data.repository

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.MarkImportantRequest
import com.aveline.ai.mobile.data.remote.dto.MemoryDto
import com.aveline.ai.mobile.domain.models.*
import com.aveline.ai.mobile.domain.repository.MemoryRepository
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 记忆仓库实现
 * 
 * 从后端 API 获取和管理记忆数据
 * 
 * Requirements: 9.1, 9.2, 9.3, 9.5, 9.6
 */
@Singleton
class MemoryRepositoryImpl @Inject constructor(
    private val apiService: AvelineApiService,
    private val appPreferences: AppPreferences
) : MemoryRepository {
    
    private val _memoriesFlow = MutableSharedFlow<List<Memory>>(replay = 1)
    
    companion object {
        private const val TAG = "MemoryRepositoryImpl"
    }

    override suspend fun getMemories(
        filter: MemoryFilter,
        sortOrder: MemorySortOrder,
        persona: String?
    ): List<Memory> {
        return try {
            // 后端 category 是单值, 前端 types 是 Set, 取第一个非空类型
            val category = filter.types.firstOrNull()?.name?.lowercase()
            val response = apiService.getMemories(
                category = category,
                minWeight = filter.minImportance,
                includeThinking = filter.includeThinking,
                persona = persona
            )
            val memories = response.data.map { it.toDomain() }
            applySortOrder(memories, sortOrder)
        } catch (e: Exception) {
            Log.w(TAG, "获取记忆列表失败: ${e.message}")
            emptyList()
        }
    }

    override suspend fun searchMemories(query: String, persona: String?): List<Memory> {
        if (query.isBlank()) return emptyList()

        return try {
            // 后端没有独立的搜索端点：list_memories 只支持 category/emotion/min_weight 过滤。
            // 搜索策略：拉取当前角色的记忆列表（传 persona 保证按角色），在客户端按关键词过滤。
            val response = apiService.getMemories(
                includeThinking = true,
                limit = 500,
                persona = persona
            )
            val q = query.trim()
            response.data.map { it.toDomain() }.filter { memory ->
                memory.content.contains(q, ignoreCase = true) ||
                memory.tags.any { it.contains(q, ignoreCase = true) } ||
                memory.summary.contains(q, ignoreCase = true)
            }
        } catch (e: Exception) {
            Log.w(TAG, "搜索记忆失败: ${e.message}")
            emptyList()
        }
    }

    override suspend fun getMemory(id: String): Memory? {
        return try {
            apiService.getMemory(id).toDomain()
        } catch (e: Exception) {
            Log.w(TAG, "获取记忆详情失败: ${e.message}")
            null
        }
    }
    
    override suspend fun deleteMemory(id: String): Result<Unit> {
        return try {
            val response = apiService.deleteMemory(id)
            
            if (response.isSuccessful) {
                // 刷新记忆列表
                refreshMemories()
                Result.success(Unit)
            } else {
                Result.failure(Exception("删除失败: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    override suspend fun markImportant(id: String, important: Boolean): Result<Unit> {
        return try {
            val response = apiService.markMemoryImportant(id, MarkImportantRequest(important))
            
            if (response.isSuccessful) {
                refreshMemories()
                Result.success(Unit)
            } else {
                Result.failure(Exception("操作失败: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    override suspend fun getMemoryStats(persona: String?): MemoryStats {
        return try {
            apiService.getMemoryStats(persona).data.toDomain()
        } catch (e: Exception) {
            Log.w(TAG, "获取记忆统计失败: ${e.message}")
            MemoryStats()
        }
    }

    override suspend fun getMemoryTypes(): List<MemoryType> {
        return MemoryType.values().filter { it != MemoryType.UNKNOWN }
    }

    override suspend fun getTags(persona: String?): List<String> {
        return try {
            val response = apiService.getMemoryTags(persona)
            response.data.map { tagItem -> tagItem.name }
        } catch (e: Exception) {
            Log.w(TAG, "获取记忆标签失败: ${e.message}")
            emptyList()
        }
    }
    
    override fun observeMemories(): Flow<List<Memory>> = _memoriesFlow.asSharedFlow()

    override suspend fun clearAll(userId: String): Result<Unit> {
        return try {
            val response = apiService.clearAllMemories(userId)
            if (response.isSuccessful) {
                refreshMemories()
                Result.success(Unit)
            } else {
                Result.failure(Exception("清除失败: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun clearSessionHistory(userId: String, mode: String): Result<Unit> {
        return try {
            val payload = buildJsonObject {
                put("user_id", userId)
                put("mode", mode)
            }
            apiService.clearSessionHistory(payload)
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    private suspend fun refreshMemories() {
        val memories = getMemories()
        _memoriesFlow.tryEmit(memories)
    }
    
    private fun applySortOrder(memories: List<Memory>, sortOrder: MemorySortOrder): List<Memory> {
        return when (sortOrder) {
            MemorySortOrder.NEWEST_FIRST -> memories.sortedByDescending { it.createdAt }
            MemorySortOrder.OLDEST_FIRST -> memories.sortedBy { it.createdAt }
            MemorySortOrder.MOST_ACCESSED -> memories.sortedByDescending { it.accessCount }
            MemorySortOrder.MOST_IMPORTANT -> memories.sortedByDescending { it.importance }
        }
    }
}

/**
 * 扩展函数：DTO 转换为 Domain
 */
private fun MemoryDto.toDomain(): Memory {
     val cat = (category ?: memoryType ?: type ?: "uncategorized").lowercase()
     val created = parseMemoryInstant(createdAt, timestamp)
     val updated = parseMemoryInstant(updatedAt, lastAccessTime) ?: created
     val lastAccessed = parseMemoryInstant(lastAccessedAt, lastAccessTime) ?: updated
     // 后端 content 可能为空（distilled 记忆），此时用 summary 作为显示内容
     val displayContent = content.ifBlank { summary ?: "" }
     return Memory(
         id = id,
         content = displayContent,
         summary = summary ?: "",
         type = mapCategoryToType(cat),
         category = cat,
         importance = importance ?: weight ?: 0.5,
         accessCount = accessCount ?: 0,
         lastAccessedAt = lastAccessed,
         createdAt = created ?: Instant.now(),
         updatedAt = updated ?: Instant.now(),
         source = source ?: "conversation",
         tags = tags ?: topics ?: displayTags ?: keywords ?: searchKeywords ?: emptyList(),
         isImportant = isImportant ?: false
     )
 }

/** 后端 category 与前端 MemoryType 对齐 */
private fun mapCategoryToType(category: String): MemoryType {
    return when (category) {
        "daily" -> MemoryType.DAILY
        "learning" -> MemoryType.LEARNING
        "work" -> MemoryType.WORK
        "festival" -> MemoryType.FESTIVAL
        "health" -> MemoryType.HEALTH
        "profile" -> MemoryType.PROFILE
        "entertainment" -> MemoryType.ENTERTAINMENT
        "finance" -> MemoryType.FINANCE
        "tech" -> MemoryType.TECH
        "emotion" -> MemoryType.EMOTION
        "relationship" -> MemoryType.RELATIONSHIP
        "sensitive" -> MemoryType.SENSITIVE
        "preference" -> MemoryType.PREFERENCE
        "thinking" -> MemoryType.THINKING
        "uncategorized", "" -> MemoryType.UNCATEGORIZED
        else -> MemoryType.UNKNOWN
    }
}
 
 /**
  * 解析后端记忆时间字段。
  *
  * 后端可能返回 ISO-8601 字符串、"yyyy-MM-dd HH:mm:ss" 字符串,
  * 或 Unix 秒级时间戳(float/double)。按优先级依次尝试。
  */
 private fun parseMemoryInstant(isoOrDatetime: String?, unixSeconds: Double?): Instant? {
     if (!isoOrDatetime.isNullOrBlank()) {
         runCatching { Instant.parse(isoOrDatetime) }.getOrNull()?.let { return it }
         runCatching {
             java.time.LocalDateTime.parse(
                 isoOrDatetime,
                 java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
             ).atZone(java.time.ZoneId.systemDefault()).toInstant()
         }.getOrNull()?.let { return it }
     }
     unixSeconds?.let {
         runCatching { Instant.ofEpochMilli((it * 1000).toLong()) }.getOrNull()
     }?.let { return it }
     return null
 }
 
private fun com.aveline.ai.mobile.data.remote.dto.MemoryStatsData.toDomain(): MemoryStats {
    return MemoryStats(
        totalCount = totalMemories,
        dailyCount = counts["daily"] ?: 0,
        learningCount = counts["learning"] ?: 0,
        workCount = counts["work"] ?: 0,
        festivalCount = counts["festival"] ?: 0,
        healthCount = counts["health"] ?: 0,
        profileCount = counts["profile"] ?: 0,
        entertainmentCount = counts["entertainment"] ?: 0,
        financeCount = counts["finance"] ?: 0,
        techCount = counts["tech"] ?: 0,
        emotionCount = counts["emotion"] ?: 0,
        relationshipCount = counts["relationship"] ?: 0,
        sensitiveCount = counts["sensitive"] ?: 0,
        preferenceCount = counts["preference"] ?: 0,
        thinkingCount = counts["thinking"] ?: 0,
        uncategorizedCount = counts["uncategorized"] ?: 0,
        importantCount = counts["important"] ?: 0,
        totalAccessCount = 0
    )
}
