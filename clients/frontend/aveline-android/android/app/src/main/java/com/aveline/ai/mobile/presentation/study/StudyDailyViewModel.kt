package com.aveline.ai.mobile.presentation.study

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.CalendarDay
import com.aveline.ai.mobile.domain.models.DailyContent
import com.aveline.ai.mobile.domain.models.DailyNote
import com.aveline.ai.mobile.domain.models.DiaryEntry
import com.aveline.ai.mobile.domain.models.LatestProgress
import com.aveline.ai.mobile.domain.repository.StudyRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import javax.inject.Inject

/**
 * Study/Daily 文件夹 UI 状态。
 *
 * 持有日历、当日内容、笔记列表、笔记内容、最新进度等数据,
 * 由 [StudyDailyViewModel] 管理,供 Study 模块各 Tab 共享。
 *
 * @property calendarDays 月度日历数据
 * @property currentDateContent 当前选中日期的 diary/plan/progress 内容
 * @property dailyNotes 专题笔记列表
 * @property latestProgress 最新学习进度
 * @property selectedDate 当前选中的日期(yyyy-MM-dd)
 * @property isLoading 是否加载中
 * @property error 错误信息
 */
data class StudyDailyUiState(
    val calendarDays: List<CalendarDay> = emptyList(),
    val currentDateContent: DailyContent? = null,
    val dailyNotes: List<DailyNote> = emptyList(),
    val latestProgress: LatestProgress? = null,
    val diaryEntries: List<DiaryEntry> = emptyList(),
    val selectedDate: String = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date()),
    val isLoading: Boolean = false,
    val error: String? = null
)

/**
 * Study/Daily 文件夹专用 ViewModel。
 *
 * 由于 [StudyViewModel] 已超过 500 行限制,这里独立拆分,
 * 专门处理 Study/Daily 文件夹相关的数据加载:
 * - 月度日历(标记哪些日期有 diary/plan/progress)
 * - 按日期读取 diary/plan/progress 全部内容
 * - 专题笔记列表与内容
 * - 最新学习进度
 *
 * 使用 @HiltViewModel 注入 [StudyRepository],遵循 MVVM + StateFlow 模式。
 */
@HiltViewModel
class StudyDailyViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val studyRepository: StudyRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(StudyDailyUiState())
    val uiState: StateFlow<StudyDailyUiState> = _uiState.asStateFlow()

    init {
        // 初始化时加载当月日历、当前日期内容(计划/日记，内部会触发 loadDiaries)、笔记列表和最新进度
        val now = Calendar.getInstance()
        val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        loadCalendar(now.get(Calendar.YEAR), now.get(Calendar.MONTH) + 1)
        loadDateContent(dateFormat.format(now.time))
        loadNotes()
        loadLatestProgress()
    }

    /**
     * 加载月度日历数据。
     *
     * @param year 年份,如 2026
     * @param month 月份,1-12
     */
    fun loadCalendar(year: Int, month: Int) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            studyRepository.getCalendar(year, month)
                .onSuccess { days ->
                    _uiState.update {
                        it.copy(calendarDays = days, isLoading = false)
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isLoading = false, error = e.message ?: "加载日历失败")
                    }
                }
        }
    }

    /**
     * 按日期加载 diary/plan/progress 全部内容,同时更新 selectedDate。
     * 切换日期时也会触发 [loadDiaries] 刷新当日日记列表。
     *
     * @param date 日期字符串,格式 yyyy-MM-dd
     */
    fun loadDateContent(date: String) {
        viewModelScope.launch {
            _uiState.update {
                it.copy(isLoading = true, error = null, selectedDate = date)
            }
            studyRepository.getDateContent(date)
                .onSuccess { content ->
                    _uiState.update {
                        it.copy(currentDateContent = content, isLoading = false)
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isLoading = false, error = e.message ?: "加载日期内容失败")
                    }
                }
        }
        // 切换日期时同步刷新日记列表(journal 系统)
        loadDiaries(date)
    }

    /**
     * 加载指定日期的日记列表(journal 系统,按作者 source 分组)。
     *
     * @param date 日期字符串,格式 yyyy-MM-dd
     */
    fun loadDiaries(date: String) {
        viewModelScope.launch {
            studyRepository.getDiaries(date)
                .onSuccess { entries ->
                    _uiState.update { it.copy(diaryEntries = entries) }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(error = e.message ?: "加载日记列表失败")
                    }
                }
        }
    }

    /**
     * 加载所有专题笔记列表。
     */
    fun loadNotes() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            studyRepository.getNotes()
                .onSuccess { notes ->
                    _uiState.update {
                        it.copy(dailyNotes = notes, isLoading = false)
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isLoading = false, error = e.message ?: "加载笔记列表失败")
                    }
                }
        }
    }

    /**
     * 将编辑后的计划项列表写回后端 plan.md（委托给 [StudyPlanViewModel]）。
     * 此处保留空实现已无意义,计划逻辑已迁移至 [StudyPlanViewModel]。
     */

    /**
     * 加载最新的学习进度文件内容。
     */
    fun loadLatestProgress() {
        viewModelScope.launch {
            studyRepository.getLatestProgress()
                .onSuccess { progress ->
                    _uiState.update { it.copy(latestProgress = progress) }
                }
                .onFailure { e ->
                    // 最新进度加载失败不阻塞主流程,仅记录错误
                    _uiState.update {
                        it.copy(error = e.message ?: "加载最新进度失败")
                    }
                }
        }
    }

    /**
     * 选择日期,触发 [loadDateContent]。
     *
     * @param date 日期字符串,格式 yyyy-MM-dd
     */
    fun selectDate(date: String) {
        loadDateContent(date)
    }

    /**
     * 刷新全部 Daily 数据(日历 + 最新进度 + 笔记列表)。
     */
    fun refreshAll() {
        val now = Calendar.getInstance()
        loadCalendar(now.get(Calendar.YEAR), now.get(Calendar.MONTH) + 1)
        loadLatestProgress()
        loadNotes()
    }

    /**
     * 清除错误信息。
     */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
}
