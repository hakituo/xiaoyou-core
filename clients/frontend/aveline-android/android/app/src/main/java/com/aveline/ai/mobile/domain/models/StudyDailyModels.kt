package com.aveline.ai.mobile.domain.models

/**
 * Study/Daily 文件夹相关领域模型。
 *
 * DailyPlan 的应用真源来自后端结构化 JSON；plan.md 只保留为人类可读投影。
 */

data class CalendarDay(
    val date: String,
    val day: Int,
    val hasDiary: Boolean,
    val hasPlan: Boolean,
    val hasProgress: Boolean
)

data class DailyContent(
    val date: String,
    val diary: String,
    val plan: String,
    val progress: String
)

data class DailyNote(
    val filename: String,
    val path: String,
    val year: Int,
    val month: Int
)

data class DailyNoteContent(
    val filename: String,
    val path: String,
    val content: String
)

data class LibraryNote(
    val subject: String,
    val filename: String,
    val relPath: String,
    val updatedTs: Long
)

data class LatestProgress(
    val date: String,
    val path: String,
    val content: String
)

/**
 * 结构化 DailyPlan。
 *
 * 与后端 core.services.journal.models.DailyPlan 对齐；Android 不再从 plan.md 反解析。
 * dailyGoalMinutes 是后端从 study.daily_study_goal_minutes 动态投影的唯一日目标。
 */
data class StudyPlan(
    val date: String,
    val dailyGoalMinutes: Int = 0,
    val items: List<StudyPlanItem> = emptyList(),
    val notes: String? = null,
    val source: String = "",
    val checkpointReviews: Map<String, Double> = emptyMap(),
    val revisionCount: Int = 0,
    val generatedAt: Double = 0.0,
    val updatedAt: Double = 0.0
)

/**
 * 结构化计划项。
 *
 * content / duration / isDone 保留现有 UI 所需字段名；其余字段直接投影后端 PlanItem，
 * 让计划页逐步摆脱 Markdown 文本语义并可直接按稳定 id 操作。
 */
data class StudyPlanItem(
    val id: String = "",
    val time: String = "",
    val content: String = "",
    val duration: String = "",
    val isDone: Boolean = false,
    val description: String? = null,
    val category: String = "study",
    val subject: String? = null,
    val priority: String = "normal",
    val estimatedDurationMinutes: Int = 60,
    val actualMinutes: Double = 0.0,
    val status: String = "pending",
    val reminderId: String? = null,
    val endReminderId: String? = null,
    val sourceKey: String = "",
    val sourceType: String = "algorithm",
    val score: Double = 0.0,
    val carryoverCount: Int = 0,
    val deferredFromDate: String? = null,
    val settlementReason: String? = null,
    val createdAt: Double = 0.0,
    val updatedAt: Double = 0.0
)

/** 旧 UI / 调用点兼容别名；底层已经是 typed StudyPlanItem。 */
typealias PlanItem = StudyPlanItem

/**
 * 日记条目（来自 /api/v1/diary，journal 系统）。
 *
 * [source] 是作者 scope（user / aveline / ling / ye …），角色会增删，**不可硬编码列举**；
 * [sourceLabel] 是后端按权威画像给出的作者展示名（"我" / "Aveline" / "Ling" …），
 * UI 一律用它做标签，这样新角色与"已下线但留有日记"的历史角色都能正常显示。
 */
data class DiaryEntry(
    val id: String,
    val timestamp: Long,
    val timeStr: String,
    val type: String,
    val content: String,
    val thought: String?,
    val mood: String,
    val tags: List<String>,
    val source: String,
    val sourceLabel: String = ""
) {
    /** 作者展示名：后端没给（老后端 / 解析失败）时退回 scope 本身，绝不猜成别的角色。 */
    val authorLabel: String
        get() = sourceLabel.ifBlank { source }
}
