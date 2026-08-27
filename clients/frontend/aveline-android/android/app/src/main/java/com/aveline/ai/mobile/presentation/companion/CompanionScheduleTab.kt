package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.CharacterDailySlot
import com.aveline.ai.mobile.presentation.status.StatusUiState
import com.aveline.ai.mobile.presentation.theme.LifeHealth
import com.aveline.ai.mobile.presentation.theme.SelectionSurface
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 当前聊天角色当天的完整日程。 */
@Composable
fun CompanionScheduleTab(uiState: StatusUiState) {
    val plan = uiState.lifeStatus?.dailyPlan
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(top = 12.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    text = "${companionRoleLabel(plan?.roleId)}的今日日程",
                    style = MaterialTheme.typography.titleMedium,
                    color = TextPrimary,
                    fontWeight = FontWeight.SemiBold
                )
                Text(
                    text = plan?.date?.ifBlank { "今日" } ?: "按当前聊天角色展示",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextTertiary
                )
            }
        }

        if (uiState.isLoading && plan == null) {
            item {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 40.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(color = LifeHealth)
                }
            }
        } else if (plan == null || plan.slots.isEmpty()) {
            item {
                Column(
                    modifier = Modifier.padding(vertical = 24.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Text(
                        text = "今日日程正在同步…",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextSecondary
                    )
                    uiState.lifeStatus?.let { status ->
                        Text(
                            text = "当前：${companionActivityLabel(status.activity)}",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextTertiary
                        )
                    }
                }
            }
        } else {
            items(
                items = plan.slots,
                key = { "${it.activity}@${it.plannedStart}" }
            ) { slot ->
                ScheduleSlotRow(
                    slot = slot,
                    isCurrent = slot.executionStatus == "in_progress"
                )
            }
        }
    }
}

@Composable
private fun ScheduleSlotRow(slot: CharacterDailySlot, isCurrent: Boolean) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = if (isCurrent) SelectionSurface else Color.Transparent
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 11.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(if (isCurrent) 9.dp else 7.dp)
                    .clip(CircleShape)
                    .background(
                        if (isCurrent) LifeHealth else TextTertiary.copy(alpha = 0.45f)
                    )
            )
            Spacer(modifier = Modifier.width(12.dp))
            Text(
                text = "${formatPlanTime(slot.plannedStart)}–${formatPlanTime(slot.plannedEnd)}",
                modifier = Modifier.width(96.dp),
                style = MaterialTheme.typography.labelMedium,
                color = if (isCurrent) TextPrimary else TextSecondary
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = companionActivityLabel(slot.activity),
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextPrimary,
                    fontWeight = if (isCurrent) FontWeight.SemiBold else FontWeight.Normal
                )
                Text(
                    text = scheduleStatusLabel(slot.executionStatus, slot.flexible),
                    style = MaterialTheme.typography.labelSmall,
                    color = if (isCurrent) LifeHealth else TextTertiary
                )
            }
        }
    }
}

private fun formatPlanTime(value: String): String {
    val time = value.substringAfter('T', value).substringBefore('+').substringBefore('Z')
    return time.take(5).ifBlank { "--:--" }
}

private fun scheduleStatusLabel(status: String, flexible: Boolean): String {
    val statusLabel = when (status) {
        "completed" -> "已完成"
        "in_progress" -> "正在进行"
        else -> "未开始"
    }
    return if (flexible) "$statusLabel · 时间可调整" else statusLabel
}

private fun companionRoleLabel(roleId: String?): String = when (roleId) {
    "aveline" -> "七濑澪"
    "ling" -> "Ling"
    "yeye" -> "Coco"
    "xiaolu" -> "小鹿"
    "rushuang" -> "Frost"
    "mianmian" -> "Mian"
    null, "" -> "当前伴侣"
    else -> roleId
}
