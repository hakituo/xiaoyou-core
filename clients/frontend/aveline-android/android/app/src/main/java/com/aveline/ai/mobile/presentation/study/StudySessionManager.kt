package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.repository.StudyRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/**
 * 学习会话与记录管理器
 *
 * 从 StudyViewModel 中提取的学习记录、会话管理相关逻辑，负责：
 * - 刷新工作区学习概览（含连续学习天数、今日复习数、历史会话记录）
 * - 写入一条学习记录
 * - 开始/结束一次低打扰学习会话
 *
 * 通过构造函数接收 ViewModel 的协程作用域与状态流，
 * 以便在保持原有行为的同时与 ViewModel 共享同一份 UI 状态。
 *
 * @property scope 协程作用域，通常为 ViewModel 的 viewModelScope
 * @property uiState 可变状态流，与 ViewModel 共享同一实例
 * @property studyRepository 学习仓库，负责远端数据访问
 */
class StudySessionManager(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<StudyUiState>,
    private val studyRepository: StudyRepository
) {

    /**
     * 刷新工作区学习概览
     *
     * 拉取学习面板（标题、摘要、连续天数、今日复习数）以及最近的历史会话记录，
     * 成功后写入 [StudyUiState] 的概览与记录字段；失败时写入错误信息。
     */
    fun refreshWorkspaceStudy() {
        scope.launch {
            // 注意:不要清 successMessage,否则调用方(如 recordStudyProgress)
            // 先设置的 successMessage 会被立即清空,用户永远看不到成功提示
            uiState.update { it.copy(isLoading = true, error = null) }
            studyRepository.getWorkspaceStudyPanel(historyLimit = 20).onSuccess { response ->
                val data = response["data"]?.jsonObject ?: response
                val panel = data["study_panel"]?.jsonObject ?: JsonObject(emptyMap())
                val studyPortrait = data["workspace_snapshot"]
                    ?.jsonObject
                    ?.get("portrait")
                    ?.jsonObject
                    ?.get("study")
                    ?.jsonObject
                val todayMinutes = studyPortrait?.get("total_minutes")?.jsonPrimitive?.intOrNull ?: 0
                val sessions = studyPortrait
                    ?.get("sessions")
                    ?.jsonArray
                    .orEmptyArray()
                    .map { item ->
                        val obj = item.jsonObject
                        StudyRecord(
                            topic = obj.string("topic"),
                            content = obj.string("content"),
                            time = obj.string("time")
                        )
                    }

                uiState.update {
                    it.copy(
                        isLoading = false,
                        overviewTitle = panel.string("title"),
                        overviewSummary = panel.string("summary"),
                        studyStreakDays = panel.int("study_streak_days") ?: 0,
                        reviewedToday = panel.int("reviewed_today") ?: 0,
                        todayStudyMinutes = todayMinutes,
                        studyRecords = sessions
                    )
                }
            }.onFailure { error ->
                uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "加载 Study Records 失败"
                    )
                }
            }
        }
    }

    /**
     * 写入一条学习记录
     *
     * 读取 [StudyUiState.recordTopic] 与 [StudyUiState.recordContent]，
     * 校验非空后调用远端接口保存，成功后清空记录内容并刷新概览。
     */
    fun recordStudyProgress() {
        val topic = uiState.value.recordTopic.trim()
        val content = uiState.value.recordContent.trim()
        if (topic.isBlank() || content.isBlank()) {
            uiState.update { it.copy(error = "请先填写学习主题和记录内容") }
            return
        }
        scope.launch {
            uiState.update { it.copy(isLoading = true, error = null, successMessage = null) }
            studyRepository.recordWorkspaceStudy(
                buildJsonObject {
                    put("topic", topic)
                    put("content", content)
                }
            ).onSuccess {
                uiState.update { state ->
                    state.copy(
                        isLoading = false,
                        successMessage = "学习记录已保存",
                        recordContent = ""
                    )
                }
                refreshWorkspaceStudy()
            }.onFailure { error ->
                uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "写入学习记录失败")
                }
            }
        }
    }

    /**
     * 开始一次低打扰学习会话
     *
     * 读取 [StudyUiState.recordTopic] 作为学习主题，校验非空后调用远端接口，
     * 同时附带学习时长与可选备注，并请求进入低打扰模式与切换到学习模式。
     * 成功后刷新工作区概览。
     */
    fun startStudySession() {
        val topic = uiState.value.recordTopic.trim()
        if (topic.isBlank()) {
            uiState.update { it.copy(error = "请先填写学习主题") }
            return
        }
        scope.launch {
            uiState.update { it.copy(isLoading = true, error = null, successMessage = null) }
            studyRepository.recordDailyStudy(
                buildJsonObject {
                    put("subject", topic)
                    put("duration_minutes", uiState.value.recordDuration)
                    if (uiState.value.recordContent.isNotBlank()) {
                        put("note", uiState.value.recordContent)
                    }
                    put("enter_low_disturbance", true)
                    put("switch_mode_to_study", true)
                }
            ).onSuccess {
                uiState.update {
                    it.copy(isLoading = false, successMessage = "学习会话已开始")
                }
                refreshWorkspaceStudy()
            }.onFailure { error ->
                uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "开始学习会话失败")
                }
            }
        }
    }

    /**
     * 结束当前学习会话
     *
     * 调用远端结束接口，成功后刷新工作区概览。
     */
    fun finishStudySession() {
        scope.launch {
            uiState.update { it.copy(isLoading = true, error = null, successMessage = null) }
            studyRepository.finishDailyStudy().onSuccess {
                uiState.update {
                    it.copy(isLoading = false, successMessage = "学习会话已结束")
                }
                refreshWorkspaceStudy()
            }.onFailure { error ->
                uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "结束学习会话失败")
                }
            }
        }
    }
}
