package com.aveline.ai.mobile.utils

import android.app.ActivityManager
import android.content.Context
import android.os.Debug
import android.os.Looper
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 性能指标数据
 * 
 * @property startupTime 启动时间（毫秒）
 * @property memoryUsage 内存使用（MB）
 * @property frameRate 帧率
 * @property messageLatency 消息延迟（毫秒）
 */
data class PerformanceMetrics(
    val startupTime: Long = 0,
    val memoryUsage: Long = 0,
    val frameRate: Float = 60f,
    val messageLatency: Long = 0,
    val cpuUsage: Float = 0f
) {
    val isStartupTimeAcceptable: Boolean
        get() = startupTime < 2000
    
    val isMemoryUsageAcceptable: Boolean
        get() = memoryUsage < 150
    
    val isFrameRateAcceptable: Boolean
        get() = frameRate >= 55f
    
    val isMessageLatencyAcceptable: Boolean
        get() = messageLatency < 500
    
    val overallScore: Int
        get() {
            var score = 100
            if (!isStartupTimeAcceptable) score -= 20
            if (!isMemoryUsageAcceptable) score -= 25
            if (!isFrameRateAcceptable) score -= 25
            if (!isMessageLatencyAcceptable) score -= 30
            return score.coerceIn(0, 100)
        }
}

/**
 * 性能监控器
 * 
 * 监控应用性能指标
 * 
 * Requirements: 21.1, 21.2, 21.4, 21.5, 21.6, 21.8
 */
@Singleton
class PerformanceMonitor @Inject constructor(
    @ApplicationContext private val context: Context
) {
    companion object {
        private const val TAG = "PerformanceMonitor"
        private const val MEMORY_WARNING_THRESHOLD = 150L * 1024 * 1024 // 150MB
        private const val STARTUP_WARNING_THRESHOLD = 2000L // 2秒
    }
    
    private val _metrics = MutableStateFlow(PerformanceMetrics())
    val metrics: StateFlow<PerformanceMetrics> = _metrics.asStateFlow()
    
    private var appStartTime: Long = 0
    
    /**
     * 记录应用启动开始
     */
    fun recordAppStart() {
        appStartTime = System.currentTimeMillis()
    }
    
    /**
     * 记录应用启动完成
     */
    fun recordAppStartupComplete() {
        if (appStartTime > 0) {
            val startupTime = System.currentTimeMillis() - appStartTime
            _metrics.value = _metrics.value.copy(startupTime = startupTime)
            
            if (startupTime > STARTUP_WARNING_THRESHOLD) {
                Log.w(TAG, "App startup time is slow: ${startupTime}ms")
            }
        }
    }
    
    /**
     * 记录消息发送延迟
     */
    fun recordMessageLatency(sendTime: Long, responseTime: Long) {
        val latency = responseTime - sendTime
        _metrics.value = _metrics.value.copy(messageLatency = latency)
    }
    
    /**
     * 更新内存使用
     */
    fun updateMemoryUsage() {
        val memoryInfo = Debug.MemoryInfo()
        Debug.getMemoryInfo(memoryInfo)

        val totalMemoryKB = memoryInfo.totalPrivateDirty.toLong()
        val memoryMB = totalMemoryKB / 1024

        _metrics.value = _metrics.value.copy(memoryUsage = memoryMB)

        if (totalMemoryKB * 1024 > MEMORY_WARNING_THRESHOLD) {
            Log.w(TAG, "Memory usage is high: ${memoryMB}MB")
        }
    }
    
    /**
     * 更新帧率
     */
    fun updateFrameRate(frameRate: Float) {
        _metrics.value = _metrics.value.copy(frameRate = frameRate)
    }
    
    /**
     * 获取当前内存使用
     */
    fun getCurrentMemoryUsage(): Long {
        val memoryInfo = Debug.MemoryInfo()
        Debug.getMemoryInfo(memoryInfo)
        return memoryInfo.totalPrivateDirty.toLong() / 1024
    }
    
    /**
     * 检查是否内存不足
     */
    fun isMemoryLow(): Boolean {
        val activityManager = context.getSystemService(Context.ACTIVITY_SERVICE) 
            as android.app.ActivityManager
        val memoryInfo = android.app.ActivityManager.MemoryInfo()
        activityManager.getMemoryInfo(memoryInfo)
        return memoryInfo.lowMemory
    }
    
    /**
     * 获取可用内存
     */
    fun getAvailableMemory(): Long {
        val activityManager = context.getSystemService(Context.ACTIVITY_SERVICE) 
            as android.app.ActivityManager
        val memoryInfo = android.app.ActivityManager.MemoryInfo()
        activityManager.getMemoryInfo(memoryInfo)
        return memoryInfo.availMem / (1024 * 1024) // MB
    }
    
    /**
     * 触发 GC（仅用于测试）
     */
    fun triggerGC() {
        System.gc()
    }
    
    /**
     * 获取线程信息
     */
    fun getThreadInfo(): String {
        val threads = Thread.getAllStackTraces().keys
        return "Active threads: ${threads.size}"
    }
    
    /**
     * 检查是否在主线程
     */
    fun isMainThread(): Boolean {
        return Looper.myLooper() == Looper.getMainLooper()
    }
    
    /**
     * 记录操作耗时
     */
    fun <T> measureTime(operation: String, block: () -> T): T {
        val start = System.nanoTime()
        val result = block()
        val elapsed = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - start)
        
        if (elapsed > 100) {
            Log.d(TAG, "$operation took ${elapsed}ms")
        }
        
        return result
    }
    
    /**
     * 获取性能报告
     */
    fun getPerformanceReport(): String {
        val metrics = _metrics.value
        return buildString {
            appendLine("=== Performance Report ===")
            appendLine("Startup Time: ${metrics.startupTime}ms ${if (metrics.isStartupTimeAcceptable) "✓" else "✗"}")
            appendLine("Memory Usage: ${metrics.memoryUsage}MB ${if (metrics.isMemoryUsageAcceptable) "✓" else "✗"}")
            appendLine("Frame Rate: ${metrics.frameRate}fps ${if (metrics.isFrameRateAcceptable) "✓" else "✗"}")
            appendLine("Message Latency: ${metrics.messageLatency}ms ${if (metrics.isMessageLatencyAcceptable) "✓" else "✗"}")
            appendLine("Overall Score: ${metrics.overallScore}/100")
            appendLine("Memory Low: ${isMemoryLow()}")
            appendLine("Available Memory: ${getAvailableMemory()}MB")
        }
    }
}
