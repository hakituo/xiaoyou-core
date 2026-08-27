package com.aveline.ai.mobile.presentation

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.domain.models.EmotionType
import com.aveline.ai.mobile.domain.models.Session
import com.aveline.ai.mobile.domain.repository.PluginsRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Main UI 状态
 * 
 * @property sessions 会话列表
 * @property currentSessionId 当前会话 ID
 * @property connectionState WebSocket 连接状态
 * @property isLoading 是否正在加载
 * @property error 错误信息
 */
data class MainUiState(
    val sessions: List<Session> = emptyList(),
    val currentSessionId: String? = null,
    val connectionState: WebSocketManager.ConnectionState = WebSocketManager.ConnectionState.DISCONNECTED,
    val currentEmotion: String = "calm",
    val emotionColors: List<String> = emptyList(),
    val manualEmotion: EmotionType? = null,
    val autoEmotion: Boolean = true,
    val isLoading: Boolean = false,
    val error: String? = null
)

/**
 * Main ViewModel
 * 
 * 管理主界面的状态和会话管理功能。
 * 
 * 功能：
 * - 会话列表管理
 * - 当前会话切换
 * - 会话操作（创建、删除、重命名、置顶）
 * - WebSocket 连接状态监听
 */
@HiltViewModel
class MainViewModel @Inject constructor(
    private val sessionRepository: SessionRepository,
    private val webSocketManager: WebSocketManager,
    private val pluginsRepository: PluginsRepository,
    private val appPreferences: AppPreferences
) : ViewModel() {

    private val _uiState = MutableStateFlow(MainUiState())
    val uiState: StateFlow<MainUiState> = _uiState.asStateFlow()

    init {
        loadSessions()
        observeCurrentSession()
        observeConnectionState()
        observeEmotionState()
        observePluginSettings()
    }
    
    /**
     * 加载会话列表
     */
    private fun loadSessions() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }
            
            val result = sessionRepository.getSessions()
            
            result.fold(
                onSuccess = { sessions ->
                    _uiState.update { 
                        it.copy(
                            sessions = sessions,
                            isLoading = false
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update { 
                        it.copy(
                            error = "加载会话失败: ${e.message}",
                            isLoading = false
                        )
                    }
                }
            )
        }
    }
    
    /**
     * 观察当前会话
     */
    private fun observeCurrentSession() {
        viewModelScope.launch {
            sessionRepository.observeCurrentSession()
                .catch { e ->
                    _uiState.update { it.copy(error = "获取当前会话失败: ${e.message}") }
                }
                .collect { session ->
                    _uiState.update { it.copy(currentSessionId = session?.id) }
                }
        }
    }
    
    /**
     * 观察 WebSocket 连接状态
     */
    private fun observeConnectionState() {
        viewModelScope.launch {
            webSocketManager.connectionState.collect { state ->
                _uiState.update { it.copy(connectionState = state) }
            }
        }
    }

    private fun observeEmotionState() {
        viewModelScope.launch {
            webSocketManager.messages.collect { message ->
                when (message) {
                    is WebSocketMessage.EmotionUpdate -> {
                        _uiState.update {
                            it.copy(
                                currentEmotion = message.primary.ifBlank { it.currentEmotion },
                                emotionColors = message.colors.filter { color -> color.isNotBlank() }
                            )
                        }
                    }

                    is WebSocketMessage.TextMessage -> {
                        message.emotion?.takeIf { it.isNotBlank() }?.let { emotion ->
                            _uiState.update { it.copy(currentEmotion = emotion) }
                        }
                    }

                    is WebSocketMessage.ConnectionEstablished -> {
                        Log.d("MainViewModel", "Connection established: heartbeat=${message.heartbeatInterval}s, reconnect=${message.reconnectSupported}")
                    }

                    is WebSocketMessage.ReconnectSync -> {
                        message.currentModel?.let { model ->
                            Log.d("MainViewModel", "Reconnect sync: currentModel=$model")
                        }
                    }

                    else -> Unit
                }
            }
        }
    }

    /**
     * 观察插件设置(手动情绪 / 自动情绪)
     *
     * 手动情绪关闭时用 WebSocket 推送,开启手动情绪后用用户选择的颜色。
     */
    private fun observePluginSettings() {
        viewModelScope.launch {
            // 先加载一次设置,触发 flow 初始发射(replay=1 只在有人发射过后才有值)
            runCatching { pluginsRepository.getSettings() }
            pluginsRepository.observeSettings()
                .catch { e ->
                    Log.w("MainViewModel", "observe plugin settings failed: ${e.message}")
                }
                .collect { settings ->
                    _uiState.update {
                        it.copy(
                            manualEmotion = settings.manualEmotion,
                            autoEmotion = settings.autoEmotion
                        )
                    }
                }
        }
    }
    
    /**
     * 重连 WebSocket (如 App 从后台恢复时)
     * Sends a reconnect message to sync server state.
     */
    fun reconnect() {
        webSocketManager.connect(forceReconnect = true)
    }

    /**
     * 切换会话
     *
     * 修复 P0-30:
     * 1. 原实现调用 getSessions() 做网络请求只为校验 sessionId 是否存在,冗余且慢;
     *    改为用本地已加载的 sessions 列表校验。
     * 2. 原实现只更新 _uiState,未持久化到 appPreferences.currentSessionId,
     *    进程重建后会恢复到旧会话;现在同步写入 appPreferences。
     */
    fun switchSession(sessionId: String) {
        // 用本地已加载的 sessions 列表校验,避免冗余网络请求
        val exists = _uiState.value.sessions.any { it.id == sessionId }
        if (!exists) return
        // 持久化 + 更新 UI 状态
        appPreferences.currentSessionId = sessionId
        _uiState.update { it.copy(currentSessionId = sessionId) }
    }
    
    /**
     * 创建新会话
     */
    fun createSession(title: String = "新对话") {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }
            
            val result = sessionRepository.createSession(title)
            
            result.fold(
                onSuccess = { session ->
                    // 刷新会话列表
                    loadSessions()
                    // 切换到新会话
                    _uiState.update { it.copy(currentSessionId = session.id) }
                },
                onFailure = { e ->
                    _uiState.update { 
                        it.copy(
                            error = "创建会话失败: ${e.message}",
                            isLoading = false
                        )
                    }
                }
            )
        }
    }
    
    /**
     * 删除会话
     */
    fun deleteSession(sessionId: String) {
        viewModelScope.launch {
            val result = sessionRepository.deleteSession(sessionId)
            
            result.fold(
                onSuccess = {
                    // 刷新会话列表
                    loadSessions()
                    
                    // 如果删除的是当前会话，切换到第一个会话
                    if (_uiState.value.currentSessionId == sessionId) {
                        val sessions = _uiState.value.sessions.filter { it.id != sessionId }
                        _uiState.update { 
                            it.copy(currentSessionId = sessions.firstOrNull()?.id)
                        }
                    }
                },
                onFailure = { e ->
                    _uiState.update { it.copy(error = "删除会话失败: ${e.message}") }
                }
            )
        }
    }
    
    /**
     * 重命名会话
     */
    fun renameSession(sessionId: String, newTitle: String) {
        viewModelScope.launch {
            val session = _uiState.value.sessions.find { it.id == sessionId }
            if (session != null) {
                val updatedSession = session.copy(title = newTitle)
                val result = sessionRepository.updateSession(updatedSession)
                
                result.fold(
                    onSuccess = {
                        // 更新本地列表
                        val updatedSessions = _uiState.value.sessions.map {
                            if (it.id == sessionId) updatedSession else it
                        }
                        _uiState.update { it.copy(sessions = updatedSessions) }
                    },
                    onFailure = { e ->
                        _uiState.update { it.copy(error = "重命名失败: ${e.message}") }
                    }
                )
            }
        }
    }
    
    /**
     * 置顶/取消置顶会话
     */
    fun toggleSessionPin(sessionId: String, isPinned: Boolean) {
        viewModelScope.launch {
            val session = _uiState.value.sessions.find { it.id == sessionId }
            if (session != null) {
                val updatedSession = session.copy(isPinned = isPinned)
                val result = sessionRepository.updateSession(updatedSession)
                
                result.fold(
                    onSuccess = {
                        // 更新本地列表
                        val updatedSessions = _uiState.value.sessions.map {
                            if (it.id == sessionId) updatedSession else it
                        }
                        _uiState.update { it.copy(sessions = updatedSessions) }
                    },
                    onFailure = { e ->
                        _uiState.update { it.copy(error = "操作失败: ${e.message}") }
                    }
                )
            }
        }
    }
    
    /**
     * 清除错误
     */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
}
