@file:Suppress("DEPRECATION")

package com.aveline.ai.mobile.utils

import android.content.Context
import android.content.pm.ApplicationInfo
import coil.ImageLoader
import coil.disk.DiskCache
import coil.memory.MemoryCache
import coil.request.CachePolicy
import coil.util.DebugLogger
import dagger.hilt.android.qualifiers.ApplicationContext
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Coil 图片加载配置
 * 
 * 配置图片加载、缓存策略
 * 
 * Requirements: 21.7
 */
@Singleton
class CoilImageLoader @Inject constructor(
    @ApplicationContext private val context: Context
) {
    companion object {
        // 内存缓存大小：50MB
        private const val MEMORY_CACHE_SIZE = 50L * 1024 * 1024
        
        // 磁盘缓存大小：100MB
        private const val DISK_CACHE_SIZE = 100L * 1024 * 1024
        
        // 网络超时
        private const val NETWORK_TIMEOUT_SECONDS = 30L
    }
    
    /**
     * 创建配置好的 ImageLoader
     */
    fun createImageLoader(okHttpClient: OkHttpClient): ImageLoader {
        val isDebug = (context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
        return ImageLoader.Builder(context)
            // 内存缓存
            .memoryCache {
                MemoryCache.Builder(context)
                    .maxSizeBytes(MEMORY_CACHE_SIZE.toInt())
                    .build()
            }
            // 磁盘缓存
            .diskCache {
                DiskCache.Builder()
                    .directory(context.cacheDir.resolve("image_cache"))
                    .maxSizeBytes(DISK_CACHE_SIZE)
                    .build()
            }
            // 网络配置
            .okHttpClient {
                okHttpClient.newBuilder()
                    .connectTimeout(NETWORK_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                    .readTimeout(NETWORK_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                    .writeTimeout(NETWORK_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                    .build()
            }
            // 缓存策略
            .memoryCachePolicy(CachePolicy.ENABLED)
            .diskCachePolicy(CachePolicy.ENABLED)
            .networkCachePolicy(CachePolicy.ENABLED)
            // 交叉淡入淡出
            .crossfade(true)
            .crossfade(300)
            // 错误占位图
            .error(android.R.drawable.ic_menu_report_image)
            // 占位图
            .placeholder(android.R.drawable.ic_menu_gallery)
            // 日志（仅调试模式）
            .apply {
                if (isDebug) {
                    logger(DebugLogger())
                }
            }
            .build()
    }
    
    /**
     * 获取内存缓存大小
     */
    fun getMemoryCacheSize(): Long = MEMORY_CACHE_SIZE
    
    /**
     * 获取磁盘缓存大小
     */
    fun getDiskCacheSize(): Long = DISK_CACHE_SIZE
    
    /**
     * 清除内存缓存
     */
    fun clearMemoryCache(imageLoader: ImageLoader) {
        imageLoader.memoryCache?.clear()
    }
    
    /**
     * 清除磁盘缓存
     */
    @OptIn(coil.annotation.ExperimentalCoilApi::class)
    fun clearDiskCache(imageLoader: ImageLoader) {
        imageLoader.diskCache?.clear()
    }
    
    /**
     * 清除所有缓存
     */
    fun clearAllCache(imageLoader: ImageLoader) {
        clearMemoryCache(imageLoader)
        clearDiskCache(imageLoader)
    }
    
    /**
     * 获取缓存统计
     */
    @OptIn(coil.annotation.ExperimentalCoilApi::class)
    fun getCacheStats(imageLoader: ImageLoader): CacheStats {
        val memoryCache = imageLoader.memoryCache
        val diskCache = imageLoader.diskCache
        
        return CacheStats(
            memoryCacheSize = memoryCache?.maxSize?.toLong() ?: 0L,
            memoryCacheUsed = memoryCache?.size?.toLong() ?: 0L,
            diskCacheSize = diskCache?.maxSize?.toLong() ?: 0L,
            diskCacheUsed = diskCache?.size?.toLong() ?: 0L
        )
    }
}

/**
 * 缓存统计
 */
data class CacheStats(
    val memoryCacheSize: Long,
    val memoryCacheUsed: Long,
    val diskCacheSize: Long,
    val diskCacheUsed: Long
) {
    val memoryCacheUsedPercent: Float
        get() = if (memoryCacheSize > 0) memoryCacheUsed.toFloat() / memoryCacheSize else 0f
    
    val diskCacheUsedPercent: Float
        get() = if (diskCacheSize > 0) diskCacheUsed.toFloat() / diskCacheSize else 0f
}
