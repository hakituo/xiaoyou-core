package com.k2fsa.sherpa.ncnn

import android.content.res.AssetManager

/**
 * sherpa-ncnn 的 Kotlin wrapper (从官方仓库 k2-fsa/sherpa-ncnn 拷贝)
 *
 * 提供流式语音识别能力:
 * - acceptSamples(): 喂入 PCM 采样 (FloatArray, -1.0~1.0, 16kHz)
 * - isReady(): 检查是否有足够数据进行一次 decode
 * - decode(): 跑一次解码, 结果累积在 text 属性
 * - inputFinished(): 通知输入结束 (flush 最后的解码)
 * - isEndpoint(): 检测端点 (一句话说完)
 * - reset(): 重置识别器 (开始新的一句话)
 *
 * 模型配置见 getModelConfig(type), type=6 是 streaming-zipformer-small-bilingual-zh-en
 */
data class FeatureExtractorConfig(
    var sampleRate: Float,
    var featureDim: Int,
)

data class ModelConfig(
    var encoderParam: String,
    var encoderBin: String,
    var decoderParam: String,
    var decoderBin: String,
    var joinerParam: String,
    var joinerBin: String,
    var tokens: String,
    var numThreads: Int = 1,
    var useGPU: Boolean = true,
)

data class DecoderConfig(
    var method: String = "modified_beam_search",
    var numActivePaths: Int = 4,
)

data class RecognizerConfig(
    var featConfig: FeatureExtractorConfig,
    var modelConfig: ModelConfig,
    var decoderConfig: DecoderConfig,
    var enableEndpoint: Boolean = true,
    var rule1MinTrailingSilence: Float = 2.4f,
    var rule2MinTrailingSilence: Float = 1.0f,
    var rule3MinUtteranceLength: Float = 30.0f,
    var hotwordsFile: String = "",
    var hotwordsScore: Float = 1.5f,
)

class SherpaNcnn(
    var config: RecognizerConfig,
    assetManager: AssetManager? = null,
) {
    private val ptr: Long

    init {
        if (assetManager != null) {
            ptr = newFromAsset(assetManager, config)
        } else {
            ptr = newFromFile(config)
        }
    }

    protected fun finalize() {
        delete(ptr)
    }

    fun acceptSamples(samples: FloatArray) =
        acceptWaveform(ptr, samples = samples, sampleRate = config.featConfig.sampleRate)

    fun isReady() = isReady(ptr)

    fun decode() = decode(ptr)

    fun inputFinished() = inputFinished(ptr)

    fun isEndpoint(): Boolean = isEndpoint(ptr)

    fun reset(recreate: Boolean = false) = reset(ptr, recreate = recreate)

    val text: String
        get() = getText(ptr)

    private external fun newFromAsset(
        assetManager: AssetManager,
        config: RecognizerConfig,
    ): Long

    private external fun newFromFile(
        config: RecognizerConfig,
    ): Long

    private external fun delete(ptr: Long)

    private external fun acceptWaveform(ptr: Long, samples: FloatArray, sampleRate: Float)

    private external fun inputFinished(ptr: Long)

    private external fun isReady(ptr: Long): Boolean

    private external fun decode(ptr: Long)

    private external fun isEndpoint(ptr: Long): Boolean

    private external fun reset(ptr: Long, recreate: Boolean)

    private external fun getText(ptr: Long): String

    companion object {
        init {
            System.loadLibrary("sherpa-ncnn-jni")
        }
    }
}

fun getFeatureExtractorConfig(
    sampleRate: Float,
    featureDim: Int
): FeatureExtractorConfig {
    return FeatureExtractorConfig(
        sampleRate = sampleRate,
        featureDim = featureDim,
    )
}

fun getDecoderConfig(method: String, numActivePaths: Int): DecoderConfig {
    return DecoderConfig(method = method, numActivePaths = numActivePaths)
}

/**
 * @param type 模型类型
 * 0 - sherpa-ncnn-2022-09-30 (仅中文)
 * 1 - sherpa-ncnn-conv-emformer-transducer-2022-12-06 (中英)
 * 2 - sherpa-ncnn-streaming-zipformer-bilingual-zh-en-2023-02-13 (中英)
 * 3 - sherpa-ncnn-streaming-zipformer-en-2023-02-13 (仅英文)
 * 4 - sherpa-ncnn-streaming-zipformer-fr-2023-04-14 (仅法语)
 * 5 - sherpa-ncnn-streaming-zipformer-zh-14M-2023-02-23 (中文小模型 14M)
 * 6 - sherpa-ncnn-streaming-zipformer-small-bilingual-zh-en-2023-02-16 (中英小模型)
 */
fun getModelConfig(type: Int, useGPU: Boolean): ModelConfig? {
    when (type) {
        0 -> {
            val modelDir = "sherpa-ncnn-2022-09-30"
            return ModelConfig(
                encoderParam = "$modelDir/encoder_jit_trace-pnnx.ncnn.param",
                encoderBin = "$modelDir/encoder_jit_trace-pnnx.ncnn.bin",
                decoderParam = "$modelDir/decoder_jit_trace-pnnx.ncnn.param",
                decoderBin = "$modelDir/decoder_jit_trace-pnnx.ncnn.bin",
                joinerParam = "$modelDir/joiner_jit_trace-pnnx.ncnn.param",
                joinerBin = "$modelDir/joiner_jit_trace-pnnx.ncnn.bin",
                tokens = "$modelDir/tokens.txt",
                numThreads = 1,
                useGPU = useGPU,
            )
        }
        1 -> {
            val modelDir = "sherpa-ncnn-conv-emformer-transducer-2022-12-06"
            return ModelConfig(
                encoderParam = "$modelDir/encoder_jit_trace-pnnx.ncnn.int8.param",
                encoderBin = "$modelDir/encoder_jit_trace-pnnx.ncnn.int8.bin",
                decoderParam = "$modelDir/decoder_jit_trace-pnnx.ncnn.param",
                decoderBin = "$modelDir/decoder_jit_trace-pnnx.ncnn.bin",
                joinerParam = "$modelDir/joiner_jit_trace-pnnx.ncnn.int8.param",
                joinerBin = "$modelDir/joiner_jit_trace-pnnx.ncnn.int8.bin",
                tokens = "$modelDir/tokens.txt",
                numThreads = 1,
                useGPU = useGPU,
            )
        }
        2 -> {
            val modelDir = "sherpa-ncnn-streaming-zipformer-bilingual-zh-en-2023-02-13"
            return ModelConfig(
                encoderParam = "$modelDir/encoder_jit_trace-pnnx.ncnn.param",
                encoderBin = "$modelDir/encoder_jit_trace-pnnx.ncnn.bin",
                decoderParam = "$modelDir/decoder_jit_trace-pnnx.ncnn.param",
                decoderBin = "$modelDir/decoder_jit_trace-pnnx.ncnn.bin",
                joinerParam = "$modelDir/joiner_jit_trace-pnnx.ncnn.param",
                joinerBin = "$modelDir/joiner_jit_trace-pnnx.ncnn.bin",
                tokens = "$modelDir/tokens.txt",
                numThreads = 1,
                useGPU = useGPU,
            )
        }
        3 -> {
            val modelDir = "sherpa-ncnn-streaming-zipformer-en-2023-02-13"
            return ModelConfig(
                encoderParam = "$modelDir/encoder_jit_trace-pnnx.ncnn.param",
                encoderBin = "$modelDir/encoder_jit_trace-pnnx.ncnn.bin",
                decoderParam = "$modelDir/decoder_jit_trace-pnnx.ncnn.param",
                decoderBin = "$modelDir/decoder_jit_trace-pnnx.ncnn.bin",
                joinerParam = "$modelDir/joiner_jit_trace-pnnx.ncnn.param",
                joinerBin = "$modelDir/joiner_jit_trace-pnnx.ncnn.bin",
                tokens = "$modelDir/tokens.txt",
                numThreads = 1,
                useGPU = useGPU,
            )
        }
        4 -> {
            val modelDir = "sherpa-ncnn-streaming-zipformer-fr-2023-04-14"
            return ModelConfig(
                encoderParam = "$modelDir/encoder_jit_trace-pnnx.ncnn.param",
                encoderBin = "$modelDir/encoder_jit_trace-pnnx.ncnn.bin",
                decoderParam = "$modelDir/decoder_jit_trace-pnnx.ncnn.param",
                decoderBin = "$modelDir/decoder_jit_trace-pnnx.ncnn.bin",
                joinerParam = "$modelDir/joiner_jit_trace-pnnx.ncnn.param",
                joinerBin = "$modelDir/joiner_jit_trace-pnnx.ncnn.bin",
                tokens = "$modelDir/tokens.txt",
                numThreads = 1,
                useGPU = useGPU,
            )
        }
        5 -> {
            val modelDir = "sherpa-ncnn-streaming-zipformer-zh-14M-2023-02-23"
            return ModelConfig(
                encoderParam = "$modelDir/encoder_jit_trace-pnnx.ncnn.param",
                encoderBin = "$modelDir/encoder_jit_trace-pnnx.ncnn.bin",
                decoderParam = "$modelDir/decoder_jit_trace-pnnx.ncnn.param",
                decoderBin = "$modelDir/decoder_jit_trace-pnnx.ncnn.bin",
                joinerParam = "$modelDir/joiner_jit_trace-pnnx.ncnn.param",
                joinerBin = "$modelDir/joiner_jit_trace-pnnx.ncnn.bin",
                tokens = "$modelDir/tokens.txt",
                numThreads = 2,
                useGPU = useGPU,
            )
        }
        6 -> {
            val modelDir = "sherpa-ncnn-streaming-zipformer-small-bilingual-zh-en-2023-02-16/96"
            return ModelConfig(
                encoderParam = "$modelDir/encoder_jit_trace-pnnx.ncnn.param",
                encoderBin = "$modelDir/encoder_jit_trace-pnnx.ncnn.bin",
                decoderParam = "$modelDir/decoder_jit_trace-pnnx.ncnn.param",
                decoderBin = "$modelDir/decoder_jit_trace-pnnx.ncnn.bin",
                joinerParam = "$modelDir/joiner_jit_trace-pnnx.ncnn.param",
                joinerBin = "$modelDir/joiner_jit_trace-pnnx.ncnn.bin",
                tokens = "$modelDir/tokens.txt",
                numThreads = 2,
                useGPU = useGPU,
            )
        }
    }
    return null
}
