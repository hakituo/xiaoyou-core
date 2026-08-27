package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.DiaryEntry
import com.aveline.ai.mobile.presentation.components.LatexMath
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 学习日记 Tab。
 *
 * 从 /api/v1/diary 读取 journal 日记列表,按作者 source 分组显示:
 * - 我的日记(source=user)
 * - Aveline 的日记(source=aveline)
 * - Ling的日记(source=ling)
 *
 * 切换日期时由 [StudyDailyViewModel.loadDateContent] 触发 [loadDiaries] 刷新。
 *
 * @param dailyUiState Daily 文件夹 UI 状态(含 diaryEntries)
 * @param onDateSelected 选择日期回调(格式: yyyy-MM-dd)
 */
@Composable
fun StudyDiaryTab(
    dailyUiState: StudyDailyUiState,
    onDateSelected: (String) -> Unit
) {
    var selectedDate by remember {
        mutableStateOf(dailyUiState.selectedDate.ifBlank {
            SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
        })
    }

    // dailyUiState.selectedDate 变化时同步本地状态
    LaunchedEffect(dailyUiState.selectedDate) {
        if (dailyUiState.selectedDate.isNotBlank() && dailyUiState.selectedDate != selectedDate) {
            selectedDate = dailyUiState.selectedDate
        }
    }

    val diaryEntries = dailyUiState.diaryEntries

    // 人物切换 FilterChip: null=全部, user=我的, aveline=Aveline, ling=Ling
    var selectedSource by remember { mutableStateOf<String?>(null) }

    // 按 source 分组,固定顺序:我的、Aveline、Ling
    val grouped = remember(diaryEntries, selectedSource) {
        val map = diaryEntries.groupBy { it.source }
        val sourceToLabel = mapOf(
            "user" to "我的日记",
            "aveline" to "Aveline 的日记",
            "ling" to "Ling的日记"
        )
        // 有 selectedSource 时只取该 source, 否则取所有有数据的 source (固定顺序)
        val sourcesToShow = if (selectedSource != null) listOf(selectedSource!!) else listOf("user", "aveline", "ling")
        sourcesToShow.mapNotNull { source ->
            map[source]?.let { entries -> sourceToLabel[source]!! to entries }
        }
    }

    // 各 source 的日记条数 (用于 FilterChip 显示数量)
    val sourceCounts = remember(diaryEntries) {
        val map = diaryEntries.groupBy { it.source }
        mapOf(
            "user" to (map["user"]?.size ?: 0),
            "aveline" to (map["aveline"]?.size ?: 0),
            "ling" to (map["ling"]?.size ?: 0)
        )
    }

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

        // 人物切换 FilterChip 行 (只在有日记时显示)
        if (diaryEntries.isNotEmpty()) {
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    FilterChip(
                        selected = selectedSource == null,
                        onClick = { selectedSource = null },
                        label = { Text("全部 ${diaryEntries.size}") }
                    )
                    FilterChip(
                        selected = selectedSource == "user",
                        onClick = { selectedSource = "user" },
                        label = { Text("我的 ${sourceCounts["user"] ?: 0}") }
                    )
                    FilterChip(
                        selected = selectedSource == "aveline",
                        onClick = { selectedSource = "aveline" },
                        label = { Text("Aveline ${sourceCounts["aveline"] ?: 0}") }
                    )
                    FilterChip(
                        selected = selectedSource == "ling",
                        onClick = { selectedSource = "ling" },
                        label = { Text("Ling ${sourceCounts["ling"] ?: 0}") }
                    )
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
                        modifier = Modifier.padding(vertical = 16.dp)
                    )
                }
            }
        } else if (grouped.isEmpty()) {
            // 选了某个 source 但该 source 当天没日记
            item {
                SectionCard(title = "今日日记", subtitle = selectedDate) {
                    Text(
                        text = "该作者今日暂无日记",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextTertiary,
                        modifier = Modifier.padding(vertical = 16.dp)
                    )
                }
            }
        } else {
            grouped.forEach { (groupLabel, entries) ->
                item(key = groupLabel) {
                    SectionCard(
                        title = groupLabel,
                        subtitle = "${entries.size} 篇"
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

/**
 * 单条日记卡片:时间 + 类型标签 + 正文(Markdown) + 想法(可选)。
 */
@Composable
private fun DiaryEntryCard(entry: DiaryEntry) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Color(0x14000000))
            .padding(14.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = entry.timeStr,
                style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.SemiBold),
                color = Primary
            )
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(4.dp))
                    .background(Color(0x1A38BDF8))
                    .padding(horizontal = 6.dp, vertical = 2.dp)
            ) {
                Text(
                    text = diaryTypeLabel(entry.type),
                    style = MaterialTheme.typography.labelSmall,
                    color = TextSecondary
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
                    .padding(10.dp)
            ) {
                Text(
                    text = "想法: ${entry.thought}",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary
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
 * 简单 Markdown 渲染器(日记用)。
 *
 * 支持:标题(#/##/###)、无序列表(- 星号)、引用(>)、粗体(**text**)、段落。
 *
 * @param text Markdown 文本
 */
@Composable
fun SimpleDiaryMarkdown(text: String) {
    val lines = text.lines()
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        lines.forEach { line ->
            val trimmed = line.trim()
            when {
                trimmed.isEmpty() -> Spacer(modifier = Modifier.height(4.dp))

                trimmed.startsWith("# ") -> Text(
                    text = trimmed.removePrefix("# ").trim(),
                    style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold),
                    color = TextPrimary
                )

                trimmed.startsWith("## ") -> {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = trimmed.removePrefix("## ").trim(),
                        style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
                        color = TextPrimary
                    )
                }

                trimmed.startsWith("### ") -> Text(
                    text = trimmed.removePrefix("### ").trim(),
                    style = MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.SemiBold),
                    color = Primary
                )

                trimmed.startsWith("> ") -> Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(6.dp))
                        .background(Color(0x1A38BDF8))
                        .padding(10.dp)
                ) {
                    Text(
                        text = trimmed.removePrefix("> ").trim(),
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary
                    )
                }

                trimmed.startsWith("- ") || trimmed.startsWith("* ") -> Row(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = "•",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Primary,
                        modifier = Modifier.width(20.dp)
                    )
                    RenderRichText(
                        text = trimmed.drop(2).trim(),
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextPrimary
                    )
                }

                else -> RenderRichText(
                    text = trimmed,
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextPrimary
                )
            }
        }
    }
}

/** 文本片段类型 */
private enum class TextSegmentType { Normal, Bold, InlineMath }

/** 文本片段(用于粗体 / 行内 LaTeX 解析) */
private data class TextSegment(
    val text: String,
    val type: TextSegmentType = TextSegmentType.Normal
)

/** 渲染含粗体(**text**)和行内 LaTeX($...$)的文本 */
@Composable
fun RenderRichText(
    text: String,
    style: androidx.compose.ui.text.TextStyle,
    color: Color
) {
    val segments = remember(text) { parseRichTextSegments(text) }

    Row(modifier = Modifier.fillMaxWidth()) {
        segments.forEach { segment ->
            when (segment.type) {
                TextSegmentType.InlineMath -> LatexMath(
                    formula = segment.text,
                    displayMode = false
                )
                TextSegmentType.Bold -> Text(
                    text = segment.text,
                    style = style,
                    color = color,
                    fontWeight = FontWeight.Bold
                )
                TextSegmentType.Normal -> Text(
                    text = segment.text,
                    style = style,
                    color = color,
                    fontWeight = FontWeight.Normal,
                    textDecoration = if (segment.text.startsWith("~~") && segment.text.endsWith("~~")) {
                        TextDecoration.LineThrough
                    } else {
                        TextDecoration.None
                    }
                )
            }
        }
    }
}

/**
 * 解析富文本片段, 支持:
 * - 粗体: **text**
 * - 行内 LaTeX: $...$
 *
 * 注意: 块级公式 $$...$$ 在 NotesMarkdownRenderer 中单独处理, 不会进入本函数。
 */
private fun parseRichTextSegments(text: String): List<TextSegment> {
    val segments = mutableListOf<TextSegment>()
    var remaining = text

    // 优先处理最靠前的标记(** 或 $), 交替解析
    while (remaining.isNotEmpty()) {
        val boldStart = remaining.indexOf("**")
        val mathStart = remaining.indexOf('$')

        when {
            // 没有任何标记, 直接作为普通文本
            boldStart == -1 && mathStart == -1 -> {
                segments.add(TextSegment(remaining, TextSegmentType.Normal))
                remaining = ""
            }
            // 只有粗体标记或粗体在前
            mathStart == -1 || (boldStart != -1 && boldStart < mathStart) -> {
                if (boldStart > 0) {
                    segments.add(TextSegment(remaining.substring(0, boldStart), TextSegmentType.Normal))
                }
                val boldEnd = remaining.indexOf("**", boldStart + 2)
                if (boldEnd >= 0) {
                    segments.add(TextSegment(remaining.substring(boldStart + 2, boldEnd), TextSegmentType.Bold))
                    remaining = remaining.substring(boldEnd + 2)
                } else {
                    segments.add(TextSegment(remaining.substring(boldStart), TextSegmentType.Normal))
                    remaining = ""
                }
            }
            // 行内 LaTeX 在前
            else -> {
                if (mathStart > 0) {
                    segments.add(TextSegment(remaining.substring(0, mathStart), TextSegmentType.Normal))
                }
                val mathEnd = remaining.indexOf('$', mathStart + 1)
                if (mathEnd >= 0) {
                    // 排除 $$ 块级公式(交给上层处理)
                    if (mathEnd == mathStart + 1 && remaining.startsWith("$$", mathStart)) {
                        // 当作普通文本保留
                        segments.add(TextSegment(remaining.substring(mathStart, mathEnd + 1), TextSegmentType.Normal))
                        remaining = remaining.substring(mathEnd + 1)
                    } else {
                        val mathContent = remaining.substring(mathStart + 1, mathEnd)
                        segments.add(TextSegment(mathContent, TextSegmentType.InlineMath))
                        remaining = remaining.substring(mathEnd + 1)
                    }
                } else {
                    segments.add(TextSegment(remaining.substring(mathStart), TextSegmentType.Normal))
                    remaining = ""
                }
            }
        }
    }
    return segments
}
