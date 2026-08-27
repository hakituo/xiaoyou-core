package com.aveline.ai.mobile.presentation.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.services.AvelineForegroundServiceV2
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
    private val dataSyncManager: DataSyncManager
) : ViewModel() {
    
    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    private val _selectedModel = MutableStateFlow<AIModel?>(null)
    val selectedModel: StateFlow<AIModel?> = _selectedModel.asStateFlow()
    
    init {
        loadSettings()
        loadAvailableModels()
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
                    accessToken = appPreferences.accessToken,
                    selectedVoiceId = appPreferences.selectedVoiceId,
                    responseLength = appPreferences.responseLength,
                    autoTtsEnabled = appPreferences.autoTtsEnabled,
                    residentModeEnabled = appPreferences.residentModeEnabled,
                    appVersion = packageInfo.versionName ?: "1.0.0",
                    buildVersion = buildVersion,
                    selectedModel = _selectedModel.value,
                    tunnelUrl = appPreferences.tunnelUrl,
                    isUsingTunnel = appPreferences.isUsingTunnel
                )
            }
        }
    }

    /**
     * 设置 Tunnel 域名 (用户在设置页输入公网域名)
     */
    fun setTunnelUrl(url: String) {
        // 归一化：去掉协议相对前缀 //，并保证带 https:// 前缀，
        // 避免 tunnelUrl 写入后经由 toggleTunnel 进入 backendUrl，
        // 使 WebSocket URL 变成缺少 scheme 的 //host 形态而被后端 403 拒绝。
        var trimmed = url.trim().removePrefix("//").trimStart('/')
        if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
            trimmed = "https://$trimmed"
        }
        appPreferences.tunnelUrl = trimmed
        _uiState.update { it.copy(tunnelUrl = trimmed) }
    }

    /**
     * 一键切换内网 / Tunnel。
     * - 开启 Tunnel: 备份当前内网地址, backendUrl 切到 tunnelUrl
     * - 关闭 Tunnel: backendUrl 恢复 lanUrlBackup (没有备份则保持不变)
     * 切换后自动重连 WebSocket。
     */
    fun toggleTunnel(enabled: Boolean) {
        val tunnel = appPreferences.tunnelUrl.trim()
        if (enabled && tunnel.isEmpty()) {
            _uiState.update {
                it.copy(
                    connectionTestResult = ConnectionTestResult(
                        success = false,
                        message = "请先填写 Tunnel 域名"
                    )
                )
            }
            return
        }

        if (enabled) {
            // 内网 -> Tunnel: 备份当前 backendUrl, 切到 tunnel
            val current = appPreferences.backendUrl
            if (current.isNotEmpty() && current != tunnel) {
                appPreferences.lanUrlBackup = current
            }
            appPreferences.backendUrl = tunnel
        } else {
            // Tunnel -> 内网: 恢复备份
            val backup = appPreferences.lanUrlBackup
            if (backup.isNotEmpty()) {
                appPreferences.backendUrl = backup
            }
        }
        appPreferences.isUsingTunnel = enabled
        // 触发 WebSocket 重连
        webSocketManager.connect(forceReconnect = true)

        _uiState.update {
            it.copy(
                backendUrl = appPreferences.backendUrl,
                isUsingTunnel = enabled,
                connectionTestResult = ConnectionTestResult(
                    success = true,
                    message = if (enabled) "已切换到 Tunnel, 连接更新中" else "已切换到内网, 连接更新中"
                )
            )
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
     * 设置后端 URL
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
     * 保存后端 URL
     */
    fun saveBackendUrl() {
        val url = _uiState.value.backendUrl
        if (validateBackendUrl(url)) {
            appPreferences.backendUrl = url
            webSocketManager.connect(forceReconnect = true)
            _uiState.update { 
                it.copy(
                    showSaveConfirm = true,
                    connectionTestResult = ConnectionTestResult(
                        success = true,
                        message = "已保存，连接将自动更新"
                    )
                )
            }
        }
    }
    
    /**
     * 验证后端 URL
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
