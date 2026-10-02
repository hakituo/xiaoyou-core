package com.aveline.ai.mobile.utils

/**
 * 图片 URL 解析器。
 *
 * 补全逻辑与视频等其他媒体完全一致，统一收敛到 [MediaUrlResolver]，
 * 这里只保留薄封装，避免同一套规则出现两份实现后行为漂移。
 */
object ImageUrlResolver {

    /**
     * 将后端下发的图片地址解析为 Android 端可直接加载的完整 URL。
     *
     * @param backendUrl 用户配置的后端地址，例如 "192.168.1.5:8000" 或 "http://example.com:8000"
     * @param imageUrl 后端下发的图片地址
     * @return 可直接交给 Coil 加载的地址
     */
    fun resolve(backendUrl: String, imageUrl: String): String =
        MediaUrlResolver.resolve(backendUrl, imageUrl)
}
