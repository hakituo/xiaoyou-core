package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Study 的执行首页。
 *
 * 这里直接消费 typed DailyPlan 与真实 Study 统计：
 * - [StudyUiState.todayStudyMinutes] 是实际学习分钟数；
 * - DailyPlan.dailyGoalMinutes 是后端 canonical 日目标；
 * - [StudyPlanUiState.planItems] 的预计总分钟是 planned，不等于 goal；
 * - 点击开始学习把完整 typed PlanItem 交给 Focus，避免再靠标题定位。
 */
@Composable
fun StudyTodayTab(
    uiState: StudyUiState,
    planUiState: StudyPlanUiState,
    onToggleItem: (PlanItem) -> Unit,
    onStartFocus: (PlanItem) -> Unit,
    onOpenPlanManager: () -> Unit
) {
    val items = planUiState.planItems
    val plannedMinutes = totalPlannedMinutes(items)
    val dailyGoalMinutes = planUiState.plan?.dailyGoalMinutes ?: 0
    val completed = items.count { it.isDone || it.status == "completed" }
    val nextItem = selectNextPlanItem(items)
    var detailItem by remember { mutableStateOf<PlanItem?>(null) }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(top = 8.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            TodayHeader(date = planUiState.plan?.date ?: planUiState.selectedDate)
        }

        item {
            TodayProgressCard(
                actualMinutes = uiState.todayStudyMinutes,
                goalMinutes = dailyGoalMinutes,
                plannedMinutes = plannedMinutes,
                completedCount = completed,
                totalCount = items.size
            )
        }

        planUiState.error?.takeIf { it.isNotBlank() }?.let { message ->
            item {
                Text(
                    text = message,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }

        item {
            NextTaskCard(
                item = nextItem,
                onOpen = { detailItem = nextItem },
                onStart = { nextItem?.let(onStartFocus) }
            )
        }

        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "今日任务",
                        style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
                        color = TextPrimary
                    )
                    Text(
                        text = if (items.isEmpty()) "暂无计划" else "$completed / ${items.size} 已完成",
                        style = MaterialTheme.typography.labelMedium,
                        color = TextTertiary
                    )
                }
                TextButton(onClick = onOpenPlanManager) {
                    Text("管理计划")
                }
            }
        }

        if (items.isEmpty()) {
            item {
                SectionCard(title = "还没有今日计划") {
                    Text(
                        text = "可以先进入计划管理手动添加；自动 Planner 生成后也会直接出现在这里。",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextSecondary
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    OutlinedButton(
                        onClick = onOpenPlanManager,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("打开计划管理")
                    }
                }
            }
        } else {
            items(items, key = { it.id.ifBlank { "${it.time}:${it.content}" } }) { item ->
                TodayTaskCard(
                    item = item,
                    onOpen = { detailItem = item },
                    onToggle = { onToggleItem(item) },
                    onStart = { onStartFocus(item) }
                )
            }
        }
    }

    detailItem?.let { item ->
        PlanItemDetailDialog(
            item = item,
            onDismiss = { detailItem = null },
            onToggle = {
                onToggleItem(item)
                detailItem = null
            },
            onStart = {
                onStartFocus(item)
                detailItem = null
            }
        )
    }
}

@Composable
private fun TodayHeader(date: String) {
    val formatted = remember(date) {
        runCatching {
            val source = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
            val target = SimpleDateFormat("M月d日 EEEE", Locale.CHINA)
            target.format(source.parse(date) ?: Date())
        }.getOrDefault(date)
    }
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = "今天",
            style = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.Bold),
            color = TextPrimary
        )
        Text(
            text = formatted,
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary
        )
    }
}

@Composable
private fun TodayProgressCard(
    actualMinutes: Int,
    goalMinutes: Int,
    plannedMinutes: Int,
    completedCount: Int,
    totalCount: Int
) {
    val progress = if (goalMinutes > 0) {
        (actualMinutes.toFloat() / goalMinutes.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    val remaining = (goalMinutes - actualMinutes).coerceAtLeast(0)

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = Primary.copy(alpha = 0.09f))
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Bottom
            ) {
                Column {
                    Text(
                        text = "今日学习",
                        style = MaterialTheme.typography.labelLarge,
                        color = TextSecondary
                    )
                    Text(
                        text = if (goalMinutes > 0) {
                            "${actualMinutes.coerceAtLeast(0)} / $goalMinutes min"
                        } else {
                            formatStudyMinutes(actualMinutes)
                        },
                        style = MaterialTheme.typography.headlineSmall.copy(fontWeight = FontWeight.Bold),
                        color = TextPrimary
                    )
                }
                Text(
                    text = if (plannedMinutes > 0) {
                        "今日计划 ${formatStudyMinutes(plannedMinutes)}"
                    } else {
                        "等待计划"
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextSecondary
                )
            }

            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(8.dp)
                    .clip(RoundedCornerShape(4.dp)),
                color = if (progress >= 1f) EmotionGreen else Primary,
                trackColor = Color(0x1AFFFFFF)
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = if (goalMinutes > 0) {
                        "目标剩余 ${formatStudyMinutes(remaining)}"
                    } else {
                        "等待学习目标"
                    },
                    style = MaterialTheme.typography.labelMedium,
                    color = TextTertiary
                )
                Text(
                    text = "$completedCount / $totalCount 项",
                    style = MaterialTheme.typography.labelMedium,
                    color = TextTertiary
                )
            }
        }
    }
}

@Composable
private fun NextTaskCard(
    item: PlanItem?,
    onOpen: () -> Unit,
    onStart: () -> Unit
) {
    SectionCard(
        title = "下一项",
        icon = Icons.Default.Schedule,
        subtitle = "现在只需要处理这一件事"
    ) {
        if (item == null) {
            Text(
                text = "今天没有待执行任务",
                style = MaterialTheme.typography.bodyMedium,
                color = TextTertiary,
                modifier = Modifier.padding(vertical = 8.dp)
            )
            return@SectionCard
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(Color(0x14000000))
                .clickable(onClick = onOpen)
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                text = item.subject?.takeIf { it.isNotBlank() }
                    ?.let { "$it · ${item.content}" }
                    ?: item.content,
                style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
                color = TextPrimary,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MetaText(item.time.ifBlank { "灵活" })
                MetaText("${item.estimatedDurationMinutes} min")
                MetaText(priorityLabel(item.priority))
            }
            item.description?.takeIf { it.isNotBlank() }?.let { description ->
                Text(
                    text = description,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Button(
                onClick = onStart,
                modifier = Modifier.fillMaxWidth()
            ) {
                Icon(Icons.Default.PlayArrow, contentDescription = null)
                Spacer(modifier = Modifier.width(6.dp))
                Text("开始学习")
            }
        }
    }
}

@Composable
private fun TodayTaskCard(
    item: PlanItem,
    onOpen: () -> Unit,
    onToggle: () -> Unit,
    onStart: () -> Unit
) {
    val done = item.isDone || item.status == "completed"
    val skipped = item.status == "skipped"
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpen),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0x10000000))
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = onToggle, enabled = !skipped) {
                Icon(
                    imageVector = if (done) Icons.Default.CheckCircle else Icons.Default.RadioButtonUnchecked,
                    contentDescription = if (done) "已完成" else "标记完成",
                    tint = when {
                        done -> EmotionGreen
                        skipped -> TextTertiary
                        else -> TextSecondary
                    },
                    modifier = Modifier.size(22.dp)
                )
            }

            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = item.subject?.takeIf { it.isNotBlank() }
                        ?.let { "$it · ${item.content}" }
                        ?: item.content,
                    style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.SemiBold),
                    color = if (done || skipped) TextTertiary else TextPrimary,
                    textDecoration = if (done) TextDecoration.LineThrough else TextDecoration.None,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MetaText(item.time.ifBlank { "灵活" })
                    MetaText("${item.estimatedDurationMinutes} min")
                    MetaText(statusLabel(item.status))
                    if (item.priority == "high" || item.priority == "urgent") {
                        MetaText(priorityLabel(item.priority))
                    }
                }
            }

            if (!done && !skipped) {
                IconButton(onClick = onStart) {
                    Icon(
                        imageVector = Icons.Default.PlayArrow,
                        contentDescription = "开始学习",
                        tint = Primary
                    )
                }
            }
        }
    }
}

@Composable
private fun MetaText(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        color = TextTertiary
    )
}

@Composable
private fun PlanItemDetailDialog(
    item: PlanItem,
    onDismiss: () -> Unit,
    onToggle: () -> Unit,
    onStart: () -> Unit
) {
    val done = item.isDone || item.status == "completed"
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                text = item.subject?.takeIf { it.isNotBlank() } ?: "计划详情",
                fontWeight = FontWeight.Bold
            )
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    text = item.content,
                    style = MaterialTheme.typography.titleMedium,
                    color = TextPrimary
                )
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    MetaText(item.time.ifBlank { "灵活安排" })
                    MetaText("${item.estimatedDurationMinutes} 分钟")
                    MetaText(priorityLabel(item.priority))
                }
                item.description?.takeIf { it.isNotBlank() }?.let {
                    Text(it, style = MaterialTheme.typography.bodyMedium, color = TextSecondary)
                }
                item.settlementReason?.takeIf { it.isNotBlank() }?.let {
                    Text(
                        text = "调整原因：$it",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary
                    )
                }
                if (item.carryoverCount > 0) {
                    Text(
                        text = "已结转 ${item.carryoverCount} 次",
                        style = MaterialTheme.typography.labelMedium,
                        color = TextTertiary
                    )
                }
            }
        },
        confirmButton = {
            if (!done && item.status != "skipped") {
                TextButton(onClick = onStart) {
                    Text("开始学习")
                }
            }
        },
        dismissButton = {
            Row {
                if (item.status != "skipped") {
                    TextButton(onClick = onToggle) {
                        Text(if (done) "标记未完成" else "标记完成")
                    }
                }
                TextButton(onClick = onDismiss) {
                    Text("关闭")
                }
            }
        }
    )
}

internal fun selectNextPlanItem(items: List<PlanItem>): PlanItem? {
    return items.firstOrNull { it.status == "in_progress" }
        ?: items.firstOrNull {
            !it.isDone && it.status != "completed" && it.status != "skipped"
        }
}

internal fun totalPlannedMinutes(items: List<PlanItem>): Int =
    items.asSequence()
        .filter { it.status != "skipped" }
        .sumOf { it.estimatedDurationMinutes.coerceAtLeast(0) }

internal fun formatStudyMinutes(minutes: Int): String {
    val safe = minutes.coerceAtLeast(0)
    val hours = safe / 60
    val rest = safe % 60
    return when {
        hours <= 0 -> "${rest}min"
        rest == 0 -> "${hours}h"
        else -> "${hours}h ${rest}min"
    }
}

private fun priorityLabel(priority: String): String = when (priority) {
    "urgent" -> "紧急"
    "high" -> "高优先级"
    "low" -> "低优先级"
    else -> "普通"
}

private fun statusLabel(status: String): String = when (status) {
    "in_progress" -> "进行中"
    "completed" -> "已完成"
    "skipped" -> "已跳过"
    else -> "待开始"
}
