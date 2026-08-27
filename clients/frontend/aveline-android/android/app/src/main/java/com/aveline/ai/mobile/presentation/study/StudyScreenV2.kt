package com.aveline.ai.mobile.presentation.study

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.components.AvelineTabRow
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.components.ModuleHeaderActionContainer
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import kotlinx.coroutines.launch

/**
 * V2 版本的学习 Tab 枚举,6 个 tab。
 *
 * 整合 Daily 文件夹功能,包含:概览/专注/计划/日记/笔记/词汇。
 */
enum class StudyTabV2(val title: String) {
    OVERVIEW("概览"),
    FOCUS("专注"),
    PLAN("计划"),
    DIARY("日记"),
    NOTES("笔记"),
    VOCAB("词汇")
}

/**
 * 学习模块主界面 V2。
 *
 * 整合学习功能并适配 Study/Daily 文件夹,使用 TabRow + HorizontalPager 组织 6 个 tab:
 * 概览 / 专注 / 计划 / 日记 / 笔记 / 词汇。
 *
 * 复用现有 [StudyUiState],新增 Study/Daily 文件夹相关回调。
 *
 * @param uiState 学习模块 UI 状态
 * @param dailyUiState Daily 文件夹 UI 状态
 * @param onTabChange Tab 切换回调
 * @param onTopicChange 学习主题变更
 * @param onContentChange 学习内容变更
 * @param onDurationChange 学习时长变更(分钟)
 * @param onRecordStudy 保存学习记录
 * @param onStartStudy 开始学习会话
 * @param onFinishStudy 结束学习会话
 * @param onClearError 清除错误信息
 * @param onStartReview 开始词汇复习
 * @param onStartNewWords 开始背新单词
 * @param onSubmitReview 提交词汇评分("1"=Again "2"=Hard "3"=Good "4"=Easy)
 * @param onSetShowAnswer 设置是否显示答案
 * @param onSetIsReviewMode 设置复习模式
 * @param onSetSessionSummary 设置会话总结(传空字符串清除)
 * @param onOpenLibraryNote 打开学习库笔记阅读页回调(传入相对路径)
 * @param onCloseLibraryNoteReader 关闭学习库笔记阅读页回调
 * @param onSelectDate 选择日期回调(格式: yyyy-MM-dd)
 * @param onRefreshDaily 刷新 Daily 数据
 * @param onSavePlan 保存计划回调(传入编辑后的完整计划项列表)
 * @param onPlanStartFocus 点击计划项「开始计时」回调(联动专注番茄钟,并跳转到专注 Tab)
 * @param onToggleFocusTimer 开始 / 暂停番茄钟
 * @param onResetFocusTimer 重置番茄钟当前阶段
 * @param onSkipFocusPhase 跳过当前阶段
 *     @param onFocusNameChange 番茄钟专注事项名变更
 * @param focusState 专注（番茄钟）状态，来自独立的 [StudyFocusViewModel]
 * @param onToggleWordOrder 切换词汇排序模式(顺序/乱序)
 * @param onAddManualStudy 手动记录当天背诵单词数
 * @param onSearch 词典搜索
 * @param onClearSearch 清空搜索结果
 */
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
    onSavePlan: (List<com.aveline.ai.mobile.domain.models.PlanItem>) -> Unit = {},
    onPlanStartFocus: (com.aveline.ai.mobile.domain.models.PlanItem) -> Unit = {},
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
    onClearSearch: () -> Unit = {}
) {
    val tabs = StudyTabV2.values()
    val pagerState = rememberPagerState(initialPage = 0) { tabs.size }
    val scope = rememberCoroutineScope()

    // 词汇子页面导航状态在此提升持有(供 StudyVocabBookHost 薄壳转发),
    // 离开词汇 Tab 时由下方监听重置
    var vocabSubScreen by remember { mutableStateOf(VocabSubScreen.DASHBOARD) }

    // 监听 pager 页面变化,通知 ViewModel
    LaunchedEffect(pagerState.currentPage) {
        onTabChange(tabs[pagerState.currentPage])
        // 离开词汇 Tab 时重置子页面,避免返回后停留在词书内
        if (tabs[pagerState.currentPage] != StudyTabV2.VOCAB) {
            vocabSubScreen = VocabSubScreen.DASHBOARD
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        // 正常 Tab 布局始终渲染(作为底层),词汇覆盖层在其之上滑动
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
        ) {
            // 顶部模块标题
            ModuleHeader(
                title = "Study",
                subtitle = "学习与成长"
            ) {
                // 刷新 Daily 数据按钮
                ModuleHeaderActionContainer {
                    androidx.compose.material3.IconButton(onClick = onRefreshDaily) {
                        if (uiState.isLoading) {
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

            // 成功消息(点击消除)
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

            // Tab 内容区域:HorizontalPager 支持左右滑动
            HorizontalPager(
                state = pagerState,
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 16.dp)
            ) { page ->
                val tab = tabs[page]
                // 与 Companion 一致:内层 Box 无 padding,只做容器对齐
                        Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.TopStart
                        ) {
                            when (tab) {
                                StudyTabV2.OVERVIEW -> Column(
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .verticalScroll(rememberScrollState())
                                        .padding(horizontal = 16.dp),
                                    verticalArrangement = Arrangement.spacedBy(16.dp)
                                ) {
                                    Spacer(modifier = Modifier.height(8.dp))
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
                                    Spacer(modifier = Modifier.height(24.dp))
                                }

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

                                StudyTabV2.PLAN -> StudyPlanTab(
                                    planUiState = planUiState,
                                    onDateSelected = onSelectDate,
                                    onSavePlan = onSavePlan,
                                    onStartFocus = { planItem ->
                                        onPlanStartFocus(planItem)
                                        scope.launch {
                                            pagerState.animateScrollToPage(StudyTabV2.FOCUS.ordinal)
                                        }
                                    }
                                )

                                StudyTabV2.DIARY -> StudyDiaryTab(
                                    dailyUiState = dailyUiState,
                                    onDateSelected = onSelectDate
                                )

                                StudyTabV2.NOTES -> StudyNotesTab(
                                    notesUiState = notesUiState,
                                    onOpenNote = onOpenLibraryNote,
                                    onCloseReader = onCloseLibraryNoteReader
                                )

                                StudyTabV2.VOCAB -> Column(
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .verticalScroll(rememberScrollState())
                                        .padding(horizontal = 16.dp),
                                    verticalArrangement = Arrangement.spacedBy(16.dp)
                                ) {
                                    Spacer(modifier = Modifier.height(8.dp))
                                    StudyVocabTab(
                                        uiState = vocabUiState,
                                        onStartReview = onStartReview,
                                        onStartNewWords = onStartNewWords,
                                        onToggleOrder = onToggleWordOrder,
                                        onAddManualStudy = onAddManualStudy,
                                        onOpenBooks = {
                                            onOpenBooks()
                                            vocabSubScreen = VocabSubScreen.BOOK_LIST
                                        },
                                        onSearch = onSearch,
                                        onClearSearch = onClearSearch
                                    )
                                    Spacer(modifier = Modifier.height(24.dp))
                                }
                            }
                        }
                    }
                }

            // 词汇子页面 / 复习 / 会话总结:整页进入(从右滑入)/退出(向右滑出)动画
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
