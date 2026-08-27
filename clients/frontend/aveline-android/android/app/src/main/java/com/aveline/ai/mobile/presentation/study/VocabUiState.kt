package com.aveline.ai.mobile.presentation.study

import kotlinx.serialization.Serializable

/**
 * 词汇复习域 UI 状态。
 *
 * 从原 [StudyUiState] 中抽取,由 [StudyVocabReviewManager] 独立维护,
 * 与 [StudyUiState] 共享同一 ViewModel 作用域但状态流分离,职责更清晰。
 *
 * @property dailyWords 每日词汇(Daily Vocabulary)列表
 * @property learnWords 待复习/待学习词汇列表(含完整释义)
 * @property isReviewMode 是否处于复习模式(全屏覆盖)
 * @property currentCardIndex 当前复习卡片索引
 * @property showAnswer 当前卡片是否展示答案
 * @property sessionStats 复习会话统计
 * @property sessionSummary 会话总结(复习完成后展示,null 表示无)
 * @property dictStats 词典统计(暂未使用)
 */
/** 单张卡片的复习结果（用于会话总结的会/不会清单） */
@Serializable
data class ReviewResultItem(
    val word: String,
    /** true=会(Good/Easy)，false=不会(Again/Hard) */
    val known: Boolean,
    val translation: String
)

/** 词典搜索结果项 */
data class DictSearchResult(
    val word: String,
    val translation: String
)

/** 复习总览数据 */
data class ReviewOverview(
    val dueTodayCount: Int = 0,
    val streakDays: Int = 0,
    val learnedWords: Int = 0,
    val dueWords: Int = 0,
    val masteredWords: Int = 0,
    val newToday: Int = 0,
    val reviewToday: Int = 0,
    /** 记忆曲线预测 [{day, retention}] */
    val memoryCurve: List<MemoryCurvePoint> = emptyList()
)

data class MemoryCurvePoint(
    val day: Int,
    val retention: Float
)

/** 高错词项 */
data class MistakeWord(
    val word: String,
    val errorCount: Int,
    val translation: String
)

data class VocabUiState(
    val dailyWords: List<StudyWord> = emptyList(),
    val learnWords: List<DailyWord> = emptyList(),
    val isReviewMode: Boolean = false,
    /** 是否处于背新单词模式（复用复习界面，区分标题与提示文案） */
    val isNewWordsMode: Boolean = false,
    val currentCardIndex: Int = 0,
    val showAnswer: Boolean = false,
    /** 本轮每个词被 Again 重排到队尾的次数（独立计数，不受 reviewResults 去重影响） */
    val redoCounts: Map<String, Int> = emptyMap(),
    val sessionStats: SessionStats? = null,
    /** 本轮复习逐词结果（会/不会），用于结算页清单 */
    val reviewResults: List<ReviewResultItem> = emptyList(),
    val sessionSummary: Any? = null,
    val dictStats: Any? = null,
    /** 新词排序模式: sequential(顺序) / shuffle(乱序) */
    val wordOrder: String = "sequential",
    /** 今日已手动记录的背诵单词总数 */
    val manualStudyToday: Int = 0,
    /** 可用词书文件名列表(来自后端 available_word_files) */
    val vocabBooks: List<String> = emptyList(),
    /** 当前选中的词书文件名 */
    val currentBook: String = "",
    /** 词书内单词列表(查看词书时填充) */
    val bookWords: List<BookWord> = emptyList(),
    /** 词书内单词总数 */
    val bookTotal: Int = 0,
    /** 词典搜索结果 */
    val searchResults: List<DictSearchResult> = emptyList(),
    val isSearching: Boolean = false,
    /** 复习总览 */
    val reviewOverview: ReviewOverview? = null,
    /** 高错词列表 */
    val mistakes: List<MistakeWord> = emptyList()
)

/** 词书内单个单词(用于词书浏览列表) */
data class BookWord(
    val word: String,
    val translation: String
)
