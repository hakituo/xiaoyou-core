package com.aveline.ai.mobile.data.repository

import android.Manifest
import android.app.AppOpsManager
import android.app.NotificationManager
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import android.os.Process
import android.os.PowerManager
import android.provider.Settings
import android.telephony.TelephonyManager
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.ContextSyncRequest
import com.aveline.ai.mobile.data.remote.dto.DeviceContextDto
import com.aveline.ai.mobile.data.remote.dto.AppUsageDto
import com.aveline.ai.mobile.data.remote.dto.NotificationDto
import com.aveline.ai.mobile.domain.models.AppUsageInfo
import com.aveline.ai.mobile.domain.models.BatteryStatus
import com.aveline.ai.mobile.domain.models.DeviceContext
import com.aveline.ai.mobile.domain.models.FullContext
import com.aveline.ai.mobile.domain.models.NetworkType
import com.aveline.ai.mobile.domain.models.NotificationInfo
import com.aveline.ai.mobile.domain.models.RingerMode
import com.aveline.ai.mobile.domain.repository.ContextRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.time.Instant
import java.util.TimeZone
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 设备上下文仓库实现
 * 
 * 收集设备状态、网络、电池、应用使用等信息
 * 
 * Requirements: 16.1, 16.2, 16.3, 16.4, 16.5
 */
@Singleton
class ContextRepositoryImpl @Inject constructor(
    @ApplicationContext private val context: Context,
    private val appPreferences: AppPreferences,
    private val apiService: AvelineApiService
) : ContextRepository {
    
    private val batteryManager = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
    private val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
    private val usageStatsManager = context.getSystemService(Context.USAGE_STATS_SERVICE) as? UsageStatsManager
    private val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    private val powerManager = context.getSystemService(Context.POWER_SERVICE) as PowerManager
    private val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
    
    override suspend fun getDeviceContext(): DeviceContext {
        return DeviceContext(
            batteryLevel = getBatteryLevel(),
            isCharging = isCharging(),
            batteryStatus = getBatteryStatus(),
            networkType = getNetworkType(),
            isNetworkAvailable = isNetworkAvailable(),
            lightLevel = getLightLevel(),
            screenBrightness = getScreenBrightness(),
            isScreenOn = isScreenOn(),
            volumeLevel = getVolumeLevel(),
            ringerMode = getRingerMode(),
            timezone = TimeZone.getDefault().id,
            locale = java.util.Locale.getDefault().toString(),
            lastUpdated = Instant.now()
        )
    }
    
    override suspend fun getAppUsage(hours: Int): List<AppUsageInfo> {
        val endTime = System.currentTimeMillis()
        val startTime = endTime - (hours * 60 * 60 * 1000L)
        return queryUsageSince(startTime, endTime)
    }

    override suspend fun getAppUsageSince(startTimeMs: Long): List<AppUsageInfo> {
        return queryUsageSince(startTimeMs, System.currentTimeMillis())
    }

    private data class UsageAccumulator(
        var totalMs: Long = 0L,
        var foregroundSince: Long? = null,
        var lastUsed: Long = 0L,
        var launchCount: Int = 0
    )

    /**
     * 查询 [startTime, endTime] 区间的应用前台使用时长。
     *
     * 不能使用 INTERVAL_DAILY 聚合桶裁切任意会话起点：系统可能返回覆盖整天的 bucket，
     * 导致“会话限额”把设置前的用量也算进去。这里改为按前后台事件逐段累加。
     */
    private suspend fun queryUsageSince(startTime: Long, endTime: Long): List<AppUsageInfo> {
        if (!hasUsageStatsPermission()) return emptyList()

        val usageStatsManager = usageStatsManager ?: return emptyList()
        val safeStart = startTime.coerceAtMost(endTime)
        // 向前看一天，用于恢复“查询起点时已经在前台”的应用状态。
        val lookbackStart = (safeStart - 24 * 60 * 60 * 1000L).coerceAtLeast(0L)
        val events = usageStatsManager.queryEvents(lookbackStart, endTime)
        val event = android.app.usage.UsageEvents.Event()
        val accumulators = mutableMapOf<String, UsageAccumulator>()
        var relevantEventCount = 0

        val foregroundEvent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            android.app.usage.UsageEvents.Event.ACTIVITY_RESUMED
        } else {
            @Suppress("DEPRECATION")
            android.app.usage.UsageEvents.Event.MOVE_TO_FOREGROUND
        }
        val backgroundEvent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            android.app.usage.UsageEvents.Event.ACTIVITY_PAUSED
        } else {
            @Suppress("DEPRECATION")
            android.app.usage.UsageEvents.Event.MOVE_TO_BACKGROUND
        }

        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            if (event.eventType != foregroundEvent && event.eventType != backgroundEvent) continue
            val packageName = event.packageName?.takeIf { it.isNotBlank() } ?: continue
            relevantEventCount++
            val accumulator = accumulators.getOrPut(packageName) { UsageAccumulator() }
            if (event.eventType == foregroundEvent) {
                if (accumulator.foregroundSince == null) {
                    accumulator.foregroundSince = event.timeStamp.coerceAtLeast(safeStart)
                    if (event.timeStamp >= safeStart) accumulator.launchCount++
                }
                accumulator.lastUsed = maxOf(accumulator.lastUsed, event.timeStamp)
            } else {
                accumulator.foregroundSince?.let { foregroundSince ->
                    val segmentEnd = event.timeStamp.coerceAtMost(endTime)
                    if (segmentEnd > foregroundSince) {
                        accumulator.totalMs += segmentEnd - foregroundSince
                    }
                }
                accumulator.foregroundSince = null
            }
        }

        // 查询结束时仍在前台的应用，累计到 endTime。
        accumulators.values.forEach { accumulator ->
            accumulator.foregroundSince?.let { foregroundSince ->
                if (endTime > foregroundSince) accumulator.totalMs += endTime - foregroundSince
            }
        }

        // 极少数 ROM 不提供 UsageEvents；此时保留 daily bucket 兜底，避免页面完全无数据。
        val aggregated = if (relevantEventCount > 0) {
            accumulators.entries
                .filter { it.value.totalMs > 0 }
                .sortedByDescending { it.value.totalMs }
        } else {
            usageStatsManager.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, safeStart, endTime)
                .orEmpty()
                .groupBy { it.packageName }
                .mapValues { (_, stats) ->
                    UsageAccumulator(
                        totalMs = stats.sumOf { it.totalTimeInForeground },
                        lastUsed = stats.maxOfOrNull { it.lastTimeUsed } ?: 0L
                    )
                }
                .entries
                .filter { it.value.totalMs > 0 }
                .sortedByDescending { it.value.totalMs }
        }

        return aggregated.map { (pkg, accumulator) ->
            val appName = try {
                val appInfo = context.packageManager.getApplicationInfo(pkg, 0)
                context.packageManager.getApplicationLabel(appInfo).toString()
            } catch (e: Exception) {
                pkg
            }

            AppUsageInfo(
                packageName = pkg,
                appName = appName,
                usageTimeMs = accumulator.totalMs,
                lastUsedTime = accumulator.lastUsed
                    .takeIf { it > 0 }
                    ?.let(Instant::ofEpochMilli),
                launchCount = accumulator.launchCount
            )
        }
    }
    
    override suspend fun getRecentNotifications(limit: Int): List<NotificationInfo> {
        if (!hasNotificationListenerPermission()) return emptyList()
        
        // NotificationListenerService 需要通过服务来获取通知
        // 这里返回空列表，实际实现需要通过 AvelineNotificationService 获取
        return emptyList()
    }
    
    override suspend fun getFullContext(): FullContext {
        return FullContext(
            device = getDeviceContext(),
            appUsage = getAppUsage(),
            notifications = getRecentNotifications(),
            collectedAt = Instant.now()
        )
    }
    
    override fun observeDeviceContext(): Flow<DeviceContext> = callbackFlow {
        launch {
            trySend(getDeviceContext())
        }

        val lightSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_LIGHT)
        val sensorListener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent?) {
                event?.let {
                    if (it.sensor.type == Sensor.TYPE_LIGHT) {
                        launch { trySend(getDeviceContext()) }
                    }
                }
            }
            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
        }

        lightSensor?.let {
            sensorManager?.registerListener(
                sensorListener,
                it,
                SensorManager.SENSOR_DELAY_NORMAL
            )
        }

        awaitClose {
            sensorManager?.unregisterListener(sensorListener)
        }
    }
    
    /**
     * 检查使用情况访问权限是否已授予。
     *
     * 修复: 原实现用 `UsageStatsManager.queryUsageStats` 查最近 1 秒的记录判断非空,
     * 这种做法不可靠: (1) 授权后立即查询, 过去 1 秒可能没有任何应用活动, 返回空 list;
     * (2) 某些 ROM (含三星 One UI) 对使用统计聚合有延迟; (3) 查到空 list 不等于没授权。
     *
     * 改用标准 API `AppOpsManager.unsafeCheckOpNoThrow(OPSTR_GET_USAGE_STATS)`,
     * 直接判断权限本身是否被授予, 不受"最近有没有使用记录"干扰。
     */
    override fun hasUsageStatsPermission(): Boolean {
        val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as? AppOpsManager
            ?: return false
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            appOps.unsafeCheckOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                context.packageName
            )
        } else {
            @Suppress("DEPRECATION")
            appOps.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                context.packageName
            )
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }
    
    override fun hasNotificationListenerPermission(): Boolean {
        return NotificationManagerCompat.getEnabledListenerPackages(context)
            .contains(context.packageName)
    }
    
    override fun openUsageStatsSettings() {
        val intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }
    
    override fun openNotificationListenerSettings() {
        val intent = Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }
    
    override suspend fun syncToBackend(context: FullContext): Result<Unit> {
        return try {
            val request = ContextSyncRequest(
                deviceContext = DeviceContextDto.fromDomain(context.device),
                appUsage = context.appUsage.map { AppUsageDto.fromDomain(it) },
                notifications = context.notifications.map { NotificationDto.fromDomain(it) },
                collectedAt = context.collectedAt.toString()
            )
            
            apiService.syncContext(request)
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    // ==================== 私有辅助方法 ====================
    
    private fun getBatteryLevel(): Int {
        return batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
    }
    
    private fun isCharging(): Boolean {
        val status = batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_STATUS)
        return status == BatteryManager.BATTERY_STATUS_CHARGING || 
               status == BatteryManager.BATTERY_STATUS_FULL
    }
    
    private fun getBatteryStatus(): BatteryStatus {
        val status = batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_STATUS)
        return when (status) {
            BatteryManager.BATTERY_STATUS_CHARGING -> BatteryStatus.CHARGING
            BatteryManager.BATTERY_STATUS_DISCHARGING -> BatteryStatus.DISCHARGING
            BatteryManager.BATTERY_STATUS_NOT_CHARGING -> BatteryStatus.NOT_CHARGING
            BatteryManager.BATTERY_STATUS_FULL -> BatteryStatus.FULL
            else -> BatteryStatus.UNKNOWN
        }
    }
    
    private fun getNetworkType(): NetworkType {
        if (!hasPermission(Manifest.permission.ACCESS_NETWORK_STATE)) {
            return NetworkType.UNKNOWN
        }
        val network = connectivityManager.activeNetwork ?: return NetworkType.OFFLINE
        val capabilities = connectivityManager.getNetworkCapabilities(network) 
            ?: return NetworkType.UNKNOWN
        
        return when {
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> NetworkType.WIFI
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> NetworkType.ETHERNET
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_BLUETOOTH) -> NetworkType.BLUETOOTH
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> {
                getCellularNetworkType()
            }
            else -> NetworkType.UNKNOWN
        }
    }
    
    private fun getCellularNetworkType(): NetworkType {
        if (!canReadCellularNetworkType()) {
            return NetworkType.UNKNOWN
        }
        val networkType = telephonyManager?.dataNetworkType ?: return NetworkType.UNKNOWN
        
        return when (networkType) {
            TelephonyManager.NETWORK_TYPE_GPRS,
            TelephonyManager.NETWORK_TYPE_EDGE,
            TelephonyManager.NETWORK_TYPE_CDMA,
            TelephonyManager.NETWORK_TYPE_1xRTT,
            @Suppress("DEPRECATION")
            TelephonyManager.NETWORK_TYPE_IDEN -> NetworkType.CELLULAR_2G
            
            TelephonyManager.NETWORK_TYPE_UMTS,
            TelephonyManager.NETWORK_TYPE_EVDO_0,
            TelephonyManager.NETWORK_TYPE_EVDO_A,
            TelephonyManager.NETWORK_TYPE_HSDPA,
            TelephonyManager.NETWORK_TYPE_HSUPA,
            TelephonyManager.NETWORK_TYPE_HSPA,
            TelephonyManager.NETWORK_TYPE_EVDO_B,
            TelephonyManager.NETWORK_TYPE_EHRPD,
            TelephonyManager.NETWORK_TYPE_HSPAP -> NetworkType.CELLULAR_3G
            
            TelephonyManager.NETWORK_TYPE_LTE -> NetworkType.CELLULAR_4G
            
            TelephonyManager.NETWORK_TYPE_NR -> NetworkType.CELLULAR_5G
            
            else -> NetworkType.UNKNOWN
        }
    }
    
    private fun isNetworkAvailable(): Boolean {
        if (!hasPermission(Manifest.permission.ACCESS_NETWORK_STATE)) {
            return false
        }
        val network = connectivityManager.activeNetwork ?: return false
        val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return false
        return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    private fun canReadCellularNetworkType(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            hasPermission(Manifest.permission.READ_BASIC_PHONE_STATE) ||
                hasPermission(Manifest.permission.READ_PHONE_STATE)
        } else {
            hasPermission(Manifest.permission.READ_PHONE_STATE)
        }
    }

    private fun hasPermission(permission: String): Boolean {
        return ContextCompat.checkSelfPermission(context, permission) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED
    }
    
    private var lastLightLevel: Float? = null
    
    private fun getLightLevel(): Float? {
        sensorManager?.getDefaultSensor(Sensor.TYPE_LIGHT) ?: return lastLightLevel
        return lastLightLevel
    }
    
    fun updateLightLevel(value: Float) {
        lastLightLevel = value
    }
    
    private fun getScreenBrightness(): Int? {
        return try {
            Settings.System.getInt(
                context.contentResolver,
                Settings.System.SCREEN_BRIGHTNESS
            )
        } catch (e: Exception) {
            null
        }
    }
    
    private fun isScreenOn(): Boolean {
        return powerManager.isInteractive
    }
    
    private fun getVolumeLevel(): Int? {
        return try {
            val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as android.media.AudioManager
            val maxVolume = audioManager.getStreamMaxVolume(android.media.AudioManager.STREAM_MUSIC)
            val currentVolume = audioManager.getStreamVolume(android.media.AudioManager.STREAM_MUSIC)
            if (maxVolume > 0) (currentVolume * 100 / maxVolume) else 0
        } catch (e: Exception) {
            null
        }
    }
    
    private fun getRingerMode(): RingerMode {
        return try {
            val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as android.media.AudioManager
            when (audioManager.ringerMode) {
                android.media.AudioManager.RINGER_MODE_SILENT -> RingerMode.SILENT
                android.media.AudioManager.RINGER_MODE_VIBRATE -> RingerMode.VIBRATE
                android.media.AudioManager.RINGER_MODE_NORMAL -> RingerMode.NORMAL
                else -> RingerMode.UNKNOWN
            }
        } catch (e: Exception) {
            RingerMode.UNKNOWN
        }
    }

    override suspend fun recordBodyMetrics(weight: Double?, height: Double?): Result<JsonObject> {
        return try {
            val payload = buildJsonObject {
                weight?.let { put("weight", it) }
                height?.let { put("height", it) }
            }
            Result.success(apiService.recordBodyMetrics(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun uploadDeviceSnapshot(): Result<JsonObject> {
        return try {
            val ctx = getDeviceContext()
            val payload = buildJsonObject {
                putJsonObject("device") {
                    put("battery_level", ctx.batteryLevel)
                    put("is_charging", ctx.isCharging)
                    put("network_type", ctx.networkType.name)
                    put("is_screen_on", ctx.isScreenOn)
                    ctx.volumeLevel?.let { put("volume_level", it) }
                }
            }
            Result.success(apiService.uploadDeviceContext(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
