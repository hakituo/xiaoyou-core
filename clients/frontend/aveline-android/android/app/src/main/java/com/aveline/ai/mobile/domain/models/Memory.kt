package com.aveline.ai.mobile.domain.models

import java.time.Instant

/**
 * 记忆类型（与后端 taxonomy.CATEGORY_ORDER 对齐）
 *
 * 后端真实分类：daily(日常) / learning(学习) / work(工作) / festival(节日)
 * / health(健康) / profile(画像) / entertainment(娱乐) / finance(财务)
 * / tech(科技) / emotion(情绪) / relationship(关系) / sensitive(敏感)
 * 以及 uncategorized(未分类) / thinking(思考) / preference(偏好) 等。
 */
enum class MemoryType {
    DAILY,          // 日常
    LEARNING,       // 学习
    WORK,           // 工作
    FESTIVAL,       // 节日
    HEALTH,         // 健康
    PROFILE,        // 画像
    ENTERTAINMENT,  // 娱乐
    FINANCE,        // 财务
    TECH,           // 科技
    EMOTION,        // 情绪
    RELATIONSHIP,   // 关系
    SENSITIVE,      // 敏感
    PREFERENCE,     // 偏好
    THINKING,       // 思考
    UNCATEGORIZED,  // 未分类
    UNKNOWN
}

/**
 * 记忆数据模型
 * 
 * @property id 记忆 ID
 * @property content 记忆内容（后端 content 可能为空，此时用 summary）
 * @property summary 记忆摘要（后端 distilled 后的简短描述）
 * @property type 记忆类型
 * @property category 后端原始分类名（uncategorized/preference/event 等）
 * @param importance 重要性 (0-1)
 * @property accessCount 访问次数
 * @property lastAccessedAt 最后访问时间
 * @property createdAt 创建时间
 * @property updatedAt 更新时间
 * @property source 来源 (对话/手动添加)
 * @property tags 标签
 * @property isImportant 是否标记为重要
 */
data class Memory(
    val id: String,
    val content: String,
    val summary: String = "",
    val type: MemoryType = MemoryType.UNKNOWN,
    val category: String = "",
    val importance: Double = 0.5,
    val accessCount: Int = 0,
    val lastAccessedAt: Instant? = null,
    val createdAt: Instant = Instant.now(),
    val updatedAt: Instant = Instant.now(),
    val source: String = "conversation",
    val tags: List<String> = emptyList(),
    val isImportant: Boolean = false
) {
    /** 显示用文本：content 优先，为空时回退到 summary */
    val displayContent: String
        get() = content.ifBlank { summary }
    val formattedCreatedAt: String
        get() = formatRelativeTime(createdAt)
    
    val formattedType: String
        get() = when (type) {
            MemoryType.DAILY -> "日常"
            MemoryType.LEARNING -> "学习"
            MemoryType.WORK -> "工作"
            MemoryType.FESTIVAL -> "节日"
            MemoryType.HEALTH -> "健康"
            MemoryType.PROFILE -> "画像"
            MemoryType.ENTERTAINMENT -> "娱乐"
            MemoryType.FINANCE -> "财务"
            MemoryType.TECH -> "科技"
            MemoryType.EMOTION -> "情绪"
            MemoryType.RELATIONSHIP -> "关系"
            MemoryType.SENSITIVE -> "敏感"
            MemoryType.PREFERENCE -> "偏好"
            MemoryType.THINKING -> "思考"
            MemoryType.UNCATEGORIZED -> "未分类"
            MemoryType.UNKNOWN -> "未知"
        }
    
    val importanceLevel: ImportanceLevel
        get() = when {
            importance >= 0.8 -> ImportanceLevel.HIGH
            importance >= 0.5 -> ImportanceLevel.MEDIUM
            else -> ImportanceLevel.LOW
        }
}

/**
 * 重要性级别
 */
enum class ImportanceLevel {
    LOW,
    MEDIUM,
    HIGH
}

/**
 * 记忆排序方式
 */
enum class MemorySortOrder {
    NEWEST_FIRST,
    OLDEST_FIRST,
    MOST_ACCESSED,
    MOST_IMPORTANT
}

data class MemoryStats(
    val totalCount: Int = 0,
    val dailyCount: Int = 0,
    val learningCount: Int = 0,
    val workCount: Int = 0,
    val festivalCount: Int = 0,
    val healthCount: Int = 0,
    val profileCount: Int = 0,
    val entertainmentCount: Int = 0,
    val financeCount: Int = 0,
    val techCount: Int = 0,
    val emotionCount: Int = 0,
    val relationshipCount: Int = 0,
    val sensitiveCount: Int = 0,
    val preferenceCount: Int = 0,
    val thinkingCount: Int = 0,
    val uncategorizedCount: Int = 0,
    val importantCount: Int = 0,
    val totalAccessCount: Int = 0
)

/**
 * 记忆过滤器
 */
data class MemoryFilter(
    val types: Set<MemoryType> = emptySet(),
    val showImportantOnly: Boolean = false,
    val minImportance: Double? = null,
    val tags: Set<String> = emptySet(),
    /** 是否包含 thinking 分类记忆 (后端默认 false 会把 thinking 整批排除, 前端默认 true 让用户看到所有记忆) */
    val includeThinking: Boolean = true
) {
    val isActive: Boolean
        get() = types.isNotEmpty() || showImportantOnly || minImportance != null || tags.isNotEmpty()
}

/**
 * 格式化相对时间
 */
private fun formatRelativeTime(instant: Instant): String {
    val now = Instant.now()
    val diffMs = now.toEpochMilli() - instant.toEpochMilli()
    
    val minutes = diffMs / (1000 * 60)
    val hours = minutes / 60
    val days = hours / 24
    
    return when {
        days > 30 -> "${days / 30} 个月前"
        days > 7 -> "${days / 7} 周前"
        days > 0 -> "${days} 天前"
        hours > 0 -> "${hours} 小时前"
        minutes > 0 -> "${minutes} 分钟前"
        else -> "刚刚"
    }
}
