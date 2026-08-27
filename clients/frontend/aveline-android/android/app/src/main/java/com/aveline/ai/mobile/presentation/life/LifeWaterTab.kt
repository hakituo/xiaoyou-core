package com.aveline.ai.mobile.presentation.life

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LocalDrink
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.data.samsung.WaterIntakeEntry
import com.aveline.ai.mobile.presentation.components.MetricRow
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.health.DailyDataUiState
import com.aveline.ai.mobile.presentation.theme.OverlayLight
import com.aveline.ai.mobile.presentation.theme.OverlayMedium
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 饮水目标(毫升),用于进度条计算 */
private const val WATER_GOAL_ML = 2000

/**
 * Life - 饮水 Tab。
 *
 * 纯 Samsung Health 数据展示: 今日饮水总量/目标/进度, 以及逐条饮水记录(几点喝了多少)。
 * 不再有手动快速记录, 所有饮水数据来自 Samsung Health。
 *
 * @param uiState 日常生活数据状态
 */
@Composable
fun LifeWaterTab(
    uiState: DailyDataUiState
) {
    val entries = uiState.waterIntakeEntries
    val totalMl = entries.sumOf { it.amountMl.toInt() }
    val progress = (totalMl.toFloat() / WATER_GOAL_ML).coerceIn(0f, 1f)

    // 今日饮水概览
    SectionCard(
        title = "今日饮水",
        icon = Icons.Default.LocalDrink,
        subtitle = "饮水量 · 目标 · 进度"
    ) {
        MetricRow(label = "饮水量", value = "$totalMl ml")
        MetricRow(label = "目标", value = "$WATER_GOAL_ML ml")
        MetricRow(label = "次数", value = entries.size.toString())
        Spacer(modifier = Modifier.height(8.dp))
        LinearProgressIndicator(
            progress = { progress },
            modifier = Modifier.fillMaxWidth(),
            color = Primary,
            trackColor = OverlayMedium
        )
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = "${(progress * 100).toInt()}%",
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary
        )
    }

    // 逐条饮水记录(时间+量, 来自 Samsung Health)
    SectionCard(
        title = "饮水记录",
        subtitle = "来自 Samsung Health · ${entries.size} 条"
    ) {
        if (entries.isEmpty()) {
            Text(
                text = "今日暂无饮水记录",
                style = MaterialTheme.typography.bodySmall,
                color = TextTertiary
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                entries.forEach { entry ->
                    WaterIntakeItem(entry = entry)
                }
            }
        }
    }
}

/**
 * 单条饮水记录展示。
 */
@Composable
private fun WaterIntakeItem(entry: WaterIntakeEntry) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(OverlayLight, RoundedCornerShape(14.dp))
            .padding(14.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = runCatching {
                java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault())
                    .format(java.util.Date(entry.startTime.toEpochMilli()))
            }.getOrDefault("--:--"),
            color = TextPrimary,
            style = MaterialTheme.typography.bodyMedium
        )
        Text(
            text = String.format("%.0f ml", entry.amountMl),
            color = TextSecondary,
            style = MaterialTheme.typography.bodyMedium
        )
    }
}
