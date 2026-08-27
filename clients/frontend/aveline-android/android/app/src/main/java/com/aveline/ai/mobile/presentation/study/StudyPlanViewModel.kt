package com.aveline.ai.mobile.presentation.study

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.PlanMarkdownCodec
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.domain.repository.StudyRepository
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
 * 计划（plan.md）域 ViewModel。
 *
 * 从 [StudyViewModel]/[StudyDailyViewModel] 中拆分出来,独立管理每日学习计划的
 * 加载与持久化。Markdown 编解码逻辑委托给领域层 [PlanMarkdownCodec]
 * （parse 与 serialize 合二为一,与后端 plan.md 格式 round-trip 兼容）。
 *
 * @property studyRepository 学习仓库（用于按日期读取 plan 文本、写回 plan.md）
 */
@HiltViewModel
class StudyPlanViewModel @Inject constructor(
    private val studyRepository: StudyRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        StudyPlanUiState(
            selectedDate = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
        )
    )
    val uiState: StateFlow<StudyPlanUiState> = _uiState.asStateFlow()

    /**
     * 加载指定日期的计划：拉取当日内容并解析 plan 文本。
     *
     * @param date 日期字符串,格式 yyyy-MM-dd
     */
    fun loadPlan(date: String) {
        _uiState.update { it.copy(selectedDate = date, isLoading = true, error = null) }
        viewModelScope.launch {
            studyRepository.getDateContent(date)
                .onSuccess { content ->
                    _uiState.update {
                        it.copy(
                            planItems = PlanMarkdownCodec.parse(content.plan),
                            isLoading = false
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

    /**
     * 将编辑后的计划项列表写回后端 plan.md,成功后重新加载以与后端保持一致。
     *
     * @param date 日期字符串,格式 yyyy-MM-dd
     * @param items 编辑后的完整计划项列表
     */
    fun savePlan(date: String, items: List<PlanItem>) {
        _uiState.update { it.copy(isSaving = true, error = null) }
        viewModelScope.launch {
            val planText = PlanMarkdownCodec.serialize(items)
            studyRepository.updatePlan(date, planText)
                .onSuccess {
                    _uiState.update { it.copy(planItems = items, isSaving = false) }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isSaving = false, error = e.message ?: "保存计划失败")
                    }
                }
        }
    }

    /** 清除错误信息 */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
}

/**
 * 计划域 UI 状态。
 *
 * @property selectedDate 当前选中的日期(yyyy-MM-dd)
 * @property planItems 解析后的计划项列表
 * @property isLoading 是否加载中
 * @property isSaving 是否保存中
 * @property error 错误信息
 */
data class StudyPlanUiState(
    val selectedDate: String = "",
    val planItems: List<PlanItem> = emptyList(),
    val isLoading: Boolean = false,
    val isSaving: Boolean = false,
    val error: String? = null
)
