package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable

/**
 * Response DTO for life status information.
 * 
 * @property status Response status
 * @property life_status The life status metrics
 * @property emotion Current emotion state
 * @property emotion_mix Emotion mix percentages
 */
@Serializable
data class LifeStatusResponse(
    val status: String,
    val life_status: LifeStatusDto,
    val emotion: String? = null,
    val emotion_mix: Map<String, Float>? = null,
    val activity: String = "idle",
    val activity_chat_eligible: Boolean = true,
    val reply_policy: ReplyPolicySummaryDto? = null,
    val sleep_summary: SleepSummaryDto? = null,
    val daily_plan: CharacterDailyPlanDto? = null
)

/** 当前活动对应的主对话基础回复方式。 */
@Serializable
data class ReplyPolicySummaryDto(
    val mode: String = "immediate",
    val reason: String = "free",
    val min_seconds: Int? = null,
    val max_seconds: Int? = null
)

/** 当前角色的睡眠阶段摘要。 */
@Serializable
data class SleepSummaryDto(
    val is_sleeping: Boolean = false,
    val phase: String? = null
)

/** 单个角色当天的日程计划。 */
@Serializable
data class CharacterDailyPlanDto(
    val role_id: String = "",
    val date: String = "",
    val slots: List<CharacterDailySlotDto> = emptyList(),
    val current_activity: String = "idle"
)

/** 日程中的一个时间槽。 */
@Serializable
data class CharacterDailySlotDto(
    val activity: String = "idle",
    val planned_start: String = "",
    val planned_end: String = "",
    val flexible: Boolean = true,
    val execution_status: String = "pending"
)

/**
 * Life status DTO representing AI assistant's life metrics.
 * 
 * @property health Health level (0.0 - 1.0)
 * @property hunger Hunger level (0.0 - 1.0)
 * @property happiness Happiness level (0.0 - 1.0)
 * @property energy Energy level (0.0 - 1.0)
 * @property timestamp Status timestamp in milliseconds
 */
@Serializable
 data class LifeStatusDto(
     val life: LifeMetricsDto? = null,
     val timestamp: String? = null
 )
 
 /**
  * 后端生命模拟返回的原始字段。
  *
  * 后端 state["life"] 使用 energy/hunger/thirst/mood_score 等字段,
  * 没有 health/happiness。UI 层需要时由 Repository 做语义映射。
  */
 @Serializable
 data class LifeMetricsDto(
     val energy: Float = 100f,
     val hunger: Float = 0f,
     val thirst: Float = 100f,
     val mood_score: Float = 80f,
     val shyness_score: Float = 0f,
     val immune_damage: Float = 0f,
     val is_sick: Boolean = false,
     val level: Int = 1,
     val xp: Int = 0,
     val coins: Int = 0
 )
