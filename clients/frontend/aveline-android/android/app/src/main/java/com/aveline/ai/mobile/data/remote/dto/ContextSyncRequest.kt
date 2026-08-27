package com.aveline.ai.mobile.data.remote.dto

import com.aveline.ai.mobile.domain.models.AppUsageInfo
import com.aveline.ai.mobile.domain.models.DeviceContext
import com.aveline.ai.mobile.domain.models.NotificationInfo
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 上下文同步请求
 */
@Serializable
data class ContextSyncRequest(
    @SerialName("device_context")
    val deviceContext: DeviceContextDto,
    
    @SerialName("app_usage")
    val appUsage: List<AppUsageDto> = emptyList(),
    
    @SerialName("notifications")
    val notifications: List<NotificationDto> = emptyList(),
    
    @SerialName("health_data")
    val healthData: List<HealthDataDto> = emptyList(),

    /** 应用用量统计窗口起点。新客户端固定为本地当天 00:00 对应的 UTC 时间。 */
    @SerialName("usage_window_start")
    val usageWindowStart: String? = null,

    /** 用量口径标识；后端只允许可信的 today-since-midnight 口径触发主动关怀。 */
    @SerialName("usage_source")
    val usageSource: String? = null,
    
    @SerialName("collected_at")
    val collectedAt: String
)

/**
 * 上下文同步响应。
 * app_limits: 后端下发的当日应用使用限额 (数字健康功能),
 *   格式为 { "package_name": limit_ms }, 例如 {"com.douyin": 3600000}。
 * Android 端 UsageLimitMonitor 读取后本地定时检查并强制退出超限应用。
 * session_caps: 后端下发的当日"会话限额"(一次性 cap),
 *   格式为 { "package_name": session_cap_ms }。会话 cap 从生效时刻起该应用
 *   本次只能再用这么久, 时长计入当日每日总量; 手机端据此做双重判断。
 */
@Serializable
data class ContextSyncResponse(
    @SerialName("status")
    val status: String = "success",
    
    @SerialName("message")
    val message: String = "",
    
    @SerialName("app_limits")
    val appLimits: Map<String, Long> = emptyMap(),
    
    @SerialName("session_caps")
    val sessionCaps: Map<String, Long> = emptyMap()
)

@Serializable
data class HealthDataDto(
    @SerialName("id")
    val id: String,
    
    @SerialName("type")
    val type: String,
    
    @SerialName("json_data")
    val jsonData: String,
    
    @SerialName("timestamp")
    val timestamp: String
)

@Serializable
data class DeviceContextDto(
    @SerialName("battery_level")
    val batteryLevel: Int,
    
    @SerialName("is_charging")
    val isCharging: Boolean,
    
    @SerialName("battery_status")
    val batteryStatus: String,
    
    @SerialName("network_type")
    val networkType: String,
    
    @SerialName("is_network_available")
    val isNetworkAvailable: Boolean,
    
    @SerialName("light_level")
    val lightLevel: Float? = null,
    
    @SerialName("screen_brightness")
    val screenBrightness: Int? = null,
    
    @SerialName("is_screen_on")
    val isScreenOn: Boolean,
    
    @SerialName("volume_level")
    val volumeLevel: Int? = null,
    
    @SerialName("ringer_mode")
    val ringerMode: String,
    
    @SerialName("timezone")
    val timezone: String,
    
    @SerialName("locale")
    val locale: String,
    
    @SerialName("last_updated")
    val lastUpdated: String
) {
    companion object {
        fun fromDomain(domain: DeviceContext): DeviceContextDto {
            return DeviceContextDto(
                batteryLevel = domain.batteryLevel,
                isCharging = domain.isCharging,
                batteryStatus = domain.batteryStatus.name,
                networkType = domain.networkType.name,
                isNetworkAvailable = domain.isNetworkAvailable,
                lightLevel = domain.lightLevel,
                screenBrightness = domain.screenBrightness,
                isScreenOn = domain.isScreenOn,
                volumeLevel = domain.volumeLevel,
                ringerMode = domain.ringerMode.name,
                timezone = domain.timezone,
                locale = domain.locale,
                lastUpdated = domain.lastUpdated.toString()
            )
        }
    }
}

@Serializable
data class AppUsageDto(
    @SerialName("package_name")
    val packageName: String,
    
    @SerialName("app_name")
    val appName: String,
    
    @SerialName("usage_time_ms")
    val usageTimeMs: Long,
    
    @SerialName("last_used_time")
    val lastUsedTime: String? = null,
    
    @SerialName("launch_count")
    val launchCount: Int
) {
    companion object {
        fun fromDomain(domain: AppUsageInfo): AppUsageDto {
            return AppUsageDto(
                packageName = domain.packageName,
                appName = domain.appName,
                usageTimeMs = domain.usageTimeMs,
                lastUsedTime = domain.lastUsedTime?.toString(),
                launchCount = domain.launchCount
            )
        }
    }
}

@Serializable
data class NotificationDto(
    @SerialName("id")
    val id: String,
    
    @SerialName("package_name")
    val packageName: String,
    
    @SerialName("app_name")
    val appName: String,
    
    @SerialName("title")
    val title: String? = null,
    
    @SerialName("text")
    val text: String? = null,
    
    @SerialName("timestamp")
    val timestamp: String,
    
    @SerialName("category")
    val category: String? = null
) {
    companion object {
        fun fromDomain(domain: NotificationInfo): NotificationDto {
            return NotificationDto(
                id = domain.id,
                packageName = domain.packageName,
                appName = domain.appName,
                title = domain.title,
                text = domain.text,
                timestamp = domain.timestamp.toString(),
                category = domain.category
            )
        }
    }
}
