package com.aveline.ai.mobile.services.foreground

import android.content.pm.ServiceInfo
import android.os.Build

/**
 * 常驻前台服务类型策略。
 *
 * Android 15 (targetSdk 35) 起, `dataSync` 类型的前台服务受"24 小时滚动窗口内累计最多 6 小时"
 * 的配额限制: 配额耗尽后系统调用 Service.onTimeout(), 若不在数秒内自行停止,
 * 系统会抛 RemoteServiceException 直接崩掉宿主进程 (宿主进程被杀 = 无障碍连接一起断)。
 *
 * Aveline 的常驻服务需要 7x24 运行 (WebSocket 长连接 / 上下文同步 / 无障碍保活),
 * 因此优先级为:
 * 1. `specialUse` (Android 14+): 不受 6 小时配额限制, 需要在 Manifest 声明
 *    FOREGROUND_SERVICE_SPECIAL_USE 权限与 android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE 属性;
 * 2. `dataSync`: Android 14 以下继续沿用, 15+ 仅在 specialUse 被系统拒绝时回退;
 * 3. 无类型: 最后兜底, 保证通知与进程至少能起来。
 *
 * 注意: 无论使用哪种类型, 服务都必须实现 onTimeout() 做优雅降级, 见 AvelineForegroundServiceV2。
 */
object ForegroundServiceTypePolicy {

    /** 不指定类型 (Android 10 以下只能用这种, 或全部候选都失败时的兜底)。 */
    const val TYPE_NONE = 0

    /** Android 14+ 的 specialUse 类型, 低版本为 TYPE_NONE。 */
    val SPECIAL_USE: Int = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
        ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
    } else {
        TYPE_NONE
    }

    /** Android 10+ 的 dataSync 类型, 低版本为 TYPE_NONE。 */
    val DATA_SYNC: Int = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
    } else {
        TYPE_NONE
    }

    /** 按优先级返回候选类型: specialUse → dataSync → 无类型。 */
    fun candidates(): List<Int> = buildList {
        if (SPECIAL_USE != TYPE_NONE) add(SPECIAL_USE)
        if (DATA_SYNC != TYPE_NONE) add(DATA_SYNC)
        add(TYPE_NONE)
    }

    /** 可读类型名, 仅用于日志/诊断。 */
    fun name(type: Int): String = when {
        type == TYPE_NONE -> "none"
        type == SPECIAL_USE -> "specialUse"
        type == DATA_SYNC -> "dataSync"
        else -> "unknown($type)"
    }

    /**
     * 该类型是否受 Android 15 的"24h 内累计 6h"配额限制。
     * 只有 dataSync 与 mediaProcessing 受限, specialUse 不受限。
     */
    fun hasRuntimeQuota(type: Int): Boolean =
        type != TYPE_NONE &&
            type == DATA_SYNC &&
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM
}
