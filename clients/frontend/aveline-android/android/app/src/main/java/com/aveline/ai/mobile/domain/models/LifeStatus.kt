package com.aveline.ai.mobile.domain.models

import kotlinx.serialization.Serializable

/**
 * Domain model for AI life status metrics.
 * Represents the AI's vital statistics (health, hunger, happiness, energy).
 */
@Serializable
data class LifeStatus(
    val health: Float,
    val hunger: Float,
    val happiness: Float,
    val energy: Float,
    val timestamp: Long,
    /** 该状态所属的角色 scope（aveline/ling/rushuang/yeye 等），用于缓存命中判断 */
    val scope: String? = null,
    /** character_daily 当前活动。 */
    val activity: String = "idle",
    /** 当前活动是否适合发起角色间 Peer Chat；不代表用户消息是否即时回复。 */
    val activityChatEligible: Boolean = true,
    /** 主对话基础回复方式：immediate / delayed / silent。 */
    val replyMode: String = "immediate",
    val replyDelayMinSeconds: Int? = null,
    val replyDelayMaxSeconds: Int? = null,
    /** 睡眠管理器是否判定角色仍在睡眠中。 */
    val isSleeping: Boolean = false,
    /** 睡眠阶段，例如 sleeping / waking。 */
    val sleepPhase: String? = null,
    /** 当前角色当天的完整日程。 */
    val dailyPlan: CharacterDailyPlan? = null
) {
    /**
     * Check if any life status metric is below the warning threshold (20%).
     */
    fun hasLowStatus(): Boolean {
        return health < 0.2f || hunger < 0.2f || happiness < 0.2f || energy < 0.2f
    }
    
    /**
     * Get the lowest status value.
     */
    fun getLowestStatus(): Float {
        return minOf(health, hunger, happiness, energy)
    }
}

@Serializable
data class CharacterDailyPlan(
    val roleId: String,
    val date: String,
    val currentActivity: String,
    val slots: List<CharacterDailySlot>
)

@Serializable
data class CharacterDailySlot(
    val activity: String,
    val plannedStart: String,
    val plannedEnd: String,
    val flexible: Boolean,
    val executionStatus: String
)
