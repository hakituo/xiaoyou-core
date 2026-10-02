package com.aveline.ai.mobile.data.samsung

import android.util.Log
import com.samsung.android.sdk.health.data.HealthDataStore
import com.samsung.android.sdk.health.data.request.DataType
import com.samsung.android.sdk.health.data.request.DataTypes
import com.samsung.android.sdk.health.data.request.InstantTimeFilter
import com.samsung.android.sdk.health.data.request.LocalTimeFilter
import com.samsung.android.sdk.health.data.request.Ordering
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit
import javax.inject.Inject
import javax.inject.Singleton

/** 活动汇总(今日累计)。 */
internal data class ActivitySummaryData(
    val activeCalories: Float,
    val totalCalories: Float,
    val activeTime: Duration,
    val totalDistance: Float
)

/** 皮肤温度三元组(°C,各字段独立可空)。 */
internal data class SkinTemperatureData(
    val current: Float?,
    val min: Float?,
    val max: Float?
)

/** 血氧饱和度三元组(0-1,各字段独立可空)。 */
internal data class BloodOxygenData(
    val current: Float?,
    val min: Float?,
    val max: Float?
)

/**
 * 高频生命体征读取器。
 *
 * 覆盖心率(含测量时间)、皮肤温度、血氧饱和度、今日步数、今日活动汇总和爬楼层数。
 * 这些数据变化频繁,由后台高频通道(默认 20 秒级)读取,见 SamsungHealthSyncController。
 *
 * 方法统一为 internal: 对外只通过 [SamsungHealthReader] 门面暴露。
 */
@Singleton
class SamsungHealthVitalsReader @Inject constructor(
    private val store: HealthDataStore
) {
    /**
     * 读取最新心率值。取最近 24 小时内最后一条心率记录。
     */
    internal suspend fun readHeartRate(now: Instant): Int? = runCatching {
        val since = now.minus(24, ChronoUnit.HOURS)
        val request = DataTypes.HEART_RATE.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .setLimit(1)
            .setOrdering(Ordering.DESC)
            .build()
        val response = store.readData(request)
        response.dataList.firstOrNull()?.getValue<Float>(DataType.HeartRateType.HEART_RATE)?.toInt()
    }.onFailure { e ->
        Log.w(TAG, "读取心率失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取最新心率测量时间。
     */
    internal suspend fun readHeartRateTimestamp(now: Instant): Instant? = runCatching {
        val since = now.minus(24, ChronoUnit.HOURS)
        val request = DataTypes.HEART_RATE.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .setLimit(1)
            .setOrdering(Ordering.DESC)
            .build()
        val response = store.readData(request)
        response.dataList.firstOrNull()?.endTime
    }.onFailure { e ->
        Log.w(TAG, "读取心率时间失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取皮肤温度三元组(当前/最低/最高,最近 24 小时最新一条)。
     * 三字段独立可空,即使部分字段缺失也会返回非空 Data。
     */
    internal suspend fun readSkinTemperatureData(now: Instant): SkinTemperatureData? = runCatching {
        val since = now.minus(24, ChronoUnit.HOURS)
        val request = DataTypes.SKIN_TEMPERATURE.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .setLimit(1)
            .setOrdering(Ordering.DESC)
            .build()
        val response = store.readData(request)
        val dp = response.dataList.firstOrNull() ?: return@runCatching null
        SkinTemperatureData(
            current = dp.getValue<Float>(DataType.SkinTemperatureType.SKIN_TEMPERATURE),
            min = dp.getValue<Float>(DataType.SkinTemperatureType.MIN_SKIN_TEMPERATURE),
            max = dp.getValue<Float>(DataType.SkinTemperatureType.MAX_SKIN_TEMPERATURE)
        )
    }.onFailure { e ->
        Log.w(TAG, "读取皮肤温度失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取血氧饱和度三元组(当前/最低/最高,最近 24 小时最新一条)。
     * SDK 返回百分比数值(如 95.0 表示 95%),由调用方转 0-1。
     */
    internal suspend fun readBloodOxygenData(now: Instant): BloodOxygenData? = runCatching {
        val since = now.minus(24, ChronoUnit.HOURS)
        val request = DataTypes.BLOOD_OXYGEN.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .setLimit(1)
            .setOrdering(Ordering.DESC)
            .build()
        val response = store.readData(request)
        val dp = response.dataList.firstOrNull() ?: return@runCatching null
        BloodOxygenData(
            current = dp.getValue<Float>(DataType.BloodOxygenType.OXYGEN_SATURATION),
            min = dp.getValue<Float>(DataType.BloodOxygenType.MIN_OXYGEN_SATURATION),
            max = dp.getValue<Float>(DataType.BloodOxygenType.MAX_OXYGEN_SATURATION)
        )
    }.onFailure { e ->
        Log.w(TAG, "读取血氧失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取今日总步数(聚合查询,Long)。
     */
    internal suspend fun readStepsToday(start: LocalDateTime, end: LocalDateTime): Long? =
        readLocalTimeAggregate(store, DataType.StepsType.TOTAL, start, end, "今日步数")

    /**
     * 读取今日活动汇总(4 个聚合字段)。
     * 包含:活动消耗热量/总消耗热量/活动时长/总距离(米)。
     */
    internal suspend fun readActivitySummary(
        start: LocalDateTime,
        end: LocalDateTime
    ): ActivitySummaryData? = runCatching {
        val activeCalories = readLocalTimeAggregate(
            store, DataType.ActivitySummaryType.TOTAL_ACTIVE_CALORIES_BURNED, start, end, "活动消耗热量"
        )
        val totalCalories = readLocalTimeAggregate(
            store, DataType.ActivitySummaryType.TOTAL_CALORIES_BURNED, start, end, "总消耗热量"
        )
        val activeTime = readLocalTimeAggregate(
            store, DataType.ActivitySummaryType.TOTAL_ACTIVE_TIME, start, end, "活动时长"
        )
        val totalDistance = readLocalTimeAggregate(
            store, DataType.ActivitySummaryType.TOTAL_DISTANCE, start, end, "总距离"
        )
        // 四字段全为空时返回 null
        if (activeCalories == null && totalCalories == null && activeTime == null && totalDistance == null) null
        else ActivitySummaryData(
            activeCalories = activeCalories ?: 0f,
            totalCalories = totalCalories ?: 0f,
            activeTime = activeTime ?: Duration.ZERO,
            totalDistance = totalDistance ?: 0f
        )
    }.onFailure { e ->
        Log.w(TAG, "读取活动汇总失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取今日爬楼层数(所有记录求和)。
     */
    internal suspend fun readFloorsClimbedToday(): Float? = runCatching {
        val (start, end) = todayLocalTimeRange()
        val request = DataTypes.FLOORS_CLIMBED.readDataRequestBuilder
            .setLocalTimeFilter(LocalTimeFilter.of(start, end))
            .build()
        val response = store.readData(request)
        val sum = response.dataList.mapNotNull { it.getValue<Float>(DataType.FloorsClimbedType.FLOOR) }.sum()
        sum.takeIf { it > 0f }
    }.onFailure { e ->
        Log.w(TAG, "读取爬楼层数失败: ${e.message}")
    }.getOrNull()

    companion object {
        private const val TAG = "SamsungHealthVitals"
    }
}
