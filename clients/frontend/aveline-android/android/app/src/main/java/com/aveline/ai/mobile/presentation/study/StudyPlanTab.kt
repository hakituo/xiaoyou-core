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
 * 支持手动编辑:勾选完成状态、修改/新增/删除计划项(时间/名称/时长)。
 *
 * 计划展示数据来自独立的 [StudyPlanViewModel],通过 [planUiState] 注入;
 * 勾选 / 新增 / 编辑 / 删除**全部写回计划真源**(而不是整篇覆盖 plan.md),
 * 否则会被后端计划同步覆盖,并丢掉标题、备注与无时间项。
 *
 * @param planUiState 计划域 UI 状态
 * @param onDateSelected 选择日期回调(格式: yyyy-MM-dd)
 * @param onToggleItem 勾选/取消勾选单个计划项回调(写回计划真源)
 * @param onAddItem 新增计划项回调(传入含时间/名称/时长的新计划项)
 * @param onUpdateItem 编辑计划项回调(第一个参数是编辑前的项,用于在真源中定位)
 * @param onDeleteItem 删除计划项回调(传入待删除的计划项)
 * @param onStartFocus 点击「开始计时」回调(联动专注番茄钟,按计划时长倒计时)
 */
@Composable
fun StudyPlanTab(
    planUiState: StudyPlanUiState,
    onDateSelected: (String) -> Unit,
    onToggleItem: (PlanItem) -> Unit = {},
    onAddItem: (PlanItem) -> Unit = {},
    onUpdateItem: (PlanItem, PlanItem) -> Unit = { _, _ -> },
    onDeleteItem: (PlanItem) -> Unit = {},
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

    // 左滑/右滑与箭头共用同一条跳日期路径
    fun gotoDate(newDate: String) {
        selectedDate = newDate
        onDateSelected(newDate)
    }

    // 正在编辑的计划项索引;-1 表示新增,null 表示未在编辑
    var editingIndex by remember { mutableStateOf<Int?>(null) }

    LazyColumn(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            // 左右滑动看前一天/后一天的计划;同时消费掉横滑,避免冒泡到顶层把侧边栏拖出来
            .horizontalPagingSwipe(
                onPrevious = { gotoDate(shiftDateString(selectedDate, -1)) },
                onNext = { gotoDate(shiftDateString(selectedDate, 1)) }
            ),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp)
    ) {
        item {
            DateSelector(
                selectedDate = selectedDate,
                onDateChange = ::gotoDate
            )
        }

        // 保存/勾选失败时明确提示,避免"点了没反应"却看不到原因
        planUiState.error?.takeIf { it.isNotBlank() }?.let { message ->
            item {
                Text(
                    text = message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.fillMaxWidth()
                )
            }
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
                                // 勾选走计划真源,不再整篇覆盖 plan.md
                                onToggle = { onToggleItem(item) },
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
                if (editingItem != null) {
                    // 传入编辑前的项,便于后端在计划真源里定位
                    onUpdateItem(editingItem, edited)
                } else {
                    onAddItem(edited)
                }
                editingIndex = null
            },
            onDelete = if (editingItem != null) {
                {
                    onDeleteItem(editingItem)
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
                    label = { Text("时间 (HH:mm，留空为灵活)") },
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

/** 日期字符串按天偏移(左右滑动翻页与箭头按钮共用同一套日期运算)。 */
fun shiftDateString(date: String, days: Int): String {
    val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
    val parsed = runCatching { dateFormat.parse(date) }.getOrNull() ?: Date()
    val cal = Calendar.getInstance().apply {
        time = parsed
        add(Calendar.DAY_OF_MONTH, days)
    }
    return dateFormat.format(cal.time)
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
            onClick = { onDateChange(shiftDateString(selectedDate, -1)) }
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
            onClick = { onDateChange(shiftDateString(selectedDate, 1)) }
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
            // 无固定时间的计划项在 plan.md 里写作"灵活"
            text = item.time.ifBlank { "灵活" },
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


