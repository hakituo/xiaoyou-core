package com.aveline.ai.mobile.services.worker

import android.content.Context
import android.content.pm.PackageManager
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.aveline.ai.mobile.data.local.database.dao.NotificationDao
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.AppUsageDto
import com.aveline.ai.mobile.data.remote.dto.ContextSyncRequest
import com.aveline.ai.mobile.data.remote.dto.DeviceContextDto
import com.aveline.ai.mobile.data.remote.dto.NotificationDto
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
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
    private val appPreferences: AppPreferences
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
                // 数字健康: 后端在同步响应里下发当日应用使用限额, 存到本地供
                // UsageLimitMonitor 定时检查并强制退出超限应用。
                val appLimits = response.body()?.appLimits
                if (!appLimits.isNullOrEmpty()) {
                    val limitsStr = appLimits.entries.joinToString(",") { "${it.key}=${it.value}" }
                    appPreferences.appUsageLimits = limitsStr
                }

                // 数字健康: 会话限额 (一次性 cap)。会话 cap 计算起点为"生效时刻"而非当天零点,
                // 因此在检测到某应用会话 cap 新增/变更时, 重置其生效起点为当前时间。
                handleSessionCaps(response.body()?.sessionCaps ?: emptyMap())

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
     * 处理后端下发的会话限额:
     * 1. 全量覆盖写入手机会话 cap 存储 (空 map 表示当日无会话限额)。
     * 2. 维护各应用的"生效起点": 会话 cap 新增或上限值变更时, 把该应用起点重置为当前时间,
     *    这样 UsageLimitMonitor 统计的是"从生效时刻至今"的用量, 而不是从当天零点算起。
     *    若上限值未变 (仍是旧的), 则保留原起点, 避免用户持续玩时被反复归零。
     * 3. 后端已清除某应用的会话 cap 时, 同时清掉它的起点记录。
     */
    private fun handleSessionCaps(caps: Map<String, Long>) {
        val now = System.currentTimeMillis()
        // 先读旧值再做覆盖, 用于对比上限是否变化
        val oldCaps = parsePairs(appPreferences.appSessionCaps)
        val oldStarts = parsePairs(appPreferences.sessionCapStarts)

        // 1. 全量覆盖写会话 cap
        val capsStr = if (caps.isEmpty()) "" else
            caps.entries.joinToString(",") { "${it.key}=${it.value}" }
        appPreferences.appSessionCaps = capsStr

        // 2. 计算新的起点映射: 新增或上限变更 -> 重置起点; 否则保留旧起点
        val newStarts = mutableMapOf<String, Long>()
        for ((pkg, capMs) in caps) {
            if (capMs <= 0) continue
            val changed = oldCaps[pkg] != capMs
            newStarts[pkg] = if (changed) now else (oldStarts[pkg] ?: now)
        }

        // 3. 覆盖写起点 (已移除会话 cap 的应用自动被清掉)
        val newStartsStr = if (newStarts.isEmpty()) "" else
            newStarts.entries.joinToString(",") { "${it.key}=${it.value}" }
        appPreferences.sessionCapStarts = newStartsStr
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
            val v = pair.substring(idx + 1).trim().toLongOrNull() ?: return@forEach
            if (pkg.isNotBlank()) map[pkg] = v
        }
        return map
    }
}
