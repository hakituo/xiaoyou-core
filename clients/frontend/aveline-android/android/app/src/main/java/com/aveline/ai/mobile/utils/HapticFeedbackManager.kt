package com.aveline.ai.mobile.utils

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.core.content.getSystemService
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 触觉反馈类型
 */
enum class HapticFeedbackType {
    LIGHT,      // 轻触反馈
    MEDIUM,     // 中等反馈
    HEAVY,      // 重度反馈
    SUCCESS,    // 成功反馈
    ERROR,      // 错误反馈
    WARNING,    // 警告反馈
    TICK,       // 滴答反馈
    CLICK       // 点击反馈
}

/**
 * 触觉反馈管理器
 * 
 * 提供统一的触觉反馈接口
 * 
 * Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8
 */
@Singleton
class HapticFeedbackManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val appPreferences: AppPreferences
) {
    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        context.getSystemService<VibratorManager>()?.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService<Vibrator>()
    }
    
    /**
     * 检查设备是否支持触觉反馈
     */
    fun hasVibrator(): Boolean {
        return vibrator?.hasVibrator() ?: false
    }
    
    /**
     * 检查触觉反馈是否启用
     */
    fun isHapticEnabled(): Boolean {
        return appPreferences.hapticFeedbackEnabled
    }
    
    /**
     * 设置触觉反馈开关
     */
    fun setHapticEnabled(enabled: Boolean) {
        appPreferences.hapticFeedbackEnabled = enabled
    }
    
    /**
     * 执行触觉反馈
     * 
     * @param type 反馈类型
     */
    fun performHapticFeedback(type: HapticFeedbackType) {
        if (!isHapticEnabled() || !hasVibrator()) return
        
        when (type) {
            HapticFeedbackType.LIGHT -> performLight()
            HapticFeedbackType.MEDIUM -> performMedium()
            HapticFeedbackType.HEAVY -> performHeavy()
            HapticFeedbackType.SUCCESS -> performSuccess()
            HapticFeedbackType.ERROR -> performError()
            HapticFeedbackType.WARNING -> performWarning()
            HapticFeedbackType.TICK -> performTick()
            HapticFeedbackType.CLICK -> performClick()
        }
    }
    
    /**
     * 轻触反馈
     * 用于：按钮点击、列表项选择
     */
    fun light() {
        if (!isHapticEnabled()) return
        performLight()
    }
    
    /**
     * 中等反馈
     * 用于：标签切换、消息发送
     */
    fun medium() {
        if (!isHapticEnabled()) return
        performMedium()
    }
    
    /**
     * 重度反馈
     * 用于：删除操作、重要确认
     */
    fun heavy() {
        if (!isHapticEnabled()) return
        performHeavy()
    }
    
    /**
     * 成功反馈
     * 用于：操作成功完成
     */
    fun success() {
        if (!isHapticEnabled()) return
        performSuccess()
    }
    
    /**
     * 错误反馈
     * 用于：操作失败
     */
    fun error() {
        if (!isHapticEnabled()) return
        performError()
    }
    
    /**
     * 警告反馈
     * 用于：推送通知、状态警告
     */
    fun warning() {
        if (!isHapticEnabled()) return
        performWarning()
    }
    
    /**
     * 滴答反馈
     * 用于：滑块拖动、滚动
     */
    fun tick() {
        if (!isHapticEnabled()) return
        performTick()
    }
    
    /**
     * 点击反馈
     * 用于：常规点击
     */
    fun click() {
        if (!isHapticEnabled()) return
        performClick()
    }
    
    private fun performLight() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator?.vibrate(
                VibrationEffect.createOneShot(10, VibrationEffect.DEFAULT_AMPLITUDE)
            )
        } else {
            @Suppress("DEPRECATION")
            vibrator?.vibrate(10)
        }
    }
    
    private fun performMedium() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator?.vibrate(
                VibrationEffect.createOneShot(20, VibrationEffect.DEFAULT_AMPLITUDE)
            )
        } else {
            @Suppress("DEPRECATION")
            vibrator?.vibrate(20)
        }
    }
    
    private fun performHeavy() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator?.vibrate(
                VibrationEffect.createOneShot(40, VibrationEffect.DEFAULT_AMPLITUDE)
            )
        } else {
            @Suppress("DEPRECATION")
            vibrator?.vibrate(40)
        }
    }
    
    private fun performSuccess() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            vibrator?.vibrate(
                VibrationEffect.createPredefined(VibrationEffect.EFFECT_TICK)
            )
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator?.vibrate(
                VibrationEffect.createWaveform(
                    longArrayOf(0, 10, 50, 10),
                    intArrayOf(0, 100, 0, 100),
                    -1
                )
            )
        } else {
            @Suppress("DEPRECATION")
            vibrator?.vibrate(longArrayOf(0, 10, 50, 10), -1)
        }
    }
    
    private fun performError() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            vibrator?.vibrate(
                VibrationEffect.createPredefined(VibrationEffect.EFFECT_DOUBLE_CLICK)
            )
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator?.vibrate(
                VibrationEffect.createWaveform(
                    longArrayOf(0, 30, 50, 30),
                    intArrayOf(0, 200, 0, 200),
                    -1
                )
            )
        } else {
            @Suppress("DEPRECATION")
            vibrator?.vibrate(longArrayOf(0, 30, 50, 30), -1)
        }
    }
    
    private fun performWarning() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator?.vibrate(
                VibrationEffect.createWaveform(
                    longArrayOf(0, 50, 100, 50),
                    intArrayOf(0, 150, 0, 150),
                    -1
                )
            )
        } else {
            @Suppress("DEPRECATION")
            vibrator?.vibrate(longArrayOf(0, 50, 100, 50), -1)
        }
    }
    
    private fun performTick() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            vibrator?.vibrate(
                VibrationEffect.createPredefined(VibrationEffect.EFFECT_TICK)
            )
        } else {
            performLight()
        }
    }
    
    private fun performClick() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            vibrator?.vibrate(
                VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK)
            )
        } else {
            performLight()
        }
    }
}
