package com.aveline.ai.mobile.services.worker

import android.content.Context
import android.content.pm.PackageManager
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.aveline.ai.mobile.data.local.database.dao.NotificationDao
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.AppLimitPolicyDto
import com.aveline.ai.mobile.data.remote.dto.AppUsageDto
import com.aveline.ai.mobile.data.remote.dto.ContextSyncRequest
import com.aveline.ai.mobile.data.remote.dto.DeviceContextDto
import com.aveline.ai.mobile.data.remote.dto.NotificationDto
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.services.wellbeing.AppLimitPolicy
import com.aveline.ai.mobile.services.wellbeing.AppLimitPolicyCodec
import com.aveline.ai.mobile.services.wellbeing.SessionLimiter
import com.aveline.ai.mobile.utils.SelfPackageGuard
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

@HiltWorker
class DataSyncWorker @AssistedInject constructor(
    @Assisted private val context: Context,
    @Assisted workerParams: WorkerParameters,
    private val notificationDao: NotificationDao,
    private val apiService: AvelineApiService,
    private val contextRepository: ContextRepository,
    private val sessionLimiter: SessionLimiter
) : CoroutineWorker(context, workerParams) {

    companion object {
        private const val MAX_RETRY_COUNT = 3  // 最大重试次数
        private const val KEY_RETRY_COUNT = "retry_count"
    }

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        // 获取当前重试次数
        val currentRetryCount = inputData.getInt(KEY_RETRY_COUNT, 0)
        
        try {
            // 注意：健康数据不再从这里同步。Health Connect 读取已彻底关闭，
            // 健康数据改由 Samsung Health（AvelineForegroundServiceV2 中的
            // SamsungHealthReader）负责，避免无谓的跨进程查询耗电。

            val unsentNotifications = notificationDao.getUnsentNotifications()

            val deviceContext = contextRepository.getDeviceContext()

            val todayMidnightMs = LocalDate.now()
                .atStartOfDay(ZoneId.systemDefault())
                .toInstant()
                .toEpochMilli()
            val appUsageDtos = if (contextRepository.hasUsageStatsPermission()) {
                // 修复: 原 getAppUsage(hours=24) 查询过去 24h 的 UsageStatsManager INTERVAL_DAILY bucket,
                // 会混入昨天的全天用量 (如昨天 B 站 3h40m), 导致每天上报的 usage_today 都包含昨天峰值,
                // 后端聚合永远卡在那个值, UI 进度条和 active care 触发都基于假数据。
                // 改为只取今天 00:00 至今的用量, 保证每日数据独立。
                contextRepository.getAppUsageSince(todayMidnightMs).map { AppUsageDto.fromDomain(it) }
            } else {
                emptyList()
            }

            val notificationDtos = unsentNotifications.map {
                val appName = try {
                    val appInfo = context.packageManager.getApplicationInfo(it.packageName, 0)
                    context.packageManager.getApplicationLabel(appInfo).toString()
                } catch (e: PackageManager.NameNotFoundException) {
                    it.packageName.substringAfterLast(".")
                }
                NotificationDto(
                    id = it.id.toString(),
                    packageName = it.packageName,
                    appName = appName,
                    title = it.title,
                    text = it.content,
                    timestamp = it.timestamp.toString(),
                    category = "intercepted"
                )
            }

            val request = ContextSyncRequest(
                deviceContext = DeviceContextDto.fromDomain(deviceContext),
                appUsage = appUsageDtos,
                notifications = notificationDtos,
                usageWindowStart = Instant.ofEpochMilli(todayMidnightMs).toString(),
                usageSource = "android_today_since_midnight_v1",
                collectedAt = Instant.now().toString()
            )

            val response = apiService.syncContext(request)

            if (response.isSuccessful) {
                // 数字健康: 后端在同步响应里下发完整的限额策略 (每日 + 单次 + 间隔 + 冷却),
                // 存到本地供无障碍服务实时判定、UsageLimitMonitor 兜底校验。
                val body = response.body()
                applyAppPolicies(
                    body?.appPolicies.orEmpty(),
                    body?.legacyDailyLimits(),
                    body?.legacySessionCaps()
                )

                if (unsentNotifications.isNotEmpty()) {
                    notificationDao.markAsSent(unsentNotifications.map { it.id })
                }
                return@withContext Result.success()
            } else {
                // 超过最大重试次数则失败，否则重试
                return@withContext if (currentRetryCount >= MAX_RETRY_COUNT) {
                    android.util.Log.w("DataSyncWorker", "同步失败，已达到最大重试次数 $MAX_RETRY_COUNT")
                    Result.failure()
                } else {
                    // WorkManager 通过 getRunAttemptCount() 追踪重试次数,无需手动传 data
                    Result.retry()
                }
            }

        } catch (e: Exception) {
            e.printStackTrace()
            // 超过最大重试次数则失败，否则重试
            return@withContext if (currentRetryCount >= MAX_RETRY_COUNT) {
                android.util.Log.w("DataSyncWorker", "同步异常，已达到最大重试次数 $MAX_RETRY_COUNT", e)
                Result.failure()
            } else {
                Result.retry()
            }
        }
    }

    /**
     * 落地后端下发的数字健康策略。
     *
     * - 后端返回 app_policies (新字段) 时直接用它, 覆盖本地策略表。
     * - 老后端只返回 app_limits / session_caps 时, 用默认的间隔与冷却补齐成完整策略。
     * - 任何情况下都剔除 Aveline 自身: 对自己 force-stop 会让系统撤销本包的无障碍授权。
     */
    private suspend fun applyAppPolicies(
        policies: List<AppLimitPolicyDto>,
        legacyLimits: Map<String, Long>?,
        legacyCaps: Map<String, Long>?,
    ) {
        val normalized = if (policies.isNotEmpty()) {
            policies
                .filter { it.packageName.isNotBlank() }
                .map {
                    AppLimitPolicy.of(
                        packageName = it.packageName.trim(),
                        dailyLimitMs = it.dailyLimitMs,
                        sessionLimitMs = it.sessionLimitMs,
                        sessionGapMs = it.sessionGapMs,
                        cooldownMs = it.cooldownMs,
                    )
                }
        } else {
            AppLimitPolicyCodec.fromLegacy(
                dailyLimits = legacyLimits.orEmpty(),
                sessionCaps = legacyCaps.orEmpty(),
            )
        }
        val safe = normalized.filter { !SelfPackageGuard.isSelf(context, it.packageName) }
        if (safe.isEmpty() && sessionLimiter.policies().isEmpty()) return
        sessionLimiter.replacePolicies(safe)
        // 会话状态随策略一起对齐: 清理已移除应用/跨天的残留状态
        sessionLimiter.reconcile()
    }
}
