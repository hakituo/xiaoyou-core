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
 * 后端下发的单个应用数字健康策略 (数字健康功能)。
 *
 * 两类限制同时生效、取更严格的那个:
 * - daily_limit_ms   每天总共允许多久 (当天 00:00 起算)
 * - session_limit_ms 一次连续使用最多多久
 *
 * 另外两个参数用来堵"退出再打开"绕过单次限制:
 * - session_gap_ms 离开多久才算本次使用结束 (小于该值视为同一次)
 * - cooldown_ms   单次超限后多久才能重新打开
 */
@Serializable
data class AppLimitPolicyDto(
    @SerialName("package_name")
    val packageName: String = "",

    @SerialName("app_name")
    val appName: String = "",

    @SerialName("daily_limit_ms")
    val dailyLimitMs: Long = 0L,

    @SerialName("session_limit_ms")
    val sessionLimitMs: Long = 0L,

    @SerialName("session_gap_ms")
    val sessionGapMs: Long = 0L,

    @SerialName("cooldown_ms")
    val cooldownMs: Long = 0L,
)

/**
 * 上下文同步响应。
 *
 * app_policies: 后端下发的完整数字健康策略 (每日 + 单次 + 间隔 + 冷却), 首选字段。
 * app_limits / session_caps: 旧版字段, 仅在 app_policies 缺失时作为兼容回退
 *   (老后端只下发这两项, 客户端用默认的间隔/冷却补齐成完整策略)。
 */
@Serializable
data class ContextSyncResponse(
    @SerialName("status")
    val status: String = "success",
    
    @SerialName("message")
    val message: String = "",
    
    @SerialName("app_policies")
    val appPolicies: List<AppLimitPolicyDto> = emptyList(),

    @Deprecated("改用 app_policies; 仅作为老后端兼容回退")
    @SerialName("app_limits")
    val appLimits: Map<String, Long> = emptyMap(),
    
    @Deprecated("改用 app_policies 的 sessionLimitMs; 仅作为老后端兼容回退")
    @SerialName("session_caps")
    val sessionCaps: Map<String, Long> = emptyMap()
) {

    /**
     * 老后端兼容回退: 每日限额表。
     *
     * 收口成普通方法, 让兼容调用方不必各自处理废弃告警
     * (Kotlin 在同类内访问废弃属性仍会告警, 在这里统一 suppress)。
     */
    @Suppress("DEPRECATION")
    fun legacyDailyLimits(): Map<String, Long> = appLimits

    /** 老后端兼容回退: 一次性会话 cap 表。 */
    @Suppress("DEPRECATION")
    fun legacySessionCaps(): Map<String, Long> = sessionCaps
}

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
