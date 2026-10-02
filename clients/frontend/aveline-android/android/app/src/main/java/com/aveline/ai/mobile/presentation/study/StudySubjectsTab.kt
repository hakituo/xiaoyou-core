package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.School
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
 * 学科入口的第一版。
 *
 * 当前只复用 Study Daily 已有的各科进度摘要，先把信息架构从 6 个功能 Tab 收敛为
 * “今天 / 学科 / 专注 / 更多”。下一阶段再把这里升级为 Curriculum Blueprint +
 * ConceptState 的正式学科树，因此本文件不伪造考纲节点或掌握度。
 */
@Composable
fun StudySubjectsTab(dailyUiState: StudyDailyUiState) {
    val subjects = parseStudySubjectProgress(dailyUiState.latestProgress?.content.orEmpty())

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(top = 8.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    text = "学科",
                    style = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.Bold),
                    color = TextPrimary
                )
                Text(
                    text = "先看当前学习进度；详细考纲树将在 Curriculum 接入后展开。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextSecondary
                )
            }
        }

        if (subjects.isEmpty()) {
            item {
                SectionCard(
                    title = "暂无学科进度",
                    icon = Icons.Default.School
                ) {
                    Text(
                        text = "还没有可展示的 Study Daily 学科进度记录。",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextTertiary,
                        modifier = Modifier.padding(vertical = 8.dp)
                    )
                }
            }
        } else {
            items(subjects, key = { it.name }) { subject ->
                SubjectOverviewCard(subject)
            }
        }
    }
}

@Composable
private fun SubjectOverviewCard(subject: StudySubjectProgress) {
    val color = when {
        subject.progress >= 0.7f -> EmotionGreen
        subject.progress >= 0.3f -> Primary
        else -> TextTertiary
    }
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0x10000000))
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = subject.name,
                        style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
                        color = TextPrimary
                    )
                    Text(
                        text = subject.status.ifBlank { "暂无状态描述" },
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary
                    )
                }
                Text(
                    text = "${(subject.progress * 100).toInt()}%",
                    style = MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.Bold),
                    color = color
                )
                Icon(
                    imageVector = Icons.Default.ChevronRight,
                    contentDescription = null,
                    tint = TextTertiary
                )
            }
            LinearProgressIndicator(
                progress = { subject.progress },
                modifier = Modifier.fillMaxWidth(),
                color = color,
                trackColor = Color(0x1AFFFFFF)
            )
        }
    }
}

internal data class StudySubjectProgress(
    val name: String,
    val status: String,
    val progress: Float
)

internal fun parseStudySubjectProgress(content: String): List<StudySubjectProgress> {
    if (content.isBlank()) return emptyList()
    val sectionStart = content.indexOf("## 各科进展")
    if (sectionStart < 0) return emptyList()

    val afterSection = content.substring(sectionStart)
    val nextSection = afterSection.indexOf("\n## ", 1)
    val sectionText = if (nextSection > 0) afterSection.substring(0, nextSection) else afterSection
    val subjectRegex = Regex("""### (.+?)\n(.*?)(?=\n###|\z)""", RegexOption.DOT_MATCHES_ALL)
    val parsed = mutableMapOf<String, StudySubjectProgress>()

    subjectRegex.findAll(sectionText).forEach { match ->
        val name = match.groupValues[1].trim()
        val body = match.groupValues[2]
        val status = body.lines()
            .firstOrNull { it.startsWith("- 状态：") }
            ?.removePrefix("- 状态：")
            ?.trim()
            .orEmpty()
        parsed[name] = StudySubjectProgress(name, status, mapStudyStatusToProgress(status))
    }

    val order = listOf(
        "语文", "数学", "英语",
        "物理", "化学", "生物",
        "政治", "历史", "地理",
        "计算机科学", "其他"
    )
    val ordered = order.mapNotNull(parsed::get)
    val extras = parsed.values.filter { it.name !in order }
    return ordered + extras
}

private fun mapStudyStatusToProgress(status: String): Float {
    if (status.isBlank() || status == "——" || status == "无") return 0f
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
