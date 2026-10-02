package com.aveline.ai.wear.data

import android.content.Context
import android.util.Log
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.tasks.await

/**
 * 通过 Wearable Data Layer 向手机端发送健康数据。
 *
 * 路径: /wear/health
 *
 * 数据分两类:
 * 1. 实时数据(Health Services): 步数、心率
 * 2. 历史数据(Health Connect): 睡眠、体重、身高、体脂、血压、体温、血糖
 */
class WearDataSender(context: Context) {

    private val dataClient = Wearable.getDataClient(context)

    /**
     * 发送实时数据(步数 + 心率)。
     * 由 HealthCollectService 的被动监听回调触发。
     */
    suspend fun sendHealthData(
        steps: Long,
        heartRate: Int?,
        heartRateTimestamp: Long?
    ) {
        val request = PutDataMapRequest.create(PATH_HEALTH).apply {
            dataMap.putLong(FIELD_STEPS, steps)
            heartRate?.let { dataMap.putInt(FIELD_HEART_RATE, it) }
            heartRateTimestamp?.let { dataMap.putLong(FIELD_HEART_RATE_TIMESTAMP, it) }
            dataMap.putLong(FIELD_COLLECTED_AT, System.currentTimeMillis())
        }
        runCatching {
            dataClient.putDataItem(request.asPutDataRequest()).await()
        }.onFailure { e ->
            Log.e(TAG, "发送实时数据失败: ${e.message}", e)
        }
    }

    /**
     * 发送完整健康数据(实时 + Health Connect 历史数据)。
     * 由用户手动触发"读取健康数据"或定时任务调用。
     */
    suspend fun sendFullHealthData(
        steps: Long,
        heartRate: Int?,
        heartRateTimestamp: Long?,
        snapshot: HealthSnapshot
    ) {
        val request = PutDataMapRequest.create(PATH_HEALTH).apply {
            // 实时数据
            dataMap.putLong(FIELD_STEPS, steps)
            heartRate?.let { dataMap.putInt(FIELD_HEART_RATE, it) }
            heartRateTimestamp?.let { dataMap.putLong(FIELD_HEART_RATE_TIMESTAMP, it) }

            // 睡眠
            snapshot.sleep?.let { sleep ->
                dataMap.putLong(FIELD_SLEEP_START, sleep.startEpochMillis)
                dataMap.putLong(FIELD_SLEEP_END, sleep.endEpochMillis)
                dataMap.putLong(FIELD_SLEEP_MINUTES, sleep.durationMinutes)
            }

            // 体重
            snapshot.weightKg?.let { dataMap.putDouble(FIELD_WEIGHT_KG, it) }
            snapshot.weightTimestamp?.let { dataMap.putLong(FIELD_WEIGHT_TIMESTAMP, it) }

            // 身高
            snapshot.heightM?.let { dataMap.putDouble(FIELD_HEIGHT_M, it) }
            snapshot.heightTimestamp?.let { dataMap.putLong(FIELD_HEIGHT_TIMESTAMP, it) }

            // 体脂
            snapshot.bodyFatPercent?.let { dataMap.putDouble(FIELD_BODY_FAT_PERCENT, it) }
            snapshot.bodyFatTimestamp?.let { dataMap.putLong(FIELD_BODY_FAT_TIMESTAMP, it) }

            // 血压
            snapshot.systolic?.let { dataMap.putInt(FIELD_SYSTOLIC, it) }
            snapshot.diastolic?.let { dataMap.putInt(FIELD_DIASTOLIC, it) }
            snapshot.bloodPressureTimestamp?.let { dataMap.putLong(FIELD_BP_TIMESTAMP, it) }

            // 体温
            snapshot.bodyTempCelsius?.let { dataMap.putDouble(FIELD_BODY_TEMP_C, it) }
            snapshot.bodyTempTimestamp?.let { dataMap.putLong(FIELD_BODY_TEMP_TIMESTAMP, it) }

            // 血糖
            snapshot.bloodGlucoseMmolL?.let { dataMap.putDouble(FIELD_BLOOD_GLUCOSE, it) }
            snapshot.bloodGlucoseTimestamp?.let { dataMap.putLong(FIELD_BLOOD_GLUCOSE_TIMESTAMP, it) }

            dataMap.putLong(FIELD_COLLECTED_AT, System.currentTimeMillis())
        }
        runCatching {
            dataClient.putDataItem(request.asPutDataRequest()).await()
            Log.i(TAG, "完整健康数据已发送到手机")
        }.onFailure { e ->
            Log.e(TAG, "发送完整数据失败: ${e.message}", e)
        }
    }

    companion object {
        private const val TAG = "WearDataSender"
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
        const val FIELD_BODY_FAT_TIMESTAMP = "body_fat_timestamp"
        // 血压
        const val FIELD_SYSTOLIC = "systolic"
        const val FIELD_DIASTOLIC = "diastolic"
        const val FIELD_BP_TIMESTAMP = "bp_timestamp"
        // 体温
        const val FIELD_BODY_TEMP_C = "body_temp_c"
        const val FIELD_BODY_TEMP_TIMESTAMP = "body_temp_timestamp"
        // 血糖
        const val FIELD_BLOOD_GLUCOSE = "blood_glucose"
        const val FIELD_BLOOD_GLUCOSE_TIMESTAMP = "blood_glucose_timestamp"
        // 元信息
        const val FIELD_COLLECTED_AT = "collected_at"
    }
}
