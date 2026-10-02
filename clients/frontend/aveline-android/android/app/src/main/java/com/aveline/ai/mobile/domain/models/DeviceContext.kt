package com.aveline.ai.mobile.domain.models

import java.time.Instant

/**
 * 设备上下文数据模型
 * 
 * 包含设备状态、网络、电池等信息
 * 
 * @property batteryLevel 电池电量 (0-100)
 * @property isCharging 是否正在充电
 * @property batteryStatus 电池状态
 * @property networkType 网络类型
 * @property isNetworkAvailable 网络是否可用
 * @property lightLevel 环境光照度 (lux)
 * @property screenBrightness 屏幕亮度 (0-255)
 * @property isScreenOn 屏幕是否开启
 * @property volumeLevel 音量级别 (0-100)
 * @property ringerMode 铃声模式
 * @property timezone 时区
 * @property locale 语言区域
 * @property lastUpdated 最后更新时间
 */
data class DeviceContext(
    val batteryLevel: Int = 0,
    val isCharging: Boolean = false,
    val batteryStatus: BatteryStatus = BatteryStatus.UNKNOWN,
    val networkType: NetworkType = NetworkType.UNKNOWN,
    val isNetworkAvailable: Boolean = false,
    val lightLevel: Float? = null,
    val screenBrightness: Int? = null,
    val isScreenOn: Boolean = false,
    val volumeLevel: Int? = null,
    val ringerMode: RingerMode = RingerMode.UNKNOWN,
    val timezone: String = "",
    val locale: String = "",
    val lastUpdated: Instant = Instant.now()
) {
    val batteryPercentage: String
        get() = "$batteryLevel%"
    
    val formattedLightLevel: String
        get() = lightLevel?.let { "${it.toInt()} lux" } ?: "--"
}

/**
 * 电池状态
 */
enum class BatteryStatus {
    UNKNOWN,
    CHARGING,
    DISCHARGING,
    NOT_CHARGING,
    FULL
}

/**
 * 网络类型
 */
enum class NetworkType {
    UNKNOWN,
    OFFLINE,
    WIFI,
    CELLULAR_2G,
    CELLULAR_3G,
    CELLULAR_4G,
    CELLULAR_5G,
    ETHERNET,
    BLUETOOTH
}

/**
 * 铃声模式
 */
enum class RingerMode {
    UNKNOWN,
    SILENT,
    VIBRATE,
    NORMAL
}

/**
 * 应用使用信息
 * 
 * @property packageName 包名
 * @property appName 应用名称
 * @property usageTimeMs 使用时间 (毫秒)
 * @property lastUsedTime 最后使用时间
 * @property launchCount 启动次数
 */
data class AppUsageInfo(
    val packageName: String,
    val appName: String,
    val usageTimeMs: Long,
    val lastUsedTime: Instant?,
    val launchCount: Int = 0
) {
    val usageTimeMinutes: Long
        get() = usageTimeMs / (1000 * 60)
    
    val usageTimeHours: Double
        get() = usageTimeMs / (1000.0 * 60 * 60)
    
    val formattedUsageTime: String
        get() {
            val hours = usageTimeMs / (1000 * 60 * 60)
            val minutes = (usageTimeMs / (1000 * 60)) % 60
            return if (hours > 0) {
                "${hours}h ${minutes}m"
            } else {
                "${minutes}m"
            }
        }
}

/**
 * 通知信息
 * 
 * @property id 通知 ID
 * @property packageName 来源应用包名
 * @property appName 来源应用名称
 * @property title 通知标题
 * @property text 通知内容
 * @property timestamp 通知时间
 * @property category 通知类别
 */
data class NotificationInfo(
    val id: String,
    val packageName: String,
    val appName: String,
    val title: String?,
    val text: String?,
    val timestamp: Instant,
    val category: String? = null
)

/**
 * 完整上下文数据
 * 
 * @property device 设备上下文
 * @property appUsage 应用使用统计
 * @property notifications 最近通知
 * @property healthData 健康数据
 */
data class FullContext(
    val device: DeviceContext,
    val appUsage: List<AppUsageInfo> = emptyList(),
    val notifications: List<NotificationInfo> = emptyList(),
    val healthData: HealthData? = null,
    val collectedAt: Instant = Instant.now()
)
