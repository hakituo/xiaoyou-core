package com.aveline.ai.mobile.presentation.plugins

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.domain.models.EmotionType
import com.aveline.ai.mobile.domain.models.PluginSettings
import com.aveline.ai.mobile.domain.models.ResponseLength
import com.aveline.ai.mobile.domain.repository.PluginsRepository
import com.aveline.ai.mobile.domain.repository.StudyRepository
import com.aveline.ai.mobile.domain.repository.ToolsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 插件设置 UI 状态
 * 
 * @property models 可用模型列表
 * @property selectedModel 当前选中的模型
 * @property settings 插件设置
 * @property isLoading 是否加载中
 * @property error 错误信息
 * @property showEmotionSelector 是否显示情绪选择器
 */
data class PluginsUiState(
    val models: List<AIModel> = emptyList(),
    val selectedModel: AIModel? = null,
    val settings: PluginSettings = PluginSettings(),
    val studyModeEnabled: Boolean = false,
    val activeStudyFileCount: Int = 0,
    val studyChunkCount: Int = 0,
    val sensitiveEnabled: Boolean? = null,
    val isSensitiveLoading: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null,
    val showEmotionSelector: Boolean = false
) {
    val cloudModels: List<AIModel>
        get() = models.filter { it.type == com.aveline.ai.mobile.domain.models.ModelType.CLOUD }
    
    val localModels: List<AIModel>
        get() = models.filter { it.type == com.aveline.ai.mobile.domain.models.ModelType.LOCAL }
    
    val hasModels: Boolean
        get() = models.isNotEmpty()
    
    val currentEmotionLabel: String
        get() = settings.manualEmotion?.let { it.label } ?: "自动检测"
}

/**
 * 插件和模型管理 ViewModel
 * 
 * 功能：
 * - 模型列表加载
 * - 模型切换
 * - 响应长度设置
 * - 呼吸频率调整
 * - 情绪设置
 * 
 * Requirements: 12.1, 12.2, 12.3, 12.4, 12.5
 */
@HiltViewModel
class PluginsViewModel @Inject constructor(
    private val pluginsRepository: PluginsRepository,
    private val studyRepository: StudyRepository,
    private val toolsRepository: ToolsRepository
) : ViewModel() {
    
    private val _uiState = MutableStateFlow(PluginsUiState())
    val uiState: StateFlow<PluginsUiState> = _uiState.asStateFlow()
    
    init {
        loadModels()
        loadSettings()
        refreshStudyMode()
        refreshSensitive()
    }
    
    /**
     * 加载模型列表
     */
    fun loadModels() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            
            try {
                val models = pluginsRepository.getModels()
                val selected = pluginsRepository.getSelectedModel()
                
                _uiState.update { 
                    it.copy(
                        models = models,
                        selectedModel = selected,
                        isLoading = false
                    )
                }
            } catch (e: Exception) {
                _uiState.update { 
                    it.copy(
                        isLoading = false,
                        error = "加载模型失败: ${e.message}"
                    )
                }
            }
        }
    }
    
    /**
     * 加载设置
     */
    private fun loadSettings() {
        viewModelScope.launch {
            try {
                val settings = pluginsRepository.getSettings()
                _uiState.update { it.copy(settings = settings) }
            } catch (e: Exception) {
                // 忽略设置加载错误，使用默认值
            }
        }
    }

    fun refreshStudyMode() {
        viewModelScope.launch {
            runCatching {
                studyRepository.getStudyModeState()
            }.onSuccess { state ->
                _uiState.update {
                    it.copy(
                        studyModeEnabled = state.isEnabled,
                        activeStudyFileCount = state.activeFileIds.size,
                        studyChunkCount = state.totalChunks
                    )
                }
            }
        }
    }

    fun toggleStudyMode() {
        viewModelScope.launch {
            val next = !_uiState.value.studyModeEnabled
            val result = studyRepository.setStudyModeEnabled(next)
            result.fold(
                onSuccess = { refreshStudyMode() },
                onFailure = { e ->
                    _uiState.update { it.copy(error = "Study mode update failed: ${e.message}") }
                }
            )
        }
    }

    fun refreshSensitive() {
        viewModelScope.launch {
            _uiState.update { it.copy(isSensitiveLoading = true) }
            val result = toolsRepository.getSensitiveStatus("default")
            result.fold(
                onSuccess = { enabled ->
                    _uiState.update {
                        it.copy(
                            isSensitiveLoading = false,
                            sensitiveEnabled = enabled
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            isSensitiveLoading = false,
                            error = "Sensitive status failed: ${e.message}"
                        )
                    }
                }
            )
        }
    }

    fun toggleSensitive() {
        viewModelScope.launch {
            val current = _uiState.value.sensitiveEnabled ?: false
            val next = !current
            _uiState.update { it.copy(isSensitiveLoading = true) }
            val result = toolsRepository.toggleSensitive("default", next)
            result.fold(
                onSuccess = { enabled ->
                    _uiState.update {
                        it.copy(
                            isSensitiveLoading = false,
                            sensitiveEnabled = enabled
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            isSensitiveLoading = false,
                            error = "Sensitive toggle failed: ${e.message}"
                        )
                    }
                }
            )
        }
    }
    
    /**
     * 设置响应长度
     */
    fun setResponseLength(length: ResponseLength) {
        viewModelScope.launch {
            val result = pluginsRepository.setResponseLength(length)
            
            result.fold(
                onSuccess = {
                    _uiState.update { 
                        it.copy(
                            settings = it.settings.copy(responseLength = length)
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update { it.copy(error = "设置失败: ${e.message}") }
                }
            )
        }
    }
    
    /**
     * 设置呼吸频率
     */
    fun setBreathingRate(rate: Float) {
        viewModelScope.launch {
            val clampedRate = rate.coerceIn(0.5f, 2.0f)
            val result = pluginsRepository.setBreathingRate(clampedRate)
            
            result.fold(
                onSuccess = {
                    _uiState.update { 
                        it.copy(
                            settings = it.settings.copy(breathingRate = clampedRate)
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update { it.copy(error = "设置失败: ${e.message}") }
                }
            )
        }
    }
    
    /**
     * 设置手动情绪
     */
    fun setManualEmotion(emotion: EmotionType?) {
        viewModelScope.launch {
            val result = pluginsRepository.setManualEmotion(emotion)
            
            result.fold(
                onSuccess = {
                    _uiState.update { 
                        it.copy(
                            settings = it.settings.copy(manualEmotion = emotion),
                            showEmotionSelector = false
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update { it.copy(error = "设置失败: ${e.message}") }
                }
            )
        }
    }
    
    /**
     * 切换自动情绪
     */
    fun toggleAutoEmotion() {
        viewModelScope.launch {
            val newAutoEmotion = !_uiState.value.settings.autoEmotion
            val result = pluginsRepository.setAutoEmotion(newAutoEmotion)
            
            result.fold(
                onSuccess = {
                    _uiState.update { 
                        it.copy(
                            settings = it.settings.copy(
                                autoEmotion = newAutoEmotion,
                                manualEmotion = if (newAutoEmotion) null else it.settings.manualEmotion
                            )
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update { it.copy(error = "设置失败: ${e.message}") }
                }
            )
        }
    }
    
    /**
     * 显示情绪选择器
     */
    fun showEmotionSelector() {
        _uiState.update { it.copy(showEmotionSelector = true) }
    }
    
    /**
     * 隐藏情绪选择器
     */
    fun hideEmotionSelector() {
        _uiState.update { it.copy(showEmotionSelector = false) }
    }
    
    /**
     * 清除错误
     */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
    
    /**
     * 重置呼吸频率到默认值
     */
    fun resetBreathingRate() {
        setBreathingRate(1.0f)
    }
}
