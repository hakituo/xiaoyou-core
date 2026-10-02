package com.aveline.ai.mobile.presentation.life

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.School
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.components.MetricRow
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.health.DailyDataUiState
import com.aveline.ai.mobile.presentation.health.DailyStudySession
import com.aveline.ai.mobile.presentation.theme.OverlayLight
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Life - 日程 Tab。
 *
 * 展示今日作息(起床/睡眠/低打扰模式)、学习会话列表(只读)、日程详情。
 * 支持点击编辑按钮手动修正起床/睡眠时间。
 *
 * @param uiState 日常生活数据状态
 * @param onUpdateSchedule 更新作息回调(sleep, wakeup), 传 null 表示不修改对应项
 */
@Composable
fun LifeScheduleTab(
    uiState: DailyDataUiState,
    onUpdateSchedule: (sleep: String?, wakeup: String?) -> Unit
) {
    var isEditing by remember { mutableStateOf(false) }
    var sleepInput by remember { mutableStateOf(uiState.sleep ?: "") }
    var wakeupInput by remember { mutableStateOf(uiState.wakeup ?: "") }

    // uiState 变化时同步输入框(比如刷新后)
    androidx.compose.runtime.LaunchedEffect(uiState.sleep, uiState.wakeup) {
        sleepInput = uiState.sleep ?: ""
        wakeupInput = uiState.wakeup ?: ""
    }

    // 今日作息
    SectionCard(
        title = "今日作息",
        icon = Icons.Default.Schedule,
        subtitle = "起床 · 睡眠 · 低打扰模式",
        trailingContent = {
            IconButton(onClick = { isEditing = !isEditing }) {
                Icon(
                    imageVector = Icons.Default.Edit,
                    contentDescription = "编辑作息",
                    tint = TextSecondary
                )
            }
        }
    ) {
        if (isEditing) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = sleepInput,
                    onValueChange = { sleepInput = it },
                    label = { Text("睡觉时间") },
                    placeholder = { Text("如 23:30") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = wakeupInput,
                    onValueChange = { wakeupInput = it },
                    label = { Text("起床时间") },
                    placeholder = { Text("如 07:30") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    TextButton(onClick = {
                        sleepInput = uiState.sleep ?: ""
                        wakeupInput = uiState.wakeup ?: ""
                        isEditing = false
                    }) {
                        Text("取消")
                    }
                    Spacer(modifier = Modifier.width(8.dp))
                    Button(onClick = {
                        val sleep = sleepInput.trim().takeIf { it.isNotBlank() }
                        val wakeup = wakeupInput.trim().takeIf { it.isNotBlank() }
                        onUpdateSchedule(sleep, wakeup)
                        isEditing = false
                    }) {
                        Text("保存")
                    }
                }
            }
        } else {
            // 睡眠时间优先用 Samsung Health 的数据(更准确,有 REM 等)
            // 若 Samsung Health 无数据,回退到后端记录的 sleep/wakeup
            val sleepTime = uiState.sleepStartTime?.let { formatEpochMillis(it) } ?: uiState.sleep
            val wakeTime = uiState.sleepEndTime?.let { formatEpochMillis(it) } ?: uiState.wakeup
            val hasSamsungSleep = uiState.sleepStartTime != null || uiState.sleepEndTime != null
            val sleepSource = if (hasSamsungSleep) "Samsung Health" else "手动记录"
            val inBedMinutes = calculateDurationMinutes(
                uiState.sleepStartTime,
                uiState.sleepEndTime
            )
            val awakeMinutes = uiState.sleepStageAwakeMinutes
                ?: inBedMinutes?.let { span ->
                    uiState.sleepMinutes?.let { actual -> (span - actual).coerceAtLeast(0) }
                }

            MetricRow(label = "入睡时间", value = sleepTime ?: "暂无记录")
            MetricRow(label = "起床时间", value = wakeTime ?: "暂无记录")
            inBedMinutes?.let {
                MetricRow(label = "在床时长", value = formatSleepDur(it))
            }
            // Samsung Health 的实际睡眠不含夜间清醒阶段。
            uiState.sleepMinutes?.let {
                MetricRow(label = "实际睡眠", value = formatSleepDur(it))
            }
            awakeMinutes?.let {
                MetricRow(label = "夜间清醒", value = formatDurMin(it))
            }
            // 睡眠阶段(有数据才显示)
            uiState.sleepStageDeepMinutes?.let {
                MetricRow(label = "  深睡", value = formatDurMin(it))
            }
            uiState.sleepStageLightMinutes?.let {
                MetricRow(label = "  浅睡", value = formatDurMin(it))
            }
            uiState.sleepStageRemMinutes?.let {
                MetricRow(label = "  REM", value = formatDurMin(it))
            }
            uiState.sleepScore?.let {
                MetricRow(label = "睡眠得分", value = "$it / 100")
            }
            if (uiState.sleepMinutes != null && hasSamsungSleep) {
                Text(
                    text = "实际睡眠 = 浅睡 + 深睡 + REM，不含夜间清醒",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary,
                    modifier = Modifier.padding(top = 6.dp)
                )
            }
            // 数据来源标注
            MetricRow(label = "数据来源", value = sleepSource)
            MetricRow(
                label = "低打扰模式",
                value = if (uiState.reducedModeActive) "已开启" else "关闭"
            )
            if (uiState.reducedModeActive) {
                uiState.reducedModeReason.takeIf { it.isNotBlank() && it != "none" }?.let {
                    MetricRow(label = "原因", value = it)
                }
                uiState.reducedModeExpectedEndTs?.let {
                    MetricRow(label = "结束时间", value = formatUnixTime(it))
                }
            }
        }
    }

    // 学习会话列表(只展示,不编辑)
    SectionCard(
        title = "学习会话",
        icon = Icons.Default.School,
        subtitle = "今日学习记录(只读)"
    ) {
        if (uiState.studySessions.isEmpty()) {
            Text(
                text = "今日暂无学习会话",
                style = MaterialTheme.typography.bodySmall,
                color = TextTertiary
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                uiState.studySessions.forEach { session ->
                    SessionItem(session = session)
                }
            }
        }
    }

    // 日程详情
    SectionCard(
        title = "日程详情",
        subtitle = "学习汇总"
    ) {
        MetricRow(label = "学习时长", value = "${uiState.studyTotalMinutes} 分钟")
        MetricRow(label = "学习次数", value = uiState.studyCount.toString())
    }
}

/**
 * 学习会话条目(只读展示)。
 */
@Composable
private fun SessionItem(session: DailyStudySession) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(OverlayLight)
            .padding(14.dp)
    ) {
        Text(
            text = session.topic.ifBlank { "学习" },
            color = TextPrimary,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold
        )
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = session.content.ifBlank { "无详情" },
            color = TextSecondary,
            style = MaterialTheme.typography.bodySmall
        )
        Spacer(modifier = Modifier.height(6.dp))
        Text(
            text = session.time.ifBlank { "--:--" },
            color = TextTertiary,
            style = MaterialTheme.typography.labelSmall
        )
    }
}

/** 格式化 Unix 时间戳(秒)为 MM-dd HH:mm */
private fun formatUnixTime(timestampSeconds: Long): String {
    return runCatching {
        SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(timestampSeconds * 1000))
    }.getOrDefault("N/A")
}

/** Unix 毫秒时间戳转 "HH:mm" (用于睡眠起止时间) */
private fun formatEpochMillis(epochMillis: Long): String {
    return runCatching {
        SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(epochMillis))
    }.getOrDefault("N/A")
}

/** 计算起止时间的自然时间跨度(分钟)。 */
private fun calculateDurationMinutes(startMillis: Long?, endMillis: Long?): Long? {
    if (startMillis == null || endMillis == null || endMillis <= startMillis) return null
    return (endMillis - startMillis) / 60_000L
}

/** 睡眠时长(分钟)转 "Xh Ym" */
private fun formatSleepDur(minutes: Long): String {
    if (minutes <= 0) return "N/A"
    val h = minutes / 60
    val m = minutes % 60
    return if (h > 0) "${h}h ${m}m" else "${m}m"
}

/** 活动时长(分钟)转 "Xh Ym" 或 "Xm" */
private fun formatDurMin(minutes: Long): String {
    if (minutes <= 0) return "0m"
    val h = minutes / 60
    val m = minutes % 60
    return if (h > 0) "${h}h ${m}m" else "${m}m"
}
