package com.aveline.ai.wear.data

import android.content.Context
import android.util.Log
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.records.HeightRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.BloodPressureRecord
import androidx.health.connect.client.records.BloodGlucoseRecord
import androidx.health.connect.client.records.BodyTemperatureRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * 手表端 Health Connect 数据读取器。
 *
 * 与 Health Services 不同,Health Connect 读取的是已经由 Samsung Health
 * 记录并同步到 Health Connect 的历史数据(睡眠/体重/身高/体脂等)。
 *
 * 这是纯 IO 操作,不涉及传感器实时采集。
 */
class HealthConnectReader(private val context: Context) {

    companion object {
        private const val TAG = "HCReader"

        /**
         * 检查 Health Connect 是否可用。
         *
         * 三星国行 Watch7 可能裁剪了 Health Connect 系统服务,
         * 即使 SDK 状态返回非 SDK_UNAVAILABLE,实际 getOrCreate 也会 NPE。
         * 所以这里做完整检查:SDK 状态 + getOrCreate 能成功创建 client。
         */
        fun isAvailable(context: Context): Boolean {
            return try {
                val status = HealthConnectClient.getSdkStatus(context)
                Log.i(TAG, "Health Connect SDK status: $status")
                if (status != HealthConnectClient.SDK_AVAILABLE) {
                    Log.w(TAG, "Health Connect SDK 不可用, status=$status")
                    return false
                }
                // 进一步验证 client 能否创建(国行可能 SDK 状态 OK 但系统服务缺失)
                HealthConnectClient.getOrCreate(context)
                true
            } catch (e: Exception) {
                Log.w(TAG, "Health Connect 不可用: ${e.message}")
                false
            }
        }
    }

    private val client: HealthConnectClient by lazy {
        HealthConnectClient.getOrCreate(context)
    }

    /**
     * 读取今日睡眠数据。
     *
     * SleepSessionRecord 包含睡眠时段的开始/结束时间和分钟数。
     * 查询范围: 过去 24 小时(覆盖昨晚睡眠)。
     */
    suspend fun readSleepData(): SleepSummary? {
        return try {
            val now = Instant.now()
            val yesterday = now.minus(24, ChronoUnit.HOURS)

            val request = ReadRecordsRequest(
                recordType = SleepSessionRecord::class,
                timeRangeFilter = TimeRangeFilter.between(yesterday, now)
            )
            val response = client.readRecords(request)

            if (response.records.isEmpty()) {
                Log.i(TAG, "睡眠记录为空")
                return null
            }

            // 取最近一条睡眠记录
            val latest = response.records.last()
            val durationMinutes = java.time.Duration.between(latest.startTime, latest.endTime).toMinutes()

            Log.i(TAG, "睡眠记录: start=${latest.startTime}, end=${latest.endTime}, minutes=$durationMinutes")

            SleepSummary(
                startEpochMillis = latest.startTime.toEpochMilli(),
                endEpochMillis = latest.endTime.toEpochMilli(),
                durationMinutes = durationMinutes
            )
        } catch (e: Exception) {
            Log.e(TAG, "读取睡眠数据失败: ${e.message}", e)
            null
        }
    }

    /**
     * 读取最新体重记录(过去 30 天)。
     */
    suspend fun readWeight(): WeightRecord? {
        return try {
            val now = Instant.now()
            val monthAgo = now.minus(30, ChronoUnit.DAYS)

            val request = ReadRecordsRequest(
                recordType = WeightRecord::class,
                timeRangeFilter = TimeRangeFilter.between(monthAgo, now),
                ascendingOrder = false,
                pageSize = 1
            )
            val response = client.readRecords(request)
            response.records.firstOrNull()?.also {
                Log.i(TAG, "体重: ${it.weight.inKilograms} kg @ ${it.time}")
            }
        } catch (e: Exception) {
            Log.e(TAG, "读取体重失败: ${e.message}", e)
            null
        }
    }

    /**
     * 读取最新身高记录(过去 365 天)。
     */
    suspend fun readHeight(): HeightRecord? {
        return try {
            val now = Instant.now()
            val yearAgo = now.minus(365, ChronoUnit.DAYS)

            val request = ReadRecordsRequest(
                recordType = HeightRecord::class,
                timeRangeFilter = TimeRangeFilter.between(yearAgo, now),
                ascendingOrder = false,
                pageSize = 1
            )
            val response = client.readRecords(request)
            response.records.firstOrNull()?.also {
                Log.i(TAG, "身高: ${it.height.inMeters} m @ ${it.time}")
            }
        } catch (e: Exception) {
            Log.e(TAG, "读取身高失败: ${e.message}", e)
            null
        }
    }

    /**
     * 读取最新体脂记录(过去 30 天)。
     */
    suspend fun readBodyFat(): BodyFatRecord? {
        return try {
            val now = Instant.now()
            val monthAgo = now.minus(30, ChronoUnit.DAYS)

            val request = ReadRecordsRequest(
                recordType = BodyFatRecord::class,
                timeRangeFilter = TimeRangeFilter.between(monthAgo, now),
                ascendingOrder = false,
                pageSize = 1
            )
            val response = client.readRecords(request)
            response.records.firstOrNull()?.also {
                Log.i(TAG, "体脂: ${it.percentage.value} % @ ${it.time}")
            }
        } catch (e: Exception) {
            Log.e(TAG, "读取体脂失败: ${e.message}", e)
            null
        }
    }

    /**
     * 读取最新血压记录(过去 24 小时)。
     */
    suspend fun readBloodPressure(): BloodPressureRecord? {
        return try {
            val now = Instant.now()
            val yesterday = now.minus(24, ChronoUnit.HOURS)

            val request = ReadRecordsRequest(
                recordType = BloodPressureRecord::class,
                timeRangeFilter = TimeRangeFilter.between(yesterday, now),
                ascendingOrder = false,
                pageSize = 1
            )
            val response = client.readRecords(request)
            response.records.firstOrNull()?.also {
                Log.i(TAG, "血压: ${it.systolic.inMillimetersOfMercury}mmHg/${it.diastolic.inMillimetersOfMercury}mmHg @ ${it.time}")
            }
        } catch (e: Exception) {
            Log.e(TAG, "读取血压失败: ${e.message}", e)
            null
        }
    }

    /**
     * 读取最新体温记录(过去 24 小时)。
     */
    suspend fun readBodyTemperature(): BodyTemperatureRecord? {
        return try {
            val now = Instant.now()
            val yesterday = now.minus(24, ChronoUnit.HOURS)

            val request = ReadRecordsRequest(
                recordType = BodyTemperatureRecord::class,
                timeRangeFilter = TimeRangeFilter.between(yesterday, now),
                ascendingOrder = false,
                pageSize = 1
            )
            val response = client.readRecords(request)
            response.records.firstOrNull()?.also {
                Log.i(TAG, "体温: ${it.temperature.inCelsius} C @ ${it.time}")
            }
        } catch (e: Exception) {
            Log.e(TAG, "读取体温失败: ${e.message}", e)
            null
        }
    }

    /**
     * 读取最新血糖记录(过去 24 小时)。
     */
    suspend fun readBloodGlucose(): BloodGlucoseRecord? {
        return try {
            val now = Instant.now()
            val yesterday = now.minus(24, ChronoUnit.HOURS)

            val request = ReadRecordsRequest(
                recordType = BloodGlucoseRecord::class,
                timeRangeFilter = TimeRangeFilter.between(yesterday, now),
                ascendingOrder = false,
                pageSize = 1
            )
            val response = client.readRecords(request)
            response.records.firstOrNull()?.also {
                Log.i(TAG, "血糖: ${it.level.inMillimolesPerLiter} mmol/L @ ${it.time}")
            }
        } catch (e: Exception) {
            Log.e(TAG, "读取血糖失败: ${e.message}", e)
            null
        }
    }

    /**
     * 一次性读取所有可用的健康数据。
     *
     * 每项独立 try, 失败不影响其他项。
     * 返回的 HealthSnapshot 包含所有能读到的字段。
     */
    suspend fun readAll(): HealthSnapshot {
        val sleep = readSleepData()
        val weight = readWeight()
        val height = readHeight()
        val bodyFat = readBodyFat()
        val bloodPressure = readBloodPressure()
        val bodyTemp = readBodyTemperature()
        val bloodGlucose = readBloodGlucose()

        return HealthSnapshot(
            sleep = sleep,
            weightKg = weight?.weight?.inKilograms,
            weightTimestamp = weight?.time?.toEpochMilli(),
            heightM = height?.height?.inMeters,
            heightTimestamp = height?.time?.toEpochMilli(),
            bodyFatPercent = bodyFat?.percentage?.value,
            bodyFatTimestamp = bodyFat?.time?.toEpochMilli(),
            systolic = bloodPressure?.systolic?.inMillimetersOfMercury?.toInt(),
            diastolic = bloodPressure?.diastolic?.inMillimetersOfMercury?.toInt(),
            bloodPressureTimestamp = bloodPressure?.time?.toEpochMilli(),
            bodyTempCelsius = bodyTemp?.temperature?.inCelsius,
            bodyTempTimestamp = bodyTemp?.time?.toEpochMilli(),
            bloodGlucoseMmolL = bloodGlucose?.level?.inMillimolesPerLiter,
            bloodGlucoseTimestamp = bloodGlucose?.time?.toEpochMilli(),
            collectedAt = Instant.now().toEpochMilli()
        )
    }
}

/** 睡眠摘要 */
data class SleepSummary(
    val startEpochMillis: Long,
    val endEpochMillis: Long,
    val durationMinutes: Long,
)

/** 健康数据快照(Health Connect 读取的所有历史数据) */
data class HealthSnapshot(
    val sleep: SleepSummary? = null,
    val weightKg: Double? = null,
    val weightTimestamp: Long? = null,
    val heightM: Double? = null,
    val heightTimestamp: Long? = null,
    val bodyFatPercent: Double? = null,
    val bodyFatTimestamp: Long? = null,
    val systolic: Int? = null,
    val diastolic: Int? = null,
    val bloodPressureTimestamp: Long? = null,
    val bodyTempCelsius: Double? = null,
    val bodyTempTimestamp: Long? = null,
    val bloodGlucoseMmolL: Double? = null,
    val bloodGlucoseTimestamp: Long? = null,
    val collectedAt: Long,
)
