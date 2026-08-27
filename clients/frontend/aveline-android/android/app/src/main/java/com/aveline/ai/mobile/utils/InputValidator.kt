package com.aveline.ai.mobile.utils

import android.net.Uri
import android.util.Patterns
import java.io.File
import java.util.regex.Pattern

/**
 * 输入验证器
 * 
 * 提供输入验证和清理功能
 * 
 * Requirements: 24.1
 */
object InputValidator {
    
    // 文件名非法字符
    private val FILENAME_INVALID_CHARS = Pattern.compile("[\\\\/:*?\"<>|]")
    
    // 路径遍历模式
    private val PATH_TRAVERSAL = Pattern.compile("(\\.\\./)|(\\.\\\\)")
    
    // 最大输入长度
    const val MAX_MESSAGE_LENGTH = 10000
    const val MAX_SESSION_TITLE_LENGTH = 100
    const val MAX_FILENAME_LENGTH = 255
    const val MAX_URL_LENGTH = 2048
    
    /**
     * 验证消息内容
     * 
     * @param message 消息内容
     * @return 验证结果
     */
    fun validateMessage(message: String): ValidationResult {
        if (message.isBlank()) {
            return ValidationResult.Error("消息不能为空")
        }
        
        if (message.length > MAX_MESSAGE_LENGTH) {
            return ValidationResult.Error("消息长度不能超过 $MAX_MESSAGE_LENGTH 字符")
        }
        
        // 检查危险内容（可选）
        if (containsDangerousContent(message)) {
            return ValidationResult.Error("消息包含不允许的内容")
        }
        
        return ValidationResult.Success
    }
    
    /**
     * 验证会话标题
     */
    fun validateSessionTitle(title: String): ValidationResult {
        if (title.isBlank()) {
            return ValidationResult.Error("标题不能为空")
        }
        
        if (title.length > MAX_SESSION_TITLE_LENGTH) {
            return ValidationResult.Error("标题长度不能超过 $MAX_SESSION_TITLE_LENGTH 字符")
        }
        
        return ValidationResult.Success
    }
    
    /**
     * 验证文件名
     */
    fun validateFilename(filename: String): ValidationResult {
        if (filename.isBlank()) {
            return ValidationResult.Error("文件名不能为空")
        }
        
        if (filename.length > MAX_FILENAME_LENGTH) {
            return ValidationResult.Error("文件名长度不能超过 $MAX_FILENAME_LENGTH 字符")
        }
        
        if (FILENAME_INVALID_CHARS.matcher(filename).find()) {
            return ValidationResult.Error("文件名包含非法字符")
        }
        
        // 检查保留文件名
        val reservedNames = listOf("CON", "PRN", "AUX", "NUL", 
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9")
        
        val nameWithoutExt = filename.substringBeforeLast('.').uppercase()
        if (nameWithoutExt in reservedNames) {
            return ValidationResult.Error("文件名不能使用保留名称")
        }
        
        return ValidationResult.Success
    }
    
    /**
     * 验证路径
     */
    fun validatePath(path: String): ValidationResult {
        if (path.isBlank()) {
            return ValidationResult.Error("路径不能为空")
        }
        
        // 检查路径遍历攻击
        if (PATH_TRAVERSAL.matcher(path).find()) {
            return ValidationResult.Error("路径包含非法的遍历字符")
        }
        
        return ValidationResult.Success
    }
    
    /**
     * 验证 URL
     */
    fun validateUrl(url: String): ValidationResult {
        if (url.isBlank()) {
            return ValidationResult.Error("URL 不能为空")
        }
        
        if (url.length > MAX_URL_LENGTH) {
            return ValidationResult.Error("URL 长度不能超过 $MAX_URL_LENGTH 字符")
        }
        
        if (!Patterns.WEB_URL.matcher(url).matches()) {
            return ValidationResult.Error("URL 格式不正确")
        }
        
        // 检查协议
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            return ValidationResult.Error("URL 必须以 http:// 或 https:// 开头")
        }
        
        return ValidationResult.Success
    }
    
    /**
     * 验证后端 URL
     */
    fun validateBackendUrl(url: String): ValidationResult {
        val baseValidation = validateUrl(url)
        if (baseValidation is ValidationResult.Error) {
            return baseValidation
        }
        
        // 建议使用 HTTPS
        if (url.startsWith("http://") && !url.contains("localhost") && !url.contains("127.0.0.1")) {
            return ValidationResult.Warning("建议使用 HTTPS 协议以提高安全性")
        }
        
        return ValidationResult.Success
    }
    
    /**
     * 验证深度链接
     */
    fun validateDeepLink(uri: Uri): ValidationResult {
        // 检查协议
        if (uri.scheme != "aveline") {
            return ValidationResult.Error("不支持的深度链接协议")
        }
        
        // 检查路径
        val path = uri.host ?: uri.path?.removePrefix("/") ?: ""
        val validPaths = listOf("chat", "status", "shop", "settings", 
            "plugins", "memory", "study", "persona")
        
        if (path.isNotEmpty() && path !in validPaths) {
            return ValidationResult.Error("无效的深度链接路径")
        }
        
        // 验证查询参数
        uri.queryParameterNames.forEach { param ->
            val value = uri.getQueryParameter(param) ?: ""
            if (containsDangerousContent(value)) {
                return ValidationResult.Error("深度链接参数包含危险内容")
            }
        }
        
        return ValidationResult.Success
    }
    
    /**
     * 验证用户 ID
     */
    fun validateUserId(userId: String): ValidationResult {
        if (userId.isBlank()) {
            return ValidationResult.Error("用户 ID 不能为空")
        }
        
        // 检查格式（字母、数字、下划线、横线）
        val pattern = Pattern.compile("^[a-zA-Z0-9_-]+$")
        if (!pattern.matcher(userId).matches()) {
            return ValidationResult.Error("用户 ID 格式不正确")
        }
        
        if (userId.length > 50) {
            return ValidationResult.Error("用户 ID 长度不能超过 50 字符")
        }
        
        return ValidationResult.Success
    }
    
    /**
     * 清理文件名
     */
    fun sanitizeFilename(filename: String): String {
        return filename
            .replace(FILENAME_INVALID_CHARS.toRegex(), "_")
            .replace("\\s+".toRegex(), "_")
            .take(MAX_FILENAME_LENGTH)
    }
    
    /**
     * 清理路径
     */
    fun sanitizePath(path: String): String {
        return path
            .replace(PATH_TRAVERSAL.toRegex(), "")
            .replace("\\\\".toRegex(), "/")
    }
    
    /**
     * 清理用户输入
     */
    fun sanitizeInput(input: String, maxLength: Int = MAX_MESSAGE_LENGTH): String {
        return input
            .trim()
            .replace("\\p{C}".toRegex(), "") // 移除控制字符
            .take(maxLength)
    }
    
    /**
     * 检查是否包含危险内容
     */
    private fun containsDangerousContent(content: String): Boolean {
        // 检查脚本注入
        val scriptPattern = Pattern.compile("<script|javascript:|on\\w+\\s*=", Pattern.CASE_INSENSITIVE)
        if (scriptPattern.matcher(content).find()) {
            return true
        }
        
        // 检查 SQL 注入（基本检查）
        val sqlPattern = Pattern.compile("(?i)(union|select|insert|update|delete|drop|alter)\\s+", Pattern.CASE_INSENSITIVE)
        if (sqlPattern.matcher(content).find()) {
            return true
        }
        
        return false
    }
    
    /**
     * 验证文件类型
     */
    fun validateFileType(mimeType: String, allowedTypes: List<String>): Boolean {
        return allowedTypes.any { allowed ->
            mimeType.startsWith(allowed) || mimeType == allowed
        }
    }
    
    /**
     * 验证文件大小
     */
    fun validateFileSize(size: Long, maxSizeMB: Int): ValidationResult {
        val maxSizeBytes = maxSizeMB.toLong() * 1024 * 1024
        
        if (size > maxSizeBytes) {
            return ValidationResult.Error("文件大小不能超过 ${maxSizeMB}MB")
        }
        
        return ValidationResult.Success
    }
}

/**
 * 验证结果
 */
sealed class ValidationResult {
    object Success : ValidationResult()
    data class Warning(val message: String) : ValidationResult()
    data class Error(val message: String) : ValidationResult()
    
    val isValid: Boolean
        get() = this is Success || this is Warning
    
    val hasError: Boolean
        get() = this is Error
    
    val messageOrNull: String?
        get() = when (this) {
            is Success -> null
            is Warning -> message
            is Error -> message
        }
}
