package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.repository.StudyRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.util.LinkedHashMap

/**
 * 复习结果按单词去重：同一单词多次提交（如 Again 重排）只保留最后一次结果，
 * 并保持首次出现顺序。用于结算页「会/不会」清单与正确率统计，避免重复计数。
 */
private fun dedupeResults(list: List<ReviewResultItem>): List<ReviewResultItem> {
    val map = LinkedHashMap<String, ReviewResultItem>()
    for (item in list) map[item.word.lowercase()] = item
    return map.values.toList()
}

/** 解析普通释义或扩展释义，缺少新字段时兼容旧词书。 */
private fun JsonObject.parseTranslations(key: String): List<WordTranslation> {
    return this[key]
        ?.jsonArray
        ?.map { element ->
            val translation = element.jsonObject
            WordTranslation(
                type = translation.string("type"),
                translation = translation.string("translation"),
                primary = translation.boolean("primary") ?: false,
                domains = translation["domains"]
                    ?.jsonArray
                    ?.mapNotNull { it.jsonPrimitive.contentOrNull }
                    .orEmpty()
            )
        }
        .orEmpty()
}

/**
 * 词汇复习会话管理器
 *
 * 从 StudyViewModel 中提取的词汇复习相关逻辑，负责：
 * - 加载待复习的词汇列表（Learn Words）
 * - 开始/提交/结束一次复习会话
 * - 维护复习卡片索引、是否展示答案、会话统计等 UI 状态
 *
 * 词汇复习专用状态写入独立的 [VocabUiState] 流（由 ViewModel 持有并暴露），
 * 通用加载/错误状态仍写入共享的 [StudyUiState] 流。
 *
 * @property scope 协程作用域，通常为 ViewModel 的 viewModelScope
 * @property uiState 通用可变状态流（仅用于 isLoading / error 等共享字段）
 * @property vocabState 词汇复习专用可变状态流
 * @property studyRepository 学习仓库，负责远端数据访问
 */
class StudyVocabReviewManager(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<StudyUiState>,
    private val vocabState: MutableStateFlow<VocabUiState>,
    private val studyRepository: StudyRepository,
    private val sessionStore: StudyVocabSessionStore? = null
) {

    /**
     * 冷启动恢复未完成会话，但不自动打开全屏复习界面。
     * 用户再次点击对应入口后，由 startReview/startNewWordsSession 从断点继续。
     */
    fun restoreUnfinishedSession(): Boolean {
        val snapshot = sessionStore?.restore() ?: return false
        vocabState.update {
            it.copy(
                learnWords = snapshot.learnWords,
                isReviewMode = false,
                isNewWordsMode = snapshot.isNewWordsMode,
                currentCardIndex = snapshot.currentCardIndex,
                showAnswer = false,
                redoCounts = snapshot.redoCounts,
                reviewResults = snapshot.reviewResults,
                sessionSummary = null
            )
        }
        return true
    }

    private fun persistUnfinishedSession() {
        sessionStore?.save(vocabState.value)
    }

    /**
     * 加载待学习的词汇列表（含翻译、短语、例句、发音等完整信息）
     *
     * 拉取成功后写入 [VocabUiState.learnWords]；失败时写入错误信息。
     */
    fun loadLearnWords(order: String = "sequential") {
        scope.launch {
            uiState.update { it.copy(isLoading = true, error = null) }
            studyRepository.getDailyVocabulary(0, order).onSuccess { response ->
                val words = parseDailyWords(response)
                uiState.update { it.copy(isLoading = false) }
                vocabState.update { it.copy(learnWords = words) }
            }.onFailure { error ->
                uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "加载 Learn Words 失败"
                    )
                }
            }
        }
    }

    /**
     * 加载从未学过的新词列表（从当前词书取不在 progress 里的词）。
     *
     * 拉取成功后写入 [VocabUiState.learnWords] 并标记 [VocabUiState.isNewWordsMode]。
     */
    fun loadNewWords(count: Int = 20, order: String = "sequential") {
        scope.launch {
            uiState.update { it.copy(isLoading = true, error = null) }
            studyRepository.getNewWords(count, order).onSuccess { response ->
                val words = parseDailyWords(response)
                uiState.update { it.copy(isLoading = false) }
                vocabState.update { it.copy(learnWords = words, isNewWordsMode = true) }
            }.onFailure { error ->
                uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "加载新词失败"
                    )
                }
            }
        }
    }

    /** 解析后端返回的词汇列表为 DailyWord 列表（复用于复习词和新词） */
    private fun parseDailyWords(response: JsonObject): List<DailyWord> {
        return response["data"]?.jsonArray.orEmptyArray().map { item ->
            val obj = item.jsonObject
            val translations = obj.parseTranslations("translations")
            val extendedTranslations = obj.parseTranslations("extended_translations")
            val phrases = obj["phrases"]
                ?.jsonArray
                ?.map { p ->
                    val pObj = p.jsonObject
                    WordPhrase(
                        phrase = pObj.string("phrase"),
                        translation = pObj.string("translation")
                    )
                }
            val sentences = obj["sentences"]
                ?.jsonArray
                ?.map { s ->
                    val sObj = s.jsonObject
                    WordSentence(
                        sentence = sObj.string("sentence"),
                        translation = sObj.string("translation")
                    )
                }
            DailyWord(
                word = obj.string("word"),
                translations = translations,
                extendedTranslations = extendedTranslations,
                phrases = phrases,
                sentences = sentences,
                us = obj["us"]?.jsonPrimitive?.contentOrNull,
                uk = obj["uk"]?.jsonPrimitive?.contentOrNull,
                status = obj.string("status"),
                dueTime = obj.long("due_time")
            )
        }
    }

    /**
     * 开始一次词汇复习会话
     *
     * 调用远端开启会话接口，成功后进入复习模式并重置卡片索引；
     * 若当前没有可复习的词汇，会自动触发 [loadLearnWords]。
     */
    fun startReview() {
        scope.launch {
            // 续背：内存里还有未完成的复习会话（非新词模式、有卡片、未背完、至少提交过一次）
            // 则从断点 currentCardIndex 继续，不重置索引、不重新拉取、不调后端开新会话。
            // 解决「中途退出再进从头重背」的体感问题。
            val current = vocabState.value
            val hasUnfinished = current.learnWords.isNotEmpty() &&
                current.currentCardIndex < current.learnWords.size &&
                !current.isNewWordsMode &&
                current.sessionSummary == null &&
                current.reviewResults.isNotEmpty()

            if (hasUnfinished) {
                vocabState.update {
                    it.copy(
                        isReviewMode = true,
                        showAnswer = false
                    )
                }
                return@launch
            }

            // 正常开新会话：首次进入 或 上轮已背完（sessionSummary 非空 / 索引到底）
            studyRepository.startReviewSession().onSuccess {
                sessionStore?.clear()
                vocabState.update {
                    it.copy(
                        isReviewMode = true,
                        isNewWordsMode = false,
                        currentCardIndex = 0,
                        showAnswer = false,
                        sessionSummary = null,
                        reviewResults = emptyList(),
                        redoCounts = emptyMap()
                    )
                }
                if (vocabState.value.learnWords.isEmpty()) {
                    loadLearnWords()
                }
            }.onFailure { error ->
                uiState.update {
                    it.copy(error = error.message ?: "开始复习失败")
                }
            }
        }
    }

    /**
     * 开始背新单词会话。
     *
     * 先加载新词，然后进入复习模式（复用翻卡 UI）。
     * 新词提交评分时 [submitReview] 会自动通过 FSRS 初始化进度。
     */
    fun startNewWordsSession(count: Int = 20) {
        scope.launch {
            val current = vocabState.value
            val hasUnfinished = current.learnWords.isNotEmpty() &&
                current.currentCardIndex < current.learnWords.size &&
                current.isNewWordsMode &&
                current.sessionSummary == null &&
                current.reviewResults.isNotEmpty()
            if (hasUnfinished) {
                vocabState.update {
                    it.copy(
                        isReviewMode = true,
                        showAnswer = false
                    )
                }
                return@launch
            }

            uiState.update { it.copy(isLoading = true, error = null) }
            studyRepository.getNewWords(count, _currentOrder()).onSuccess { response ->
                val words = parseDailyWords(response)
                if (words.isEmpty()) {
                    uiState.update {
                        it.copy(isLoading = false, error = "当前词书没有新词了")
                    }
                    return@onSuccess
                }
                uiState.update { it.copy(isLoading = false) }
                sessionStore?.clear()
                vocabState.update {
                    it.copy(
                        learnWords = words,
                        isNewWordsMode = true,
                        isReviewMode = true,
                        currentCardIndex = 0,
                        showAnswer = false,
                        sessionSummary = null,
                        reviewResults = emptyList(),
                        redoCounts = emptyMap()
                    )
                }
            }.onFailure { error ->
                uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "加载新词失败"
                    )
                }
            }
        }
    }

    /** 获取当前排序模式（复习/新词共用） */
    private fun _currentOrder(): String = vocabState.value.wordOrder

    /**
     * 提交当前卡片的复习质量评分
     *
     * @param quality 复习质量评分（通常 0-5）
     *
     * 乐观更新：立即在本地推进到下一张卡片（若已是最后一张则调用 [finishSession] 结束会话），
     * 评分再在后台异步同步到后端，响应仅用于刷新会话统计（streak 等）。
     */
    fun submitReview(quality: Int) {
        // 乐观更新：先同步推进本地卡片状态（立即切卡、翻回问题面），
        // 再在后台把评分同步到后端。这样点 Again/Hard/Good/Easy 不再卡顿。
        val vocab = vocabState.value
        val currentIdx = vocab.currentCardIndex
        val currentList = vocab.learnWords
        val currentWord = currentList.getOrNull(currentIdx) ?: return

        // 记录本轮该词的会/不会结果（用于结算页清单）
        val known = quality >= 3
        val firstTranslation = currentWord.translations.firstOrNull()?.translation ?: ""
        val resultItem = ReviewResultItem(
            word = currentWord.word,
            known = known,
            translation = firstTranslation
        )

        // Again(quality<=1)：按 Anki 语义在本轮内重排到队尾当场再背，
        // 避免「点 1m 和 10m 没区别」「复习完又来一遍」的错觉。
        // 每词最多重排 2 次，防止无限 Again 死循环。
        // 注意重排计数用独立的 redoCounts（reviewResults 是按词去重的，
        // 不能用于计数，否则恒 < 2 导致无限重排）。
        val redoCount = vocab.redoCounts[currentWord.word] ?: 0
        val shouldRedo = quality <= 1 && redoCount < 2

        if (shouldRedo) {
            // 把当前词复制一份追加到队尾，索引前进 1（队尾副本稍后再次出现）
            val newList = currentList.toMutableList().apply { add(currentWord) }
            vocabState.update {
                it.copy(
                    learnWords = newList,
                    currentCardIndex = currentIdx + 1,
                    showAnswer = false,
                    reviewResults = dedupeResults(it.reviewResults + resultItem),
                    redoCounts = it.redoCounts + (currentWord.word to (redoCount + 1))
                )
            }
            persistUnfinishedSession()
        } else {
            val nextIndex = currentIdx + 1
            if (nextIndex >= currentList.size) {
                // 进入结算前清空本轮重置的临时列表，保留 reviewResults（去重）
                vocabState.update { it.copy(reviewResults = dedupeResults(it.reviewResults + resultItem)) }
                sessionStore?.clear()
                finishSession()
            } else {
                vocabState.update {
                    it.copy(
                        currentCardIndex = nextIndex,
                        showAnswer = false,
                        reviewResults = dedupeResults(it.reviewResults + resultItem)
                    )
                }
                persistUnfinishedSession()
            }
        }

        // 后台同步后端：评分与之前完全一致，算法（FSRS 排程）不受影响。
        // 响应只用来刷新会话统计（streak 等）；失败时提示但不阻塞流程，
        // 该词会被后端视为未复习，下次继续推送（更保守，不会漏推）。
        scope.launch {
            studyRepository.submitReview(currentWord.word, quality).onSuccess { response ->
                val stats = response["data"]?.jsonObject?.get("session_stats")?.jsonObject
                val sessionStats = stats?.let {
                    SessionStats(
                        active = it.boolean("active") ?: false,
                        duration = it.int("duration") ?: 0,
                        wordsReviewed = it.int("words_reviewed") ?: 0,
                        correctCount = it.int("correct_count") ?: 0,
                        accuracy = it.double("accuracy") ?: 0.0,
                        streak = it.int("streak") ?: 0
                    )
                }
                vocabState.update { it.copy(sessionStats = sessionStats) }
            }.onFailure { error ->
                uiState.update {
                    it.copy(error = error.message ?: "提交复习失败")
                }
            }
        }
    }

    /**
     * 结束当前复习会话
     *
     * 调用远端结束会话接口，成功后写入会话总结并退出复习模式，
     * 同时刷新词汇列表以便展示最新状态。
     */
    fun finishSession() {
        scope.launch {
            studyRepository.endReviewSession().onSuccess { response ->
                sessionStore?.clear()
                vocabState.update {
                    it.copy(
                        sessionSummary = response["data"],
                        isReviewMode = false
                    )
                }
                loadLearnWords()
            }.onFailure { error ->
                sessionStore?.clear()
                vocabState.update { it.copy(isReviewMode = false) }
                uiState.update {
                    it.copy(error = error.message ?: "结束会话失败")
                }
            }
        }
    }

    /** 设置是否展示当前卡片的答案 */
    fun setShowAnswer(show: Boolean) {
        vocabState.update { it.copy(showAnswer = show) }
    }

    /** 设置是否处于复习模式 */
    fun setIsReviewMode(isReview: Boolean) {
        vocabState.update { it.copy(isReviewMode = isReview) }
    }

    /** 设置会话总结数据 */
    fun setSessionSummary(summary: Any?) {
        vocabState.update { it.copy(sessionSummary = summary) }
        if (summary != null) sessionStore?.clear()
    }
}
