package com.aveline.ai.mobile.presentation.study

import android.content.Context
import android.content.SharedPreferences
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.repository.StudyFocusSessionRepository
import com.aveline.ai.mobile.domain.repository.StudyRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject

/** 后端专注会话快照。 */
data class FocusBackendSession(
    val sessionId: String = "",
    val subject: String = "",
    val status: String = "",
    val mode: String = "",
    val planItemId: String? = null,
    val planDate: String? = null,
    val remainingSeconds: Int = 0,
    val plannedMinutes: Int = 0,
    val focusRate: Double = 0.0,
    val nudgeCount: Int = 0,
    val summaryText: String = ""
)

/**
 * 专注（番茄钟）域 ViewModel。
 *
 * FocusSession 是执行真源；从 DailyPlan 启动时把稳定 plan_item_id / plan_date 一并写入后端会话。
 */
@HiltViewModel
class StudyFocusViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val studyRepository: StudyRepository,
    private val focusSessionRepository: StudyFocusSessionRepository
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

    private val _backendSession = MutableStateFlow<FocusBackendSession?>(null)
    val backendSession: StateFlow<FocusBackendSession?> = _backendSession.asStateFlow()

    /** 当前专注事项若来自 typed DailyPlan，则保存其稳定 ID 与所属日期。 */
    private var linkedPlanItemId: String? = null
    private var linkedPlanDate: String? = null

    private var sessionActionInFlight = false
    private var finishingSessionId: String? = null

    private val timerManager = FocusTimerManager(
        scope = viewModelScope,
        state = _uiState,
        onWorkCompleted = { completedState ->
            finishBackendSession(
                note = "番茄钟自然完成 ${completedState.workMinutes} 分钟"
            )
        },
        onPhaseChanged = { from, to, stateAfter ->
            if (from != FocusPhase.WORK && to == FocusPhase.WORK && stateAfter.isRunning) {
                startBackendSession(startLocalTimer = false, pauseLocalOnFailure = true)
            }
        }
    )

    init {
        syncFromBackend(recoverLocalTimer = true)
    }

    fun toggleTimer() {
        if (sessionActionInFlight || finishingSessionId != null) return
        val current = _uiState.value

        if (current.phase != FocusPhase.WORK) {
            timerManager.toggle()
            return
        }

        if (current.isRunning) {
            timerManager.pause()
            pauseBackendSession()
            return
        }

        when (_backendSession.value?.status) {
            "paused" -> resumeBackendSession()
            "active" -> timerManager.toggle()
            else -> startBackendSession(startLocalTimer = true)
        }
    }

    fun resetTimer() {
        if (sessionActionInFlight || finishingSessionId != null) return
        val shouldFinish = _uiState.value.phase == FocusPhase.WORK && _backendSession.value != null
        timerManager.reset()
        if (shouldFinish) {
            finishBackendSession(note = "番茄钟手动重置")
        }
    }

    fun skipPhase() {
        if (sessionActionInFlight || finishingSessionId != null) return
        val from = _uiState.value.phase
        if (from == FocusPhase.WORK && _backendSession.value != null) {
            finishBackendSession(note = "番茄钟手动跳过当前专注阶段")
        }
        timerManager.skipPhase()
    }

    fun setFocusName(name: String) {
        _uiState.update { it.copy(focusName = name) }
        // 计划页点击“开始计时”时会先把 typed 计划加载到 StudyPlanFocusLink，
        // 因而这里能把展示标题恢复为稳定 plan_item_id + plan_date；手动输入无唯一匹配则保持 null。
        val target = StudyPlanFocusLink.resolveUniqueTarget(name)
        linkedPlanItemId = target?.itemId
        linkedPlanDate = target?.planDate
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

    private fun startBackendSession(
        startLocalTimer: Boolean,
        pauseLocalOnFailure: Boolean = false
    ) {
        if (sessionActionInFlight || finishingSessionId != null || _backendSession.value != null) return
        sessionActionInFlight = true

        val snapshot = _uiState.value
        val subject = snapshot.focusName.trim().ifBlank { "专注学习" }
        val plannedMinutes = snapshot.workMinutes.coerceAtLeast(1)
        val planItemId = linkedPlanItemId
        val planDate = linkedPlanDate

        viewModelScope.launch {
            try {
                focusSessionRepository.startFocusSession(
                    subject = subject,
                    plannedMinutes = plannedMinutes,
                    mode = "gentle",
                    planItemId = planItemId,
                    planDate = planDate
                ).onSuccess { obj ->
                    val backend = obj.toBackendSession(
                        fallbackSubject = subject,
                        fallbackPlannedMinutes = plannedMinutes,
                        fallbackStatus = "active"
                    )
                    if (backend.sessionId.isBlank()) {
                        android.util.Log.w("StudyFocusVM", "后端创建 FocusSession 成功但缺少 session_id: $obj")
                        if (pauseLocalOnFailure) timerManager.pause()
                        return@onSuccess
                    }
                    linkedPlanItemId = backend.planItemId ?: planItemId
                    linkedPlanDate = backend.planDate ?: planDate
                    _backendSession.value = backend
                    if (startLocalTimer && !_uiState.value.isRunning) {
                        timerManager.toggle()
                    }
                    android.util.Log.d(
                        "StudyFocusVM",
                        "FocusSession 已开始: id=${backend.sessionId} planItem=${backend.planItemId} planDate=${backend.planDate} subject=$subject minutes=$plannedMinutes"
                    )
                }.onFailure { error ->
                    android.util.Log.w("StudyFocusVM", "创建 FocusSession 失败: ${error.message}")
                    if (pauseLocalOnFailure) timerManager.pause()
                }
            } finally {
                sessionActionInFlight = false
            }
        }
    }

    private fun pauseBackendSession() {
        val current = _backendSession.value ?: return
        if (current.sessionId.isBlank() || current.status != "active" || sessionActionInFlight) return
        sessionActionInFlight = true

        viewModelScope.launch {
            try {
                studyRepository.pauseFocusSession(current.sessionId)
                    .onSuccess { response ->
                        val data = response["data"]?.jsonObject ?: response
                        _backendSession.value = data.toBackendSession(
                            fallbackSubject = current.subject,
                            fallbackPlannedMinutes = current.plannedMinutes,
                            fallbackStatus = "paused"
                        ).copy(
                            sessionId = current.sessionId,
                            status = "paused",
                            planItemId = current.planItemId,
                            planDate = current.planDate
                        )
                    }
                    .onFailure { error ->
                        android.util.Log.w("StudyFocusVM", "暂停 FocusSession 失败: ${error.message}")
                    }
            } finally {
                sessionActionInFlight = false
            }
        }
    }

    private fun resumeBackendSession() {
        val current = _backendSession.value ?: return
        if (sessionActionInFlight || current.sessionId.isBlank()) return
        sessionActionInFlight = true

        viewModelScope.launch {
            try {
                studyRepository.resumeFocusSession(current.sessionId)
                    .onSuccess { response ->
                        val data = response["data"]?.jsonObject ?: response
                        _backendSession.value = data.toBackendSession(
                            fallbackSubject = current.subject,
                            fallbackPlannedMinutes = current.plannedMinutes,
                            fallbackStatus = "active"
                        ).copy(
                            sessionId = current.sessionId,
                            status = "active",
                            planItemId = current.planItemId,
                            planDate = current.planDate
                        )
                        if (!_uiState.value.isRunning) timerManager.toggle()
                    }
                    .onFailure { error ->
                        android.util.Log.w("StudyFocusVM", "恢复 FocusSession 失败: ${error.message}")
                    }
            } finally {
                sessionActionInFlight = false
            }
        }
    }

    private fun finishBackendSession(note: String) {
        val current = _backendSession.value ?: return
        if (current.sessionId.isBlank()) {
            _backendSession.value = null
            return
        }
        if (finishingSessionId == current.sessionId) return
        finishingSessionId = current.sessionId

        viewModelScope.launch {
            try {
                studyRepository.finishFocusSession(
                    id = current.sessionId,
                    note = note
                ).onSuccess { finished ->
                    android.util.Log.d(
                        "StudyFocusVM",
                        "FocusSession 已结束: id=${current.sessionId} planItem=${current.planItemId} summary=${finished["summary_text"]}"
                    )
                    if (_backendSession.value?.sessionId == current.sessionId) {
                        _backendSession.value = null
                    }

                    if (_uiState.value.phase == FocusPhase.WORK && _uiState.value.isRunning) {
                        finishingSessionId = null
                        startBackendSession(startLocalTimer = false, pauseLocalOnFailure = true)
                    }
                }.onFailure { error ->
                    android.util.Log.w("StudyFocusVM", "结束 FocusSession 失败: ${error.message}")
                    if (_uiState.value.phase == FocusPhase.WORK && _uiState.value.isRunning) {
                        timerManager.pause()
                    }
                }
            } finally {
                if (finishingSessionId == current.sessionId) {
                    finishingSessionId = null
                }
            }
        }
    }

    fun syncFromBackend(
        userId: String = "default",
        recoverLocalTimer: Boolean = false
    ) {
        viewModelScope.launch {
            studyRepository.getFocusSessionCurrent(userId)
                .onSuccess { obj ->
                    if (obj.isEmpty()) {
                        _backendSession.value = null
                        return@onSuccess
                    }

                    val backend = obj.toBackendSession(
                        fallbackSubject = _uiState.value.focusName,
                        fallbackPlannedMinutes = _uiState.value.workMinutes,
                        fallbackStatus = "active"
                    )
                    linkedPlanItemId = backend.planItemId
                    linkedPlanDate = backend.planDate
                    _backendSession.value = backend

                    if (recoverLocalTimer && backend.sessionId.isNotBlank()) {
                        val remaining = backend.remainingSeconds.coerceAtLeast(0)
                        _uiState.update { current ->
                            current.copy(
                                phase = FocusPhase.WORK,
                                focusName = backend.subject.ifBlank { current.focusName },
                                workMinutes = backend.plannedMinutes.coerceAtLeast(1),
                                remainingSeconds = remaining,
                                isRunning = false
                            )
                        }
                        prefs.edit()
                            .putString(KEY_NAME, backend.subject)
                            .putInt(KEY_WORK, backend.plannedMinutes.coerceAtLeast(1))
                            .apply()

                        when {
                            backend.status == "active" && remaining > 0 -> timerManager.toggle()
                            backend.status == "active" && remaining <= 0 ->
                                finishBackendSession(note = "恢复会话时检测到计划专注时间已结束")
                        }
                    }
                }
                .onFailure {
                    android.util.Log.w("StudyFocusVM", "拉取后端专注会话失败: ${it.message}")
                }
        }
    }

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

private fun JsonObject.toBackendSession(
    fallbackSubject: String,
    fallbackPlannedMinutes: Int,
    fallbackStatus: String
): FocusBackendSession {
    return FocusBackendSession(
        sessionId = this["session_id"]?.jsonPrimitive?.contentOrNull.orEmpty(),
        subject = this["subject"]?.jsonPrimitive?.contentOrNull ?: fallbackSubject,
        status = this["status"]?.jsonPrimitive?.contentOrNull ?: fallbackStatus,
        mode = this["mode"]?.jsonPrimitive?.contentOrNull ?: "gentle",
        planItemId = this["plan_item_id"]?.jsonPrimitive?.contentOrNull,
        planDate = this["plan_date"]?.jsonPrimitive?.contentOrNull,
        remainingSeconds = this["remaining_seconds"]?.jsonPrimitive?.intOrNull ?: 0,
        plannedMinutes = this["planned_minutes"]?.jsonPrimitive?.intOrNull ?: fallbackPlannedMinutes,
        focusRate = this["focus_rate"]?.jsonPrimitive?.doubleOrNull ?: 0.0,
        nudgeCount = this["nudge_count"]?.jsonPrimitive?.intOrNull ?: 0,
        summaryText = this["summary_text"]?.jsonPrimitive?.contentOrNull.orEmpty()
    )
}
