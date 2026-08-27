package com.aveline.ai.mobile.services

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import androidx.core.content.ContextCompat
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.Locale
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

sealed class VoiceInputState {
    data object Idle : VoiceInputState()
    data object Recording : VoiceInputState()
    data object Processing : VoiceInputState()
    data class Error(val message: String) : VoiceInputState()
    data class Result(val text: String) : VoiceInputState()
}

/**
 * 语音输入统一管理器
 *
 * 根据 asrProvider 配置选择底层引擎:
 * - "sherpa_ncnn": 用 SherpaNcnnAsrEngine (端侧, 不依赖云/GMS)
 * - "system": 用 Android SpeechRecognizer (依赖 GMS, 国行不可用)
 * - "auto" (默认): 优先 sherpa_ncnn, 不可用时降级 system
 *
 * 对外统一暴露 state/partialText/amplitude, UI 无需关心底层引擎
 */
@Singleton
class VoiceInputManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val appPreferences: AppPreferences,
    private val sherpaNcnnEngine: SherpaNcnnAsrEngine
) {

    companion object {
        private const val TAG = "VoiceInputManager"
    }

    private val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())
    private var sherpaObserverJob: Job? = null

    // ── System SpeechRecognizer (fallback) ──────────────
    private var speechRecognizer: SpeechRecognizer? = null

    // ── 统一对外状态 ──────────────────────────────────────
    private val _state = MutableStateFlow<VoiceInputState>(VoiceInputState.Idle)
    val state: StateFlow<VoiceInputState> = _state.asStateFlow()

    private val _partialText = MutableStateFlow("")
    val partialText: StateFlow<String> = _partialText.asStateFlow()

    private val _amplitude = MutableStateFlow(0f)
    val amplitude: StateFlow<Float> = _amplitude.asStateFlow()

    /**
     * 当前实际使用的引擎: "sherpa_ncnn" / "system"
     * 每次 startListening 时根据配置和可用性决定
     */
    private var activeEngine: String = "system"

    fun hasRecordAudioPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
    }

    /**
     * 根据 asrProvider 配置和引擎可用性, 决定使用哪个引擎
     */
    private fun resolveEngine(): String {
        val provider = appPreferences.asrProvider
        return when (provider) {
            "sherpa_ncnn" -> {
                if (sherpaNcnnEngine.isAvailable()) "sherpa_ncnn"
                else {
                    Log.w(TAG, "asrProvider=sherpa_ncnn 但引擎不可用, 降级 system")
                    "system"
                }
            }
            "system" -> "system"
            "auto" -> {
                if (sherpaNcnnEngine.isAvailable()) "sherpa_ncnn" else "system"
            }
            else -> {
                Log.w(TAG, "未知 asrProvider=$provider, 用 system")
                "system"
            }
        }
    }

    fun startListening() {
        if (!hasRecordAudioPermission()) {
            _state.value = VoiceInputState.Error("缺少录音权限")
            return
        }

        if (_state.value == VoiceInputState.Recording) {
            stopListening()
            return
        }

        activeEngine = resolveEngine()
        Log.i(TAG, "使用 ASR 引擎: $activeEngine (provider=${appPreferences.asrProvider})")

        when (activeEngine) {
            "sherpa_ncnn" -> startSherpaNcnn()
            else -> startSystemSpeechRecognizer()
        }
    }

    // ── sherpa-ncnn 通道 ─────────────────────────────────

    private fun startSherpaNcnn() {
        // 先初始化引擎 (加载模型, 耗时但只首次)
        if (!sherpaNcnnEngine.initialize()) {
            Log.w(TAG, "sherpa-ncnn 初始化失败, 降级 system")
            activeEngine = "system"
            startSystemSpeechRecognizer()
            return
        }

        // 观察 sherpa 引擎状态, 转发到本管理器的 state
        sherpaObserverJob?.cancel()
        sherpaObserverJob = scope.launch {
            sherpaNcnnEngine.state.collect { asrState ->
                _state.value = when (asrState) {
                    is AsrState.Idle -> VoiceInputState.Idle
                    is AsrState.Recording -> VoiceInputState.Recording
                    is AsrState.Processing -> VoiceInputState.Processing
                    is AsrState.Error -> VoiceInputState.Error(asrState.message)
                    is AsrState.Result -> VoiceInputState.Result(asrState.text)
                }
            }
        }
        // 观察 partialText 和 amplitude
        scope.launch {
            sherpaNcnnEngine.partialText.collect { _partialText.value = it }
        }
        scope.launch {
            sherpaNcnnEngine.amplitude.collect { _amplitude.value = it }
        }

        sherpaNcnnEngine.startListening()
    }

    // ── System SpeechRecognizer 通道 (原有逻辑) ──────────

    private fun startSystemSpeechRecognizer() {
        // 检查系统 SpeechRecognizer 是否可用（国行手机无 GMS 时不可用）
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            Log.e(TAG, "系统 SpeechRecognizer 不可用（可能无 GMS）。请在设置里切换 ASR 引擎为 sherpa_ncnn")
            _state.value = VoiceInputState.Error(
                "系统语音识别不可用（国行手机无 GMS）。请在设置 → ASR 引擎里切换为 sherpa_ncnn"
            )
            return
        }

        // 清理 sherpa 观察协程
        sherpaObserverJob?.cancel()
        sherpaObserverJob = null

        speechRecognizer?.destroy()
        speechRecognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    Log.d(TAG, "onReadyForSpeech")
                    _state.value = VoiceInputState.Recording
                }

                override fun onBeginningOfSpeech() {
                    Log.d(TAG, "onBeginningOfSpeech")
                }

                override fun onRmsChanged(rmsdB: Float) {
                    _amplitude.value = rmsdB / 10f
                }

                override fun onBufferReceived(buffer: ByteArray?) {
                    Log.d(TAG, "onBufferReceived")
                }

                override fun onEndOfSpeech() {
                    Log.d(TAG, "onEndOfSpeech")
                    _state.value = VoiceInputState.Processing
                }

                override fun onError(error: Int) {
                    val errorMessage = getErrorMessage(error)
                    Log.e(TAG, "onError: $errorMessage")
                    _state.value = VoiceInputState.Error(errorMessage)
                }

                override fun onResults(results: Bundle?) {
                    Log.d(TAG, "onResults")
                    val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    val text = matches?.firstOrNull() ?: ""

                    if (text.isNotBlank()) {
                        _state.value = VoiceInputState.Result(text)
                    } else {
                        _state.value = VoiceInputState.Error("未识别到语音")
                    }
                }

                override fun onPartialResults(partialResults: Bundle?) {
                    Log.d(TAG, "onPartialResults")
                    val matches = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    val text = matches?.firstOrNull() ?: ""
                    _partialText.value = text
                }

                override fun onEvent(eventType: Int, params: Bundle?) {
                    Log.d(TAG, "onEvent: $eventType")
                }
            })
        }

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault().toString())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
        }

        speechRecognizer?.startListening(intent)
    }

    fun stopListening() {
        when (activeEngine) {
            "sherpa_ncnn" -> {
                sherpaNcnnEngine.stopListening()
                // state 已通过 observer 转发
            }
            else -> {
                speechRecognizer?.stopListening()
                _amplitude.value = 0f
            }
        }
    }

    fun cancel() {
        when (activeEngine) {
            "sherpa_ncnn" -> sherpaNcnnEngine.cancel()
            else -> {
                speechRecognizer?.cancel()
                _state.value = VoiceInputState.Idle
                _partialText.value = ""
                _amplitude.value = 0f
            }
        }
    }

    fun reset() {
        _state.value = VoiceInputState.Idle
        _partialText.value = ""
        _amplitude.value = 0f
    }

    fun destroy() {
        sherpaObserverJob?.cancel()
        sherpaObserverJob = null
        speechRecognizer?.destroy()
        speechRecognizer = null
        sherpaNcnnEngine.destroy()
        _state.value = VoiceInputState.Idle
        _partialText.value = ""
        _amplitude.value = 0f
    }

    private fun getErrorMessage(error: Int): String {
        return when (error) {
            SpeechRecognizer.ERROR_AUDIO -> "音频录制错误"
            SpeechRecognizer.ERROR_CLIENT -> "客户端错误"
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "权限不足"
            SpeechRecognizer.ERROR_NETWORK -> "网络错误"
            SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "网络超时"
            SpeechRecognizer.ERROR_NO_MATCH -> "未识别到语音"
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "识别器繁忙"
            SpeechRecognizer.ERROR_SERVER -> "服务器错误"
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "语音超时"
            else -> "未知错误 ($error)"
        }
    }
}
