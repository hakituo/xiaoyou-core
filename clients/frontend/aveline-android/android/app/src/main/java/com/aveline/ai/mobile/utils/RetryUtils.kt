package com.aveline.ai.mobile.utils

import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import java.io.IOException
import kotlin.math.min
import kotlin.math.pow

/**
 * 重试配置
 * 
 * @property maxRetries 最大重试次数
 * @property initialDelayMs 初始延迟（毫秒）
 * @property maxDelayMs 最大延迟（毫秒）
 * @property multiplier 延迟倍数
 * @property retryableExceptions 可重试的异常类型
 */
data class RetryConfig(
    val maxRetries: Int = 3,
    val initialDelayMs: Long = 1000,
    val maxDelayMs: Long = 30000,
    val multiplier: Double = 2.0,
    val retryableExceptions: List<Class<out Exception>> = listOf(
        IOException::class.java,
        java.net.SocketTimeoutException::class.java,
        java.net.UnknownHostException::class.java
    )
) {
    companion object {
        val DEFAULT = RetryConfig()
        val AGGRESSIVE = RetryConfig(
            maxRetries = 5,
            initialDelayMs = 500,
            maxDelayMs = 60000
        )
        val CONSERVATIVE = RetryConfig(
            maxRetries = 2,
            initialDelayMs = 2000,
            maxDelayMs = 10000
        )
        val NO_RETRY = RetryConfig(maxRetries = 0)
    }
}

/**
 * 重试工具类
 * 
 * 提供指数退避重试机制
 * 
 * Requirements: 22.1, 22.2
 */
object RetryUtils {
    
    /**
     * 执行带重试的挂起函数
     * 
     * @param config 重试配置
     * @param block 要执行的代码块
     * @return 执行结果
     */
    suspend fun <T> retry(
        config: RetryConfig = RetryConfig.DEFAULT,
        block: suspend () -> T
    ): Result<T> {
        var lastException: Exception? = null
        var currentDelay = config.initialDelayMs
        
        repeat(config.maxRetries + 1) { attempt ->
            try {
                return Result.success(block())
            } catch (e: Exception) {
                lastException = e
                
                // 检查是否可重试
                if (!isRetryable(e, config) || attempt == config.maxRetries) {
                    return Result.failure(e)
                }
                
                // 等待后重试
                delay(currentDelay)
                
                // 计算下次延迟（指数退避）
                currentDelay = min(
                    (currentDelay * config.multiplier).toLong(),
                    config.maxDelayMs
                )
            }
        }
        
        return Result.failure(lastException ?: Exception("Unknown error"))
    }
    
    /**
     * 执行带重试的挂起函数（返回 Flow）
     * 
     * @param config 重试配置
     * @param block 要执行的代码块
     * @return 结果 Flow
     */
    fun <T> retryFlow(
        config: RetryConfig = RetryConfig.DEFAULT,
        block: suspend () -> T
    ): Flow<Result<T>> = flow {
        var lastException: Exception? = null
        var currentDelay = config.initialDelayMs
        
        repeat(config.maxRetries + 1) { attempt ->
            try {
                emit(Result.success(block()))
                return@flow
            } catch (e: Exception) {
                lastException = e
                
                if (!isRetryable(e, config) || attempt == config.maxRetries) {
                    emit(Result.failure(e))
                    return@flow
                }
                
                delay(currentDelay)
                currentDelay = min(
                    (currentDelay * config.multiplier).toLong(),
                    config.maxDelayMs
                )
            }
        }
        
        emit(Result.failure(lastException ?: Exception("Unknown error")))
    }
    
    /**
     * 检查异常是否可重试
     */
    private fun isRetryable(
        exception: Exception,
        config: RetryConfig
    ): Boolean {
        return config.retryableExceptions.any { clazz ->
            clazz.isInstance(exception)
        }
    }
    
    /**
     * 计算指数退避延迟
     * 
     * @param attempt 当前尝试次数（从0开始）
     * @param initialDelay 初始延迟
     * @param multiplier 倍数
     * @param maxDelay 最大延迟
     * @return 延迟时间（毫秒）
     */
    fun calculateExponentialBackoff(
        attempt: Int,
        initialDelay: Long = 1000,
        multiplier: Double = 2.0,
        maxDelay: Long = 30000
    ): Long {
        val delay = (initialDelay * multiplier.pow(attempt)).toLong()
        return min(delay, maxDelay)
    }
    
    /**
     * 默认熔断器实例(单例)。
     *
     * 修复 P0-23: 原 withCircuitBreaker 每次调用都 new CircuitBreaker,
     * 熔断状态(failureCount/isOpen)不跨调用保留,熔断器完全失效。
     * 改为使用静态单例,保证熔断状态在整个应用生命周期内累积。
     */
    private val defaultCircuitBreaker = CircuitBreaker()

    /**
     * 执行带熔断器的操作。
     *
     * 注意:使用默认的全局熔断器实例(5次失败/60秒重置)。
     * 如需独立熔断器,请自行创建 CircuitBreaker 实例并调用 execute。
     *
     * @param block 要执行的代码块
     * @return 执行结果
     */
    fun <T> withCircuitBreaker(block: () -> T): Result<T> {
        return defaultCircuitBreaker.execute(block)
    }
}

/**
 * 熔断器
 */
class CircuitBreaker(
    private val failureThreshold: Int = 5,
    private val resetTimeMs: Long = 60000
) {
    private var failureCount: Int = 0
    private var lastFailureTime: Long = 0
    private var isOpen: Boolean = false
    
    @Synchronized
    fun <T> execute(block: () -> T): Result<T> {
        // 检查是否应该重置
        if (isOpen && System.currentTimeMillis() - lastFailureTime > resetTimeMs) {
            reset()
        }
        
        // 如果熔断器打开，直接返回失败
        if (isOpen) {
            return Result.failure(Exception("Circuit breaker is open"))
        }
        
        return try {
            val result = block()
            onSuccess()
            Result.success(result)
        } catch (e: Exception) {
            onFailure()
            Result.failure(e)
        }
    }
    
    @Synchronized
    private fun onSuccess() {
        failureCount = 0
        isOpen = false
    }
    
    @Synchronized
    private fun onFailure() {
        failureCount++
        lastFailureTime = System.currentTimeMillis()
        
        if (failureCount >= failureThreshold) {
            isOpen = true
        }
    }
    
    @Synchronized
    private fun reset() {
        failureCount = 0
        isOpen = false
        lastFailureTime = 0
    }
}
