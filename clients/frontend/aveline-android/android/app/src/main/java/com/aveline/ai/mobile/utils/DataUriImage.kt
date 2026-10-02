package com.aveline.ai.mobile.utils

import java.util.Base64

/**
 * data URI（`data:image/...;base64,xxxx`）解码。
 *
 * 背景：后端推送表情包时把图片编码成 data URI，随 `image_result` 事件下发给前端
 * （见 `core/services/aveline/stream_orchestrator.py` 的 `_emit_media_image_results`
 * 与 `core/interfaces/websocket/adapters/streaming.py` 的 `_send_media_image_result`）。
 *
 * Coil 2.x 没有 data URI 对应的 Fetcher（Coil 3 才有 `DataUriFetcher`），
 * 把 data URI 直接当 URL 交给 `AsyncImage` 时，找不到可用 Fetcher 会直接落到
 * error 占位图（右下角三角感叹号图标）。因此这里先解码成 ByteArray，
 * 再由 Coil 的 `ByteArrayMapper` → `ByteBufferFetcher` 正常解码显示。
 */
object DataUriImage {

    private val DATA_URI_REGEX = Regex(
        pattern = """^data:([^,;]+)?(;base64)?,(.+)$""",
        // Kotlin 里等价于 Java DOTALL 的选项是 DOT_MATCHES_ALL：
        // base64 里可能带换行，没有它 (.+) 匹配不到完整数据
        options = setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
    )

    /** 是否是 data URI（忽略大小写与前导空白）。 */
    fun isDataUri(value: String): Boolean =
        value.trimStart().startsWith("data:", ignoreCase = true)

    /**
     * 解码 data URI 里的图片字节。
     *
     * @return 图片字节；非 data URI、非 base64 编码或数据非法时返回 null，
     *         由调用方回退为普通 URL 处理。
     */
    fun decode(value: String): ByteArray? {
        if (!isDataUri(value)) return null

        val match = DATA_URI_REGEX.matchEntire(value.trim()) ?: return null
        // 仅支持 ;base64 形式，data:image/svg+xml,<转义文本> 这类不做处理
        if (match.groupValues[2].isEmpty()) return null

        val payload = match.groupValues[3].filterNot { it.isWhitespace() }
        if (payload.isEmpty()) return null

        return runCatching {
            // MIME 解码器：容忍换行与个别非法字符，避免整张图加载失败
            Base64.getMimeDecoder().decode(payload)
        }.getOrNull()?.takeIf { it.isNotEmpty() }
    }
}
