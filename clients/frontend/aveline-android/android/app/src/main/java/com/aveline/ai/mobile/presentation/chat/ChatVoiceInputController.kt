package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.services.VoiceInputManager
import com.aveline.ai.mobile.services.VoiceInputState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 负责语音输入（录音转文字）的状态观察与控制。
 *
 * 从 ChatViewModel 拆出，职责：
 * - 监听 [VoiceInputManager] 的 state / amplitude / partialText，写入 uiState
 * - 录音控制：开始 / 停止 / 取消
 * - 权限检查
 *
 * @param scope ViewModel 的协程作用域
 * @param uiState UI 状态流，语音输入状态写入此流
 * @param voiceInputManager 底层语音输入管理器
 */
class ChatVoiceInputController(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val voiceInputManager: VoiceInputManager
) {
    /** 监听语音输入状态：录音状态、振幅、识别中间文本同步到 uiState。 */
    fun observeState() {
        scope.launch {
            voiceInputManager.state.collect { state ->
                uiState.update {
                    it.copy(
                        voiceInputState = state,
                        isRecording = state is VoiceInputState.Recording
                    )
                }
                if (state is VoiceInputState.Result) {
                    uiState.update {
                        it.copy(
                            inputText = state.text,
                            voiceInputState = VoiceInputState.Idle
                        )
                    }
                }
            }
        }

        scope.launch {
            voiceInputManager.amplitude.collect { amplitude ->
                uiState.update { it.copy(voiceAmplitude = amplitude) }
            }
        }

        scope.launch {
            voiceInputManager.partialText.collect { text ->
                uiState.update { it.copy(voicePartialText = text) }
            }
        }
    }

    fun startRecording() {
        if (voiceInputManager.hasRecordAudioPermission()) {
            voiceInputManager.startListening()
        } else {
            uiState.update { it.copy(error = "缺少录音权限") }
        }
    }

    fun stopRecording() {
        voiceInputManager.stopListening()
    }

    fun cancelRecording() {
        voiceInputManager.cancel()
    }

    fun hasPermission(): Boolean = voiceInputManager.hasRecordAudioPermission()
}
