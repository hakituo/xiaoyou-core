package com.aveline.ai.mobile.data.wear

import android.content.Context
import android.util.Log
import com.aveline.ai.mobile.domain.models.HealthData
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.DataEvent
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import java.time.Instant

/**
 * 通过 Wearable Data Layer 接收手表端健康数据。
 *
 * 监听路径 `/wear/health`,接收两类数据:
 * 1. 实时数据(Health Services): 步数、心率
 * 2. 历史数据(Health Connect): 睡眠、体重、身高、体脂、血压、体温、血糖
 *
 * 如果 Wearable API 在当前设备不可用(部分 ROM 裁剪了 Wearable 模块),
 * 返回空 Flow 优雅降级,绝不崩溃。
 */
class WearDataSource(private val context: Context) {

    companion object {
        private const val TAG = "WearDataSource"
        const val PATH_HEALTH = "/wear/health"
        // 实时数据
        const val FIELD_STEPS = "steps"
        const val FIELD_HEART_RATE = "heart_rate"
        const val FIELD_HEART_RATE_TIMESTAMP = "heart_rate_timestamp"
        // 睡眠
        const val FIELD_SLEEP_START = "sleep_start"
        const val FIELD_SLEEP_END = "sleep_end"
        const val FIELD_SLEEP_MINUTES = "sleep_minutes"
        // 体重
        const val FIELD_WEIGHT_KG = "weight_kg"
        const val FIELD_WEIGHT_TIMESTAMP = "weight_timestamp"
        // 身高
        const val FIELD_HEIGHT_M = "height_m"
        const val FIELD_HEIGHT_TIMESTAMP = "height_timestamp"
        // 体脂
        const val FIELD_BODY_FAT_PERCENT = "body_fat_percent"
        // 血压
        const val FIELD_SYSTOLIC = "systolic"
        const val FIELD_DIASTOLIC = "diastolic"
        // 体温
        const val FIELD_BODY_TEMP_C = "body_temp_c"
        // 血糖
        const val FIELD_BLOOD_GLUCOSE = "blood_glucose"
        // 元信息
        const val FIELD_COLLECTED_AT = "collected_at"
    }

    /**
     * 检查 Wearable API 在当前设备是否可用。
     *
     * 部分手机虽然有 Google Play Services,但 ROM 裁剪了 Wearable 模块,
     * 会导致 ConnectionResult{statusCode=API_UNAVAILABLE}。
     */
    private fun isWearableAvailable(): Boolean {
        return try {
            val availability = GoogleApiAvailability.getInstance()
            val result = availability.isGooglePlayServicesAvailable(context)
            if (result != ConnectionResult.SUCCESS) {
                Log.w(TAG, "Google Play Services 不可用: $result")
                return false
            }
            true
        } catch (e: Exception) {
            Log.w(TAG, "Wearable API 检查失败: ${e.message}")
            false
        }
    }

    fun observeHealthData(): Flow<HealthData> = callbackFlow {
        // 先检查 Wearable API 是否可用,不可用则优雅关闭(不传异常,不崩溃)
        if (!isWearableAvailable()) {
            Log.w(TAG, "Wearable API 不可用,跳过手表数据监听")
            close()
            return@callbackFlow
        }

        val dataClient: DataClient = try {
            Wearable.getDataClient(context)
        } catch (e: Exception) {
            Log.e(TAG, "创建 DataClient 失败: ${e.message}")
            close()
            return@callbackFlow
        }

        val listener = DataClient.OnDataChangedListener { dataEvents: DataEventBuffer ->
            dataEvents.forEach { event ->
                if (event.type == DataEvent.TYPE_CHANGED && event.dataItem.uri.path == PATH_HEALTH) {
                    val dataMap = DataMapItem.fromDataItem(event.dataItem).dataMap

                    val healthData = HealthData(
                        steps = dataMap.getLong(FIELD_STEPS, 0L),
                        heartRate = if (dataMap.containsKey(FIELD_HEART_RATE)) {
                            dataMap.getInt(FIELD_HEART_RATE)
                        } else null,
                        heartRateTimestamp = dataMap.getLong(FIELD_HEART_RATE_TIMESTAMP, -1L)
                            .takeIf { it > 0 }
                            ?.let { Instant.ofEpochMilli(it) },
                        // 睡眠
                        sleepMinutes = if (dataMap.containsKey(FIELD_SLEEP_MINUTES)) {
                            dataMap.getLong(FIELD_SLEEP_MINUTES)
                        } else null,
                        sleepStartTime = dataMap.getLong(FIELD_SLEEP_START, -1L)
                            .takeIf { it > 0 }
                            ?.let { Instant.ofEpochMilli(it) },
                        sleepEndTime = dataMap.getLong(FIELD_SLEEP_END, -1L)
                            .takeIf { it > 0 }
                            ?.let { Instant.ofEpochMilli(it) },
                        // 体重
                        weight = if (dataMap.containsKey(FIELD_WEIGHT_KG)) {
                            dataMap.getDouble(FIELD_WEIGHT_KG)
                        } else null,
                        weightTimestamp = dataMap.getLong(FIELD_WEIGHT_TIMESTAMP, -1L)
                            .takeIf { it > 0 }
                            ?.let { Instant.ofEpochMilli(it) },
                        // 身高
                        height = if (dataMap.containsKey(FIELD_HEIGHT_M)) {
                            dataMap.getDouble(FIELD_HEIGHT_M)
                        } else null,
                        heightTimestamp = dataMap.getLong(FIELD_HEIGHT_TIMESTAMP, -1L)
                            .takeIf { it > 0 }
                            ?.let { Instant.ofEpochMilli(it) },
                        // 体脂
                        bodyFat = if (dataMap.containsKey(FIELD_BODY_FAT_PERCENT)) {
                            dataMap.getDouble(FIELD_BODY_FAT_PERCENT)
                        } else null,
                        // 血压
                        bloodPressureSystolic = if (dataMap.containsKey(FIELD_SYSTOLIC)) {
                            dataMap.getInt(FIELD_SYSTOLIC).toDouble()
                        } else null,
                        bloodPressureDiastolic = if (dataMap.containsKey(FIELD_DIASTOLIC)) {
                            dataMap.getInt(FIELD_DIASTOLIC).toDouble()
                        } else null,
                        // 体温
                        bodyTemperature = if (dataMap.containsKey(FIELD_BODY_TEMP_C)) {
                            dataMap.getDouble(FIELD_BODY_TEMP_C)
                        } else null,
                        // 血糖
                        bloodGlucose = if (dataMap.containsKey(FIELD_BLOOD_GLUCOSE)) {
                            dataMap.getDouble(FIELD_BLOOD_GLUCOSE)
                        } else null,
                        lastUpdated = dataMap.getLong(FIELD_COLLECTED_AT, -1L)
                            .takeIf { it > 0 }
                            ?.let { Instant.ofEpochMilli(it) }
                            ?: Instant.now()
                    )
                    trySend(healthData)
                }
            }
            dataEvents.release()
        }

        // addListener 失败时优雅关闭(不传异常),避免 Flow 消费方崩溃
        dataClient.addListener(listener).apply {
            addOnSuccessListener { Log.i(TAG, "Wearable DataClient 监听已启动") }
            addOnFailureListener { e ->
                Log.w(TAG, "Wearable API 不可用,已跳过手表数据监听: ${e.message}")
                close()
            }
        }

        awaitClose {
            runCatching { dataClient.removeListener(listener) }
        }
    }
}
