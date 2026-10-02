package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Article
import androidx.compose.material.icons.automirrored.filled.ListAlt
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.EditCalendar
import androidx.compose.material.icons.filled.History
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** Study 顶层“更多”里的功能入口。 */
enum class StudyMoreSection(val title: String) {
    HUB("更多"),
    PLAN("计划管理"),
    VOCAB("词汇"),
    NOTES("笔记"),
    DIARY("日记"),
    RECORDS("学习记录")
}

@Composable
fun StudyMoreTab(
    section: StudyMoreSection,
    uiState: StudyUiState,
    dailyUiState: StudyDailyUiState,
    planUiState: StudyPlanUiState,
    notesUiState: StudyNotesUiState,
    vocabUiState: VocabUiState,
    onSectionChange: (StudyMoreSection) -> Unit,
    onDateSelected: (String) -> Unit,
    onTogglePlanItem: (PlanItem) -> Unit,
    onAddPlanItem: (PlanItem) -> Unit,
    onUpdatePlanItem: (PlanItem, PlanItem) -> Unit,
    onDeletePlanItem: (PlanItem) -> Unit,
    onPlanStartFocus: (PlanItem) -> Unit,
    onTopicChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onDurationChange: (Int) -> Unit,
    onRecordStudy: () -> Unit,
    onStartStudy: () -> Unit,
    onFinishStudy: () -> Unit,
    onStartReview: () -> Unit,
    onStartNewWords: () -> Unit,
    onToggleWordOrder: () -> Unit,
    onAddManualStudy: (Int) -> Unit,
    onOpenBooks: () -> Unit,
    onSearch: (String) -> Unit,
    onClearSearch: () -> Unit,
    onOpenLibraryNote: (String) -> Unit,
    onCloseLibraryNoteReader: () -> Unit
) {
    if (section == StudyMoreSection.HUB) {
        StudyMoreHub(onSectionChange)
        return
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            // 二级板块统一吞掉横向滑动：默认不让横滑冒泡到顶层把全局侧边栏拖出来。
            // 有"上一个 / 下一个"概念的板块（计划 / 日记）在更内层自己接住横滑翻日期，
            // 更内层的手势先拿到事件，因此不会被这里抢走。
            .consumeHorizontalSwipe()
    ) {
        MoreSectionHeader(
            title = section.title,
            onBack = { onSectionChange(StudyMoreSection.HUB) }
        )
        when (section) {
            StudyMoreSection.PLAN -> StudyPlanTab(
                planUiState = planUiState,
                onDateSelected = onDateSelected,
                onToggleItem = onTogglePlanItem,
                onAddItem = onAddPlanItem,
                onUpdateItem = onUpdatePlanItem,
                onDeleteItem = onDeletePlanItem,
                onStartFocus = onPlanStartFocus
            )

            StudyMoreSection.VOCAB -> LazyColumn(
                modifier = Modifier.fillMaxWidth(),
                contentPadding = PaddingValues(bottom = 28.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                item {
                    StudyVocabTab(
                        uiState = vocabUiState,
                        onStartReview = onStartReview,
                        onStartNewWords = onStartNewWords,
                        onToggleOrder = onToggleWordOrder,
                        onAddManualStudy = onAddManualStudy,
                        onOpenBooks = onOpenBooks,
                        onSearch = onSearch,
                        onClearSearch = onClearSearch
                    )
                }
            }

            StudyMoreSection.NOTES -> StudyNotesTab(
                notesUiState = notesUiState,
                onOpenNote = onOpenLibraryNote,
                onCloseReader = onCloseLibraryNoteReader
            )

            StudyMoreSection.DIARY -> StudyDiaryTab(
                dailyUiState = dailyUiState,
                onDateSelected = onDateSelected
            )

            StudyMoreSection.RECORDS -> LazyColumn(
                modifier = Modifier.fillMaxWidth(),
                contentPadding = PaddingValues(bottom = 28.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                item {
                    StudyOverviewTab(
                        uiState = uiState,
                        dailyUiState = dailyUiState,
                        onTopicChange = onTopicChange,
                        onContentChange = onContentChange,
                        onDurationChange = onDurationChange,
                        onRecordStudy = onRecordStudy,
                        onStartStudy = onStartStudy,
                        onFinishStudy = onFinishStudy
                    )
                }
            }

            StudyMoreSection.HUB -> Unit
        }
    }
}

@Composable
private fun StudyMoreHub(onOpen: (StudyMoreSection) -> Unit) {
    val entries = listOf(
        MoreEntry(StudyMoreSection.PLAN, Icons.Default.EditCalendar, "查看其他日期、添加或编辑计划项"),
        MoreEntry(StudyMoreSection.VOCAB, Icons.AutoMirrored.Filled.MenuBook, "复习、新词、词书与词典"),
        MoreEntry(StudyMoreSection.NOTES, Icons.AutoMirrored.Filled.Article, "打开 Study 学习库笔记"),
        MoreEntry(StudyMoreSection.DIARY, Icons.Default.History, "查看每天的学习日记"),
        MoreEntry(StudyMoreSection.RECORDS, Icons.AutoMirrored.Filled.ListAlt, "旧学习记录、最新进度与手动记录")
    )

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(top = 8.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    text = "更多",
                    style = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.Bold),
                    color = TextPrimary
                )
                Text(
                    text = "低频工具放在这里，今天的执行入口保持干净。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextSecondary
                )
            }
        }
        items(entries, key = { it.section.name }) { entry ->
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onOpen(entry.section) },
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(containerColor = Color(0x10000000))
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        imageVector = entry.icon,
                        contentDescription = null,
                        tint = Primary
                    )
                    Spacer(modifier = Modifier.padding(horizontal = 7.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = entry.section.title,
                            style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                            color = TextPrimary
                        )
                        Text(
                            text = entry.subtitle,
                            style = MaterialTheme.typography.bodySmall,
                            color = TextTertiary
                        )
                    }
                    Icon(
                        imageVector = Icons.Default.ChevronRight,
                        contentDescription = null,
                        tint = TextTertiary
                    )
                }
            }
        }
    }
}

@Composable
private fun MoreSectionHeader(title: String, onBack: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        IconButton(onClick = onBack) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = "返回更多",
                tint = TextPrimary
            )
        }
        Text(
            text = title,
            style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold),
            color = TextPrimary
        )
    }
}

private data class MoreEntry(
    val section: StudyMoreSection,
    val icon: ImageVector,
    val subtitle: String
)
