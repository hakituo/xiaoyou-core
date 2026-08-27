package com.aveline.ai.mobile.presentation.status

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.repository.StatusRepositoryImpl
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.LifeStatus
import com.aveline.ai.mobile.domain.repository.StatusRepository
import com.aveline.ai.mobile.domain.repository.ToolsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject

/**
 * 状态面板 UI 状态
 * 
 * @property lifeStatus 生命状态
 * @property emotion 当前情绪
 * @property emotionMix 情绪混合比例
 * @property connected WebSocket 连接状态
 * @property clock 系统时钟
 * @property isLoading 是否加载中
 * @property error 错误信息
 */
data class StatusUiState(
    val lifeStatus: LifeStatus? = null,
    val emotion: Emotion = Emotion.NEUTRAL,
    val emotionMix: Map<String, Float> = emptyMap(),
    val connected: Boolean = false,
    val clock: String = "",
    val systemStats: JsonObject? = null,
    val isLoading: Boolean = false,
    val isActionRunning: Boolean = false,
    val actionMessage: String? = null,
    val error: String? = null
) {
    val hasLowStatus: Boolean
        get() = lifeStatus?.hasLowStatus() ?: false
    
    val lowestStatusValue: Float
        get() = lifeStatus?.getLowestStatus() ?: 0f
    
    val lowestStatusName: String
        get() {
            val status = lifeStatus ?: return ""
            val lowest = minOf(
                status.health to "健康",
                status.hunger to "饥饿",
                status.happiness to "快乐",
                status.energy to "能量"
            ) { a, b -> a.first.compareTo(b.first) }
            return lowest.second
        }
    
    val connectionStatusText: String
        get() = if (connected) "已连接" else "未连接"
    
    val healthPercent: Int
        get() = ((lifeStatus?.health ?: 0f) * 100).toInt()
    
    val hungerPercent: Int
        get() = ((lifeStatus?.hunger ?: 0f) * 100).toInt()
    
    val happinessPercent: Int
        get() = ((lifeStatus?.happiness ?: 0f) * 100).toInt()
    
    val energyPercent: Int
        get() = ((lifeStatus?.energy ?: 0f) * 100).toInt()
}

/**
 * 状态面板 ViewModel
 * 
 * 功能：
 * - 生命状态显示
 * - 情绪状态显示
 * - 连接状态显示
 * - 系统时钟同步
 * 
 * Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
 */
@HiltViewModel
class StatusViewModel @Inject constructor(
    private val statusRepository: StatusRepository,
    private val statusRepositoryImpl: StatusRepositoryImpl,
    private val toolsRepository: ToolsRepository,
    private val webSocketManager: WebSocketManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(StatusUiState())
    val uiState: StateFlow<StatusUiState> = _uiState.asStateFlow()

    private var clockJob: Job? = null
    private var emotionJob: Job? = null

    /** 当前正在查看的 persona 文件名（来自聊天会话/伴侣面板选择，纯只读）；为 null 表示用后端默认 */
    @Volatile
    private var currentPersonaFilename: String? = null

    @Volatile
    private var currentConversationId: String? = null

    init {
        observeConnection()
        observeEmotion()
        startClock()
    }

    /**
     * 设置“正在查看的角色”对应的 persona 文件名（纯只读查询，不切对话人设）。
     * 由 ChatScreen 在聊天进入 / 面板内选版本时调用，随后按该角色加载生命状态。
     */
    fun setControlContext(filename: String?, conversationId: String?) {
        val normalizedFilename = filename?.takeIf { it.isNotBlank() }
        val normalizedConversationId = conversationId?.takeIf { it.isNotBlank() }
        if (
            normalizedFilename == currentPersonaFilename &&
            normalizedConversationId == currentConversationId
        ) return
        currentPersonaFilename = normalizedFilename
        currentConversationId = normalizedConversationId
        viewModelScope.launch(Dispatchers.IO) {
            loadStatus()
        }
    }

    /** 兼容仅更新查看角色的旧调用。 */
    fun setViewingPersona(filename: String) {
        setControlContext(filename, currentConversationId)
    }
    
    /**
     * 加载生命状态（按当前角色 scope）
     */
    fun loadStatus() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }

            val result = statusRepository.getLifeStatus(persona = currentPersonaFilename)

            result.fold(
                onSuccess = { status ->
                    _uiState.update {
                        it.copy(
                            lifeStatus = status,
                            isLoading = false
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            error = "加载失败: ${e.message}"
                        )
                    }
                }
            )

            loadSystemStats()
        }
    }
    
    /**
     * 刷新状态（按当前角色 scope）
     */
    fun refreshStatus() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }
            
            val result = statusRepositoryImpl.forceRefreshLifeStatus(persona = currentPersonaFilename)
            
            result.fold(
                onSuccess = { status ->
                    _uiState.update {
                        it.copy(
                            lifeStatus = status,
                            isLoading = false
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            error = "刷新失败: ${e.message}"
                        )
                    }
                }
            )

            loadSystemStats()
        }
    }

    fun wakeCompanion() = runCompanionAction("唤醒失败") {
        statusRepository.wakeCompanion(currentPersonaFilename, currentConversationId)
    }

    fun interruptCompanion() = runCompanionAction("打断失败") {
        statusRepository.interruptCompanion(currentPersonaFilename, currentConversationId)
    }

    fun skipCompanionActivity() = runCompanionAction("跳过失败") {
        statusRepository.skipCompanionActivity(currentPersonaFilename, currentConversationId)
    }

    private fun runCompanionAction(
        fallbackError: String,
        action: suspend () -> Result<String>
    ) {
        if (_uiState.value.isActionRunning) return
        viewModelScope.launch {
            _uiState.update {
                it.copy(isActionRunning = true, actionMessage = null, error = null)
            }
            action().fold(
                onSuccess = { message ->
                    _uiState.update {
                        it.copy(isActionRunning = false, actionMessage = message)
                    }
                    statusRepositoryImpl.forceRefreshLifeStatus(currentPersonaFilename)
                        .onSuccess { status ->
                            _uiState.update { it.copy(lifeStatus = status) }
                        }
                },
                onFailure = { error ->
                    _uiState.update {
                        it.copy(
                            isActionRunning = false,
                            error = "$fallbackError: ${error.message ?: "未知错误"}"
                        )
                    }
                }
            )
        }
    }

    private fun loadSystemStats() {
        viewModelScope.launch {
            toolsRepository.getSystemStats().onSuccess { statsElement ->
                val stats = statsElement?.jsonObject
                _uiState.update { it.copy(systemStats = stats) }
            }.onFailure {
                // 保持安静失败，状态页仍可展示其他实时数据
            }
        }
    }
    
    /**
     * 观察连接状态
     */
    private fun observeConnection() {
        viewModelScope.launch {
            webSocketManager.connectionState.collect { state ->
                _uiState.update { 
                    it.copy(connected = state == WebSocketManager.ConnectionState.CONNECTED)
                }
            }
        }
    }
    
    /**
     * 观察情绪变化
     */
    private fun observeEmotion() {
        emotionJob = viewModelScope.launch {
            statusRepository.observeEmotion().collect { emotion ->
                _uiState.update { it.copy(emotion = emotion) }
            }
        }
        // Also observe emotionMix from WebSocket EmotionUpdate messages directly
        viewModelScope.launch {
            webSocketManager.messages.collect { message ->
                when (message) {
                    is com.aveline.ai.mobile.data.remote.api.WebSocketMessage.EmotionUpdate -> {
                        if (message.emotionMix.isNotEmpty()) {
                            _uiState.update { it.copy(emotionMix = message.emotionMix) }
                        }
                    }
                    is com.aveline.ai.mobile.data.remote.api.WebSocketMessage.ConnectionEstablished -> {
                        Log.d("StatusViewModel", "Connection established: heartbeat=${message.heartbeatInterval}s, reconnect=${message.reconnectSupported}")
                    }
                    is com.aveline.ai.mobile.data.remote.api.WebSocketMessage.ReconnectSync -> {
                        // Sync emotion and life status from reconnect
                        message.currentModel?.let { model ->
                            Log.d("StatusViewModel", "Reconnect sync: currentModel=$model")
                        }
                        message.lifeStatus?.let { status ->
                            val syncedLifeStatus = com.aveline.ai.mobile.domain.models.LifeStatus(
                                health = status["health"] ?: 1.0f,
                                hunger = status["hunger"] ?: 0f,
                                happiness = status["mood_score"] ?: 1.0f,
                                energy = status["energy"] ?: 1.0f,
                                timestamp = System.currentTimeMillis(),
                                scope = _uiState.value.lifeStatus?.scope,
                                activity = _uiState.value.lifeStatus?.activity ?: "idle",
                                activityChatEligible = _uiState.value.lifeStatus?.activityChatEligible ?: true,
                                replyMode = _uiState.value.lifeStatus?.replyMode ?: "immediate",
                                replyDelayMinSeconds = _uiState.value.lifeStatus?.replyDelayMinSeconds,
                                replyDelayMaxSeconds = _uiState.value.lifeStatus?.replyDelayMaxSeconds,
                                isSleeping = _uiState.value.lifeStatus?.isSleeping ?: false,
                                sleepPhase = _uiState.value.lifeStatus?.sleepPhase,
                                dailyPlan = _uiState.value.lifeStatus?.dailyPlan
                            )
                            _uiState.update { it.copy(lifeStatus = syncedLifeStatus) }
                        }
                    }
                    else -> Unit
                }
            }
        }
    }
    
    /**
     * 启动时钟
     */
    private fun startClock() {
        clockJob = viewModelScope.launch {
            while (true) {
                val now = java.time.LocalDateTime.now()
                val formatted = now.format(
                    java.time.format.DateTimeFormatter.ofPattern("HH:mm:ss")
                )
                _uiState.update { it.copy(clock = formatted) }
                delay(1000)
            }
        }
    }
    
    /**
     * 清除错误
     */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
    
    override fun onCleared() {
        super.onCleared()
        clockJob?.cancel()
        emotionJob?.cancel()
    }
}
