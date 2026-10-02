package com.aveline.ai.mobile.data.samsung

import android.util.Log
import com.samsung.android.sdk.health.data.HealthDataStore
import com.samsung.android.sdk.health.data.data.Field
import com.samsung.android.sdk.health.data.data.HealthDataPoint
import com.samsung.android.sdk.health.data.request.DataType
import com.samsung.android.sdk.health.data.request.DataTypes
import com.samsung.android.sdk.health.data.request.InstantTimeFilter
import com.samsung.android.sdk.health.data.request.Ordering
import java.time.Instant
import java.time.temporal.ChronoUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 取某个体成分字段在记录集合里的最近一次非空值。
 *
 * 某次测量没测这一项时该记录该字段为 null,不能因此认定"没有体成分数据",
 * 需要继续往前找更早的记录,直到找到该字段有值的最近一条。
 */
internal fun <T : Any> latestBodyCompositionValue(
    points: List<HealthDataPoint>,
    field: Field<T>
): T? = points
    .sortedByDescending { it.endTime }
    .firstNotNullOfOrNull { it.getValue(field) }

/**
 * 低频体征读取器: 身体成分、血压、体温、血糖。
 *
 * 这些都是"站上秤/量一次才变"的数据,由后台低频通道(24 小时)读取,
 * 见 SamsungHealthSyncController; 高频数据见 [SamsungHealthVitalsReader]。
 *
 * 方法统一为 internal: 对外只通过 [SamsungHealthReader] 门面暴露。
 */
@Singleton
class SamsungHealthBodyReader @Inject constructor(
    private val store: HealthDataStore
) {
    /**
     * 读取身体成分记录(最近 [BODY_COMPOSITION_LOOKBACK_DAYS] 天内, 时间倒序, 最多 [BODY_COMPOSITION_MAX_RECORDS] 条)。
     *
     * 为什么不只读"最新一条记录":
     * 1. Samsung Health 的体重可能来自普通体重秤或手动录入, 这类记录只有体重字段;
     *    而体脂率/骨骼肌/水分来自体脂秤的另一次测量。只取最新一条时, 一旦最新那条
     *    只有体重, 其余字段会全部为 null, 界面表现就是"身体成分全是 N/A"。
     * 2. 回溯窗口过窄会把久未测量的体成分整片滤掉。Samsung Health App 自身展示的是
     *    任意久以前的"最近一次体成分", 所以窗口必须远宽于 30 天, 否则会出现
     *    "三星健康里明明有数据, App 里全是 N/A"。
     *
     * 各字段的取值口径统一为"窗口内最近一次非空值"(见 [latestBodyCompositionValue])。
     */
    internal suspend fun readBodyCompositionPoints(now: Instant): List<HealthDataPoint> = runCatching {
        val since = now.minus(BODY_COMPOSITION_LOOKBACK_DAYS, ChronoUnit.DAYS)
        val request = DataTypes.BODY_COMPOSITION.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .setLimit(BODY_COMPOSITION_MAX_RECORDS)
            .setOrdering(Ordering.DESC)
            .build()
        val points = store.readData(request).dataList
        Log.d(
            TAG,
            "体成分记录 ${points.size} 条, 区间 ${since} ~ ${now}, " +
                // endTime 是 Instant?(可能为空), 不能用 maxByOrNull(它要求非空 Comparable)
                "最新测量时间=${points.mapNotNull { it.endTime }.maxOrNull()}"
        )
        points
    }.onFailure { e ->
        // 权限缺失/平台异常时返回空列表, 界面上表现为 N/A;
        // 必须留下日志, 否则"没数据"和"读失败"在界面上无法区分。
        Log.w(TAG, "读取身体成分失败: ${e.message}", e)
    }.getOrDefault(emptyList())

    /**
     * 读取血压字段(最近 30 天最新一条)。
     */
    internal suspend fun readBloodPressureField(
        field: Field<Float>,
        now: Instant
    ): Float? = runCatching {
        val since = now.minus(30, ChronoUnit.DAYS)
        val request = DataTypes.BLOOD_PRESSURE.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .setLimit(1)
            .setOrdering(Ordering.DESC)
            .build()
        val response = store.readData(request)
        response.dataList.firstOrNull()?.getValue<Float>(field)
    }.onFailure { e ->
        Log.w(TAG, "读取血压失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取体温(最近 30 天最新一条)。
     */
    internal suspend fun readBodyTemperature(now: Instant): Float? = runCatching {
        val since = now.minus(30, ChronoUnit.DAYS)
        val request = DataTypes.BODY_TEMPERATURE.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .setLimit(1)
            .setOrdering(Ordering.DESC)
            .build()
        val response = store.readData(request)
        response.dataList.firstOrNull()?.getValue<Float>(DataType.BodyTemperatureType.BODY_TEMPERATURE)
    }.onFailure { e ->
        Log.w(TAG, "读取体温失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取血糖(最近 30 天最新一条)。
     */
    internal suspend fun readBloodGlucose(now: Instant): Float? = runCatching {
        val since = now.minus(30, ChronoUnit.DAYS)
        val request = DataTypes.BLOOD_GLUCOSE.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .setLimit(1)
            .setOrdering(Ordering.DESC)
            .build()
        val response = store.readData(request)
        response.dataList.firstOrNull()?.getValue<Float>(DataType.BloodGlucoseType.GLUCOSE_LEVEL)
    }.onFailure { e ->
        Log.w(TAG, "读取血糖失败: ${e.message}")
    }.getOrNull()

    companion object {
        private const val TAG = "SamsungHealthBody"

        /**
         * 体成分查询回溯天数。
         *
         * 体成分不像心率那样天天更新, 用户可能几个月才测一次; 30 天的窗口会让
         * "上一次测量"直接过滤掉, 表现为整块 N/A。这里放宽到一年。
         */
        private const val BODY_COMPOSITION_LOOKBACK_DAYS = 365L

        /** 体成分单次最多拉取的记录条数(倒序, 即最近的若干条), 避免记录过密时一次拉太多。 */
        private const val BODY_COMPOSITION_MAX_RECORDS = 200
    }
}
