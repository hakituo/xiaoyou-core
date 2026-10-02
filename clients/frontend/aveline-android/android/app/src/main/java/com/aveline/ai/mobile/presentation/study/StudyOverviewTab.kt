package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.automirrored.filled.TrendingUp
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.School
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 学习概览 Tab。
 *
 * 展示学习仪表盘:学习模式开关、今日学习统计、学习会话输入、各科进度。
 * 优先使用 [StudyDailyUiState.latestProgress] 中的进度内容,为空时使用 placeholder。
 *
 * @param uiState 学习模块 UI 状态
 * @param dailyUiState Daily 文件夹 UI 状态
 * @param onToggleStudyMode 切换学习模式
 * @param onTopicChange 学习主题变更
 * @param onContentChange 学习内容变更
 * @param onDurationChange 学习时长变更(分钟)
 * @param onRecordStudy 保存学习记录
 * @param onStartStudy 开始学习会话
 * @param onFinishStudy 结束学习会话
 */
@Composable
fun StudyOverviewTab(
    uiState: StudyUiState,
    dailyUiState: StudyDailyUiState,
    onTopicChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onDurationChange: (Int) -> Unit,
    onRecordStudy: () -> Unit,
    onStartStudy: () -> Unit,
    onFinishStudy: () -> Unit
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // 今日学习统计(从 Daily 整合)
        TodayStudySection(uiState = uiState)

        // 最新学习进度(优先使用后端 latestProgress,为空时使用 placeholder)
        LatestProgressSection(dailyUiState = dailyUiState)

        // 学习会话输入(从 Daily 整合,去掉重复)
        StudySessionSection(
            topic = uiState.recordTopic,
            content = uiState.recordContent,
            duration = uiState.recordDuration,
            onTopicChange = onTopicChange,
            onContentChange = onContentChange,
            onDurationChange = onDurationChange,
            onRecordStudy = onRecordStudy,
            onStartStudy = onStartStudy,
            onFinishStudy = onFinishStudy
        )

        // 各科进度(从 Daily 进度文件解析)
        SubjectProgressSection(dailyUiState = dailyUiState)
    }
}

/** 今日学习统计分区:时长/科目/会话数(使用后端真实数据) */
@Composable
private fun TodayStudySection(uiState: StudyUiState) {
    val subjectCount = uiState.studyRecords.map { it.topic }.distinct().size
    val sessionCount = uiState.studyRecords.size

    SectionCard(
        title = "今日学习",
        icon = Icons.Default.Schedule,
        subtitle = "时长 · 科目 · 会话数"
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            TodayStatCard(
                icon = Icons.Default.Schedule,
                label = "学习时长",
                value = "${uiState.todayStudyMinutes}分钟",
                modifier = Modifier.weight(1f)
            )
            TodayStatCard(
                icon = Icons.Default.School,
                label = "科目数",
                value = subjectCount.toString(),
                modifier = Modifier.weight(1f)
            )
            TodayStatCard(
                icon = Icons.Default.Schedule,
                label = "会话数",
                value = sessionCount.toString(),
                modifier = Modifier.weight(1f)
            )
        }
        Spacer(modifier = Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            MiniStat(label = "连续学习", value = "${uiState.studyStreakDays}天")
            MiniStat(label = "今日复习", value = uiState.reviewedToday.toString())
        }
    }
}

/** 今日统计小卡片 */
@Composable
private fun TodayStatCard(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    value: String,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(Color(0x14000000))
            .padding(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = Primary,
            modifier = Modifier.size(20.dp)
        )
        Spacer(modifier = Modifier.height(6.dp))
        Text(
            text = value,
            style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
            color = TextPrimary
        )
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary
        )
    }
}

/** 迷你统计标签 */
@Composable
private fun MiniStat(label: String, value: String) {
    Column(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x1AFFFFFF))
            .padding(horizontal = 10.dp, vertical = 6.dp)
    ) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = TextTertiary)
        Text(value, style = MaterialTheme.typography.bodyMedium, color = TextPrimary, fontWeight = FontWeight.Bold)
    }
}

/**
 * 最新学习进度分区。
 *
 * 只展示 [StudyDailyUiState.latestProgress] 中的后端进度内容,不再使用 placeholder。
 */
@Composable
private fun LatestProgressSection(dailyUiState: StudyDailyUiState) {
    val progress = dailyUiState.latestProgress

    SectionCard(
        title = "最新学习进度",
        icon = Icons.AutoMirrored.Filled.TrendingUp,
        subtitle = progress?.date ?: "暂无日期"
    ) {
        if (progress?.content.isNullOrBlank()) {
            Text(
                text = "暂无学习进度记录",
                style = MaterialTheme.typography.bodyMedium,
                color = TextTertiary,
                modifier = Modifier.padding(vertical = 12.dp)
            )
        } else {
            // 复用日记 Tab 的简单 Markdown 渲染器
            SimpleDiaryMarkdown(text = progress?.content.orEmpty())
        }
    }
}

/** 学习会话分区:主题/时长/笔记输入 + 开始/结束按钮 */
@Composable
private fun StudySessionSection(
    topic: String,
    content: String,
    duration: Int,
    onTopicChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onDurationChange: (Int) -> Unit,
    onRecordStudy: () -> Unit,
    onStartStudy: () -> Unit,
    onFinishStudy: () -> Unit
) {
    SectionCard(
        title = "学习会话",
        icon = Icons.AutoMirrored.Filled.MenuBook,
        subtitle = "主题 · 时长 · 笔记"
    ) {
        OutlinedTextField(
            value = topic,
            onValueChange = onTopicChange,
            label = { Text("科目") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(10.dp))
        OutlinedTextField(
            value = duration.toString(),
            onValueChange = { text ->
                text.toIntOrNull()?.let(onDurationChange)
            },
            label = { Text("时长(分钟)") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(10.dp))
        OutlinedTextField(
            value = content,
            onValueChange = onContentChange,
            label = { Text("笔记") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 2
        )
        Spacer(modifier = Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = onRecordStudy,
                modifier = Modifier.weight(1f)
            ) {
                Text("保存记录")
            }
            Button(
                onClick = onStartStudy,
                modifier = Modifier.weight(1f)
            ) {
                Text("开始会话")
            }
            Button(
                onClick = onFinishStudy,
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0x33000000))
            ) {
                Text("结束")
            }
        }
    }
}

/**
 * 各科进度分区:从 Daily 进度文件解析各科状态。
 *
 * 解析 progress 文件中的 `## 各科进展` 部分,提取科目名和状态文字,
 * 映射为进度百分比后按标准顺序(语数英→物化生→政史地→其他)排列。
 */
@Composable
private fun SubjectProgressSection(dailyUiState: StudyDailyUiState) {
    val progressContent = dailyUiState.latestProgress?.content
    val subjects = if (!progressContent.isNullOrBlank()) {
        parseSubjectProgress(progressContent)
    } else {
        emptyList()
    }

    SectionCard(
        title = "各科进度",
        icon = Icons.Default.Assessment,
        subtitle = "各学科掌握情况"
    ) {
        if (subjects.isEmpty()) {
            Text(
                text = "暂无各科进度数据",
                style = MaterialTheme.typography.bodyMedium,
                color = TextTertiary,
                modifier = Modifier.padding(vertical = 12.dp)
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                subjects.forEach { (name, progress) ->
                    SubjectProgressBar(name = name, progress = progress)
                }
            }
        }
    }
}

/**
 * 从进度文件内容解析各科进度。
 *
 * 解析 `## 各科进展` 下的 `### 科目名` 和 `- 状态：...`，
 * 将状态文字映射为进度百分比,按标准顺序排列。
 */
private fun parseSubjectProgress(content: String): List<Pair<String, Float>> {
    if (content.isBlank()) return emptyList()

    // 找到 "## 各科进展" 部分
    val sectionStart = content.indexOf("## 各科进展")
    if (sectionStart < 0) return emptyList()

    // 截取到下一个二级标题或文件末尾
    val afterSection = content.substring(sectionStart)
    val nextSection = afterSection.indexOf("\n## ", 1)
    val sectionText = if (nextSection > 0) {
        afterSection.substring(0, nextSection)
    } else {
        afterSection
    }

    // 按 ### 分割科目,提取科目名和状态
    val subjectRegex = Regex("""### (.+?)\n(.*?)(?=\n###|\z)""", RegexOption.DOT_MATCHES_ALL)
    val subjects = mutableMapOf<String, Float>()

    subjectRegex.findAll(sectionText).forEach { match ->
        val name = match.groupValues[1].trim()
        val body = match.groupValues[2]

        // 提取状态行
        val statusLine = body.lines().firstOrNull { it.startsWith("- 状态：") }
        val status = statusLine?.removePrefix("- 状态：")?.trim() ?: ""

        subjects[name] = mapStatusToProgress(status)
    }

    // 按标准顺序排列:语数英 → 物化生 → 政史地 → 其他
    val order = listOf(
        "语文", "数学", "英语",
        "物理", "化学", "生物",
        "政治", "历史", "地理",
        "计算机科学", "其他"
    )
    val ordered = order.mapNotNull { name -> subjects[name]?.let { name to it } }
    // 加上未在标准顺序中的科目
    val extras = subjects.filterKeys { it !in order }.map { it.key to it.value }
    return ordered + extras
}

/**
 * 将状态文字映射为进度百分比。
 *
 * 规则基于 progress 文件中Ling写的状态描述:
 * - "完整"/"全覆盖" → 90%
 * - "体系" → 70%
 * - "很大"/"很广" → 60%
 * - "框架" → 40%
 * - "较少" → 20%
 * - "弱项"/"需关注" → 50%
 * - "无"/"——" → 0%
 * - 其他 → 50%
 */
private fun mapStatusToProgress(status: String): Float {
    if (status.isBlank() || status == "——" || status == "无") return 0.0f
    return when {
        status.contains("完整") || status.contains("全覆盖") -> 0.9f
        status.contains("体系") -> 0.7f
        status.contains("很大") || status.contains("很广") -> 0.6f
        status.contains("框架") -> 0.4f
        status.contains("较少") -> 0.2f
        status.contains("弱项") || status.contains("需关注") -> 0.5f
        else -> 0.5f
    }
}

/** 单个科目进度条 */
@Composable
private fun SubjectProgressBar(name: String, progress: Float) {
    val color = when {
        progress >= 0.7f -> EmotionGreen
        progress >= 0.3f -> Primary
        else -> TextTertiary
    }
    Column {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                text = name,
                style = MaterialTheme.typography.bodyMedium,
                color = TextPrimary
            )
            Text(
                text = "${(progress * 100).toInt()}%",
                style = MaterialTheme.typography.labelSmall,
                color = color
            )
        }
        Spacer(modifier = Modifier.height(4.dp))
        LinearProgressIndicator(
            progress = { progress },
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(3.dp)),
            color = color,
            trackColor = Color(0x1AFFFFFF)
        )
    }
}
