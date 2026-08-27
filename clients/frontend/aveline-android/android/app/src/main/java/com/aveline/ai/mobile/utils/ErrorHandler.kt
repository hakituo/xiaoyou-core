package com.aveline.ai.mobile.utils

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import retrofit2.HttpException
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 错误类型
 */
sealed class AppError {
    data class NetworkError(
        val code: Int = 0,
        val message: String = "",
        val retryable: Boolean = true,
        val retryAfterSeconds: Int = 5
    ) : AppError()
    
    data class HttpError(
        val code: Int,
        val message: String,
        val retryable: Boolean = false,
        val retryAfterSeconds: Int = 5
    ) : AppError()
    
    data class AuthError(
        val message: String
    ) : AppError()
    
    data class PermissionError(
        val permission: String
    ) : AppError()
    
    data class DataError(
        val message: String,
        val retryable: Boolean = false,
        val retryAfterSeconds: Int = 5
    ) : AppError()
    
    data class UnknownError(
        val throwable: Throwable?
    ) : AppError()
}

/**
 * 错误处理器
 * 
 * 统一处理应用中的各种错误
 * 
 * Requirements: 22.1, 22.2, 22.3, 22.8
 */
@Singleton
class ErrorHandler @Inject constructor(
    @ApplicationContext private val context: Context
) {
    /**
     * 解析异常为应用错误
     */
    fun parseError(throwable: Throwable): AppError {
        return when (throwable) {
            is HttpException -> parseHttpException(throwable)
            is UnknownHostException -> AppError.NetworkError(
                message = "无法连接到服务器，请检查网络连接"
            )
            is SocketTimeoutException -> AppError.NetworkError(
                message = "连接超时，请稍后重试"
            )
            is IOException -> AppError.NetworkError(
                message = "网络错误: ${throwable.message}"
            )
            is SecurityException -> AppError.PermissionError(
                permission = "unknown"
            )
            else -> AppError.UnknownError(throwable)
        }
    }
    
    /**
     * 解析 HTTP 异常
     */
    private fun parseHttpException(exception: HttpException): AppError {
        return when (exception.code()) {
            400 -> AppError.HttpError(
                code = 400,
                message = "请求参数错误"
            )
            401 -> AppError.AuthError(
                message = "未授权，请重新登录"
            )
            403 -> AppError.AuthError(
                message = "权限不足"
            )
            404 -> AppError.HttpError(
                code = 404,
                message = "请求的资源不存在"
            )
            429 -> AppError.HttpError(
                code = 429,
                message = "请求过于频繁，请稍后重试"
            )
            in 500..599 -> AppError.HttpError(
                code = exception.code(),
                message = "服务器错误，请稍后重试"
            )
            else -> AppError.HttpError(
                code = exception.code(),
                message = exception.message() ?: "未知错误"
            )
        }
    }
    
    /**
     * 获取用户友好的错误消息
     */
    fun getErrorMessage(error: AppError): String {
        return when (error) {
            is AppError.NetworkError -> error.message.ifEmpty {
                "网络连接失败"
            }
            is AppError.HttpError -> error.message
            is AppError.AuthError -> error.message
            is AppError.PermissionError -> "缺少必要权限: ${error.permission}"
            is AppError.DataError -> error.message
            is AppError.UnknownError -> error.throwable?.message ?: "发生未知错误"
        }
    }
    
    /**
     * 判断错误是否可重试
     * Uses the retryable field from backend response when available,
     * falls back to code-based heuristics.
     */
    fun isRetryable(error: AppError): Boolean {
        return when (error) {
            is AppError.NetworkError -> error.retryable
            is AppError.HttpError -> error.retryable || error.code in listOf(429, 500, 502, 503, 504)
            is AppError.AuthError -> false
            is AppError.PermissionError -> false
            is AppError.DataError -> error.retryable
            is AppError.UnknownError -> false
        }
    }
    
    /**
     * 获取建议的重试延迟（秒）
     * Uses retryAfterSeconds from backend when available.
     */
    fun getRetryAfterSeconds(error: AppError): Int {
        return when (error) {
            is AppError.NetworkError -> error.retryAfterSeconds
            is AppError.HttpError -> error.retryAfterSeconds
            is AppError.DataError -> error.retryAfterSeconds
            else -> 5
        }
    }
    
    /**
     * 判断是否需要重新登录
     */
    fun requiresReauth(error: AppError): Boolean {
        return error is AppError.AuthError
    }
    
    /**
     * 判断是否为网络错误
     */
    fun isNetworkError(error: AppError): Boolean {
        return error is AppError.NetworkError
    }
    
    /**
     * 判断是否为权限错误
     */
    fun isPermissionError(error: AppError): Boolean {
        return error is AppError.PermissionError
    }
}
