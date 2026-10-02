package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
  * 记忆 DTO。
  *
  * 兼容后端 weighted_memory_manager 返回的字段命名:
  * id / content / category / weight / timestamp / created_at / last_access_time /
  * topics / emotions / emotion / is_important / source / display_tags 等。
  */
 @Serializable
 data class MemoryDto(
     @SerialName("id")
     val id: String,
 
     @SerialName("content")
     val content: String,
 
     @SerialName("summary")
     val summary: String? = null,
 
     @SerialName("type")
     val type: String? = null,
 
     @SerialName("memory_type")
     val memoryType: String? = null,
 
     @SerialName("category")
     val category: String? = null,
 
     @SerialName("importance")
     val importance: Double? = null,
 
     @SerialName("weight")
     val weight: Double? = null,
 
     @SerialName("access_count")
     val accessCount: Int? = null,
 
     @SerialName("last_accessed_at")
     val lastAccessedAt: String? = null,
 
     @SerialName("last_access_time")
     val lastAccessTime: Double? = null,
 
     @SerialName("created_at")
     val createdAt: String? = null,
 
     @SerialName("timestamp")
     val timestamp: Double? = null,
 
     @SerialName("updated_at")
     val updatedAt: String? = null,
 
     @SerialName("source")
     val source: String? = null,
 
     @SerialName("tags")
     val tags: List<String>? = null,
 
     @SerialName("topics")
     val topics: List<String>? = null,
 
     @SerialName("display_tags")
     val displayTags: List<String>? = null,
 
     @SerialName("keywords")
     val keywords: List<String>? = null,

     @SerialName("search_keywords")
     val searchKeywords: List<String>? = null,
 
     @SerialName("emotion")
     val emotion: String? = null,

     @SerialName("emotions")
     val emotions: List<String>? = null,
 
     @SerialName("is_important")
     val isImportant: Boolean? = null
 )

/**
 * 记忆列表响应
 */
@Serializable
data class MemoryListResponse(
    @SerialName("status")
    val status: String,
    
    @SerialName("data")
    val data: List<MemoryDto>,
    
    @SerialName("timestamp")
    val timestamp: Double? = null
)

/**
  * 记忆统计数据。
  *
  * 后端 /api/v1/memories/stats 返回:
  * counts / avg_weight / total_memories / distribution
  */
 @Serializable
 data class MemoryStatsData(
     @SerialName("counts")
     val counts: Map<String, Int> = emptyMap(),
 
     @SerialName("avg_weight")
     val avgWeight: Map<String, Double> = emptyMap(),
 
     @SerialName("total_memories")
     val totalMemories: Int = 0,
 
     @SerialName("distribution")
     val distribution: Map<String, Double> = emptyMap()
 )

/**
 * 记忆统计响应
 */
@Serializable
data class MemoryStatsResponse(
    @SerialName("status")
    val status: String,
    
    @SerialName("data")
    val data: MemoryStatsData,
    
    @SerialName("timestamp")
    val timestamp: Double? = null
)

/**
 * 记忆标签项
 */
@Serializable
data class TagItem(
    @SerialName("name")
    val name: String,
    
    @SerialName("weight")
    val weight: Double
)

/**
 * 记忆标签响应
 */
@Serializable
data class TagsResponse(
    @SerialName("status")
    val status: String,
    
    @SerialName("data")
    val data: List<TagItem>,
    
    @SerialName("timestamp")
    val timestamp: Double? = null
)
