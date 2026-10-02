package com.aveline.ai.mobile.presentation.wellbeing

import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.provider.Settings
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.remote.dto.AppLimitDto
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.domain.repository.WellbeingRepository
import com.aveline.ai.mobile.services.AvelineAccessibilityService
import com.aveline.ai.mobile.services.wellbeing.AppLimitPolicy
import com.aveline.ai.mobile.services.wellbeing.SessionLimiter
import com.aveline.ai.mobile.utils.SelfPackageGuard
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
 *
 * 限额在本地落地为 [AppLimitPolicy] (每日 + 单次 + 间隔 + 冷却 四元组),
 * 无障碍服务据此实时判定, 15 分钟 Worker 兜底校验。
 */
@HiltViewModel
class WellbeingViewModel @Inject constructor(
    private val wellbeingRepository: WellbeingRepository,
    private val contextRepository: ContextRepository,
    private val sessionLimiter: SessionLimiter,
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
                    // "本次已用"与拦截状态来自本地会话状态机 (SessionLimiter), 后端不知道这些。
                    val displayLimits = limits.map { limit ->
                        val usageMs = localUsage[limit.packageName] ?: limit.usageTodayMs
                        decorate(limit, usageMs)
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
                    decorate(limit, usageMs)
                }.sortedByDescending { it.ratio }
                state.copy(limits = updated, hasUsageStatsPermission = hasUsagePermission)
            }
        }
    }

    /**
     * 把"本地真实用量 + 会话状态机判定"合并进一条限额展示数据。
     *
     * 顺带把间隔/冷却补成生效值 (后端为旧版本时不下发这两个字段)。
     */
    private suspend fun decorate(limit: AppLimitDto, usageMs: Long): AppLimitDto {
        val decision = sessionLimiter.peek(limit.packageName)
        val sessionLimit = limit.effectiveSessionLimitMs()
        return limit.copy(
            usageTodayMs = usageMs,
            ratio = if (limit.limitMs > 0) usageMs.toDouble() / limit.limitMs.toDouble() else 0.0,
            sessionLimitMs = sessionLimit,
            sessionGapMs = limit.sessionGapMs.takeIf { it > 0 } ?: AppLimitPolicy.DEFAULT_SESSION_GAP_MS,
            cooldownMs = if (sessionLimit > 0) {
                limit.cooldownMs.takeIf { it > 0 } ?: AppLimitPolicy.DEFAULT_COOLDOWN_MS
            } else {
                0L
            },
            sessionUsedMs = when (decision) {
                is SessionLimiter.LimitDecision.Allow -> decision.sessionUsedMs
                is SessionLimiter.LimitDecision.Block -> decision.sessionUsedMs
            },
            blockedUntilMs = when (decision) {
                is SessionLimiter.LimitDecision.Block -> decision.blockedUntilMs
                is SessionLimiter.LimitDecision.Allow -> 0L
            },
            blockReason = when (decision) {
                is SessionLimiter.LimitDecision.Block -> decision.reason.name.lowercase()
                is SessionLimiter.LimitDecision.Allow -> ""
            }
        )
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

    /**
     * 把后端限额同步落到本地策略表, 供无障碍服务实时判定与 Worker 兜底。
     *
     * 页面保存/删除后立即生效, 不需要等下一轮 15 分钟同步。
     * 后端没下发间隔/冷却 (旧后端) 时用 [AppLimitPolicy.of] 的默认值补齐。
     */
    private fun cacheLimitsForLocalEnforcement(limits: List<AppLimitDto>) {
        val selfExcluded = limits
            .filter { it.packageName.isNotBlank() && !SelfPackageGuard.isSelf(context, it.packageName) }
            .map { limit ->
                AppLimitPolicy.of(
                    packageName = limit.packageName,
                    dailyLimitMs = limit.limitMs,
                    sessionLimitMs = limit.effectiveSessionLimitMs(),
                    sessionGapMs = limit.sessionGapMs,
                    cooldownMs = limit.cooldownMs,
                )
            }
            .filter { !it.isEmpty }
        viewModelScope.launch { sessionLimiter.replacePolicies(selfExcluded) }
    }

    /** 加载已安装应用 (排除系统应用, 便于选择)。 */
    private fun loadInstalledApps() {
        viewModelScope.launch {
            try {
                val apps = withContext(Dispatchers.IO) {
                    val pm = context.packageManager
                    pm.getInstalledApplications(PackageManager.GET_META_DATA)
                        .filter { ai -> (ai.flags and ApplicationInfo.FLAG_SYSTEM) == 0 }
                        // 不给 Aveline 自己设限额: 自身超限触发 force-stop 会撤销无障碍授权。
                        .filter { ai -> !SelfPackageGuard.isSelf(context, ai.packageName) }
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

    /**
     * 保存限额。editing 为 null 表示新增, 否则覆盖原 package。
     *
     * @param dailyLimitMs 每日总额度毫秒
     * @param sessionLimitMs 单次连续使用额度毫秒, 0 = 不限单次
     * @param cooldownMs 单次超限后休息多久毫秒 (0 = 用默认 5 分钟)
     */
    fun saveLimit(
        packageName: String,
        appName: String,
        dailyLimitMs: Long,
        sessionLimitMs: Long = 0,
        cooldownMs: Long = 0
    ) {
        if (packageName.isBlank()) {
            _uiState.update { it.copy(error = "应用包名不能为空") }
            return
        }
        if (dailyLimitMs <= 0 && sessionLimitMs <= 0) {
            _uiState.update { it.copy(error = "每日限额和单次限额至少填一个") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            wellbeingRepository.setAppLimit(
                packageName = packageName.trim(),
                appName = appName.ifBlank { packageName.trim() },
                limitMs = dailyLimitMs,
                sessionLimitMs = sessionLimitMs,
                sessionGapMs = 0,   // 0 = 用后端默认 (离开 2 分钟算作结束)
                cooldownMs = cooldownMs,
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
                    // 本地会话状态一并清掉, 避免"已超限/休息中"的旧状态继续拦截
                    sessionLimiter.reset(packageName)
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
