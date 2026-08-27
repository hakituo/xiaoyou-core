package com.aveline.ai.mobile.presentation.settings

import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.domain.models.ResponseLength

/**
 * 设置界面 UI 状态
 *
 * 包含权限状态、后端配置、模型选择、语音设置等所有设置相关状态。
 * [ConnectionTestResult] 定义在 SettingsViewModel.kt 底部。
 */
data class SettingsUiState(
    // 权限状态
    val hasUsageStatsPermission: Boolean = false,
    val hasNotificationPermission: Boolean = false,

    // 隐私 / 同步
    val isContextSyncEnabled: Boolean = true,
    val residentModeEnabled: Boolean = false,
    /** 开启常驻模式时,若不在电池优化白名单则置 true,UI 弹引导对话框 */
    val showBatteryOptimizationRequest: Boolean = false,

    // 后端配置
    val backendUrl: String = "",
    val accessToken: String = "",
    val isTestingConnection: Boolean = false,
    val connectionTestResult: ConnectionTestResult? = null,
    val showSaveConfirm: Boolean = false,

    // Cloudflare Tunnel 切换
    /** Tunnel 备用域名 (留空表示未配置, UI 隐藏切换开关) */
    val tunnelUrl: String = "",
    /** 当前是否走 Tunnel (true=走公网域名, false=走内网 IP) */
    val isUsingTunnel: Boolean = false,

    // 模型选择
    val availableModels: List<AIModel> = emptyList(),
    val selectedModel: AIModel? = null,
    val isLoadingModels: Boolean = false,
    val modelLoadError: String? = null,

    // 语音 / 响应
    val selectedVoiceId: String = "",
    val responseLength: ResponseLength = ResponseLength.NORMAL,
    val autoTtsEnabled: Boolean = false,

    // 数据 / 版本
    val appVersion: String = "1.0.0",
    val buildVersion: String = "1",
    val showClearConfirm: Boolean = false,
    val isClearing: Boolean = false,
    /** 清除历史失败时的错误信息,非 null 表示需向用户展示 */
    val clearError: String? = null
) {
    /** 后端 URL 是否合法 */
    val isBackendUrlValid: Boolean
        get() = backendUrl.trim().let {
            it.isNotEmpty() && Regex("^(https?://).+").matches(it)
        }

    /** 两项权限是否全部授予 */
    val allPermissionsGranted: Boolean
        get() = hasUsageStatsPermission && hasNotificationPermission

    /** 未授予的权限数量 */
    val missingPermissionsCount: Int
        get() = listOf(hasUsageStatsPermission, hasNotificationPermission)
            .count { !it }
}
