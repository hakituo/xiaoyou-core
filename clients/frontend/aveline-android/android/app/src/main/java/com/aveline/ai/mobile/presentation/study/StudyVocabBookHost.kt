package com.aveline.ai.mobile.presentation.study

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.aveline.ai.mobile.presentation.theme.Background

/**
 * 词汇模块宿主组件。
 *
 * 接管词汇相关的全屏覆盖层与子页面导航:
 * - 复习模式 [VocabReviewSession]
 * - 会话总结 [VocabSessionSummary]
 * - 词书列表 [VocabBookListScreen]
 * - 词书详情 [VocabBookDetailScreen]
 *
 * 子页面状态 [VocabSubScreen] 由 [StudyScreenV2] 提升持有并透传,
 * 本组件只负责渲染、整页切换动画(Slide + Fade)与返回键逐级回退逻辑,
 * 使主屏幕退化为薄壳转发。
 *
 * @param uiState 词汇 UI 状态
 * @param vocabSubScreen 当前词书子页面层级(由主屏提升持有)
 * @param onVocabSubScreenChange 子页面层级变更回调
 * @param onSetShowAnswer 是否显示答案
 * @param onSubmitReview 提交词汇评分
 * @param onSetIsReviewMode 设置复习模式开关
 * @param onSetSessionSummary 设置会话总结(传空字符串清除)
 * @param onSwitchBook 切换到指定词书
 */
@Composable
fun StudyVocabBookHost(
    uiState: VocabUiState,
    vocabSubScreen: VocabSubScreen,
    onVocabSubScreenChange: (VocabSubScreen) -> Unit,
    onSetShowAnswer: (Boolean) -> Unit,
    onSubmitReview: (String) -> Unit,
    onSetIsReviewMode: (Boolean) -> Unit,
    onSetSessionSummary: (String) -> Unit,
    onSwitchBook: (String) -> Unit
) {
    // 当前应展示的页面(单一来源,供 AnimatedContent 做整页切换动画)
    val currentScreen = when {
        uiState.isReviewMode -> VocabScreen.REVIEW
        uiState.sessionSummary != null -> VocabScreen.SUMMARY
        vocabSubScreen == VocabSubScreen.BOOK_DETAIL -> VocabScreen.BOOK_DETAIL
        vocabSubScreen == VocabSubScreen.BOOK_LIST -> VocabScreen.BOOK_LIST
        else -> VocabScreen.NONE
    }

    // 系统返回键:优先在词汇子页面/复习内逐级返回,不直接退出到聊天主页
    BackHandler(
        enabled = currentScreen != VocabScreen.NONE
    ) {
        when {
            uiState.isReviewMode -> onSetIsReviewMode(false)
            uiState.sessionSummary != null -> onSetSessionSummary("")
            vocabSubScreen == VocabSubScreen.BOOK_DETAIL -> onVocabSubScreenChange(VocabSubScreen.BOOK_LIST)
            vocabSubScreen == VocabSubScreen.BOOK_LIST -> onVocabSubScreenChange(VocabSubScreen.DASHBOARD)
            else -> onVocabSubScreenChange(VocabSubScreen.DASHBOARD)
        }
    }

    AnimatedContent(
        targetState = currentScreen,
        transitionSpec = {
            // 根据导航方向决定滑入滑出方向:前进向右进、向左出;回退相反
            val forward = targetState.ordinal > initialState.ordinal
            val (inX, outX) = if (forward) 1 to -1 else -1 to 1
            (slideInHorizontally(tween(300)) { it * inX } + fadeIn(tween(300)))
                .togetherWith(
                    slideOutHorizontally(tween(300)) { it * outX } + fadeOut(tween(300))
                )
        },
        modifier = Modifier
            .fillMaxSize()
            .background(Background)
    ) { screen ->
        when (screen) {
            VocabScreen.REVIEW -> {
                VocabReviewSession(
                    uiState = uiState,
                    onSetShowAnswer = onSetShowAnswer,
                    onSubmitReview = onSubmitReview,
                    onSetIsReviewMode = onSetIsReviewMode
                )
            }
            VocabScreen.SUMMARY -> {
                VocabSessionSummary(
                    sessionStats = uiState.sessionStats,
                    reviewResults = uiState.reviewResults,
                    isNewWordsMode = uiState.isNewWordsMode,
                    onContinue = { onSetSessionSummary("") }
                )
            }
            VocabScreen.BOOK_LIST -> {
                VocabBookListScreen(
                    uiState = uiState,
                    onBack = { onVocabSubScreenChange(VocabSubScreen.DASHBOARD) },
                    onSelectBook = { filename ->
                        onSwitchBook(filename)
                        onVocabSubScreenChange(VocabSubScreen.BOOK_DETAIL)
                    }
                )
            }
            VocabScreen.BOOK_DETAIL -> {
                VocabBookDetailScreen(
                    uiState = uiState,
                    onBack = { onVocabSubScreenChange(VocabSubScreen.BOOK_LIST) }
                )
            }
            VocabScreen.NONE -> { /* 不渲染 */ }
        }
    }
}

/** 宿主内部页面枚举(顺序决定整页切换的滑入滑出方向) */
private enum class VocabScreen {
    NONE,        // 未进入词汇模块
    BOOK_LIST,  // 词书列表
    BOOK_DETAIL,// 词书详情
    REVIEW,     // 复习模式
    SUMMARY     // 会话总结
}
