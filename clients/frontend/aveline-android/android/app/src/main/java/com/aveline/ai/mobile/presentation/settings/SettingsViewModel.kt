package com.aveline.ai.mobile.presentation.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.services.AvelineForegroundServiceV2
import com.aveline.ai.mobile.services.endpoint.EndpointResolver
import com.aveline.ai.mobile.services.endpoint.resolver.EndpointChannel
import com.aveline.ai.mobile.services.worker.DataSyncManager
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.domain.models.ResponseLength
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.domain.repository.PluginsRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 设置界面 ViewModel
 * 
 * 管理权限状态和设置选项
 * 
 * Requirements: 17.1, 17.2, 17.3, 17.4, 17.5
 */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val contextRepository: ContextRepository,
    private val pluginsRepository: PluginsRepository,
    private val chatRepository: ChatRepository,
    private val appPreferences: AppPreferences,
    private val apiService: AvelineApiService,
    private val webSocketManager: WebSocketManager,
    private val endpointResolver: EndpointResolver,
    private val dataSyncManager: DataSyncManager
) : ViewModel() {
    
    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    private val _selectedModel = MutableStateFlow<AIModel?>(null)
    val selectedModel: StateFlow<AIModel?> = _selectedModel.asStateFlow()
    
    init {
        loadSettings()
        loadAvailableModels()
        observeActiveEndpoint()
    }

    /**
     * 跟随裁决器展示「当前生效地址 / 通道」。
     *
     * 不能只在 loadSettings 里读一次快照：通道会随网络变化自动切换，
     * 设置页停在屏幕上时也应该实时反映（否则用户看到的是一直没变的旧值）。
     */
    private fun observeActiveEndpoint() {
        viewModelScope.launch {
            endpointResolver.active.collect { endpoint ->
                _uiState.update {
                    it.copy(
                        activeUrl = endpoint.url,
                        activeChannel = channelLabel(endpoint.channel)
                    )
                }
            }
        }
    }

    private fun channelLabel(channel: EndpointChannel): String = when (channel) {
        EndpointChannel.MANUAL -> "手动锁定"
        EndpointChannel.LAN -> "局域网"
        EndpointChannel.VPN -> "组网"
        EndpointChannel.TUNNEL -> "公网"
        EndpointChannel.NONE -> "未确定"
    }
    
    /**
     * 加载设置和权限状态
     */
    private fun loadSettings() {
        viewModelScope.launch {
            val packageInfo: PackageInfo = try {
                context.packageManager.getPackageInfo(context.packageName, 0)
            } catch (e: PackageManager.NameNotFoundException) {
                PackageInfo().apply {
                    versionName = "1.0.0"
                    @Suppress("DEPRECATION")
                    versionCode = 1
                }
            }
            
            // longVersionCode 是 API 28+ 字段, 兼容 Android 8.0/8.1 (API 26/27) 用 versionCode
            val buildVersion = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                packageInfo.longVersionCode.toString()
            } else {
                @Suppress("DEPRECATION")
                packageInfo.versionCode.toString()
            }
            
            _uiState.update { state ->
                state.copy(
                    hasUsageStatsPermission = contextRepository.hasUsageStatsPermission(),
                    hasNotificationPermission = contextRepository.hasNotificationListenerPermission(),
                    isContextSyncEnabled = appPreferences.isContextSyncEnabled,
                    backendUrl = appPreferences.backendUrl,
                    lanUrl = appPreferences.lanUrl,
                    vpnUrl = appPreferences.vpnUrl,
                    tunnelUrl = appPreferences.tunnelUrl,
                    activeUrl = endpointResolver.active.value.url,
                    activeChannel = channelLabel(endpointResolver.active.value.channel),
                    accessToken = appPreferences.accessToken,
                    selectedVoiceId = appPreferences.selectedVoiceId,
                    responseLength = appPreferences.responseLength,
                    autoTtsEnabled = appPreferences.autoTtsEnabled,
                    residentModeEnabled = appPreferences.residentModeEnabled,
                    appVersion = packageInfo.versionName ?: "1.0.0",
                    buildVersion = buildVersion,
                    selectedModel = _selectedModel.value
                )
            }
        }
    }

    /**
     * 设置 Tunnel 域名 (用户在设置页输入公网域名)
     */
    fun setTunnelUrl(url: String) {
        // 与 setLanUrl 对齐：只 trim，不在每次键入时强补 https://。
        // 原实现把空串也补成 "https://"，导致用户删光输入框后前缀立刻回来，永远清不掉。
        // 协议头兜底由消费端负责：WebSocketManager.normalizeWsScheme 补 wss://，
        // NetworkModule.normalizeBackendUrl 补 http://，写入层无需替用户补前缀。
        val trimmed = url.trim()
        appPreferences.tunnelUrl = trimmed
        _uiState.update { it.copy(tunnelUrl = trimmed) }
    }

    /**
     * 设置组网通道地址（Tailscale 等点对点 VPN 的后端入口）。
     *
     * 与 [setTunnelUrl] 并存：两条都是远程通道，出门时组网优先、公网兜底，
     * 不需要用户在两者之间手动切换。留空即停用组网通道（行为回到只有公网域名时）。
     */
    fun setVpnUrl(url: String) {
        val trimmed = url.trim()
        appPreferences.vpnUrl = trimmed
        _uiState.update { it.copy(vpnUrl = trimmed, connectionTestResult = null) }
    }

    /**
     * 设置局域网地址槽位（自动发现会覆盖它，用户手填后同样会被后续发现结果刷新）。
     */
    fun setLanUrl(url: String) {
        val trimmed = url.trim()
        appPreferences.lanUrl = trimmed
        _uiState.update { it.copy(lanUrl = trimmed, connectionTestResult = null) }
    }

    /**
     * 立即重新裁决一次通道（按当前网络类型选：WiFi 先局域网、蜂窝先公网）。
     *
     * 用户手动填完地址后不必等下一次网络变化，点一下就立刻生效。
     */
    fun reprobeEndpoint() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isTestingConnection = true,
                    connectionTestResult = null
                )
            }
            // resolve 返回 null 表示所有候选都不通（此时 active 仍是沿用中的旧地址，
            // 所以不能用「返回地址非空」当成功判据）
            val endpoint = endpointResolver.resolve("设置页手动重探")
            _uiState.update {
                it.copy(
                    isTestingConnection = false,
                    activeUrl = endpointResolver.active.value.url,
                    activeChannel = channelLabel(endpointResolver.active.value.channel),
                    connectionTestResult = if (endpoint != null) {
                        ConnectionTestResult(
                            success = true,
                            message = "已连接: ${channelLabel(endpoint.channel)} ${endpoint.url}"
                        )
                    } else {
                        // 区分「压根没填候选」和「填了但都不通」：两者的处理方式完全不同，
                        // 统一提示「不可达」会让用户以为地址坏了，实际是槽位空着。
                        val hasCandidate = appPreferences.lanUrl.isNotBlank() ||
                            appPreferences.vpnUrl.isNotBlank() ||
                            appPreferences.tunnelUrl.isNotBlank()
                        ConnectionTestResult(
                            success = false,
                            message = if (hasCandidate) {
                                "所有候选地址都不可达，请检查地址、访问令牌与网络"
                            } else {
                                "还没有可用的候选地址，请先填写局域网地址、组网地址或公网域名"
                            }
                        )
                    }
                )
            }
            if (endpoint != null) webSocketManager.connect(forceReconnect = true)
        }
    }

    /**
     * 加载可用模型列表与当前选中模型。
     */
    fun loadAvailableModels() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isLoadingModels = true,
                    modelLoadError = null
                )
            }

            try {
                val models = pluginsRepository.getModels()
                val selected = pluginsRepository.getSelectedModel()

                _selectedModel.value = selected
                _uiState.update {
                    it.copy(
                        availableModels = models,
                        selectedModel = selected,
                        isLoadingModels = false,
                        modelLoadError = null
                    )
                }
            } catch (e: Exception) {
                _selectedModel.value = null
                _uiState.update {
                    it.copy(
                        availableModels = emptyList(),
                        selectedModel = null,
                        isLoadingModels = false,
                        modelLoadError = "模型加载失败: ${e.message ?: "未知错误"}"
                    )
                }
            }
        }
    }
    
    /**
     * 刷新权限状态
     */
    fun refreshPermissions() {
        viewModelScope.launch {
            _uiState.update { state ->
                state.copy(
                    hasUsageStatsPermission = contextRepository.hasUsageStatsPermission(),
                    hasNotificationPermission = contextRepository.hasNotificationListenerPermission()
                )
            }
        }
    }
    
    /**
     * 设置手动锁定的后端地址（留空 = 自动在局域网/公网之间选择）。
     *
     * 非空时 EndpointResolver 不再做任何探测，直接用这个地址 —— 用于「我就想固定走
     * 公网测链路」这类场景。
     */
    fun setBackendUrl(url: String) {
        val trimmedUrl = url.trim()
        _uiState.update { it.copy(backendUrl = trimmedUrl, connectionTestResult = null) }
    }
    
    /**
     * 设置 Access Token
     */
    fun setAccessToken(token: String) {
        val trimmedToken = token.trim()
        appPreferences.accessToken = trimmedToken
        _uiState.update { it.copy(accessToken = trimmedToken) }
    }
    fun testConnection() {
        viewModelScope.launch {
            _uiState.update { it.copy(isTestingConnection = true, connectionTestResult = null) }
            
            try {
                val response = apiService.healthCheck()
                if (response.isSuccessful) {
                    _uiState.update { 
                        it.copy(
                            isTestingConnection = false,
                            connectionTestResult = ConnectionTestResult(
                                success = true,
                                message = "连接成功"
                            )
                        )
                    }
                } else {
                    _uiState.update { 
                        it.copy(
                            isTestingConnection = false,
                            connectionTestResult = ConnectionTestResult(
                                success = false,
                                message = "服务器返回错误: ${response.code()}"
                            )
                        )
                    }
                }
            } catch (e: Exception) {
                _uiState.update { 
                    it.copy(
                        isTestingConnection = false,
                        connectionTestResult = ConnectionTestResult(
                            success = false,
                            message = "连接失败: ${e.message}"
                        )
                    )
                }
            }
        }
    }
    
    /**
     * 保存四个地址槽位，并立即重新裁决一次通道。
     *
     * 保存后直接重探而不是等下一次网络变化：用户刚填完地址，期望立刻看到结果。
     */
    fun saveBackendUrl() {
        val state = _uiState.value
        if (!state.isBackendUrlValid) return

        appPreferences.backendUrl = state.backendUrl.trim()
        appPreferences.lanUrl = state.lanUrl.trim()
        appPreferences.vpnUrl = state.vpnUrl.trim()
        appPreferences.tunnelUrl = state.tunnelUrl.trim()

        _uiState.update { it.copy(showSaveConfirm = true) }
        reprobeEndpoint()
    }
    
    /**
     * 验证后端 URL（单个地址）
     */
    fun validateBackendUrl(url: String): Boolean {
        val trimmed = url.trim()
        if (trimmed.isEmpty()) return false
        
        // 允许 http:// 和 https://
        val urlPattern = Regex("^(https?://).+")
        return urlPattern.matches(trimmed)
    }
    
    /**
     * 设置语音 ID
     */
    fun setVoiceId(voiceId: String) {
        appPreferences.selectedVoiceId = voiceId
        _uiState.update { it.copy(selectedVoiceId = voiceId) }
    }
    
    /**
     * 设置响应长度
     */
    fun setResponseLength(length: ResponseLength) {
        appPreferences.responseLength = length
        _uiState.update { it.copy(responseLength = length) }
    }

    /**
     * 选择模型并持久化。
     */
    fun selectModel(model: AIModel) {
        viewModelScope.launch {
            val result = pluginsRepository.switchModel(model.id)

            result.fold(
                onSuccess = {
                    _selectedModel.value = model
                    _uiState.update {
                        it.copy(
                            selectedModel = model,
                            modelLoadError = null
                        )
                    }
                },
                onFailure = { error ->
                    _uiState.update {
                        it.copy(
                            modelLoadError = "模型切换失败: ${error.message ?: "未知错误"}"
                        )
                    }
                }
            )
        }
    }
    
    /**
     * 切换自动 TTS
     */
    fun toggleAutoTts(enabled: Boolean) {
        appPreferences.autoTtsEnabled = enabled
        _uiState.update { it.copy(autoTtsEnabled = enabled) }
    }
    
    /**
     * 切换常驻模式
     */
    fun toggleResidentMode(enabled: Boolean) {
        appPreferences.residentModeEnabled = enabled
        if (enabled) {
            AvelineForegroundServiceV2.start(context)
            dataSyncManager.startPeriodicSync()
            // 开启常驻模式时,若不在电池优化白名单则引导用户加入(国产 ROM 后台保活必备)
            if (!isIgnoringBatteryOptimizations()) {
                _uiState.update { it.copy(showBatteryOptimizationRequest = true) }
            }
        } else {
            AvelineForegroundServiceV2.stop(context)
            dataSyncManager.stopPeriodicSync()
        }
        _uiState.update { it.copy(residentModeEnabled = enabled) }
    }

    /**
     * 检查应用是否在电池优化白名单中(未被电池优化限制)。
     * Android 6.0 以下无此概念,视为已加入。
     */
    private fun isIgnoringBatteryOptimizations(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        return powerManager.isIgnoringBatteryOptimizations(context.packageName)
    }

    /**
     * 用户确认加入电池优化白名单,跳转系统设置页。
     */
    fun confirmBatteryOptimization() {
        _uiState.update { it.copy(showBatteryOptimizationRequest = false) }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                data = Uri.parse("package:${context.packageName}")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            runCatching { context.startActivity(intent) }
        }
    }

    /**
     * 用户取消加入电池优化白名单,仅关闭对话框。
     */
    fun dismissBatteryOptimization() {
        _uiState.update { it.copy(showBatteryOptimizationRequest = false) }
    }
    
    /**
     * 打开应用使用统计设置
     */
    fun openUsageStatsSettings() {
        contextRepository.openUsageStatsSettings()
    }
    
    /**
     * 打开通知监听设置
     */
    fun openNotificationSettings() {
        contextRepository.openNotificationListenerSettings()
    }
    
    /**
     * 切换上下文同步
     */
    fun toggleContextSync(enabled: Boolean) {
        appPreferences.isContextSyncEnabled = enabled
        _uiState.update { it.copy(isContextSyncEnabled = enabled) }
    }
    
    /**
     * 显示清除确认对话框
     */
    fun showClearHistoryConfirm() {
        _uiState.update { it.copy(showClearConfirm = true) }
    }
    
    /**
     * 隐藏清除确认对话框
     */
    fun hideClearHistoryConfirm() {
        _uiState.update { it.copy(showClearConfirm = false) }
    }
    
    /**
     * 隐藏保存确认
     */
    fun hideSaveConfirm() {
        _uiState.update { it.copy(showSaveConfirm = false) }
    }
    
    /**
     * 清除当前会话的聊天历史。
     * 没有 currentSessionId 时直接报错,避免静默失败。
     */
    fun clearHistory() {
        viewModelScope.launch {
            _uiState.update { it.copy(isClearing = true, clearError = null) }

            val sessionId = appPreferences.currentSessionId
            if (sessionId.isNullOrBlank()) {
                _uiState.update {
                    it.copy(
                        isClearing = false,
                        showClearConfirm = false,
                        clearError = "没有当前会话,无法清除"
                    )
                }
                return@launch
            }

            chatRepository.clearHistory(sessionId).fold(
                onSuccess = {
                    _uiState.update {
                        it.copy(
                            isClearing = false,
                            showClearConfirm = false,
                            clearError = null
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            isClearing = false,
                            showClearConfirm = false,
                            clearError = "清除失败: ${e.message ?: "未知错误"}"
                        )
                    }
                }
            )
        }
    }

    /**
     * 清除已展示的清除历史错误信息
     */
    fun clearClearError() {
        _uiState.update { it.copy(clearError = null) }
    }
    
    /**
     * 清除连接测试结果
     */
    fun clearConnectionTestResult() {
        _uiState.update { it.copy(connectionTestResult = null) }
    }
}

/**
 * 连接测试结果
 */
data class ConnectionTestResult(
    val success: Boolean,
    val message: String
)
