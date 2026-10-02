package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.DiaryEntry
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 学习日记 Tab。
 *
 * 从 /api/v1/diary 读取 journal 日记列表，按作者 source 分组显示。
 *
 * **作者名单完全来自后端数据**：后端返回哪些角色当天有日记，这里就呈现哪些角色，
 * 前端不维护任何角色名单 —— 角色会增删，写死的名单既会挡住新角色写出的日记，
 * 也会挡住「以前注册过、现在没注册」的角色留下的历史日记。展示名同理，
 * 直接取后端给的 [DiaryEntry.sourceLabel]，不在本地维护 role_id → 中文名的映射。
 *
 * 切换日期时由 [StudyDailyViewModel.loadDateContent] 触发 [loadDiaries] 刷新。
 *
 * @param dailyUiState Daily 文件夹 UI 状态(含 diaryEntries)
 * @param onDateSelected 选择日期回调(格式: yyyy-MM-dd)
 */
@Composable
fun StudyDiaryTab(
    dailyUiState: StudyDailyUiState,
    onDateSelected: (String) -> Unit,
) {
    var selectedDate by remember {
        mutableStateOf(
            dailyUiState.selectedDate.ifBlank {
                SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
            },
        )
    }

    // dailyUiState.selectedDate 变化时同步本地状态
    LaunchedEffect(dailyUiState.selectedDate) {
        if (dailyUiState.selectedDate.isNotBlank() && dailyUiState.selectedDate != selectedDate) {
            selectedDate = dailyUiState.selectedDate
        }
    }

    val diaryEntries = dailyUiState.diaryEntries

    // 人物切换 FilterChip: null=全部, 其余为作者 scope(user / aveline / ling / ye …)
    var selectedSource by remember { mutableStateOf<String?>(null) }

    // 当天出现的作者（source → 展示名），顺序：主人手记置顶，其余按当天首次出现顺序。
    // 名单来自返回数据本身，角色增删 / 历史角色都不需要改这里。
    val authors = remember(diaryEntries) {
        val labels = LinkedHashMap<String, String>()
        val ownerEntry = diaryEntries.firstOrNull { it.source == "user" }
        if (ownerEntry != null) {
            labels["user"] = ownerEntry.authorLabel
        }
        diaryEntries.forEach { entry ->
            if (!labels.containsKey(entry.source)) {
                labels[entry.source] = entry.authorLabel
            }
        }
        labels.toList()
    }

    // 按 source 分组：只渲染当天真的有日记的作者
    val grouped = remember(diaryEntries, selectedSource, authors) {
        val bySource = diaryEntries.groupBy { it.source }
        authors
            .filter { (source, _) -> selectedSource == null || selectedSource == source }
            .mapNotNull { (source, label) ->
                bySource[source]?.takeIf { it.isNotEmpty() }?.let { label to it }
            }
    }

    // 左滑/右滑与箭头共用同一条跳日期路径
    fun gotoDate(newDate: String) {
        selectedDate = newDate
        onDateSelected(newDate)
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            // 左右滑动看前一天/后一天的日记;同时消费掉横滑,避免冒泡到顶层把侧边栏拖出来
            .horizontalPagingSwipe(
                onPrevious = { gotoDate(shiftDateString(selectedDate, -1)) },
                onNext = { gotoDate(shiftDateString(selectedDate, 1)) }
            ),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp),
    ) {
        item {
            DateSelector(
                selectedDate = selectedDate,
                onDateChange = ::gotoDate,
            )
        }

        if (diaryEntries.isNotEmpty()) {
            item {
                // 作者数量随数据变化（可能不止两三个），横向可滚动避免挤爆一行
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    FilterChip(
                        selected = selectedSource == null,
                        onClick = { selectedSource = null },
                        label = { Text("全部 ${diaryEntries.size}") },
                    )
                    authors.forEach { (source, label) ->
                        val count = diaryEntries.count { it.source == source }
                        FilterChip(
                            selected = selectedSource == source,
                            onClick = { selectedSource = source },
                            label = { Text("$label $count") },
                        )
                    }
                }
            }
        }

        if (diaryEntries.isEmpty()) {
            item {
                SectionCard(title = "今日日记", subtitle = selectedDate) {
                    Text(
                        text = "今日暂无日记",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextTertiary,
                        modifier = Modifier.padding(vertical = 16.dp),
                    )
                }
            }
        } else if (grouped.isEmpty()) {
            item {
                SectionCard(title = "今日日记", subtitle = selectedDate) {
                    Text(
                        text = "该作者今日暂无日记",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextTertiary,
                        modifier = Modifier.padding(vertical = 16.dp),
                    )
                }
            }
        } else {
            grouped.forEach { (groupLabel, entries) ->
                item(key = groupLabel) {
                    SectionCard(
                        // 展示名由后端给出：我 → 我的日记 / Ling → Ling的日记，无需本地映射
                        title = "${groupLabel}的日记",
                        subtitle = "${entries.size} 篇",
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            entries.forEach { entry ->
                                DiaryEntryCard(entry = entry)
                            }
                        }
                    }
                }
            }
        }
    }
}

/** 单条日记卡片:时间 + 类型标签 + 正文(Markdown) + 想法(可选)。 */
@Composable
private fun DiaryEntryCard(entry: DiaryEntry) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Color(0x14000000))
            .padding(14.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = entry.timeStr,
                style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.SemiBold),
                color = Primary,
            )
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(4.dp))
                    .background(Color(0x1A38BDF8))
                    .padding(horizontal = 6.dp, vertical = 2.dp),
            ) {
                Text(
                    text = diaryTypeLabel(entry.type),
                    style = MaterialTheme.typography.labelSmall,
                    color = TextSecondary,
                )
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        SimpleDiaryMarkdown(text = entry.content)
        if (!entry.thought.isNullOrBlank() && entry.thought != "auto_generated_daily_summary") {
            Spacer(modifier = Modifier.height(8.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(6.dp))
                    .background(Color(0x1A38BDF8))
                    .padding(10.dp),
            ) {
                Text(
                    text = "想法: ${entry.thought}",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                )
            }
        }
    }
}

/** 后端 type 字段转中文标签 */
private fun diaryTypeLabel(type: String): String = when (type) {
    "daily_summary" -> "每日总结"
    "proactive" -> "主动记录"
    "daily" -> "日记"
    else -> type
}

/**
 * 日记正文复用聊天/笔记的统一 Markdown AST renderer。
 *
 * 旧版 `RenderRichText` 使用 `Row(Text + LatexMath + Text)`，行内公式后面的长文本会被剩余宽度约束；
 * 现在统一走 [NotesMarkdownRenderer]，避免维护第二套 Markdown / LaTeX 状态机。
 */
@Composable
fun SimpleDiaryMarkdown(text: String) {
    NotesMarkdownRenderer(text = text)
}
