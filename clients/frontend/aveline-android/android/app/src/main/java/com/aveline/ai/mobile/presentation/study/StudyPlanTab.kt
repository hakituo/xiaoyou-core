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
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * 学习计划 Tab。
 *
 * 适配 Study/Daily 文件夹的 plan.md 格式,展示每日学习计划的 checkbox 列表。
 * 支持手动编辑:勾选完成状态、修改/新增/删除计划项(时间/名称/时长),
 * 所有改动通过 [onSavePlan] 写回后端 plan.md 持久化。
 *
 * 计划数据来自独立的 [StudyPlanViewModel],通过 [planUiState] 注入,
 * 编解码逻辑由领域层 [com.aveline.ai.mobile.domain.PlanMarkdownCodec] 处理。
 *
 * @param planUiState 计划域 UI 状态
 * @param onDateSelected 选择日期回调(格式: yyyy-MM-dd)
 * @param onSavePlan 保存计划回调(传入编辑后的完整计划项列表)
 * @param onStartFocus 点击「开始计时」回调(联动专注番茄钟,按计划时长倒计时)
 */
@Composable
fun StudyPlanTab(
    planUiState: StudyPlanUiState,
    onDateSelected: (String) -> Unit,
    onSavePlan: (List<PlanItem>) -> Unit = {},
    onStartFocus: (PlanItem) -> Unit = {}
) {
    // 当前选中的日期,优先使用 planUiState 中的 selectedDate
    var selectedDate by remember {
        mutableStateOf(planUiState.selectedDate.ifBlank {
            SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
        })
    }

    // planUiState.selectedDate 变化时同步本地状态
    LaunchedEffect(planUiState.selectedDate) {
        if (planUiState.selectedDate.isNotBlank() && planUiState.selectedDate != selectedDate) {
            selectedDate = planUiState.selectedDate
        }
    }

    val planItems = planUiState.planItems

    // 正在编辑的计划项索引;-1 表示新增,null 表示未在编辑
    var editingIndex by remember { mutableStateOf<Int?>(null) }

    LazyColumn(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp)
    ) {
        item {
            DateSelector(
                selectedDate = selectedDate,
                onDateChange = { newDate ->
                    selectedDate = newDate
                    onDateSelected(newDate)
                }
            )
        }

        item {
            SectionCard(title = "今日计划") {
                if (planItems.isEmpty()) {
                    Text(
                        text = "今日暂无学习计划,点击下方按钮添加",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextTertiary,
                        modifier = Modifier.padding(vertical = 16.dp)
                    )
                } else {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        planItems.forEachIndexed { index, item ->
                            PlanItemRow(
                                item = item,
                                        isChecked = item.isDone,
                                        onToggle = {
                                            // 勾选状态直接写回 plan.md
                                            val newItems = planItems.toMutableList()
                                                .also { it[index] = item.copy(isDone = !item.isDone) }
                                            onSavePlan(newItems)
                                        },
                                        onEdit = { editingIndex = index },
                                        onStartFocus = { onStartFocus(item) }
                                    )
                        }
                    }
                }
                Spacer(modifier = Modifier.height(10.dp))
                androidx.compose.material3.OutlinedButton(
                    onClick = { editingIndex = -1 },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("+ 添加计划项")
                }
            }
        }

        item {
            // 完成统计
            val completedCount = planItems.count { it.isDone }
            val totalCount = planItems.size
            SectionCard(title = "完成统计") {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column {
                        Text(
                            text = "$completedCount / $totalCount",
                            style = MaterialTheme.typography.headlineSmall.copy(fontWeight = FontWeight.Bold),
                            color = if (completedCount == totalCount && totalCount > 0) EmotionGreen else TextPrimary
                        )
                        Text(
                            text = "已完成计划项",
                            style = MaterialTheme.typography.labelSmall,
                            color = TextTertiary
                        )
                    }
                    if (totalCount > 0) {
                        val progress = completedCount.toFloat() / totalCount
                        androidx.compose.material3.LinearProgressIndicator(
                            progress = { progress },
                            modifier = Modifier
                                .weight(1f)
                                .padding(start = 16.dp)
                                .height(8.dp)
                                .clip(RoundedCornerShape(4.dp)),
                            color = if (progress >= 1f) EmotionGreen else Primary,
                            trackColor = Color(0x1AFFFFFF)
                        )
                    }
                }
            }
        }
    }

    // 编辑/新增计划项对话框
    editingIndex?.let { index ->
        val editingItem = planItems.getOrNull(index)
        PlanItemEditDialog(
            initial = editingItem,
            onDismiss = { editingIndex = null },
            onConfirm = { edited ->
                val newItems = planItems.toMutableList()
                if (editingItem != null) {
                    newItems[index] = edited
                } else {
                    newItems.add(edited)
                }
                onSavePlan(newItems)
                editingIndex = null
            },
            onDelete = if (editingItem != null) {
                {
                    val newItems = planItems.toMutableList().also { it.removeAt(index) }
                    onSavePlan(newItems)
                    editingIndex = null
                }
            } else null
        )
    }
}

/** 计划项编辑对话框:时间 / 名称 / 时长 */
@Composable
private fun PlanItemEditDialog(
    initial: PlanItem?,
    onDismiss: () -> Unit,
    onConfirm: (PlanItem) -> Unit,
    onDelete: (() -> Unit)? = null
) {
    var time by remember { mutableStateOf(initial?.time ?: "08:00") }
    var content by remember { mutableStateOf(initial?.content ?: "") }
    var duration by remember { mutableStateOf(initial?.duration ?: "") }

    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial != null) "编辑计划项" else "新增计划项") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                androidx.compose.material3.OutlinedTextField(
                    value = time,
                    onValueChange = { time = it },
                    label = { Text("时间 (HH:mm)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                androidx.compose.material3.OutlinedTextField(
                    value = content,
                    onValueChange = { content = it },
                    label = { Text("计划名称") },
                    modifier = Modifier.fillMaxWidth()
                )
                androidx.compose.material3.OutlinedTextField(
                    value = duration,
                    onValueChange = { duration = it },
                    label = { Text("时长 (如 45分钟,可留空)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            androidx.compose.material3.TextButton(
                onClick = {
                    if (content.isNotBlank()) {
                        onConfirm(
                            PlanItem(
                                time = time.trim(),
                                content = content.trim(),
                                duration = duration.trim(),
                                isDone = initial?.isDone ?: false
                            )
                        )
                    }
                }
            ) {
                Text("保存")
            }
        },
        dismissButton = {
            Row {
                if (onDelete != null) {
                    androidx.compose.material3.TextButton(onClick = onDelete) {
                        Text("删除", color = MaterialTheme.colorScheme.error)
                    }
                }
                androidx.compose.material3.TextButton(onClick = onDismiss) {
                    Text("取消")
                }
            }
        }
    )
}

/** 日期滚动选择器:左箭头 + 日期文本 + 右箭头 */
@Composable
fun DateSelector(
    selectedDate: String,
    onDateChange: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
    val displayFormat = SimpleDateFormat("MM月dd日 E", Locale.CHINA)

    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        IconButton(
            onClick = {
                val date = dateFormat.parse(selectedDate) ?: Date()
                val cal = Calendar.getInstance().apply {
                    time = date
                    add(Calendar.DAY_OF_MONTH, -1)
                }
                onDateChange(dateFormat.format(cal.time))
            }
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
                contentDescription = "前一天",
                tint = TextSecondary
            )
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            val displayDate = runCatching {
                displayFormat.format(dateFormat.parse(selectedDate) ?: Date())
            }.getOrDefault(selectedDate)
            Text(
                text = displayDate,
                style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
                color = TextPrimary
            )
            Text(
                text = selectedDate,
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary
            )
        }
        IconButton(
            onClick = {
                val date = dateFormat.parse(selectedDate) ?: Date()
                val cal = Calendar.getInstance().apply {
                    time = date
                    add(Calendar.DAY_OF_MONTH, 1)
                }
                onDateChange(dateFormat.format(cal.time))
            }
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = "后一天",
                tint = TextSecondary
            )
        }
    }
}

/** 单个计划项:时间 + 内容 + checkbox + 编辑入口 + 开始计时 */
@Composable
private fun PlanItemRow(
    item: PlanItem,
    isChecked: Boolean,
    onToggle: () -> Unit,
    onEdit: () -> Unit = {},
    onStartFocus: () -> Unit = {}
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(Color(0x14000000))
            .clickable { onToggle() }
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = if (isChecked) Icons.Default.CheckCircle else Icons.Default.RadioButtonUnchecked,
            contentDescription = if (isChecked) "已完成" else "未完成",
            tint = if (isChecked) EmotionGreen else TextTertiary,
            modifier = Modifier.size(22.dp)
        )
        Spacer(modifier = Modifier.width(12.dp))
        Text(
            text = item.time,
            style = MaterialTheme.typography.labelMedium,
            color = if (isChecked) TextTertiary else Primary,
            modifier = Modifier.width(56.dp)
        )
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = item.content,
                style = MaterialTheme.typography.bodyMedium,
                color = if (isChecked) TextTertiary else TextPrimary,
                textDecoration = if (isChecked) TextDecoration.LineThrough else TextDecoration.None,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            if (item.duration.isNotBlank()) {
                Text(
                    text = item.duration,
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary
                )
            }
        }
        IconButton(onClick = onStartFocus) {
            Icon(
                imageVector = Icons.Default.PlayArrow,
                contentDescription = "开始计时",
                tint = Primary,
                modifier = Modifier.size(18.dp)
            )
        }
        IconButton(onClick = onEdit) {
            Icon(
                imageVector = androidx.compose.material.icons.Icons.Default.Edit,
                contentDescription = "编辑",
                tint = TextTertiary,
                modifier = Modifier.size(18.dp)
            )
        }
    }
}

/** 从时长字符串(如 "45分钟" / "1小时30分" / "90")解析出分钟数,无法解析返回 null */
fun parseDurationMinutes(duration: String): Int? {
    if (duration.isBlank()) return null
    val hour = "(\\d+)\\s*小时".toRegex().find(duration)?.groupValues?.get(1)?.toIntOrNull() ?: 0
    val minute = "(\\d+)\\s*分钟?".toRegex().find(duration)?.groupValues?.get(1)?.toIntOrNull() ?: 0
    val total = hour * 60 + minute
    if (total > 0) return total
    // 纯数字兜底(视为分钟)
    return duration.trim().toIntOrNull()
}


