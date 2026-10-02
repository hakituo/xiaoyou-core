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
    /** 手动锁定的后端地址；留空 = 自动在局域网/公网之间选择 */
    val backendUrl: String = "",
    /** 局域网地址槽位（自动发现或手填），在家优先走它 */
    val lanUrl: String = "",
    /** 组网通道槽位（Tailscale 点对点地址），外出时优先于公网域名 */
    val vpnUrl: String = "",
    /** 公网域名槽位（Cloudflare Tunnel），组网不通时的兜底 */
    val tunnelUrl: String = "",
    /** 当前生效地址（裁决结果），只读展示 */
    val activeUrl: String = "",
    /** 当前生效通道的中文名（局域网 / 组网 / 公网 / 手动锁定 / 未确定），只读展示 */
    val activeChannel: String = "",
    val accessToken: String = "",
    val isTestingConnection: Boolean = false,
    val connectionTestResult: ConnectionTestResult? = null,
    val showSaveConfirm: Boolean = false,

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
    /**
     * 地址槽位是否合法：至少填了一个，且填了的都是合法 URL。
     *
     * 四个槽位都可能为空（纯自动发现模式），所以不能要求每个都合法；
     * 但填了就必须合法 —— 留着一条错的地址会让裁决器白等一个超时。
     */
    val isBackendUrlValid: Boolean
        get() {
            val filled = listOf(backendUrl, lanUrl, vpnUrl, tunnelUrl)
                .map { it.trim() }
                .filter { it.isNotEmpty() }
            return filled.isNotEmpty() && filled.none { isInvalidBackendUrl(it) }
        }

    /** 两项权限是否全部授予 */
    val allPermissionsGranted: Boolean
        get() = hasUsageStatsPermission && hasNotificationPermission

    /** 未授予的权限数量 */
    val missingPermissionsCount: Int
        get() = listOf(hasUsageStatsPermission, hasNotificationPermission)
            .count { !it }
}

private val BACKEND_URL_PATTERN = Regex("^(https?://).+")

/**
 * 地址槽位是否「填了但格式不对」，供 UI 标红。
 *
 * 放在顶层而不是 SettingsUiState 里：网络分区（SettingsGeneralSections）拿到的是
 * 三个字符串而不是整个 state，两边必须共用同一套判断，否则会出现「保存按钮可点、
 * 输入框却标红」这种自相矛盾的界面。
 */
internal fun isInvalidBackendUrl(value: String): Boolean {
    val trimmed = value.trim()
    return trimmed.isNotEmpty() && !BACKEND_URL_PATTERN.matches(trimmed)
}
