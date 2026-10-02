package com.aveline.ai.mobile.utils

import android.content.Context
import coil.request.ImageRequest

/**
 * 统一构造 `AsyncImage` 的 model。
 *
 * Coil 2.x 没有 data URI 对应的 Fetcher（Coil 3 才有 `DataUriFetcher`），
 * 后端下发的 `image_base64`、表情包这类 `data:image/...;base64,...` 地址
 * 若直接当 URL 传给 `AsyncImage`，会因为找不到可用 Fetcher 直接显示
 * error 占位图（右下角三角感叹号图标）。
 *
 * 因此遇到 data URI 时先解码成 ByteArray，交给 Coil 的
 * `ByteArrayMapper` → `ByteBufferFetcher` 正常解码；其它地址原样返回。
 */
object CoilImageModel {

    fun build(context: Context, url: String): Any {
        val bytes = DataUriImage.decode(url) ?: return url
        return ImageRequest.Builder(context)
            .data(bytes)
            // data URI 很长（几十到几百 KB），直接拿原文当缓存 key 太占内存，取哈希即可
            .memoryCacheKey("data-uri:${url.hashCode()}")
            .build()
    }
}
