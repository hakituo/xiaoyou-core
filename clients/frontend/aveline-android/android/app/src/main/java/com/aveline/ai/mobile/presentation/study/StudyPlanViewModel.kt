package com.aveline.ai.mobile.presentation.study

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.repository.StudyPlanRepository
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.domain.models.StudyPlan
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.inject.Inject

/**
 * 计划域 ViewModel。
 *
 * Android 现在直接读取后端结构化 DailyPlan JSON；plan.md 仅保留为人类可读投影，
 * 不再作为计划页的数据源或计划项定位依据。所有写操作按稳定 plan_item_id 执行。
 */
@HiltViewModel
class StudyPlanViewModel @Inject constructor(
    private val studyPlanRepository: StudyPlanRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        StudyPlanUiState(
            selectedDate = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
        )
    )
    val uiState: StateFlow<StudyPlanUiState> = _uiState.asStateFlow()

    fun loadPlan(date: String) {
        _uiState.update { it.copy(selectedDate = date, isLoading = true, error = null) }
        viewModelScope.launch {
            studyPlanRepository.getPlan(date)
                .onSuccess { plan ->
                    StudyPlanFocusLink.replace(plan.items, plan.date)
                    _uiState.update {
                        it.copy(
                            plan = plan,
                            planItems = plan.items,
                            isLoading = false,
                            error = null
                        )
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isLoading = false, error = e.message ?: "加载计划失败")
                    }
                }
        }
    }

    fun addItem(date: String, time: String, content: String, duration: String) {
        runPlanWrite(date, "新增计划项失败") {
            studyPlanRepository.addItem(
                date = date,
                time = time.trim(),
                title = content.trim(),
                durationMinutes = parseDurationMinutes(duration)
            )
        }
    }

    fun updateItem(
        date: String,
        item: PlanItem,
        time: String,
        content: String,
        duration: String
    ) {
        runPlanWrite(date, "编辑计划项失败") {
            studyPlanRepository.updateItem(
                date = date,
                itemId = item.id,
                time = time.trim(),
                title = content.trim(),
                durationMinutes = parseDurationMinutes(duration)
            )
        }
    }

    fun removeItem(date: String, item: PlanItem) {
        runPlanWrite(date, "删除计划项失败") {
            studyPlanRepository.removeItem(date, item.id)
        }
    }

    private fun runPlanWrite(
        date: String,
        fallbackError: String,
        write: suspend () -> Result<Unit>
    ) {
        _uiState.update { it.copy(isSaving = true, error = null) }
        viewModelScope.launch {
            write().onFailure { e ->
                _uiState.update { it.copy(error = e.message ?: fallbackError) }
            }
            _uiState.update { it.copy(isSaving = false) }
            loadPlan(date)
        }
    }

    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }

    fun toggleItemDone(date: String, item: PlanItem) {
        if (item.id.isBlank()) {
            _uiState.update { it.copy(error = "计划项缺少稳定 ID，请刷新计划后重试") }
            return
        }
        val current = _uiState.value.planItems
        val index = current.indexOfFirst { it.id == item.id }
        if (index < 0) return

        val targetDone = !item.isDone
        val targetStatus = if (targetDone) "completed" else "pending"
        val optimistic = current.toMutableList().also {
            it[index] = item.copy(isDone = targetDone, status = targetStatus)
        }
        _uiState.update {
            it.copy(planItems = optimistic, isSaving = true, error = null)
        }

        viewModelScope.launch {
            studyPlanRepository.updateItemStatus(date, item.id, targetDone)
                .onFailure { e ->
                    _uiState.update { it.copy(error = e.message ?: "更新计划项失败") }
                }
            _uiState.update { it.copy(isSaving = false) }
            loadPlan(date)
        }
    }
}

/** 计划域 UI 状态。 */
data class StudyPlanUiState(
    val selectedDate: String = "",
    val plan: StudyPlan? = null,
    val planItems: List<PlanItem> = emptyList(),
    val isLoading: Boolean = false,
    val isSaving: Boolean = false,
    val error: String? = null
)
