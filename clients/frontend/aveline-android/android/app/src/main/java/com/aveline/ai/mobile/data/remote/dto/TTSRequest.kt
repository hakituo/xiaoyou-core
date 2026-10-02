package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable

@Serializable
data class TTSRequest(
    val text: String,
    val text_lang: String = "zh",
    val speed: Float = 1.0f,
    var voice: String? = null,
    var reference_audio: String? = null
) {
    init {
        // TTSEngine 的既有参数同时承载“参考音频”选择；为保持调用链兼容，
        // Chat 层用 voice:<name> 表示后端注册音色，在真正序列化请求前拆成 voice 字段。
        val selector = reference_audio?.trim().orEmpty()
        if (voice.isNullOrBlank() && selector.startsWith(VOICE_SELECTOR_PREFIX)) {
            voice = selector.removePrefix(VOICE_SELECTOR_PREFIX).trim().ifEmpty { null }
            reference_audio = null
        }
    }

    private companion object {
        const val VOICE_SELECTOR_PREFIX = "voice:"
    }
}

@Serializable
data class TTSResponse(
    val status: String = "",
    val data: TTSDataDto? = null,
    val request_id: String? = null,
    val timestamp: String? = null
)

@Serializable
data class TTSDataDto(
    val audio_base64: String = "",
    val sample_rate: Int = 24000,
    val file_path: String = "",
    val text: String = "",
    val source: String = ""
)
