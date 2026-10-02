package com.aveline.ai.mobile.domain.models

import java.time.Instant

/**
 * 健康数据模型
 * 
 * 包含从 Health Connect 读取的所有健康数据
 * 
 * @property steps 今日步数
 * @property stepsGoal 步数目标
 * @property heartRate 最新心率 (bpm)
 * @property heartRateTimestamp 心率测量时间
 * @property oxygenSaturation 血氧饱和度 (0-1)
 * @property oxygenSaturationTimestamp 血氧测量时间
 * @property weight 体重
 * @property height 身高
 * @property bmi 体重指数
 * @property bodyFat 体脂率 (0-1)
 * @property sleepMinutes 昨晚睡眠时长 (分钟)
 * @property sleepStartTime 睡眠开始时间
 * @property sleepEndTime 睡眠结束时间
 * @property caloriesBurned 今日消耗卡路里
 * @property bloodPressureSystolic 收缩压
 * @property bloodPressureDiastolic 舒张压
 * @property bloodGlucose 血糖
 * @property bodyTemperature 体温 (°C)
 * @property lastUpdated 数据最后更新时间
 */
data class HealthData(
    val steps: Long = 0,
    val stepsGoal: Long = 10000,
    val heartRate: Int? = null,
    val heartRateTimestamp: Instant? = null,
    val oxygenSaturation: Double? = null,
    val oxygenSaturationTimestamp: Instant? = null,
    val weight: Double? = null,
    val weightTimestamp: Instant? = null,
    val height: Double? = null,
    val heightTimestamp: Instant? = null,
    val bmi: Double? = null,
    val bodyFat: Double? = null,
    val sleepMinutes: Long? = null,
    val sleepStartTime: Instant? = null,
    val sleepEndTime: Instant? = null,
    val caloriesBurned: Double? = null,
    val bloodPressureSystolic: Double? = null,
    val bloodPressureDiastolic: Double? = null,
    val bloodGlucose: Double? = null,
    val bodyTemperature: Double? = null,
    val lastUpdated: Instant = Instant.now()
) {
    val stepsProgress: Float
        get() = if (stepsGoal > 0) (steps.toFloat() / stepsGoal.toFloat()).coerceIn(0f, 1f) else 0f
    
    val hasVitalSigns: Boolean
        get() = heartRate != null || oxygenSaturation != null
    
    val hasBodyMetrics: Boolean
        get() = weight != null || height != null || bmi != null
    
    val hasSleepData: Boolean
        get() = sleepMinutes != null && sleepMinutes > 0
    
    val formattedSleepDuration: String
        get() {
            if (sleepMinutes == null) return "--"
            val hours = sleepMinutes / 60
            val minutes = sleepMinutes % 60
            return if (hours > 0) {
                "${hours}h ${minutes}m"
            } else {
                "${minutes}m"
            }
        }
}

/**
 * Health Connect 可用性状态
 */
enum class HealthConnectAvailability {
    AVAILABLE,
    NOT_INSTALLED,
    UPDATE_REQUIRED,
    NOT_SUPPORTED
}

/**
 * 健康权限状态
 */
data class HealthPermissionState(
    val steps: Boolean = false,
    val heartRate: Boolean = false,
    val oxygenSaturation: Boolean = false,
    val sleep: Boolean = false,
    val weight: Boolean = false,
    val height: Boolean = false,
    val bodyFat: Boolean = false,
    val calories: Boolean = false,
    val bloodPressure: Boolean = false,
    val bloodGlucose: Boolean = false,
    val bodyTemperature: Boolean = false
) {
    val allGranted: Boolean
        get() = steps && heartRate && oxygenSaturation && sleep && 
                weight && height && bodyFat && calories &&
                bloodPressure && bloodGlucose && bodyTemperature
    
    val vitalSignsGranted: Boolean
        get() = steps && heartRate && oxygenSaturation
    
    val bodyMetricsGranted: Boolean
        get() = weight && height && bodyFat
    
    val missingPermissionsCount: Int
        get() = listOf(
            steps, heartRate, oxygenSaturation, sleep,
            weight, height, bodyFat, calories,
            bloodPressure, bloodGlucose, bodyTemperature
        ).count { !it }
}
