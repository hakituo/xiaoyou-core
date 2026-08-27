package com.aveline.ai.mobile.utils

/**
 * 图片 URL 解析器
 *
 * 后端下发的图片地址可能是：
 * - 绝对地址：http/https/data URI，直接返回
 * - 相对地址：/output/image/... 或 output/image/...，需要拼接后端 base URL
 *
 * 该对象无副作用，便于单元测试。
 */
object ImageUrlResolver {

    /**
     * 将后端下发的图片地址解析为 Android 端可直接加载的完整 URL。
     *
     * @param backendUrl 用户配置的后端地址，例如 "192.168.1.5:8000" 或 "http://example.com:8000"
     * @param imageUrl 后端下发的图片地址
     * @return 可直接交给 Coil 加载的地址
     */
    fun resolve(backendUrl: String, imageUrl: String): String {
        val trimmed = imageUrl.trim()
        if (trimmed.isEmpty()) {
            return imageUrl
        }

        // data URI / 已完整的网络地址直接返回
        if (isAbsolute(trimmed)) {
            return trimmed
        }

        val base = normalizeBackendUrl(backendUrl)
        if (base.isEmpty()) {
            // 没有配置后端地址，无法补全，原样返回让调用方自行失败
            return trimmed
        }

        val path = if (trimmed.startsWith("/")) trimmed else "/$trimmed"
        return "$base$path"
    }

    private fun isAbsolute(url: String): Boolean {
        return url.startsWith("data:", ignoreCase = true) ||
            url.startsWith("http://", ignoreCase = true) ||
            url.startsWith("https://", ignoreCase = true)
    }

    private fun normalizeBackendUrl(raw: String): String {
        val trimmed = raw.trim().trimEnd('/')
        if (trimmed.isEmpty()) {
            return ""
        }
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            trimmed
        } else {
            "http://$trimmed"
        }
    }
}
