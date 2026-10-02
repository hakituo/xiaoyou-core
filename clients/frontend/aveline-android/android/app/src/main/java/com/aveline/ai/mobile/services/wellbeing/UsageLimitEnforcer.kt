package com.aveline.ai.mobile.services.wellbeing

import android.content.Context
import android.util.Log
import com.aveline.ai.mobile.services.AvelineAccessibilityService
import com.aveline.ai.mobile.services.AvelineNotificationManager
import com.aveline.ai.mobile.services.SystemControlExecutor
import com.aveline.ai.mobile.services.wellbeing.SessionLimiter.Companion.formatDuration
import com.aveline.ai.mobile.utils.SelfPackageGuard
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.delay
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 限额拦截的统一执行器。
 *
 * ```
 * LimitDecision.BLOCK
 *        ↓
 *  回桌面 (无障碍)
 *        ↓
 *  Shizuku force-stop
 *        ↓
 *    本地通知
 * ```
 *
 * 无障碍服务 (实时) 与 15 分钟 Worker (兜底) 共用这里, 保证两条路径的行为完全一致。
 *
 * 注意: 无障碍权限本身不能 force-stop 前台应用, 真正强停依赖 Shizuku;
 * 没有 Shizuku 时退化为"先回桌面再 kill 后台进程", 并在通知里如实告知用户。
 *
 * 拦截动作**每次都执行**, 但通知受 [LimitNoticeTracker] 抑制:
 * 每日额度同一天只提醒 1 次, 单次额度同一冷却周期只提醒 1 次。
 */
@Singleton
class UsageLimitEnforcer @Inject constructor(
    @ApplicationContext private val context: Context,
    private val systemControlExecutor: SystemControlExecutor,
    private val notificationManager: AvelineNotificationManager,
    private val sessionLimiter: SessionLimiter,
    private val noticeTracker: LimitNoticeTracker,
) {

    /**
     * 执行拦截: 回桌面 → 强退 → 通知。
     *
     * @param goHome 是否先把用户送回桌面。15 分钟兜底 Worker 应传 false: 它拿不到
     *   前台信息, 若用户此刻正在用别的应用, 无条件回桌面会把人凭空打断
     *   (Worker 每 15 分钟跑一次 = 每 15 分钟被踹回桌面一次)。强退本身照旧执行。
     * @return 是否成功让目标应用退出前台
     */
    suspend fun block(
        packageName: String,
        decision: SessionLimiter.LimitDecision.Block,
        goHome: Boolean = true,
    ): Boolean {
        // 双保险: 任何路径都不允许对 Aveline 自身动手 (force-stop 自身会撤销无障碍授权)
        if (SelfPackageGuard.isSelf(context, packageName)) {
            Log.w(TAG, "拒绝拦截 Aveline 自身: $packageName")
            return false
        }

        val appName = sessionLimiter.appLabel(packageName)
        // 先退回桌面, 再结束已转入后台的目标进程; 即使没有 Shizuku 也能让页面消失
        val movedHome = if (goHome) {
            AvelineAccessibilityService.instance?.goHome() ?: false
        } else {
            false
        }
        delay(BACKGROUND_SETTLE_MS)
        val stopped = systemControlExecutor.forceStopApp(
            packageName = packageName,
            acceptBackgroundFallback = true
        )
        Log.i(
            TAG,
            "已拦截 $packageName: ${decision.reason}, home=$movedHome, stopped=$stopped, " +
                "daily=${decision.dailyUsedMs}/${decision.dailyLimitMs}, " +
                "session=${decision.sessionUsedMs}/${decision.sessionLimitMs}"
        )

        // 通知只在"该提醒时"发: 拦截照旧, 但不再每开一次就弹一条
        val noticed = noticeTracker.takeNoticeSlot(
            packageName = packageName,
            reason = decision.reason,
            blockedUntilMs = decision.blockedUntilMs,
            dailyLimitMs = decision.dailyLimitMs,
        )
        if (noticed) {
            notificationManager.showSystemNotification(
                title = titleFor(appName, decision),
                message = messageFor(appName, decision, stopped)
            )
        } else {
            Log.d(TAG, "已拦截 $packageName 但跳过通知 (今日已提醒过)")
        }
        return stopped
    }

    private fun titleFor(
        appName: String,
        decision: SessionLimiter.LimitDecision.Block,
    ): String = when (decision.reason) {
        SessionLimiter.BlockReason.DAILY -> "$appName 今天的额度用完了"
        SessionLimiter.BlockReason.SESSION -> "$appName 本次时间到啦"
        SessionLimiter.BlockReason.COOLDOWN -> "$appName 还在休息中"
    }

    private fun messageFor(
        appName: String,
        decision: SessionLimiter.LimitDecision.Block,
        stopped: Boolean,
    ): String {
        val remaining = (decision.blockedUntilMs - System.currentTimeMillis()).coerceAtLeast(0L)
        val body = when (decision.reason) {
            SessionLimiter.BlockReason.DAILY ->
                "今天累计已用 ${formatDuration(decision.dailyUsedMs)}，" +
                    "达到每日限额 ${formatDuration(decision.dailyLimitMs)}。明天 0 点恢复～"

            SessionLimiter.BlockReason.SESSION ->
                "本次连续用了 ${formatDuration(decision.sessionUsedMs)}" +
                    "（单次限额 ${formatDuration(decision.sessionLimitMs)}）。" +
                    if (remaining > 0) {
                        "休息 ${formatDuration(remaining)} 后可以继续，今天还能用 " +
                            formatDuration(
                                (decision.dailyLimitMs - decision.dailyUsedMs).coerceAtLeast(0L)
                            )
                    } else {
                        "起来动一动吧～"
                    }

            SessionLimiter.BlockReason.COOLDOWN ->
                "刚超时休息过，还需要 ${formatDuration(remaining)} 才能继续。"
        }
        // 强退失败时如实告知, 否则用户以为限额没生效
        return if (stopped) body else "$body（无法自动关闭，请手动退出休息一下～）"
    }

    companion object {
        private const val TAG = "UsageLimitEnforcer"

        /** 回桌面后等系统完成窗口切换再强停, 提高无 Shizuku 场景的成功率。 */
        private const val BACKGROUND_SETTLE_MS = 150L
    }
}
