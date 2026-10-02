package com.aveline.ai.mobile.presentation.study

import android.content.Context
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.time.LocalDate

/**
 * 未完成词汇会话的最小快照。
 *
 * 长期复习进度仍由后端 FSRS 与每日错词文件负责；这里只保存本轮尚未走完的
 * 卡片队列、当前位置和 Again 重排次数，用于 App 被杀进程后的断点恢复。
 */
@Serializable
data class VocabSessionSnapshot(
    val version: Int = CURRENT_VERSION,
    /** 快照所属业务日期（yyyy-MM-dd），跨天后不再恢复。 */
    val date: String = "",
    val learnWords: List<DailyWord>,
    val currentCardIndex: Int,
    val isNewWordsMode: Boolean,
    val redoCounts: Map<String, Int>,
    val reviewResults: List<ReviewResultItem>
) {
    fun isValid(today: String): Boolean =
        version == CURRENT_VERSION &&
            date == today &&
            learnWords.isNotEmpty() &&
            currentCardIndex in learnWords.indices &&
            reviewResults.isNotEmpty()

    companion object {
        // v3 使旧版错误的 FSRS 分钟级队列失效；长期评分已经在
        // 后端进度中，不会随本地临时快照失效而丢失。
        // v4 起快照带日期：跨天（date != 今天）不再恢复，避免昨天没背完的
        // 队列被当成今天的断点续背。旧版本快照一律丢弃。
        const val CURRENT_VERSION = 4
    }
}

/** 使用应用私有 SharedPreferences 持久化词汇会话快照。 */
class StudyVocabSessionStore(context: Context) {
    private val preferences =
        context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
    }

    fun save(state: VocabUiState) {
        val today = todayKey()
        val snapshot = VocabSessionSnapshot(
            date = state.sessionDate.ifBlank { today },
            learnWords = state.learnWords,
            currentCardIndex = state.currentCardIndex,
            isNewWordsMode = state.isNewWordsMode,
            redoCounts = state.redoCounts,
            reviewResults = state.reviewResults
        )
        if (!snapshot.isValid(today)) return

        preferences.edit()
            .putString(KEY_SNAPSHOT, json.encodeToString(VocabSessionSnapshot.serializer(), snapshot))
            .apply()
    }

    fun restore(): VocabSessionSnapshot? {
        val raw = preferences.getString(KEY_SNAPSHOT, null) ?: return null
        val today = todayKey()
        return runCatching {
            json.decodeFromString(VocabSessionSnapshot.serializer(), raw)
        }.getOrNull()?.takeIf { it.isValid(today) }
    }

    fun clear() {
        preferences.edit().remove(KEY_SNAPSHOT).apply()
    }

    /** 设备本地时区的日期键（yyyy-MM-dd），与后端业务日期口径一致。 */
    private fun todayKey(): String = LocalDate.now().toString()

    companion object {
        private const val PREFERENCES_NAME = "study_vocab_session"
        private const val KEY_SNAPSHOT = "unfinished_session_v1"
    }
}
