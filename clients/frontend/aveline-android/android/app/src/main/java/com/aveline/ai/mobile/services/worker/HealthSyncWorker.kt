package com.aveline.ai.mobile.services.worker

import android.content.Context
import android.util.Log
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.aveline.ai.mobile.data.samsung.SamsungHealthReader
import com.aveline.ai.mobile.data.samsung.toSyncJson
import com.aveline.ai.mobile.domain.repository.HealthRepository
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * 后台周期性同步 Samsung Health 生命体征(心率/血氧/皮肤温度等)到后端。
 *
 * 与 [com.aveline.ai.mobile.services.foreground.SamsungHealthSyncController] 的区别:
 * 该 controller 运行在前台服务作用域内, 仅当"常驻模式"开启且前台服务存活时才会后台同步,
 * 进程被系统回收后同步即停止。本 Worker 由 WorkManager 调度, 独立于 App 进程与前台服务,
 * 可扛 Doze 与进程死亡, 保证心率等数据在后台也能定时刷新。
 *
 * 注意: WorkManager 周期任务最小间隔为 15 分钟(Android 平台限制), 故后台刷新为 15 分钟一次;
 * App 在前台时仍由 SamsungHealthSyncController 按 20 秒高频刷新。
 */
@HiltWorker
class HealthSyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val reader: SamsungHealthReader,
    private val healthRepository: HealthRepository
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            if (!reader.hasPermissions()) {
                Log.d(TAG, "Samsung Health 未授权, 跳过后台同步")
                return@withContext Result.success()
            }
            val result = healthRepository.syncHealthData(reader.readVitals().toSyncJson())
            if (result.isFailure) {
                Log.w(TAG, "Samsung Health 后台同步失败: ${result.exceptionOrNull()?.message}")
                return@withContext Result.retry()
            }
            Log.d(TAG, "Samsung Health 后台生命体征同步完成")
            Result.success()
        } catch (error: Exception) {
            Log.w(TAG, "Samsung Health 后台同步异常: ${error.message}")
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "HealthSyncWorker"
    }
}
