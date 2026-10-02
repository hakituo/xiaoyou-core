package com.aveline.ai.mobile.presentation.study

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.presentation.components.AvelineTabRow
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.components.ModuleHeaderActionContainer
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import kotlinx.coroutines.launch

/**
 * Study 顶层信息架构。
 *
 * 旧枚举项暂时保留给 NavGraph 的按需加载回调使用，但不会出现在 TabRow 中。
 */
enum class StudyTabV2(val title: String) {
    TODAY("今天"),
    SUBJECTS("学科"),
    FOCUS("专注"),
    MORE("更多"),

    // Legacy loading targets — hidden from top-level navigation.
    OVERVIEW("概览"),
    PLAN("计划"),
    DIARY("日记"),
    NOTES("笔记"),
    VOCAB("词汇")
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun StudyScreenV2(
    uiState: StudyUiState,
    dailyUiState: StudyDailyUiState,
    focusState: StudyFocusState,
    planUiState: StudyPlanUiState,
    notesUiState: StudyNotesUiState,
    vocabUiState: VocabUiState,
    onTabChange: (StudyTabV2) -> Unit,
    onMoreSectionOpen: (StudyMoreSection) -> Unit = {},
    onTopicChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onDurationChange: (Int) -> Unit,
    onRecordStudy: () -> Unit,
    onStartStudy: () -> Unit,
    onFinishStudy: () -> Unit,
    onClearError: () -> Unit,
    onStartReview: () -> Unit,
    onStartNewWords: () -> Unit = {},
    onSubmitReview: (String) -> Unit,
    onSetShowAnswer: (Boolean) -> Unit,
    onSetIsReviewMode: (Boolean) -> Unit,
    onSetSessionSummary: (String) -> Unit,
    onOpenLibraryNote: (String) -> Unit,
    onCloseLibraryNoteReader: () -> Unit,
    onSelectDate: (String) -> Unit,
    onRefreshDaily: () -> Unit,
    onTogglePlanItem: (PlanItem) -> Unit = {},
    onAddPlanItem: (PlanItem) -> Unit = {},
    onUpdatePlanItem: (PlanItem, PlanItem) -> Unit = { _, _ -> },
    onDeletePlanItem: (PlanItem) -> Unit = {},
    onPlanStartFocus: (PlanItem) -> Unit = {},
    onToggleFocusTimer: () -> Unit = {},
    onResetFocusTimer: () -> Unit = {},
    onSkipFocusPhase: () -> Unit = {},
    onFocusWorkMinutesChange: (Int) -> Unit = {},
    onFocusBreakMinutesChange: (Int) -> Unit = {},
    onFocusLongBreakMinutesChange: (Int) -> Unit = {},
    onFocusNameChange: (String) -> Unit = {},
    onToggleWordOrder: () -> Unit = {},
    onAddManualStudy: (Int) -> Unit = {},
    onOpenBooks: () -> Unit = {},
    onLoadBookWords: () -> Unit = {},
    onSwitchBook: (String) -> Unit = {},
    onSearch: (String) -> Unit = {},
    onClearSearch: () -> Unit = {},
    /**
     * 深链直达背单词（通知点击）：true 时首屏直接落在「更多 → 词汇」，
     * 而不是停在"今天"概览页 —— 用户点背单词通知就是为了马上背，
     * 落到概览还要再点两次才能开始。
     */
    initialVocab: Boolean = false
) {
    val tabs = remember {
        listOf(
            StudyTabV2.TODAY,
            StudyTabV2.SUBJECTS,
            StudyTabV2.FOCUS,
            StudyTabV2.MORE
        )
    }
    // 直达背单词时首屏翻到「更多」页（TabRow 第 4 项）
    val pagerState = rememberPagerState(
        initialPage = if (initialVocab) tabs.indexOf(StudyTabV2.MORE) else 0
    ) { tabs.size }
    val scope = rememberCoroutineScope()
    var moreSection by remember {
        mutableStateOf(if (initialVocab) StudyMoreSection.VOCAB else StudyMoreSection.HUB)
    }
    var vocabSubScreen by remember { mutableStateOf(VocabSubScreen.DASHBOARD) }

    LaunchedEffect(pagerState.currentPage) {
        val tab = tabs[pagerState.currentPage]
        onTabChange(tab)
        // Today 依赖 typed DailyPlan；复用 NavGraph 现有 PLAN 加载分支，避免重复网络层逻辑。
        if (tab == StudyTabV2.TODAY) {
            onTabChange(StudyTabV2.PLAN)
        }
        if (tab != StudyTabV2.MORE) {
            moreSection = StudyMoreSection.HUB
            if (!vocabUiState.isReviewMode) {
                vocabSubScreen = VocabSubScreen.DASHBOARD
            }
        }
    }

    fun requestMoreSection(section: StudyMoreSection) {
        moreSection = section
        onMoreSectionOpen(section)
        when (section) {
            StudyMoreSection.PLAN -> onTabChange(StudyTabV2.PLAN)
            StudyMoreSection.VOCAB -> onTabChange(StudyTabV2.VOCAB)
            StudyMoreSection.NOTES -> onTabChange(StudyTabV2.NOTES)
            StudyMoreSection.DIARY -> onTabChange(StudyTabV2.DIARY)
            StudyMoreSection.RECORDS -> onTabChange(StudyTabV2.OVERVIEW)
            StudyMoreSection.HUB -> Unit
        }
    }

    // 深链直达背单词：切页的 LaunchedEffect 只会触发 onTabChange(MORE)（不加载词汇），
    // 这里补一次分区切换，才会真正拉取今日单词/复习总览。
    LaunchedEffect(Unit) {
        if (initialVocab) requestMoreSection(StudyMoreSection.VOCAB)
    }

    // 系统返回键逐级回退：二级板块 → 「更多」入口，而不是直接退出 Study 回到聊天页。
    // 词汇全屏层（StudyVocabBookHost）的 BackHandler 在它之后组合，LIFO 下优先级更高，
    // 所以背单词/词书里按返回仍然是先在词汇内部退一层。
    BackHandler(enabled = moreSection != StudyMoreSection.HUB) {
        moreSection = StudyMoreSection.HUB
        if (!vocabUiState.isReviewMode) {
            vocabSubScreen = VocabSubScreen.DASHBOARD
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
        ) {
            ModuleHeader(
                title = "Study",
                subtitle = "今天只做下一件事"
            ) {
                ModuleHeaderActionContainer {
                    androidx.compose.material3.IconButton(onClick = onRefreshDaily) {
                        if (uiState.isLoading || planUiState.isLoading) {
                            androidx.compose.material3.CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                color = Color.White,
                                strokeWidth = 2.dp
                            )
                        } else {
                            androidx.compose.material3.Icon(
                                imageVector = Icons.Default.Refresh,
                                contentDescription = "刷新",
                                tint = Color.White
                            )
                        }
                    }
                }
            }

            AvelineTabRow(
                titles = tabs.map { it.title },
                selectedTabIndex = pagerState.currentPage,
                onTabSelected = { index ->
                    scope.launch { pagerState.animateScrollToPage(index) }
                },
                modifier = Modifier.fillMaxWidth()
            )

            uiState.successMessage?.takeIf { it.isNotBlank() }?.let { message ->
                androidx.compose.material3.Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .clickable { onClearError() },
                    colors = androidx.compose.material3.CardDefaults.cardColors(
                        containerColor = EmotionGreen.copy(alpha = 0.1f)
                    ),
                    shape = RoundedCornerShape(14.dp)
                ) {
                    Text(
                        text = message,
                        color = EmotionGreen,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(14.dp)
                    )
                }
            }

            // 「更多」进入二级板块（计划/词汇/笔记/日记/学习记录）后禁用外层手势：
            // 否则子页面里的横向滑动会被外层 pager 吃掉，把整个“更多”页翻到左边的「专注」。
            // 注意只禁用手势，TabRow 点击走 animateScrollToPage 的程序化切页不受影响。
            val pagerGestureEnabled = moreSection == StudyMoreSection.HUB

            HorizontalPager(
                state = pagerState,
                userScrollEnabled = pagerGestureEnabled,
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 16.dp)
            ) { page ->
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.TopStart
                ) {
                    when (tabs[page]) {
                        StudyTabV2.TODAY -> StudyTodayTab(
                            uiState = uiState,
                            planUiState = planUiState,
                            onToggleItem = onTogglePlanItem,
                            onStartFocus = { item ->
                                StudyPlanFocusLink.select(item.id)
                                onPlanStartFocus(item)
                                scope.launch { pagerState.animateScrollToPage(StudyTabV2.FOCUS.ordinal) }
                            },
                            onOpenPlanManager = {
                                requestMoreSection(StudyMoreSection.PLAN)
                                scope.launch { pagerState.animateScrollToPage(StudyTabV2.MORE.ordinal) }
                            }
                        )

                        StudyTabV2.SUBJECTS -> StudySubjectsTab(dailyUiState = dailyUiState)

                        StudyTabV2.FOCUS -> StudyFocusTab(
                            focusState = focusState,
                            onToggleTimer = onToggleFocusTimer,
                            onReset = onResetFocusTimer,
                            onSkipPhase = onSkipFocusPhase,
                            onWorkMinutesChange = onFocusWorkMinutesChange,
                            onBreakMinutesChange = onFocusBreakMinutesChange,
                            onLongBreakMinutesChange = onFocusLongBreakMinutesChange,
                            onFocusNameChange = onFocusNameChange
                        )

                        StudyTabV2.MORE -> StudyMoreTab(
                            section = moreSection,
                            uiState = uiState,
                            dailyUiState = dailyUiState,
                            planUiState = planUiState,
                            notesUiState = notesUiState,
                            vocabUiState = vocabUiState,
                            onSectionChange = { section ->
                                requestMoreSection(section)
                                if (section != StudyMoreSection.VOCAB && !vocabUiState.isReviewMode) {
                                    vocabSubScreen = VocabSubScreen.DASHBOARD
                                }
                            },
                            onDateSelected = onSelectDate,
                            onTogglePlanItem = onTogglePlanItem,
                            onAddPlanItem = onAddPlanItem,
                            onUpdatePlanItem = onUpdatePlanItem,
                            onDeletePlanItem = onDeletePlanItem,
                            onPlanStartFocus = { item ->
                                StudyPlanFocusLink.select(item.id)
                                onPlanStartFocus(item)
                                scope.launch { pagerState.animateScrollToPage(StudyTabV2.FOCUS.ordinal) }
                            },
                            onTopicChange = onTopicChange,
                            onContentChange = onContentChange,
                            onDurationChange = onDurationChange,
                            onRecordStudy = onRecordStudy,
                            onStartStudy = onStartStudy,
                            onFinishStudy = onFinishStudy,
                            onStartReview = onStartReview,
                            onStartNewWords = onStartNewWords,
                            onToggleWordOrder = onToggleWordOrder,
                            onAddManualStudy = onAddManualStudy,
                            onOpenBooks = {
                                onOpenBooks()
                                vocabSubScreen = VocabSubScreen.BOOK_LIST
                            },
                            onSearch = onSearch,
                            onClearSearch = onClearSearch,
                            onOpenLibraryNote = onOpenLibraryNote,
                            onCloseLibraryNoteReader = onCloseLibraryNoteReader
                        )

                        else -> Unit
                    }
                }
            }
        }

        val showVocabHost = vocabUiState.isReviewMode
            || vocabUiState.sessionSummary != null
            || vocabSubScreen != VocabSubScreen.DASHBOARD
        AnimatedVisibility(
            visible = showVocabHost,
            modifier = Modifier.background(Background),
            enter = slideInHorizontally(tween(300)) { it } + fadeIn(tween(300)),
            exit = slideOutHorizontally(tween(300)) { it } + fadeOut(tween(300))
        ) {
            StudyVocabBookHost(
                uiState = vocabUiState,
                vocabSubScreen = vocabSubScreen,
                onVocabSubScreenChange = { vocabSubScreen = it },
                onSetShowAnswer = onSetShowAnswer,
                onSubmitReview = onSubmitReview,
                onSetIsReviewMode = onSetIsReviewMode,
                onSetSessionSummary = onSetSessionSummary,
                onSwitchBook = onSwitchBook
            )
        }
    }
}
