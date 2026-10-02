package com.aveline.ai.mobile.presentation.life

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.DirectionsRun
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.HealthAndSafety
import androidx.compose.material.icons.filled.LocalFireDepartment
import androidx.compose.material.icons.filled.MonitorHeart
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Thermostat
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.WaterDrop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.components.MetricRow
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.health.DailyDataUiState
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * Life - 健康 Tab。
 *
 * 展示今日健康指标、Samsung Health 同步按钮、设备上下文信息。
 * 数据来源:
 * - 实时数据(步数/心率): 手表端 Health Services via Wearable Data Layer
 * - 历史数据(睡眠/体脂/体重等): Samsung Health Data SDK(国行设备替代 Health Connect)
 *
 * @param uiState 日常生活数据状态
 * @param onSyncSamsungHealth 从 Samsung Health 同步数据(需要 Activity)
 */
@Composable
fun LifeHealthTab(
    uiState: DailyDataUiState,
    onSyncSamsungHealth: () -> Unit
) {
    // 今日健康指标(数据来源: Samsung Health + 手表实时数据)
    SectionCard(
        title = "今日健康",
        icon = Icons.Default.MonitorHeart,
        subtitle = "体重 · 步数 · 心率 · 睡眠"
    ) {
        val weight = uiState.healthWeightKg ?: uiState.weightKg
        MetricRow(
            label = "体重",
            value = weight?.let { String.format("%.1f kg", it) } ?: "N/A"
        )
        MetricRow(
            label = "步数",
            value = uiState.steps?.let { "$it 步" } ?: "N/A"
        )
        MetricRow(
            label = "心率",
            value = uiState.heartRate?.let { "$it bpm" } ?: "N/A"
        )
        MetricRow(
            label = "睡眠",
            value = formatSleepDuration(uiState.sleepMinutes)
        )
        // 睡眠起止时间(有数据才显示)
        uiState.sleepStartTime?.let { MetricRow(label = "  入睡", value = formatEpochMillis(it)) }
        uiState.sleepEndTime?.let { MetricRow(label = "  起床", value = formatEpochMillis(it)) }
        // 睡眠得分(有数据才显示)
        uiState.sleepScore?.let {
            MetricRow(label = "睡眠得分", value = "$it / 100")
        }
        // 睡眠阶段(子项,有数据才显示)
        uiState.sleepStageDeepMinutes?.let {
            MetricRow(label = "  深睡", value = formatDurationMinutes(it))
        }
        uiState.sleepStageLightMinutes?.let {
            MetricRow(label = "  浅睡", value = formatDurationMinutes(it))
        }
        uiState.sleepStageRemMinutes?.let {
            MetricRow(label = "  REM", value = formatDurationMinutes(it))
        }
        uiState.sleepStageAwakeMinutes?.let {
            MetricRow(label = "  清醒", value = formatDurationMinutes(it))
        }
        MetricRow(label = "日期", value = uiState.portraitDate.ifBlank { "今日" })
    }

    // 身体成分(数据来源: Samsung Health)
    SectionCard(
        title = "身体成分",
        icon = Icons.Default.HealthAndSafety,
        subtitle = "体脂 · 骨骼肌 · 脂肪量 · 水分 · BMI"
    ) {
        MetricRow(
            label = "体脂率",
            value = uiState.bodyFatPercent?.let {
                String.format("%.1f%%", it * 100)
            } ?: "N/A"
        )
        MetricRow(
            label = "脂肪量",
            value = uiState.bodyFatMass?.let { String.format("%.1f kg", it) } ?: "N/A"
        )
        MetricRow(
            label = "骨骼肌率",
            value = uiState.skeletalMusclePercent?.let {
                String.format("%.1f%%", it * 100)
            } ?: "N/A"
        )
        MetricRow(
            label = "骨骼肌量",
            value = uiState.skeletalMuscleMass?.let { String.format("%.1f kg", it) } ?: "N/A"
        )
        MetricRow(
            label = "去脂体重",
            value = uiState.fatFreeMass?.let { String.format("%.1f kg", it) } ?: "N/A"
        )
        MetricRow(
            label = "总体水分",
            value = uiState.totalBodyWater?.let { String.format("%.1f kg", it) } ?: "N/A"
        )
        MetricRow(
            label = "身高",
            value = uiState.heightM?.let { String.format("%.2f m", it) } ?: "N/A"
        )
        MetricRow(
            label = "BMI",
            value = computeBmi(uiState.healthWeightKg, uiState.heightM)?.let {
                String.format("%.1f", it)
            } ?: "N/A"
        )
    }

    // 皮肤温度与血氧(数据来源: Samsung Health)
    SectionCard(
        title = "皮肤温度与血氧",
        icon = Icons.Default.Thermostat,
        subtitle = "皮温 · 血氧"
    ) {
        MetricRow(
            label = "皮肤温度",
            value = uiState.skinTemperature?.let { String.format("%.1f °C", it) } ?: "N/A"
        )
        MetricRow(
            label = "血氧饱和度",
            value = uiState.bloodOxygen?.let { String.format("%.1f%%", it * 100) } ?: "N/A"
        )
    }

    // 今日活动汇总(数据来源: Samsung Health 聚合查询)
    SectionCard(
        title = "今日活动",
        icon = Icons.AutoMirrored.Filled.DirectionsRun,
        subtitle = "步数 · 热量 · 时长 · 距离 · 爬楼"
    ) {
        MetricRow(
            label = "今日步数",
            value = uiState.stepsToday?.let { "$it 步" } ?: "N/A"
        )
        MetricRow(
            label = "活动消耗",
            value = uiState.activeCaloriesBurned?.let { String.format("%.0f kcal", it) } ?: "N/A"
        )
        MetricRow(
            label = "总消耗",
            value = uiState.totalCaloriesBurned?.let { String.format("%.0f kcal", it) } ?: "N/A"
        )
        MetricRow(
            label = "活动时长",
            value = uiState.activeTimeMinutes?.let { formatDurationMinutes(it) } ?: "N/A"
        )
        MetricRow(
            label = "总距离",
            value = uiState.totalDistanceKm?.let { String.format("%.2f km", it) } ?: "N/A"
        )
        MetricRow(
            label = "爬楼层数",
            value = uiState.floorsClimbed?.let { String.format("%.0f 层", it) } ?: "N/A"
        )
    }

    // 运动会话(数据来源: Samsung Health)
    SectionCard(
        title = "运动记录",
        icon = Icons.AutoMirrored.Filled.DirectionsRun,
        subtitle = "今日运动会话 · ${uiState.exerciseSessions.size} 项"
    ) {
        if (uiState.exerciseSessions.isEmpty()) {
            MetricRow(label = "暂无记录", value = "")
        } else {
            uiState.exerciseSessions.forEachIndexed { index, session ->
                MetricRow(
                    label = "${index + 1}. ${session.exerciseTypeName}${session.customTitle?.let { " · $it" } ?: ""}",
                    value = "${session.durationMinutes} 分钟 · ${String.format("%.0f", session.calories)} kcal"
                )
            }
        }
    }

    // 健康预警(数据来源: Samsung Health)
    SectionCard(
        title = "健康预警",
        icon = Icons.Default.Warning,
        subtitle = "睡眠呼吸暂停 · 心律不齐"
    ) {
        MetricRow(
            label = "睡眠呼吸暂停",
            value = uiState.sleepApneaSign ?: "无记录"
        )
        MetricRow(
            label = "心律不齐",
            value = uiState.irregularHeartRhythmStatus ?: "无记录"
        )
    }

    // 能量评分(数据来源: Samsung Health)
    SectionCard(
        title = "能量评分",
        icon = Icons.Default.Bolt,
        subtitle = "今日综合能量评分"
    ) {
        MetricRow(
            label = "能量评分",
            value = uiState.energyScore?.let { String.format("%.0f", it) } ?: "N/A"
        )
    }

    // 设备上下文: 电池/网络/亮度/音量, 来自 ContextRepository 本地系统 API, 不需要 HC 权限
    SectionCard(
        title = "设备上下文",
        icon = Icons.Default.Devices,
        subtitle = "电池 · 网络 · 亮度 · 音量"
    ) {
        MetricRow(
            label = "电池",
            value = uiState.batteryLevel?.let { level ->
                if (uiState.isCharging) "${level}% 充电中" else "${level}%"
            } ?: "N/A"
        )
        MetricRow(
            label = "网络",
            value = formatNetworkType(uiState.networkType)
        )
        MetricRow(
            label = "亮度",
            value = uiState.screenBrightness?.let { "${it}/255" } ?: "N/A"
        )
        MetricRow(
            label = "音量",
            value = uiState.volumeLevel?.let { "${it}/100" } ?: "N/A"
        )
    }
}

/** 睡眠时长(分钟)转 "Xh Ym" 或 "N/A" */
private fun formatSleepDuration(minutes: Long?): String {
    if (minutes == null || minutes <= 0) return "N/A"
    val h = minutes / 60
    val m = minutes % 60
    return if (h > 0) "${h}h ${m}m" else "${m}m"
}

/** 活动时长(分钟)转 "Xh Ym" 或 "Xm" */
private fun formatDurationMinutes(minutes: Long): String {
    if (minutes <= 0) return "0m"
    val h = minutes / 60
    val m = minutes % 60
    return if (h > 0) "${h}h ${m}m" else "${m}m"
}

/** 计算BMI (体重kg / 身高m²) */
private fun computeBmi(weightKg: Double?, heightM: Double?): Double? {
    if (weightKg == null || heightM == null || heightM <= 0) return null
    return weightKg / (heightM * heightM)
}

/** Unix 毫秒时间戳转 "HH:mm" 格式(用于睡眠起止时间显示) */
private fun formatEpochMillis(epochMillis: Long): String {
    return runCatching {
        java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault()).format(java.util.Date(epochMillis))
    }.getOrDefault("N/A")
}


/** 网络类型枚举转中文显示 */
private fun formatNetworkType(type: com.aveline.ai.mobile.domain.models.NetworkType): String {
    return when (type) {
        com.aveline.ai.mobile.domain.models.NetworkType.WIFI -> "WiFi"
        com.aveline.ai.mobile.domain.models.NetworkType.CELLULAR_2G -> "2G"
        com.aveline.ai.mobile.domain.models.NetworkType.CELLULAR_3G -> "3G"
        com.aveline.ai.mobile.domain.models.NetworkType.CELLULAR_4G -> "4G"
        com.aveline.ai.mobile.domain.models.NetworkType.CELLULAR_5G -> "5G"
        com.aveline.ai.mobile.domain.models.NetworkType.ETHERNET -> "以太网"
        com.aveline.ai.mobile.domain.models.NetworkType.BLUETOOTH -> "蓝牙"
        com.aveline.ai.mobile.domain.models.NetworkType.OFFLINE -> "离线"
        else -> "未知"
    }
}
