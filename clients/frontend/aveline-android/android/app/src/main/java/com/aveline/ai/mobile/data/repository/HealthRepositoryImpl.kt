package com.aveline.ai.mobile.data.repository

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeightRecord
import androidx.health.connect.client.records.OxygenSaturationRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.records.BloodPressureRecord
import androidx.health.connect.client.records.BloodGlucoseRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.BodyTemperatureRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.domain.models.HealthConnectAvailability
import com.aveline.ai.mobile.domain.models.HealthData
import com.aveline.ai.mobile.domain.models.HealthPermissionState
import com.aveline.ai.mobile.domain.repository.HealthRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.serialization.json.JsonObject
import java.time.Instant
import java.time.temporal.ChronoUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Health Connect 数据仓库实现
 * 
 * 使用 Android Health Connect SDK 读取健康数据
 * 
 * Requirements: 8.1, 8.2, 16.2
 */
@Singleton
class HealthRepositoryImpl @Inject constructor(
    @ApplicationContext private val context: Context,
    private val apiService: AvelineApiService
) : HealthRepository {
    
    private val healthConnectClient: HealthConnectClient by lazy {
        HealthConnectClient.getOrCreate(context)
    }
    
    private val _healthDataFlow = MutableSharedFlow<HealthData>(replay = 1)
    
    companion object {
        private val REQUIRED_PERMISSIONS = setOf(
            HealthPermission.getReadPermission(StepsRecord::class),
            HealthPermission.getReadPermission(HeartRateRecord::class),
            HealthPermission.getReadPermission(OxygenSaturationRecord::class),
            HealthPermission.getReadPermission(SleepSessionRecord::class),
            HealthPermission.getReadPermission(TotalCaloriesBurnedRecord::class),
            HealthPermission.getReadPermission(WeightRecord::class),
            HealthPermission.getReadPermission(HeightRecord::class),
            HealthPermission.getReadPermission(BodyFatRecord::class),
            HealthPermission.getReadPermission(BloodPressureRecord::class),
            HealthPermission.getReadPermission(BloodGlucoseRecord::class),
            HealthPermission.getReadPermission(BodyTemperatureRecord::class)
        )
    }
    
    override suspend fun checkAvailability(): HealthConnectAvailability {
        try {
            val status = HealthConnectClient.getSdkStatus(context)
            return when (status) {
                HealthConnectClient.SDK_AVAILABLE -> HealthConnectAvailability.AVAILABLE
                HealthConnectClient.SDK_UNAVAILABLE -> HealthConnectAvailability.NOT_INSTALLED
                HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> HealthConnectAvailability.UPDATE_REQUIRED
                else -> HealthConnectAvailability.NOT_SUPPORTED
            }
        } catch (e: Exception) {
            return HealthConnectAvailability.NOT_SUPPORTED
        }
    }
    
    override suspend fun getPermissionState(): HealthPermissionState {
        val grantedStrings = try {
            healthConnectClient.permissionController
                .getGrantedPermissions()
                .map { it.toString() }
                .toSet()
        } catch (e: Exception) {
            emptySet()
        }

        return HealthPermissionState(
            steps = grantedStrings.contains(HealthPermission.getReadPermission(StepsRecord::class).toString()),
            heartRate = grantedStrings.contains(HealthPermission.getReadPermission(HeartRateRecord::class).toString()),
            oxygenSaturation = grantedStrings.contains(HealthPermission.getReadPermission(OxygenSaturationRecord::class).toString()),
            sleep = grantedStrings.contains(HealthPermission.getReadPermission(SleepSessionRecord::class).toString()),
            weight = grantedStrings.contains(HealthPermission.getReadPermission(WeightRecord::class).toString()),
            height = grantedStrings.contains(HealthPermission.getReadPermission(HeightRecord::class).toString()),
            bodyFat = grantedStrings.contains(HealthPermission.getReadPermission(BodyFatRecord::class).toString()),
            calories = grantedStrings.contains(HealthPermission.getReadPermission(TotalCaloriesBurnedRecord::class).toString()),
            bloodPressure = grantedStrings.contains(HealthPermission.getReadPermission(BloodPressureRecord::class).toString()),
            bloodGlucose = grantedStrings.contains(HealthPermission.getReadPermission(BloodGlucoseRecord::class).toString()),
            bodyTemperature = grantedStrings.contains(HealthPermission.getReadPermission(BodyTemperatureRecord::class).toString())
        )
    }
    
    override fun getRequiredPermissions(): Set<String> = REQUIRED_PERMISSIONS
    
    override suspend fun hasAllPermissions(): Boolean {
        try {
            if (checkAvailability() != HealthConnectAvailability.AVAILABLE) return false
            val grantedStrings = healthConnectClient.permissionController
                .getGrantedPermissions()
                .map { it.toString() }
                .toSet()
            return REQUIRED_PERMISSIONS.all { required ->
                grantedStrings.contains(required.toString())
            }
        } catch (e: Exception) {
            return false
        }
    }

    /**
     * 获取当前 Health Connect SDK 可用性(缓存, 不抛异常)。
     * 国行三星等设备可能未安装官方 Provider, 上层需据此展示更友好的文案。
     */
    override suspend fun getCurrentAvailability(): HealthConnectAvailability {
        return checkAvailability()
    }
    
    override suspend fun readHealthData(): HealthData? {
        if (!hasAllPermissions()) return null
        
        return try {
            val vitalSigns = readVitalSignsInternal()
            val bodyMetrics = readBodyMetricsInternal()
            
            HealthData(
                steps = vitalSigns.steps,
                heartRate = vitalSigns.heartRate,
                heartRateTimestamp = vitalSigns.heartRateTimestamp,
                oxygenSaturation = vitalSigns.oxygenSaturation,
                oxygenSaturationTimestamp = vitalSigns.oxygenSaturationTimestamp,
                weight = bodyMetrics.weight,
                weightTimestamp = bodyMetrics.weightTimestamp,
                height = bodyMetrics.height,
                heightTimestamp = bodyMetrics.heightTimestamp,
                sleepMinutes = bodyMetrics.sleepMinutes,
                sleepStartTime = bodyMetrics.sleepStartTime,
                sleepEndTime = bodyMetrics.sleepEndTime,
                caloriesBurned = vitalSigns.caloriesBurned,
                lastUpdated = Instant.now()
            ).also {
                _healthDataFlow.tryEmit(it)
            }
        } catch (e: Exception) {
            null
        }
    }
    
    override suspend fun readVitalSigns(): HealthData? {
        if (!hasAllPermissions()) return null
        return try {
            readVitalSignsInternal()
        } catch (e: Exception) {
            null
        }
    }
    
    override suspend fun readBodyMetrics(): HealthData? {
        if (!hasAllPermissions()) return null
        return try {
            readBodyMetricsInternal()
        } catch (e: Exception) {
            null
        }
    }
    
    override fun observeHealthData(): Flow<HealthData> = _healthDataFlow.asSharedFlow()
    
    override fun openHealthConnectSettings() {
        try {
            val intent = Intent("androidx.health.ACTION_HEALTH_CONNECT_SETTINGS")
            context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: Exception) {
            try {
                // Fallback to market
                val intent = Intent(Intent.ACTION_VIEW).apply {
                    data = Uri.parse("market://details?id=com.google.android.apps.healthdata")
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                context.startActivity(intent)
            } catch (e2: Exception) {
                // If no market app
                val intent = Intent(Intent.ACTION_VIEW).apply {
                    data = Uri.parse("https://play.google.com/store/apps/details?id=com.google.android.apps.healthdata")
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                context.startActivity(intent)
            }
        }
    }

    // ==================== 每日画像与记录相关实现 ====================

    override suspend fun getDailyPortraitToday(): Result<JsonObject> {
        return try {
            Result.success(apiService.getDailyPortraitToday())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getDailyRecent(limit: Int): Result<JsonObject> {
        return try {
            Result.success(apiService.getDailyRecent(limit))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun recordDailyDrink(payload: JsonObject): Result<JsonObject> {
        return try {
            Result.success(apiService.recordDailyDrink(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun recordDailyStudy(payload: JsonObject): Result<JsonObject> {
        return try {
            Result.success(apiService.recordDailyStudy(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun finishDailyStudy(): Result<JsonObject> {
        return try {
            Result.success(apiService.finishDailyStudy())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun recordDailySchedule(payload: JsonObject): Result<JsonObject> {
        return try {
            Result.success(apiService.recordDailySchedule(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun syncHealthData(payload: JsonObject): Result<JsonObject> {
        return try {
            Result.success(apiService.syncHealthData(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private suspend fun readVitalSignsInternal(): HealthData {
        val now = Instant.now()
        val todayStart = now.truncatedTo(ChronoUnit.DAYS)
        val lastHour = now.minus(1, ChronoUnit.HOURS)
        
        // 读取今日步数
        val stepsRequest = ReadRecordsRequest(
            recordType = StepsRecord::class,
            timeRangeFilter = TimeRangeFilter.between(todayStart, now)
        )
        val stepsResponse = healthConnectClient.readRecords(stepsRequest)
        val totalSteps = stepsResponse.records.sumOf { it.count }
        
        // 读取最新心率
        val hrRequest = ReadRecordsRequest(
            recordType = HeartRateRecord::class,
            timeRangeFilter = TimeRangeFilter.between(lastHour, now),
            ascendingOrder = false,
            pageSize = 1
        )
        val hrResponse = healthConnectClient.readRecords(hrRequest)
        val lastHr = hrResponse.records.firstOrNull()?.samples?.lastOrNull()?.beatsPerMinute
        val hrTimestamp = hrResponse.records.firstOrNull()?.endTime
        
        // 读取最新血氧
        val spo2Request = ReadRecordsRequest(
            recordType = OxygenSaturationRecord::class,
            timeRangeFilter = TimeRangeFilter.between(lastHour, now),
            ascendingOrder = false,
            pageSize = 1
        )
        val spo2Response = healthConnectClient.readRecords(spo2Request)
        val lastSpo2 = spo2Response.records.firstOrNull()?.percentage?.value
        val spo2Timestamp = spo2Response.records.firstOrNull()?.time
        
        // 读取今日卡路里
        val caloriesRequest = ReadRecordsRequest(
            recordType = TotalCaloriesBurnedRecord::class,
            timeRangeFilter = TimeRangeFilter.between(todayStart, now)
        )
        val caloriesResponse = healthConnectClient.readRecords(caloriesRequest)
        val totalCalories = caloriesResponse.records.sumOf { it.energy.inKilocalories }
        
        return HealthData(
            steps = totalSteps,
            heartRate = lastHr?.toInt(),
            heartRateTimestamp = hrTimestamp,
            oxygenSaturation = lastSpo2,
            oxygenSaturationTimestamp = spo2Timestamp,
            caloriesBurned = totalCalories,
            lastUpdated = now
        )
    }
    
    private suspend fun readBodyMetricsInternal(): HealthData {
        val now = Instant.now()
        val monthAgo = now.minus(30, ChronoUnit.DAYS)
        
        // 读取最新体重
        val weightRequest = ReadRecordsRequest(
            recordType = WeightRecord::class,
            timeRangeFilter = TimeRangeFilter.between(monthAgo, now),
            ascendingOrder = false,
            pageSize = 1
        )
        val weightResponse = healthConnectClient.readRecords(weightRequest)
        val weight = weightResponse.records.firstOrNull()?.weight?.inKilograms
        val weightTimestamp = weightResponse.records.firstOrNull()?.time
        
        // 读取最新身高
        val heightRequest = ReadRecordsRequest(
            recordType = HeightRecord::class,
            timeRangeFilter = TimeRangeFilter.between(monthAgo, now),
            ascendingOrder = false,
            pageSize = 1
        )
        val heightResponse = healthConnectClient.readRecords(heightRequest)
        val height = heightResponse.records.firstOrNull()?.height?.inMeters
        val heightTimestamp = heightResponse.records.firstOrNull()?.time
        
        // 计算 BMI
        val bmi = if (weight != null && height != null && height > 0) {
            weight / (height * height)
        } else null
        
        // 读取最新睡眠
        val sleepRequest = ReadRecordsRequest(
            recordType = SleepSessionRecord::class,
            timeRangeFilter = TimeRangeFilter.between(monthAgo, now),
            ascendingOrder = false,
            pageSize = 1
        )
        val sleepResponse = healthConnectClient.readRecords(sleepRequest)
        val sleepSession = sleepResponse.records.firstOrNull()
        val sleepMinutes = sleepSession?.let {
            ChronoUnit.MINUTES.between(it.startTime, it.endTime)
        }
        
        return HealthData(
            weight = weight,
            weightTimestamp = weightTimestamp,
            height = height,
            heightTimestamp = heightTimestamp,
            bmi = bmi,
            sleepMinutes = sleepMinutes,
            sleepStartTime = sleepSession?.startTime,
            sleepEndTime = sleepSession?.endTime,
            lastUpdated = now
        )
    }
}
