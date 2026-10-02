package com.aveline.ai.mobile.utils

import android.content.Context
import android.content.res.Configuration
import android.os.Build
import android.os.LocaleList
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 支持的语言
 */
enum class AppLanguage(
    val code: String,
    val displayName: String
) {
    SYSTEM("system", "跟随系统"),
    ENGLISH("en", "English"),
    CHINESE("zh", "中文");
    
    companion object {
        fun fromCode(code: String): AppLanguage {
            return values().find { it.code == code } ?: SYSTEM
        }
    }
}

/**
 * 语言管理器
 * 
 * 管理应用语言设置和切换
 * 
 * Requirements: 25.1, 25.2, 25.3, 25.4
 */
@Singleton
class LanguageManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val appPreferences: AppPreferences
) {
    private val _currentLanguage = MutableStateFlow(getSavedLanguage())
    val currentLanguage: StateFlow<AppLanguage> = _currentLanguage.asStateFlow()
    
    init {
        // 初始化时应用保存的语言
        if (_currentLanguage.value != AppLanguage.SYSTEM) {
            applyLanguage(_currentLanguage.value)
        }
    }
    
    /**
     * 获取保存的语言设置
     */
    private fun getSavedLanguage(): AppLanguage {
        val savedCode = appPreferences.languageCode
        return if (savedCode.isEmpty()) {
            // 首次启动，检测系统语言
            detectSystemLanguage()
        } else {
            AppLanguage.fromCode(savedCode)
        }
    }
    
    /**
     * 检测系统语言
     */
    private fun detectSystemLanguage(): AppLanguage {
        val systemLocale = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            context.resources.configuration.locales[0]
        } else {
            @Suppress("DEPRECATION")
            context.resources.configuration.locale
        }
        
        return when (systemLocale.language) {
            "zh" -> AppLanguage.CHINESE
            "en" -> AppLanguage.ENGLISH
            else -> AppLanguage.ENGLISH // 默认英语
        }
    }
    
    /**
     * 设置语言
     */
    fun setLanguage(language: AppLanguage) {
        appPreferences.languageCode = language.code
        _currentLanguage.value = language
        
        if (language != AppLanguage.SYSTEM) {
            applyLanguage(language)
        }
    }
    
    /**
     * 应用语言到应用上下文
     */
    private fun applyLanguage(language: AppLanguage) {
        val locale = when (language) {
            AppLanguage.ENGLISH -> Locale.ENGLISH
            AppLanguage.CHINESE -> Locale.CHINESE
            AppLanguage.SYSTEM -> {
                // 恢复系统语言
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                    LocaleList.getDefault().get(0)
                } else {
                    @Suppress("DEPRECATION")
                    Locale.getDefault()
                }
            }
        }
        
        Locale.setDefault(locale)
        
        val config = Configuration(context.resources.configuration)
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            config.setLocales(LocaleList(locale))
        } else {
            @Suppress("DEPRECATION")
            config.locale = locale
        }
        
        @Suppress("DEPRECATION")
        context.resources.updateConfiguration(config, context.resources.displayMetrics)
    }
    
    /**
     * 获取当前 Locale
     */
    fun getCurrentLocale(): Locale {
        return when (_currentLanguage.value) {
            AppLanguage.SYSTEM -> detectSystemLanguage().let {
                when (it) {
                    AppLanguage.CHINESE -> Locale.CHINESE
                    AppLanguage.ENGLISH -> Locale.ENGLISH
                    else -> Locale.ENGLISH
                }
            }
            AppLanguage.ENGLISH -> Locale.ENGLISH
            AppLanguage.CHINESE -> Locale.CHINESE
        }
    }
    
    /**
     * 获取支持的语言列表
     */
    fun getSupportedLanguages(): List<AppLanguage> {
        return AppLanguage.values().toList()
    }
    
    /**
     * 检查是否需要重启应用以应用语言更改
     * 
     * 注意：在 Compose 中，通常不需要重启，
     * 因为字符串资源会自动更新
     */
    fun requiresRestart(): Boolean {
        return false
    }
}
