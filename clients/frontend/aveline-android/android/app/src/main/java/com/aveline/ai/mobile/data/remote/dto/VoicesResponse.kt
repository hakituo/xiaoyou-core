package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable

/**
 * Response DTO for available TTS voices.
 *
 * 后端 `/api/v1/media/voices` 实际把列表放在 `data.voices` 里，
 * 这里同时兼容顶层 `voices`（扁平结构），读取时取 [data] 优先。
 *
 * 所有字段都给默认值：后端换字段/少字段时不应让整个响应反序列化失败。
 *
 * @property status Response status
 * @property data 后端实际结构：`{"data": {"voices": [...]}}`
 * @property voices 扁平结构兼容：`{"voices": [...]}`
 */
@Serializable
data class VoicesResponse(
    val status: String = "",
    val data: VoicesData? = null,
    val voices: List<VoiceDto> = emptyList()
) {
    /** 不分响应结构差异，统一取出音色列表。 */
    val allVoices: List<VoiceDto>
        get() = (data?.voices ?: voices)
}

/** `data.voices` 内层结构。 */
@Serializable
data class VoicesData(
    val voices: List<VoiceDto> = emptyList()
)

/**
 * Voice model DTO。
 *
 * @property id Voice id（对火山音色等于音色名，可直接作为 TTS 的 voice 参数）
 * @property name Voice display name
 * @property language Voice language
 * @property gender Voice gender (male, female, neutral)
 */
@Serializable
data class VoiceDto(
    val id: String = "",
    val name: String = "",
    val language: String = "",
    val gender: String = ""
)
