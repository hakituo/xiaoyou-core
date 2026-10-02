package com.aveline.ai.mobile.services.worker

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class DataSyncManager @Inject constructor(
    @ApplicationContext private val context: Context
) {
    companion object {
        private const val SYNC_WORK_NAME = "aveline_data_sync_work"
        private const val USAGE_LIMIT_WORK_NAME = "aveline_usage_limit_monitor"
        private const val HEALTH_SYNC_WORK_NAME = "aveline_health_sync_work"
        // WorkManager 周期任务最小间隔为 15 分钟 (Android 平台限制)
        private const val HEALTH_SYNC_INTERVAL_MIN = 15L
    }

    fun startPeriodicSync() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val syncRequest = PeriodicWorkRequestBuilder<DataSyncWorker>(
            15, TimeUnit.MINUTES // 15分钟是WorkManager允许的最小周期
        )
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            SYNC_WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP, // 保持现有的（如果存在）
            syncRequest
        )

        // 数字健康监控: 本地定时检查应用使用限额并强制退出超限应用。
        // 不要求网络 (强退是本地 Shizuku 操作), 用 KEEP 避免重复注册。
        val monitorRequest = PeriodicWorkRequestBuilder<UsageLimitMonitor>(
            15, TimeUnit.MINUTES
        ).build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            USAGE_LIMIT_WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            monitorRequest
        )
    }

    /**
     * 三星健康后台同步: 独立于"常驻模式"与前台服务, 保证心率等生命体征在后台定时刷新。
     * 本方法不依赖 residentMode, 应在 App 启动时无条件调用 (见 [com.aveline.ai.AvelineApplication])。
     * 未授权 Samsung Health 时 Worker 会自动跳过, 故可安全常驻注册。
     */
    fun startHealthSync() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val healthRequest = PeriodicWorkRequestBuilder<HealthSyncWorker>(
            HEALTH_SYNC_INTERVAL_MIN, TimeUnit.MINUTES // 15分钟是WorkManager允许的最小周期
        )
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            HEALTH_SYNC_WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP, // 保持现有的（如果存在）
            healthRequest
        )
    }

    fun stopPeriodicSync() {
        WorkManager.getInstance(context).cancelUniqueWork(SYNC_WORK_NAME)
        WorkManager.getInstance(context).cancelUniqueWork(USAGE_LIMIT_WORK_NAME)
        // 注意: 不取消 HEALTH_SYNC_WORK_NAME, 健康后台同步独立于常驻模式, 需一直运行
    }
}
