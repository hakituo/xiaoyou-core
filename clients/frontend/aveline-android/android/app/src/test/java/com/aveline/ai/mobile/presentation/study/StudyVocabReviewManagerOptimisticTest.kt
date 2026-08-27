package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.repository.StudyRepository
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * StudyVocabReviewManager.submitReview 乐观更新回归测试
 *
 * 验证点：
 * 1. 点 Again/Hard/Good/Easy 后，即使后端响应尚未返回，卡片也必须立即切到下一张并翻回问题面
 *    （修复前：必须等后端 /vocab/review 返回才切卡，导致 1~2 秒卡顿）
 * 2. Again(quality<=1) 仍按 Anki 语义在本轮内把当前词追加到队尾重排（重排逻辑不受网络影响）
 * 3. 最后一张卡提交后正常触发结束会话
 * 4. 后台同步仍以相同 word/quality 提交后端，仅用响应刷新会话统计（算法不受影响）
 */
class StudyVocabReviewManagerOptimisticTest {

    private fun word(name: String) = DailyWord(
        word = name,
        translations = listOf(WordTranslation(type = "n.", translation = "释义 $name")),
        phrases = null,
        sentences = null,
        us = null,
        uk = null,
        status = "review",
        dueTime = null
    )

    private fun sessionStatsJson(streak: Int = 2): JsonObject = buildJsonObject {
        put(
            "data", buildJsonObject {
                put(
                    "session_stats", buildJsonObject {
                        put("active", true)
                        put("duration", 12)
                        put("words_reviewed", 3)
                        put("correct_count", 2)
                        put("accuracy", 0.67)
                        put("streak", streak)
                    }
                )
            }
        )
    }

    private fun manager(
        repo: StudyRepository,
        learnWords: List<DailyWord>,
        currentCardIndex: Int = 0,
        showAnswer: Boolean = true
    ): Pair<StudyVocabReviewManager, MutableStateFlow<VocabUiState>> {
        val uiState = MutableStateFlow(StudyUiState())
        val vocabState = MutableStateFlow(
            VocabUiState(
                learnWords = learnWords,
                currentCardIndex = currentCardIndex,
                showAnswer = showAnswer,
                isReviewMode = true
            )
        )
        val m = StudyVocabReviewManager(
            CoroutineScope(UnconfinedTestDispatcher()), uiState, vocabState, repo
        )
        return m to vocabState
    }

    @Test
    fun `后端未响应时卡片已立即切到下一张并翻回问题面`() {
        val repo = mockk<StudyRepository>()
        // 后端请求挂起（模拟 1~2s 网络延迟），用于验证切卡不依赖响应
        val gate = CompletableDeferred<Unit>()
        coEvery { repo.submitReview(any(), any()) } coAnswers {
            gate.await()
            Result.success(sessionStatsJson())
        }
        val (m, vocabState) = manager(repo, listOf(word("apple"), word("banana")))

        m.submitReview(3)

        // 核心断言：后端未返回，索引已前进、翻回问题面、本轮结果已记录
        assertEquals(1, vocabState.value.currentCardIndex)
        assertFalse(vocabState.value.showAnswer)
        assertEquals(1, vocabState.value.reviewResults.size)
        assertTrue(vocabState.value.reviewResults[0].known)

        // 放行后端响应，仅刷新会话统计
        gate.complete(Unit)
        assertEquals(2, vocabState.value.sessionStats?.streak)
        coVerify { repo.submitReview("apple", 3) }
    }

    @Test
    fun `Again-当前词追加队尾且记录重排次数`() {
        val repo = mockk<StudyRepository>()
        coEvery { repo.submitReview(any(), any()) } returns Result.success(sessionStatsJson())
        val (m, vocabState) = manager(repo, listOf(word("apple"), word("banana")))

        m.submitReview(1)

        assertEquals(1, vocabState.value.currentCardIndex)
        assertEquals(3, vocabState.value.learnWords.size)
        assertEquals("apple", vocabState.value.learnWords[2].word)
        assertEquals(1, vocabState.value.redoCounts["apple"])
        assertFalse(vocabState.value.reviewResults[0].known)
        coVerify { repo.submitReview("apple", 1) }
    }

    @Test
    fun `Good-不会重排直接切卡`() {
        val repo = mockk<StudyRepository>()
        coEvery { repo.submitReview(any(), any()) } returns Result.success(sessionStatsJson())
        val (m, vocabState) = manager(repo, listOf(word("apple"), word("banana")))

        m.submitReview(3)

        assertEquals(1, vocabState.value.currentCardIndex)
        assertEquals(2, vocabState.value.learnWords.size)
        assertTrue(vocabState.value.redoCounts.isEmpty())
        coVerify { repo.submitReview("apple", 3) }
    }

    @Test
    fun `最后一张卡-正常触发结束会话`() {
        val repo = mockk<StudyRepository>()
        coEvery { repo.submitReview(any(), any()) } returns Result.success(sessionStatsJson())
        coEvery { repo.endReviewSession() } returns Result.success(
            buildJsonObject { put("data", buildJsonObject { put("ok", true) }) }
        )
        // finishSession 成功后 manager 会刷新词汇列表，需要桩掉
        coEvery { repo.getDailyVocabulary(any(), any()) } returns Result.success(
            buildJsonObject { put("data", buildJsonArray { }) }
        )
        val (m, vocabState) = manager(repo, listOf(word("apple")))

        m.submitReview(4)

        coVerify { repo.endReviewSession() }
        assertFalse(vocabState.value.isReviewMode)
        assertNotNull(vocabState.value.sessionSummary)
        coVerify { repo.submitReview("apple", 4) }
    }
}
