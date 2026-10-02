package com.aveline.ai.mobile.services

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.provider.Settings
import com.aveline.ai.mobile.domain.models.PhoneAction
import com.aveline.ai.mobile.domain.models.PhoneActionResult
import kotlinx.serialization.json.JsonPrimitive

/**
 * 通知相关动作执行器
 *
 * 从 PhoneActionExecutor 中提取的通知相关逻辑，负责：
 * - 勿扰模式（DND）的开启与关闭
 *
 * 通过构造函数接收应用上下文，用于获取 NotificationManager 等系统服务。
 *
 * @property context 应用上下文
 */
class NotificationActionExecutor(
    private val context: Context
) {

    /**
     * 设置勿扰模式
     *
     * 需要通知策略访问权限。若未授权，会打开对应的设置页面引导用户授权；
     * 已授权时，根据 [action.enable] 切换为优先级打扰过滤或全部允许。
     *
     * @param action 勿扰模式设置动作
     * @return 执行结果
     */
    fun setDndMode(action: PhoneAction.SetDndMode): PhoneActionResult {
        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        if (!notificationManager.isNotificationPolicyAccessGranted) {
            val intent = Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
            return PhoneActionResult(
                actionId = action.actionId,
                success = false,
                resultType = "dnd_permission_needed",
                error = "需要勿扰模式权限，已打开设置页面"
            )
        }

        if (action.enable) {
            notificationManager.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_PRIORITY)
        } else {
            notificationManager.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_ALL)
        }

        return PhoneActionResult(
            actionId = action.actionId,
            success = true,
            resultType = "dnd_mode_set",
            data = mapOf("enabled" to JsonPrimitive(action.enable))
        )
    }
}
