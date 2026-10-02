package com.aveline.ai.mobile.services.worker

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.services.wellbeing.SessionLimiter
import com.aveline.ai.mobile.services.wellbeing.UsageLimitEnforcer
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import android.util.Log

/**
 * 数字健康监控 Worker —— **兜底执行器, 不是主执行器**。
 *
 * 15 分钟周期远粗于"单次最多 10 分钟"这类限制 (WorkManager 的周期任务本来也不是精确闹钟),
 * 因此单次额度的实时判定由 [com.aveline.ai.mobile.services.AvelineAccessibilityService]
 * 通过 [SessionLimiter] 完成。本 Worker 只负责:
 *
 * 1. **兜底校验**: 每日额度超限的应用强退一次 (15 分钟粒度对"每天 2 小时"完全够用)
 * 2. **状态恢复**: 清理已移除策略 / 跨天 / 离开超过 sessionGap 的残留会话
 * 3. **异常修正**: 无障碍服务被系统回收时, 至少每日额度仍然有人执行
 *
 * 真正的会话额度不在 Worker 里判定 —— 它拿不到前台信息, 不能替用户结束会话。
 */
@HiltWorker
class UsageLimitMonitor @AssistedInject constructor(
    @Assisted private val context: Context,
    @Assisted workerParams: WorkerParameters,
    private val contextRepository: ContextRepository,
    private val sessionLimiter: SessionLimiter,
    private val usageLimitEnforcer: UsageLimitEnforcer,
) : CoroutineWorker(context, workerParams) {

    companion object {
        private const val TAG = "UsageLimitMonitor"
    }

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            if (!contextRepository.hasUsageStatsPermission()) {
                // 未授权使用情况访问, 无法获取用量, 跳过 (不报错, 等授权)
                return@withContext Result.success()
            }

            val policies = sessionLimiter.policies()
            if (policies.isEmpty()) {
                return@withContext Result.success() // 无限额设定
            }

            // 先做状态恢复, 再逐应用兜底校验, 保证用的是最新的会话状态
            sessionLimiter.reconcile()

            for ((packageName, policy) in policies) {
                try {
                    // 双保险: 即便策略表被外部写入了自身包名, 这里也不会对自己动手。
                    if (com.aveline.ai.mobile.utils.SelfPackageGuard.isSelf(context, packageName)) {
                        continue
                    }
                    if (policy.dailyLimitMs <= 0) continue // 未设每日额度, 交给无障碍实时判定
                    val decision = sessionLimiter.enforceFallback(packageName)
                    if (decision is SessionLimiter.LimitDecision.Block) {
                        Log.i(TAG, "兜底拦截 $packageName: ${decision.reason} (每日额度)")
                        // goHome=false: 兜底时用户可能正在用别的应用, 不能把人踹回桌面
                        usageLimitEnforcer.block(packageName, decision, goHome = false)
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "兜底校验 $packageName 失败: ${e.message}")
                }
            }

            Result.success()
        } catch (e: Exception) {
            Log.e(TAG, "UsageLimitMonitor 运行异常", e)
            Result.success() // 监控失败不应阻断 WorkManager 重试风暴
        }
    }
}
