package com.aveline.ai.mobile.data.samsung

import android.util.Log
import com.samsung.android.sdk.health.data.HealthDataStore
import com.samsung.android.sdk.health.data.request.DataType
import com.samsung.android.sdk.health.data.request.DataTypes
import com.samsung.android.sdk.health.data.request.InstantTimeFilter
import com.samsung.android.sdk.health.data.request.LocalDateFilter
import com.samsung.android.sdk.health.data.request.Ordering
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.temporal.ChronoUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 能量评分、健康预警与各类健康目标读取器。
 *
 * 评分与预警沿用最新的单条记录口径; 各类目标(睡眠/步数/热量/时长/饮水/营养)
 * 都是 LocalDate 维度的聚合查询, 见 [readLocalDateAggregate]。
 *
 * 方法统一为 internal: 对外只通过 [SamsungHealthReader] 门面暴露。
 */
@Singleton
class SamsungHealthScoreGoalReader @Inject constructor(
    private val store: HealthDataStore
) {
    /**
     * 读取睡眠呼吸暂停征兆(最近 7 天最新一条,返回枚举名称字符串)。
     */
    internal suspend fun readSleepApneaSign(now: Instant): String? = runCatching {
        val since = now.minus(7, ChronoUnit.DAYS)
        val request = DataTypes.SLEEP_APNEA.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .setLimit(1)
            .setOrdering(Ordering.DESC)
            .build()
        val response = store.readData(request)
        response.dataList.firstOrNull()
            ?.getValue<DataType.SleepApneaType.DetectedSign>(DataType.SleepApneaType.DETECTED_SIGN)
            ?.name
    }.onFailure { e ->
        Log.w(TAG, "读取睡眠呼吸暂停征兆失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取心律不齐通知状态(最近 7 天最新一条,返回枚举名称字符串)。
     */
    internal suspend fun readIrregularHeartRhythmStatus(now: Instant): String? = runCatching {
        val since = now.minus(7, ChronoUnit.DAYS)
        val request = DataTypes.IRREGULAR_HEART_RHYTHM_NOTIFICATION.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .setLimit(1)
            .setOrdering(Ordering.DESC)
            .build()
        val response = store.readData(request)
        response.dataList.firstOrNull()
            ?.getValue<DataType.IrregularHeartRhythmNotificationType.IrregularHeartRhythmStatus>(
                DataType.IrregularHeartRhythmNotificationType.STATUS
            )
            ?.name
    }.onFailure { e ->
        Log.w(TAG, "读取心律不齐状态失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取今日能量评分。
     * 注意:ENERGY_SCORE 使用 LocalDateBuilder(非 DualTimeBuilder),
     * 不能用 setInstantTimeFilter,需用 setLocalDateFilter(LocalDateFilter)。
     *
     * 修复: of(today, today) 在 SDK 内部被判定 "Time Range is invalid"(start==end),
     * 改用 since(today) 表示 [today, +∞) 开放区间。
     */
    internal suspend fun readEnergyScore(today: LocalDate): Float? = runCatching {
        val request = DataTypes.ENERGY_SCORE.readDataRequestBuilder
            .setLocalDateFilter(LocalDateFilter.since(today))
            .setLimit(1)
            .setOrdering(Ordering.DESC)
            .build()
        val response = store.readData(request)
        response.dataList.firstOrNull()?.getValue<Float>(DataType.EnergyScoreType.ENERGY_SCORE)
    }.onFailure { e ->
        Log.w(TAG, "读取能量评分失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取睡眠目标就寝时间(LocalTime)。
     */
    internal suspend fun readSleepGoalBedTime(today: LocalDate): LocalTime? =
        readLocalDateAggregate(store, DataType.SleepGoalType.LAST_BED_TIME, today, "睡眠目标就寝时间")

    /**
     * 读取睡眠目标起床时间(LocalTime)。
     */
    internal suspend fun readSleepGoalWakeTime(today: LocalDate): LocalTime? =
        readLocalDateAggregate(store, DataType.SleepGoalType.LAST_WAKE_UP_TIME, today, "睡眠目标起床时间")

    /**
     * 读取步数目标(Integer)。
     */
    internal suspend fun readStepsGoal(today: LocalDate): Int? =
        readLocalDateAggregate(store, DataType.StepsGoalType.LAST, today, "步数目标")

    /**
     * 读取活动热量目标(Integer,kcal)。
     */
    internal suspend fun readActiveCaloriesGoal(today: LocalDate): Int? =
        readLocalDateAggregate(store, DataType.ActiveCaloriesBurnedGoalType.LAST, today, "活动热量目标")

    /**
     * 读取活动时长目标(Duration)。
     */
    internal suspend fun readActiveTimeGoal(today: LocalDate): Duration? =
        readLocalDateAggregate(store, DataType.ActiveTimeGoalType.LAST, today, "活动时长目标")

    /**
     * 读取饮水目标(Float,ml)。
     */
    internal suspend fun readWaterIntakeGoal(today: LocalDate): Float? =
        readLocalDateAggregate(store, DataType.WaterIntakeGoalType.LAST, today, "饮水目标")

    /**
     * 读取热量摄入目标(Float,kcal)。
     */
    internal suspend fun readNutritionGoal(today: LocalDate): Float? =
        readLocalDateAggregate(store, DataType.NutritionGoalType.LAST_CALORIES, today, "热量摄入目标")

    companion object {
        private const val TAG = "SamsungHealthScore"
    }
}
