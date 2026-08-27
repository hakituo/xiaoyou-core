package com.aveline.ai.mobile.presentation.wellbeing

import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.provider.Settings
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.dto.AppLimitDto
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.domain.repository.WellbeingRepository
import com.aveline.ai.mobile.services.AvelineAccessibilityService
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import javax.inject.Inject

/**
 * 已安装应用项 (用于"添加限额"时选择应用)。
 */
data class InstalledApp(
    val packageName: String,
    val appName: String
)

/**
 * 数字健康 UI 状态。
 *
 * @property isLoading 是否加载中
 * @property error 错误信息
 * @property successMessage 操作成功提示
 * @property date 当前展示的限额所属日期 (默认今天)
 * @property limits 限额列表 (含今日用量进度, 按超限比例降序)
 * @property installedApps 已安装应用 (用于添加限额时选择)
 * @property showAddDialog 是否显示"添加/编辑限额"对话框
 * @property editingLimit 正在编辑的限额 (null=新增)
 */
data class WellbeingUiState(
    val isLoading: Boolean = false,
    val error: String? = null,
    val successMessage: String? = null,
    val date: String = "",
    val limits: List<AppLimitDto> = emptyList(),
    val installedApps: List<InstalledApp> = emptyList(),
    val showAddDialog: Boolean = false,
    val editingLimit: AppLimitDto? = null,
    val hasUsageStatsPermission: Boolean = false,
    val hasAccessibilityService: Boolean = false
)

/**
 * 数字健康(应用使用时长限额)ViewModel。
 *
 * 负责: 拉取限额列表、拉取已安装应用、设置/移除限额, 并管理对话框状态。
 * 底层通过 [WellbeingRepository] 走后端 REST 接口, 与 nightly / set_app_limit 工具同源。
 */
@HiltViewModel
class WellbeingViewModel @Inject constructor(
    private val wellbeingRepository: WellbeingRepository,
    private val contextRepository: ContextRepository,
    private val appPreferences: AppPreferences,
    @ApplicationContext private val context: Context
) : ViewModel() {

    private val _uiState = MutableStateFlow(WellbeingUiState())
    val uiState: StateFlow<WellbeingUiState> = _uiState.asStateFlow()

    init {
        loadInstalledApps()
        refreshPermissions()
        refresh()
    }

    /** 取"今天"的日期字符串 (YYY-MM-DD), 与 nightly 为当天生成的限额对齐。 */
    private fun todayDate(): String = LocalDate.now().toString()

    /** 刷新限额列表 (拉"今天"的限额, 与后端 digital_wellbeing/limits_{date}.json 对齐)。 */
    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            wellbeingRepository.getAppLimits(todayDate())
                .onSuccess { limits ->
                    // 页面拿到后端限额后立即落到本地，保存/删除不再需要等待下一轮 15 分钟同步才生效。
                    cacheLimitsForLocalEnforcement(limits)
                    val hasUsagePermission = contextRepository.hasUsageStatsPermission()
                    val localUsage = if (hasUsagePermission) {
                        withContext(Dispatchers.IO) {
                            val todayStart = LocalDate.now()
                                .atStartOfDay(java.time.ZoneId.systemDefault())
                                .toInstant()
                                .toEpochMilli()
                            contextRepository.getAppUsageSince(todayStart)
                                .associate { it.packageName to it.usageTimeMs }
                        }
                    } else {
                        emptyMap()
                    }
                    // 后端用量最多有一个同步周期的延迟；界面优先显示手机刚读取的本地用量。
                    val displayLimits = limits.map { limit ->
                        val usageMs = localUsage[limit.packageName] ?: limit.usageTodayMs
                        limit.copy(
                            usageTodayMs = usageMs,
                            ratio = if (limit.limitMs > 0) {
                                usageMs.toDouble() / limit.limitMs.toDouble()
                            } else {
                                0.0
                            }
                        )
                    }.sortedByDescending { it.ratio }
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            limits = displayLimits,
                            date = todayDate(),  // 直接用请求的日期, 不再依赖后端返回
                            hasUsageStatsPermission = hasUsagePermission,
                            hasAccessibilityService = AvelineAccessibilityService.isEnabledInSystem(context)
                        )
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isLoading = false, error = e.message ?: "加载限额失败")
                    }
                }
        }
    }

    /**
     * 仅重新读取本地用量并刷新进度条, 不重新拉取后端限额。
     * 用于页面在前台时定时刷新, 让"今日已用"随时间实时增长, 避免每 15 秒打一次网络。
     */
    fun refreshUsage() {
        val currentLimits = _uiState.value.limits
        if (currentLimits.isEmpty()) return
        viewModelScope.launch {
            val hasUsagePermission = contextRepository.hasUsageStatsPermission()
            val localUsage = if (hasUsagePermission) {
                withContext(Dispatchers.IO) {
                    val todayStart = LocalDate.now()
                        .atStartOfDay(java.time.ZoneId.systemDefault())
                        .toInstant()
                        .toEpochMilli()
                    contextRepository.getAppUsageSince(todayStart)
                        .associate { it.packageName to it.usageTimeMs }
                }
            } else {
                emptyMap()
            }
            _uiState.update { state ->
                val updated = state.limits.map { limit ->
                    val usageMs = localUsage[limit.packageName] ?: limit.usageTodayMs
                    limit.copy(
                        usageTodayMs = usageMs,
                        ratio = if (limit.limitMs > 0) {
                            usageMs.toDouble() / limit.limitMs.toDouble()
                        } else {
                            0.0
                        }
                    )
                }.sortedByDescending { it.ratio }
                state.copy(limits = updated, hasUsageStatsPermission = hasUsagePermission)
            }
        }
    }

    /** 从系统返回页面时重新读取权限，避免状态卡一直显示旧值。 */
    fun refreshPermissions() {
        _uiState.update {
            it.copy(
                hasUsageStatsPermission = contextRepository.hasUsageStatsPermission(),
                hasAccessibilityService = AvelineAccessibilityService.isEnabledInSystem(context)
            )
        }
    }

    fun openUsageStatsSettings() {
        context.startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        })
    }

    fun openAccessibilitySettings() {
        context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        })
    }

    /** 同步每日限额和会话限额；会话额度未变化时保留原生效时刻。 */
    private fun cacheLimitsForLocalEnforcement(limits: List<AppLimitDto>) {
        appPreferences.appUsageLimits = limits
            .filter { it.packageName.isNotBlank() && it.limitMs > 0 }
            .joinToString(",") { "${it.packageName}=${it.limitMs}" }

        val oldCaps = parsePairs(appPreferences.appSessionCaps)
        val oldStarts = parsePairs(appPreferences.sessionCapStarts)
        val newCaps = limits
            .filter { it.packageName.isNotBlank() && it.sessionCapMs > 0 }
            .associate { it.packageName to it.sessionCapMs }
        val now = System.currentTimeMillis()
        appPreferences.appSessionCaps = newCaps.entries
            .joinToString(",") { "${it.key}=${it.value}" }
        appPreferences.sessionCapStarts = newCaps.entries
            .joinToString(",") { (pkg, capMs) ->
                val start = if (oldCaps[pkg] == capMs) oldStarts[pkg] ?: now else now
                "$pkg=$start"
            }
    }

    private fun parsePairs(raw: String): Map<String, Long> = buildMap {
        raw.split(',').forEach { pair ->
            val separator = pair.indexOf('=')
            if (separator <= 0) return@forEach
            val packageName = pair.substring(0, separator).trim()
            val value = pair.substring(separator + 1).trim().toLongOrNull() ?: return@forEach
            if (packageName.isNotBlank() && value > 0) put(packageName, value)
        }
    }

    /** 加载已安装应用 (排除系统应用, 便于选择)。 */
    private fun loadInstalledApps() {
        viewModelScope.launch {
            try {
                val apps = withContext(Dispatchers.IO) {
                    val pm = context.packageManager
                    pm.getInstalledApplications(PackageManager.GET_META_DATA)
                        .filter { ai -> (ai.flags and ApplicationInfo.FLAG_SYSTEM) == 0 }
                        .map { ai ->
                            InstalledApp(
                                packageName = ai.packageName,
                                appName = pm.getApplicationLabel(ai).toString()
                            )
                        }
                        .sortedBy { it.appName.lowercase() }
                }
                _uiState.update { it.copy(installedApps = apps) }
            } catch (e: Exception) {
                _uiState.update { it.copy(installedApps = emptyList()) }
            }
        }
    }

    /** 打开"添加限额"对话框。 */
    fun openAddDialog() {
        _uiState.update { it.copy(showAddDialog = true, editingLimit = null) }
    }

    /** 打开"编辑限额"对话框 (编辑已有项)。 */
    fun openEditDialog(limit: AppLimitDto) {
        _uiState.update { it.copy(showAddDialog = true, editingLimit = limit) }
    }

    /** 关闭对话框。 */
    fun dismissAddDialog() {
        _uiState.update { it.copy(showAddDialog = false, editingLimit = null) }
    }

    /** 保存限额。editing 为 null 表示新增, 否则覆盖原 package。 */
    fun saveLimit(
        packageName: String,
        appName: String,
        limitMs: Long
    ) {
        if (packageName.isBlank()) {
            _uiState.update { it.copy(error = "应用包名不能为空") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            wellbeingRepository.setAppLimit(
                packageName = packageName.trim(),
                appName = appName.ifBlank { packageName.trim() },
                limitMs = limitMs,
                targetDate = todayDate()
            ).onSuccess {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        showAddDialog = false,
                        editingLimit = null,
                        successMessage = "限额已保存"
                    )
                }
                refresh()
            }.onFailure { e ->
                _uiState.update {
                    it.copy(isLoading = false, error = e.message ?: "保存失败")
                }
            }
        }
    }

    /** 移除限额。 */
    fun removeLimit(packageName: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            wellbeingRepository.deleteAppLimit(packageName, targetDate = todayDate())
                .onSuccess {
                    _uiState.update {
                        it.copy(isLoading = false, successMessage = "限额已移除")
                    }
                    refresh()
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isLoading = false, error = e.message ?: "移除失败")
                    }
                }
        }
    }

    /** 清除成功/错误消息。 */
    fun clearMessages() {
        _uiState.update { it.copy(error = null, successMessage = null) }
    }
}
