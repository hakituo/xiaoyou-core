package com.aveline.ai.mobile.services.worker

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.services.AvelineNotificationManager
import com.aveline.ai.mobile.services.SystemControlExecutor
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import android.util.Log

/**
 * 数字健康监控 Worker
 *
 * 随 DataSyncManager 一同注册为 15 分钟周期的 PeriodicWork。
 * 每次运行:
 * 1. 读 AppPreferences 中后端下发的当日应用使用限额与会话限额
 * 2. 读 UsageStatsManager 当日应用使用时长 (ContextRepository.getAppUsage)
 * 3. 对比: 超限的应用强制退出 (SystemControlExecutor, 依赖 Shizuku) + 本地系统通知
 *    - 每周期都强退, 不去重: 只要应用仍超限, 用户重新打开后下一个周期仍会被拦下
 * 4. 会话限额按"生效起点至今"的用量判断, 每日限额按当日用量判断, 时长共用一份用量
 *
 * 设计: 强制退出在手机本地完成, 不依赖后端在线 (离线也能拦)。
 * 后端仅在手机同步时补一条 active care 关怀消息。
 */
@HiltWorker
class UsageLimitMonitor @AssistedInject constructor(
    @Assisted private val context: Context,
    @Assisted workerParams: WorkerParameters,
    private val appPreferences: AppPreferences,
    private val contextRepository: ContextRepository,
    private val systemControlExecutor: SystemControlExecutor,
    private val notificationManager: AvelineNotificationManager,
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

            val limitsRaw = appPreferences.appUsageLimits
            val sessionCapsRaw = appPreferences.appSessionCaps
            if (limitsRaw.isBlank() && sessionCapsRaw.isBlank()) {
                return@withContext Result.success() // 无限额设定
            }

            val limits = parsePairs(limitsRaw)
            val sessionCaps = parsePairs(sessionCapsRaw)
            val sessionStarts = parsePairs(appPreferences.sessionCapStarts)
            if (limits.isEmpty() && sessionCaps.isEmpty()) {
                return@withContext Result.success()
            }

            // 修复: 原 getAppUsage(hours=24) 会混入昨天的 UsageStatsManager daily bucket,
            // 导致每日限额判断基于"昨天+今天"的假数据。改为只查今天 00:00 至今。
            val todayMidnightMs = java.time.LocalDate.now()
                .atStartOfDay(java.time.ZoneId.systemDefault())
                .toInstant()
                .toEpochMilli()
            val usage = contextRepository.getAppUsageSince(todayMidnightMs)

            // 会话 cap: 每个应用按各自的生效起点独立统计用量,
            // 不再用全局 min start 导致后设的应用被错误计入先设应用的时段。
            val sessionUsage: Map<String, Long> = buildMap {
                for ((pkg, capMs) in sessionCaps) {
                    if (capMs <= 0) continue
                    val startMs = sessionStarts[pkg] ?: 0L
                    if (startMs <= 0) continue
                    val sinceStart = contextRepository.getAppUsageSince(startMs)
                        .firstOrNull { it.packageName == pkg }?.usageTimeMs ?: 0L
                    put(pkg, sinceStart)
                }
            }

            // 每周期强退: 只要应用仍超限, 本轮就强退一次 (不去重)。
            // 这样用户重新打开后, 下一个 15 分钟周期仍会被拦下, 形成持续打断。
            for (app in usage) {
                val pkg = app.packageName
                // 每日限额判断
                val limitMs = limits[pkg] ?: 0L
                if (limitMs > 0 && app.usageTimeMs > limitMs) {
                    forceStop(app, "每日已使用超过设定时长")
                }
                // 会话限额判断 (一次性 cap): 按各自生效起点独立计算
                val capMs = sessionCaps[pkg] ?: 0L
                if (capMs > 0) {
                    val sinceStart = sessionUsage[pkg] ?: 0L
                    if (sinceStart > capMs) {
                        forceStop(app, "本次已使用超过会话限额")
                    }
                }
            }

            Result.success()
        } catch (e: Exception) {
            Log.e(TAG, "UsageLimitMonitor 运行异常", e)
            Result.success() // 监控失败不应阻断 WorkManager 重试风暴
        }
    }

    /** 强制退出单个应用并弹本地通知, 返回是否成功。 */
    private suspend fun forceStop(app: com.aveline.ai.mobile.domain.models.AppUsageInfo, reason: String): Boolean {
        Log.i(TAG, "应用 ${app.appName} 超限 ($reason), 强制退出")
        val ok = systemControlExecutor.forceStopApp(app.packageName)
        // 通知去重: 每个应用每天最多发一次强退通知 (无论成功/失败), 避免 15 分钟周期刷屏。
        // 强退操作本身不去重 —— 用户重新打开后下一周期仍会被拦, 保持"持续打断"设计。
        if (shouldNotifyForceStop(app.packageName)) {
            if (ok) {
                notificationManager.showSystemNotification(
                    title = "已限制应用使用",
                    message = "${app.appName} $reason，已自动退出。休息一下吧～"
                )
            } else {
                // 修复: 原实现强退失败只打 Log.w, 用户完全无感知, 以为限额没生效。
                // 改为发通知告知用户: 超限了但无法自动强退 (需 Shizuku 运行中), 请手动关闭。
                // 注: 无障碍权限不能 force-stop 应用, 必须 Shizuku 或 root。
                notificationManager.showSystemNotification(
                    title = "${app.appName} 已超时",
                    message = "${app.appName} $reason。无法自动关闭（需 Shizuku 运行中），请手动退出休息一下～"
                )
            }
            markNotifiedForceStop(app.packageName)
        }
        if (!ok) {
            Log.w(TAG, "强退 ${app.packageName} 失败 (可能未启用 Shizuku)")
        }
        return ok
    }

    /**
     * 检查今天是否已对该应用发过强退通知 (避免每 15 分钟周期刷屏)。
     * todayForceStopped 格式: "yyyy-MM-dd:pkg1,pkg2", 跨天自动重置。
     */
    private fun shouldNotifyForceStop(pkg: String): Boolean {
        val raw = appPreferences.todayForceStopped
        val today = java.time.LocalDate.now().toString()
        val parts = raw.split(":", limit = 2)
        if (parts.isEmpty() || parts[0] != today) return true // 跨天, 视为未通知
        val pkgs = parts.getOrNull(1)?.split(",")?.map { it.trim() } ?: emptyList()
        return pkg !in pkgs
    }

    /** 标记今天已对该应用发过强退通知。 */
    private fun markNotifiedForceStop(pkg: String) {
        val today = java.time.LocalDate.now().toString()
        val raw = appPreferences.todayForceStopped
        val parts = raw.split(":", limit = 2)
        val pkgs = if (parts.isNotEmpty() && parts[0] == today) {
            (parts.getOrNull(1)?.split(",")?.map { it.trim() } ?: emptyList())
        } else emptyList()
        val updated = (pkgs + pkg).distinct().joinToString(",")
        appPreferences.todayForceStopped = "$today:$updated"
    }

    /**
     * 解析 "pkg1=ms1,pkg2=ms2" 为 map。
     */
    private fun parsePairs(raw: String): Map<String, Long> {
        val map = mutableMapOf<String, Long>()
        raw.split(',').forEach { pair ->
            val idx = pair.indexOf('=')
            if (idx <= 0) return@forEach
            val pkg = pair.substring(0, idx).trim()
            val ms = pair.substring(idx + 1).trim().toLongOrNull() ?: return@forEach
            if (pkg.isNotBlank() && ms > 0) map[pkg] = ms
        }
        return map
    }
}
