package com.aveline.ai.mobile.presentation.study

import android.content.Context
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * 未完成词汇会话的最小快照。
 *
 * 长期复习进度仍由后端 FSRS 与每日错词文件负责；这里只保存本轮尚未走完的
 * 卡片队列、当前位置和 Again 重排次数，用于 App 被杀进程后的断点恢复。
 */
@Serializable
data class VocabSessionSnapshot(
    val version: Int = CURRENT_VERSION,
    val learnWords: List<DailyWord>,
    val currentCardIndex: Int,
    val isNewWordsMode: Boolean,
    val redoCounts: Map<String, Int>,
    val reviewResults: List<ReviewResultItem>
) {
    fun isValid(): Boolean =
        version == CURRENT_VERSION &&
            learnWords.isNotEmpty() &&
            currentCardIndex in learnWords.indices &&
            reviewResults.isNotEmpty()

    companion object {
        const val CURRENT_VERSION = 1
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
        val snapshot = VocabSessionSnapshot(
            learnWords = state.learnWords,
            currentCardIndex = state.currentCardIndex,
            isNewWordsMode = state.isNewWordsMode,
            redoCounts = state.redoCounts,
            reviewResults = state.reviewResults
        )
        if (!snapshot.isValid()) return

        preferences.edit()
            .putString(KEY_SNAPSHOT, json.encodeToString(VocabSessionSnapshot.serializer(), snapshot))
            .apply()
    }

    fun restore(): VocabSessionSnapshot? {
        val raw = preferences.getString(KEY_SNAPSHOT, null) ?: return null
        return runCatching {
            json.decodeFromString(VocabSessionSnapshot.serializer(), raw)
        }.getOrNull()?.takeIf { it.isValid() }
    }

    fun clear() {
        preferences.edit().remove(KEY_SNAPSHOT).apply()
    }

    companion object {
        private const val PREFERENCES_NAME = "study_vocab_session"
        private const val KEY_SNAPSHOT = "unfinished_session_v1"
    }
}
