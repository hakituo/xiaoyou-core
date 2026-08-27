package com.aveline.ai.mobile.services

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import androidx.core.content.ContextCompat
import com.k2fsa.sherpa.ncnn.SherpaNcnn
import com.k2fsa.sherpa.ncnn.RecognizerConfig
import com.k2fsa.sherpa.ncnn.getDecoderConfig
import com.k2fsa.sherpa.ncnn.getFeatureExtractorConfig
import com.k2fsa.sherpa.ncnn.getModelConfig
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

/**
 * sherpa-ncnn 端侧 ASR 引擎
 *
 * 职责:
 * 1. 加载 sherpa-ncnn 模型 (从 assets, 用 AssetManager)
 * 2. 用 AudioRecord 录制 16kHz 单声道 PCM
 * 3. 把 short[] PCM 转 FloatArray (-1.0~1.0) 喂给 SherpaNcnn.acceptSamples
 * 4. 循环 decode() 拿流式 partial 结果
 * 5. 检测 endpoint (一句话说完) 自动断句
 *
 * 与 VoiceInputManager 的关系:
 * - VoiceInputManager 根据 asr_provider 配置选择本引擎或系统 SpeechRecognizer
 * - 本引擎暴露 state/partialText/finalText 供 UI 观察
 *
 * 线程模型:
 * - 录音 + 识别在 IO dispatcher 单协程内跑 (避免多线程访问 recognizer)
 * - state/partialText 用 StateFlow 在主线程观察
 *
 * 端点检测 (endpoint):
 * - rule1MinTrailingSilence=2.4s: 连续 2.4s 静音判定一句话结束
 * - rule2MinTrailingSilence=1.0s: 已说够一定长度后, 1s 静音即结束
 * - rule3MinUtteranceLength=30s: 单句最长 30s 强制截断
 */
@Singleton
class SherpaNcnnAsrEngine @Inject constructor(
    @ApplicationContext private val context: Context
) {
    companion object {
        private const val TAG = "SherpaNcnnAsrEngine"

        // 音频参数: sherpa-ncnn 要求 16kHz 单声道 16-bit PCM
        private const val SAMPLE_RATE = 16000
        private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT

        // 模型类型: 6 = streaming-zipformer-small-bilingual-zh-en (中英双语小模型)
        private const val MODEL_TYPE = 6

        // 录音每次读取的样本数 (32ms 一批, 平衡延迟和性能)
        private const val CHUNK_SAMPLES = 512 // 512 samples ≈ 32ms @ 16kHz

        // 单次录音最长时长 (防止无限录音)
        private const val MAX_RECORD_MS = 60_000L
    }

    private val engineScope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private var recognizer: SherpaNcnn? = null
    private var audioRecord: AudioRecord? = null
    private var recordJob: Job? = null

    private var isInitialized = false
    private var loadError: String? = null

    private val _state = MutableStateFlow<AsrState>(AsrState.Idle)
    val state: StateFlow<AsrState> = _state.asStateFlow()

    private val _partialText = MutableStateFlow("")
    val partialText: StateFlow<String> = _partialText.asStateFlow()

    private val _amplitude = MutableStateFlow(0f)
    val amplitude: StateFlow<Float> = _amplitude.asStateFlow()

    /**
     * 检查引擎是否可用 (.so 已加载 + 模型已初始化)
     *
     * .so 加载在 SherpaNcnn.companion.init 里, 失败会抛 UnsatisfiedLinkError
     * 这里用 try-catch 检测, 不影响 app 启动
     */
    fun isAvailable(): Boolean {
        return try {
            // 触发 SherpaNcnn 类加载, 看 System.loadLibrary 是否成功
            Class.forName("com.k2fsa.sherpa.ncnn.SherpaNcnn")
            true
        } catch (e: Throwable) {
            Log.w(TAG, "sherpa-ncnn 不可用: ${e.message}")
            false
        }
    }

    /**
     * 初始化模型 (从 assets 加载)
     *
     * 应在 app 启动后或首次使用 ASR 前调用。
     * 耗时约 1-3s (取决于设备), 建议在 IO 线程。
     */
    fun initialize(): Boolean {
        if (isInitialized) return true
        if (!isAvailable()) {
            loadError = "sherpa-ncnn .so 库未加载, 请运行 download_assets.py 下载"
            Log.e(TAG, loadError!!)
            return false
        }

        return try {
            val modelConfig = getModelConfig(MODEL_TYPE, useGPU = false)
                ?: throw IllegalStateException("getModelConfig($MODEL_TYPE) 返回 null")

            // getModelConfig 返回的 path 不含 assets 子目录前缀
            // 模型实际放在 assets/sherpa_ncnn_models/ 下, 这里给每个 path 加前缀
            // SherpaNcnn.newFromAsset 用 AssetManager.open(path) 加载, path 相对 assets 根
            val assetsPrefix = "sherpa_ncnn_models/"
            modelConfig.encoderParam = assetsPrefix + modelConfig.encoderParam
            modelConfig.encoderBin = assetsPrefix + modelConfig.encoderBin
            modelConfig.decoderParam = assetsPrefix + modelConfig.decoderParam
            modelConfig.decoderBin = assetsPrefix + modelConfig.decoderBin
            modelConfig.joinerParam = assetsPrefix + modelConfig.joinerParam
            modelConfig.joinerBin = assetsPrefix + modelConfig.joinerBin
            modelConfig.tokens = assetsPrefix + modelConfig.tokens

            val recognizerConfig = RecognizerConfig(
                featConfig = getFeatureExtractorConfig(
                    sampleRate = SAMPLE_RATE.toFloat(),
                    featureDim = 80
                ),
                modelConfig = modelConfig,
                decoderConfig = getDecoderConfig(
                    method = "modified_beam_search",
                    numActivePaths = 4
                ),
                enableEndpoint = true,
                rule1MinTrailingSilence = 2.4f,
                rule2MinTrailingSilence = 1.0f,
                rule3MinUtteranceLength = 30.0f,
            )

            // 用 AssetManager 加载 (模型文件在 assets/sherpa_ncnn_models/ 下)
            recognizer = SherpaNcnn(recognizerConfig, context.assets)
            isInitialized = true
            loadError = null
            Log.i(TAG, "sherpa-ncnn 模型加载成功 (type=$MODEL_TYPE)")
            true
        } catch (e: UnsatisfiedLinkError) {
            loadError = "native 库加载失败: ${e.message}"
            Log.e(TAG, loadError!!, e)
            false
        } catch (e: Exception) {
            loadError = "模型初始化失败: ${e.message}"
            Log.e(TAG, loadError!!, e)
            false
        }
    }

    /**
     * 检查录音权限
     */
    fun hasRecordAudioPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
    }

    /**
     * 开始录音 + 识别
     *
     * 流程:
     * 1. 检查权限和初始化
     * 2. 创建 AudioRecord
     * 3. 启动协程循环: 读 PCM → 转 Float → acceptSamples → decode → 更新 partialText
     * 4. 检测 endpoint → 自动断句, 累积到 finalText
     */
    fun startListening() {
        if (!hasRecordAudioPermission()) {
            _state.value = AsrState.Error("缺少录音权限")
            return
        }

        if (_state.value == AsrState.Recording) {
            stopListening()
            return
        }

        if (!isInitialized && !initialize()) {
            _state.value = AsrState.Error(loadError ?: "sherpa-ncnn 初始化失败")
            return
        }

        // 重置状态
        _partialText.value = ""
        _amplitude.value = 0f

        try {
            val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT)
            val bufferSize = maxOf(minBuf * 2, CHUNK_SAMPLES * 2 * 2) // 至少够 2 个 chunk

            @Suppress("MissingPermission")
            audioRecord = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                CHANNEL_CONFIG,
                AUDIO_FORMAT,
                bufferSize
            )

            if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
                _state.value = AsrState.Error("AudioRecord 初始化失败")
                return
            }

            // 重置 recognizer 开始新句
            recognizer?.reset(recreate = false)

            audioRecord?.startRecording()
            _state.value = AsrState.Recording

            recordJob = engineScope.launch {
                recordLoop()
            }
        } catch (e: SecurityException) {
            _state.value = AsrState.Error("录音权限被拒绝")
        } catch (e: Exception) {
            _state.value = AsrState.Error("启动录音失败: ${e.message}")
            Log.e(TAG, "startListening 失败", e)
        }
    }

    /**
     * 停止录音, 返回最终识别结果
     */
    fun stopListening(): String {
        _state.value = AsrState.Processing

        recordJob?.cancel()
        recordJob = null

        try {
            audioRecord?.stop()
        } catch (e: Exception) {
            Log.w(TAG, "AudioRecord.stop 异常: ${e.message}")
        }

        // 通知 recognizer 输入结束, flush 最后的解码
        try {
            recognizer?.inputFinished()
            while (recognizer?.isReady() == true) {
                recognizer?.decode()
            }
        } catch (e: Exception) {
            Log.w(TAG, "flush decode 异常: ${e.message}")
        }

        val finalText = recognizer?.text ?: ""
        val partial = _partialText.value
        val result = if (finalText.isNotBlank()) finalText else partial

        _state.value = if (result.isNotBlank()) AsrState.Result(result) else AsrState.Error("未识别到语音")
        _amplitude.value = 0f
        return result
    }

    /**
     * 取消录音 (不返回结果)
     */
    fun cancel() {
        recordJob?.cancel()
        recordJob = null
        try {
            audioRecord?.stop()
        } catch (e: Exception) {
            // 忽略
        }
        recognizer?.reset(recreate = false)
        _state.value = AsrState.Idle
        _partialText.value = ""
        _amplitude.value = 0f
    }

    /**
     * 重置状态 (UI 用, 不影响 recognizer)
     */
    fun reset() {
        _state.value = AsrState.Idle
        _partialText.value = ""
        _amplitude.value = 0f
    }

    /**
     * 释放资源 (app 退出时调用)
     */
    fun destroy() {
        cancel()
        audioRecord?.release()
        audioRecord = null
        recognizer = null
        isInitialized = false
    }

    // ── 录音+识别循环 ────────────────────────────────────

    /**
     * 核心循环: 读 PCM → 转 Float → 喂 recognizer → decode → 更新 partialText
     *
     * 端点检测: isEndpoint() 返回 true 时表示一句话说完, 累积到 finalText
     */
    private suspend fun recordLoop() {
        val shortBuffer = ShortArray(CHUNK_SAMPLES)
        val startTime = System.currentTimeMillis()

        while (engineScope.isActive && _state.value == AsrState.Recording) {
            // 超时保护
            if (System.currentTimeMillis() - startTime > MAX_RECORD_MS) {
                Log.w(TAG, "录音超时 ${MAX_RECORD_MS}ms, 自动停止")
                stopListening()
                return
            }

            val read = try {
                audioRecord?.read(shortBuffer, 0, CHUNK_SAMPLES) ?: -1
            } catch (e: Exception) {
                Log.e(TAG, "AudioRecord.read 异常", e)
                -1
            }

            if (read <= 0) {
                Log.w(TAG, "AudioRecord.read 返回 $read, 停止")
                _state.value = AsrState.Error("录音读取失败")
                return
            }

            // 计算音量 (RMS)
            var sum = 0L
            for (i in 0 until read) {
                sum += shortBuffer[i].toLong() * shortBuffer[i]
            }
            val rms = kotlin.math.sqrt(sum.toDouble() / read).toFloat()
            _amplitude.value = (rms / 32768f).coerceIn(0f, 1f)

            // short[] → FloatArray (-1.0~1.0)
            val samples = FloatArray(read) { i ->
                shortBuffer[i] / 32768.0f
            }

            // 喂给 recognizer
            try {
                recognizer?.acceptSamples(samples)

                // 解码所有可解码的
                while (recognizer?.isReady() == true) {
                    recognizer?.decode()
                }

                // 更新 partial 文本
                val text = recognizer?.text ?: ""
                if (text != _partialText.value) {
                    _partialText.value = text
                }

                // 端点检测: 一句话说完
                if (recognizer?.isEndpoint() == true) {
                    // 一句话结束, 当前 text 已是完整句
                    // 通知 UI (可选: 自动停止或继续录下一句)
                    // 这里选择继续录, 让用户手动停或超时停
                    // reset 后开始新句, 但保留已识别文本
                    recognizer?.reset(recreate = false)
                }
            } catch (e: Exception) {
                Log.w(TAG, "识别循环异常: ${e.message}")
            }
        }
    }
}

/**
 * ASR 引擎状态
 */
sealed class AsrState {
    data object Idle : AsrState()
    data object Recording : AsrState()
    data object Processing : AsrState()
    data class Error(val message: String) : AsrState()
    data class Result(val text: String) : AsrState()
}
