package com.aveline.ai.mobile.presentation.study

import android.content.Context
import android.content.SharedPreferences
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.repository.StudyRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import javax.inject.Inject

/**
 * 后端专注会话快照（跨端同步，只读展示用）。
 * 字段均为聚合状态，不含任何图像/媒体数据。
 */
data class FocusBackendSession(
    val sessionId: String = "",
    val subject: String = "",
    val status: String = "",          // active / paused / finished
    val mode: String = "",            // gentle / strict
    val remainingSeconds: Int = 0,
    val plannedMinutes: Int = 0,
    val focusRate: Double = 0.0,      // 专注率 %
    val nudgeCount: Int = 0,
    val summaryText: String = ""
)

/**
 * 专注（番茄钟）域 ViewModel。
 *
 * 从 [StudyViewModel] 中拆分出来,独立管理番茄钟状态、计时、配置持久化与后端上报。
 * 计时/阶段推进逻辑委托给 [FocusTimerManager]（纯逻辑、可单测）；
 * 配置（工作时长 / 休息时长 / 长休息时长 / 专注名）持久化到 SharedPreferences，
 * 杀进程后不丢失。
 *
 * @property context ApplicationContext（注入,用于 SharedPreferences）
 * @property studyRepository 学习仓库（用于完成番茄后上报后端学习会话）
 */
@HiltViewModel
class StudyFocusViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val studyRepository: StudyRepository
) : ViewModel() {

    private val prefs: SharedPreferences =
        context.getSharedPreferences("study_focus_config", Context.MODE_PRIVATE)

    private val _uiState = MutableStateFlow(
        StudyFocusState(
            workMinutes = prefs.getInt(KEY_WORK, 25),
            breakMinutes = prefs.getInt(KEY_BREAK, 5),
            longBreakMinutes = prefs.getInt(KEY_LONG_BREAK, 15),
            focusName = prefs.getString(KEY_NAME, "") ?: ""
        )
    )
    val uiState: StateFlow<StudyFocusState> = _uiState.asStateFlow()

    /**
     * 后端当前专注会话的轻量快照（跨端同步用）。
     * 仅保存聚合状态（主题/剩余/状态/专注率），绝不保存任何画面数据。
     * 为 null 表示后端无进行中会话。
     */
    private val _backendSession = MutableStateFlow<FocusBackendSession?>(null)
    val backendSession: StateFlow<FocusBackendSession?> = _backendSession.asStateFlow()

    private val timerManager = FocusTimerManager(
        scope = viewModelScope,
        state = _uiState,
        onWorkCompleted = { completedState -> reportToBackend(completedState) }
    )

    // -------------------------------------------------------------------------
    // UI 操作
    // -------------------------------------------------------------------------

    fun toggleTimer() = timerManager.toggle()
    fun resetTimer() = timerManager.reset()
    fun skipPhase() = timerManager.skipPhase()

    fun setFocusName(name: String) {
        _uiState.update { it.copy(focusName = name) }
        prefs.edit().putString(KEY_NAME, name).apply()
    }

    fun setWorkMinutes(minutes: Int) {
        _uiState.update {
            val newSeconds = if (it.phase == FocusPhase.WORK) minutes * 60 else it.remainingSeconds
            it.copy(workMinutes = minutes, remainingSeconds = newSeconds)
        }
        prefs.edit().putInt(KEY_WORK, minutes).apply()
    }

    fun setBreakMinutes(minutes: Int) {
        _uiState.update {
            val newSeconds = if (it.phase == FocusPhase.BREAK) minutes * 60 else it.remainingSeconds
            it.copy(breakMinutes = minutes, remainingSeconds = newSeconds)
        }
        prefs.edit().putInt(KEY_BREAK, minutes).apply()
    }

    fun setLongBreakMinutes(minutes: Int) {
        _uiState.update {
            val newSeconds = if (it.phase == FocusPhase.LONG_BREAK) minutes * 60 else it.remainingSeconds
            it.copy(longBreakMinutes = minutes, remainingSeconds = newSeconds)
        }
        prefs.edit().putInt(KEY_LONG_BREAK, minutes).apply()
    }

    // -------------------------------------------------------------------------
    // 后端上报（番茄钟 WORK 阶段自然完成）
    // -------------------------------------------------------------------------

    /**
     * 一个工作阶段自然完成后,将本次专注时长写入后端学习会话,
     * 与概览 Tab 的"今日学习"统计联动(subject = 自定义专注名)。
     * 不传 enter_low_disturbance / switch_mode_to_study,避免打断用户当前模式。
     */
    private fun reportToBackend(completedState: StudyFocusState) {
        val subject = completedState.focusName.trim().ifBlank { "专注学习" }
        viewModelScope.launch {
            studyRepository.recordDailyStudy(
                buildJsonObject {
                    put("subject", subject)
                    put("duration_minutes", completedState.workMinutes)
                    put("note", "番茄钟专注 ${completedState.workMinutes} 分钟")
                    put("enter_low_disturbance", false)
                    put("switch_mode_to_study", false)
                }
            ).onSuccess {
                android.util.Log.d("StudyFocusVM", "番茄钟已上报: subject=$subject minutes=${completedState.workMinutes}")
            }.onFailure { e ->
                android.util.Log.w("StudyFocusVM", "番茄钟上报失败: ${e.message}")
            }
        }
    }

    // ==================== 跨端同步：拉取后端当前专注会话 ====================

    /** 从后端拉取当前进行中的专注会话，用于 Android/Web 跨端对齐展示。 */
    fun syncFromBackend(userId: String = "default") {
        viewModelScope.launch {
            studyRepository.getFocusSessionCurrent(userId)
                .onSuccess { obj ->
                    if (obj.isEmpty()) {
                        _backendSession.value = null
                        return@onSuccess
                    }
                    _backendSession.value = FocusBackendSession(
                        sessionId = obj["session_id"]?.toString()?.trim('"') ?: "",
                        subject = obj["subject"]?.toString()?.trim('"') ?: "",
                        status = obj["status"]?.toString()?.trim('"') ?: "",
                        mode = obj["mode"]?.toString()?.trim('"') ?: "",
                        remainingSeconds = (obj["remaining_seconds"] as? Number)?.toInt() ?: 0,
                        plannedMinutes = (obj["planned_minutes"] as? Number)?.toInt() ?: 0,
                        focusRate = (obj["focus_rate"] as? Number)?.toDouble() ?: 0.0,
                        nudgeCount = (obj["nudge_count"] as? Number)?.toInt() ?: 0,
                        summaryText = obj["summary_text"]?.toString()?.trim('"') ?: ""
                    )
                }
                .onFailure {
                    // 网络失败时保留旧值，不阻断本地番茄钟
                    android.util.Log.w("StudyFocusVM", "拉取后端专注会话失败: ${it.message}")
                }
        }
    }

    /** 定时轮询后端会话（由 UI 在专注页可见时调用）。 */
    fun startBackendSync(userId: String = "default") {
        syncFromBackend(userId)
    }

    fun clearBackendSession() {
        _backendSession.value = null
    }

    override fun onCleared() {
        super.onCleared()
        timerManager.clear()
    }

    companion object {
        private const val KEY_WORK = "work_minutes"
        private const val KEY_BREAK = "break_minutes"
        private const val KEY_LONG_BREAK = "long_break_minutes"
        private const val KEY_NAME = "focus_name"
    }
}
