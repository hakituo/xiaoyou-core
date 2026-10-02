package com.aveline.ai.mobile.utils

import android.content.Context
import android.content.res.Configuration
import android.os.Build
import android.provider.Settings
import android.view.accessibility.AccessibilityManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 无障碍设置状态
 * 
 * @property isTalkBackEnabled TalkBack 是否启用
 * @property isHighContrastEnabled 高对比度模式是否启用
 * @property isReduceMotionEnabled 减少动画是否启用
 * @property fontScale 系统字体缩放比例
 * @property isScreenReaderEnabled 屏幕阅读器是否启用
 */
data class AccessibilityState(
    val isTalkBackEnabled: Boolean = false,
    val isHighContrastEnabled: Boolean = false,
    val isReduceMotionEnabled: Boolean = false,
    val fontScale: Float = 1.0f,
    val isScreenReaderEnabled: Boolean = false
) {
    val needsAccessibilitySupport: Boolean
        get() = isTalkBackEnabled || isScreenReaderEnabled || isHighContrastEnabled
    
    val shouldReduceAnimations: Boolean
        get() = isReduceMotionEnabled || isScreenReaderEnabled
    
    val needsLargerTouchTargets: Boolean
        get() = isScreenReaderEnabled
}

/**
 * 无障碍管理器
 * 
 * 管理应用的无障碍功能设置
 * 
 * Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6, 26.7
 */
@Singleton
class AccessibilityManager @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private val accessibilityManager: AccessibilityManager? = 
        context.getSystemService(Context.ACCESSIBILITY_SERVICE) as? AccessibilityManager
    
    private val _accessibilityState = MutableStateFlow(getCurrentState())
    val accessibilityState: StateFlow<AccessibilityState> = _accessibilityState.asStateFlow()
    
    /**
     * 获取当前无障碍状态
     */
    private fun getCurrentState(): AccessibilityState {
        return AccessibilityState(
            isTalkBackEnabled = isTalkBackEnabled(),
            isHighContrastEnabled = isHighContrastEnabled(),
            isReduceMotionEnabled = isReduceMotionEnabled(),
            fontScale = getFontScale(),
            isScreenReaderEnabled = isScreenReaderEnabled()
        )
    }
    
    /**
     * 刷新无障碍状态
     */
    fun refreshState() {
        _accessibilityState.value = getCurrentState()
    }
    
    /**
     * 检查 TalkBack 是否启用
     */
    private fun isTalkBackEnabled(): Boolean {
        return accessibilityManager?.isTouchExplorationEnabled ?: false
    }
    
    /**
     * 检查屏幕阅读器是否启用
     */
    private fun isScreenReaderEnabled(): Boolean {
        return accessibilityManager?.let {
            it.isTouchExplorationEnabled || it.isEnabled
        } ?: false
    }
    
    /**
     * 检查高对比度模式是否启用
     */
    private fun isHighContrastEnabled(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            context.resources.configuration.isNightModeActive &&
            Settings.Secure.getInt(
                context.contentResolver,
                Settings.Secure.ACCESSIBILITY_DISPLAY_INVERSION_ENABLED,
                0
            ) == 1
        } else {
            Settings.Secure.getInt(
                context.contentResolver,
                Settings.Secure.ACCESSIBILITY_DISPLAY_INVERSION_ENABLED,
                0
            ) == 1
        }
    }
    
    /**
     * 检查减少动画是否启用
     */
    private fun isReduceMotionEnabled(): Boolean {
        return Settings.Global.getFloat(
            context.contentResolver,
            Settings.Global.ANIMATOR_DURATION_SCALE,
            1.0f
        ) == 0.0f
    }
    
    /**
     * 获取系统字体缩放比例
     */
    private fun getFontScale(): Float {
        return context.resources.configuration.fontScale
    }
    
    /**
     * 检查是否需要无障碍支持
     */
    fun needsAccessibilitySupport(): Boolean {
        return _accessibilityState.value.needsAccessibilitySupport
    }
    
    /**
     * 检查是否应该减少动画
     */
    fun shouldReduceAnimations(): Boolean {
        return _accessibilityState.value.shouldReduceAnimations
    }
    
    /**
     * 检查是否需要更大的触摸目标
     */
    fun needsLargerTouchTargets(): Boolean {
        return _accessibilityState.value.needsLargerTouchTargets
    }
    
    /**
     * 获取推荐的动画持续时间
     * 
     * @param defaultDuration 默认持续时间
     * @return 调整后的持续时间
     */
    fun getRecommendedAnimationDuration(defaultDuration: Int): Int {
        return if (shouldReduceAnimations()) {
            0
        } else {
            defaultDuration
        }
    }
    
    /**
     * 获取推荐的触摸目标大小
     * 
     * @param defaultSize 默认大小（dp）
     * @return 调整后的大小（dp）
     */
    fun getRecommendedTouchTargetSize(defaultSize: Int): Int {
        return if (needsLargerTouchTargets()) {
            maxOf(defaultSize, 48)
        } else {
            maxOf(defaultSize, 44)
        }
    }
    
    /**
     * 检查颜色对比度是否符合 WCAG 标准
     * 
     * @param foreground 前景色
     * @param background 背景色
     * @return 对比度比例
     */
    fun calculateContrastRatio(foreground: Int, background: Int): Float {
        val fgLuminance = calculateLuminance(foreground)
        val bgLuminance = calculateLuminance(background)
        
        val lighter = maxOf(fgLuminance, bgLuminance)
        val darker = minOf(fgLuminance, bgLuminance)
        
        return (lighter + 0.05f) / (darker + 0.05f)
    }
    
    /**
     * 计算颜色的相对亮度
     */
    private fun calculateLuminance(color: Int): Float {
        val r = (color shr 16 and 0xFF) / 255.0f
        val g = (color shr 8 and 0xFF) / 255.0f
        val b = (color and 0xFF) / 255.0f
        
        val rLinear = if (r <= 0.03928f) r / 12.92f else ((r + 0.055f) / 1.055f).pow(2.4f)
        val gLinear = if (g <= 0.03928f) g / 12.92f else ((g + 0.055f) / 1.055f).pow(2.4f)
        val bLinear = if (b <= 0.03928f) b / 12.92f else ((b + 0.055f) / 1.055f).pow(2.4f)
        
        return 0.2126f * rLinear + 0.7152f * gLinear + 0.0722f * bLinear
    }
    
    private fun Float.pow(exp: Float): Float {
        return Math.pow(this.toDouble(), exp.toDouble()).toFloat()
    }
    
    /**
     * 检查对比度是否符合 WCAG AA 标准
     * 
     * @param contrastRatio 对比度比例
     * @param isLargeText 是否为大文本
     * @return 是否符合标准
     */
    fun meetsWCAGAA(contrastRatio: Float, isLargeText: Boolean = false): Boolean {
        val threshold = if (isLargeText) 3.0f else 4.5f
        return contrastRatio >= threshold
    }
}

/**
 * 扩展属性：检查是否为夜间模式
 */
val Configuration.isNightModeActive: Boolean
    get() = (uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
