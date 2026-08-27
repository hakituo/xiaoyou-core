package com.aveline.ai.mobile.services.foreground

import android.util.Log
import com.aveline.ai.mobile.data.samsung.SamsungHealthReader
import com.aveline.ai.mobile.data.samsung.toSyncJson
import com.aveline.ai.mobile.domain.repository.HealthRepository
import com.aveline.ai.mobile.utils.AppForegroundTracker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** 按生命体征、全量和体成分三档管理 Samsung Health 定时同步。 */
class SamsungHealthSyncController(
    private val scope: CoroutineScope,
    private val reader: SamsungHealthReader,
    private val repository: HealthRepository
) {
    private var vitalsJob: Job? = null
    private var fullJob: Job? = null
    private var bodyJob: Job? = null

    fun start() {
        if (vitalsJob?.isActive == true) return

        vitalsJob = scope.launch {
            while (isActive) {
                try {
                    delay(if (AppForegroundTracker.isForeground) VITALS_FOREGROUND_MS else VITALS_BACKGROUND_MS)
                    if (!reader.hasPermissions()) continue
                    repository.syncHealthData(reader.readVitals().toSyncJson())
                } catch (error: Exception) {
                    Log.w(TAG, "Samsung Health 生命体征同步失败: ${error.message}")
                }
            }
        }
        fullJob = scope.launch {
            var firstRun = true
            while (isActive) {
                try {
                    if (firstRun) firstRun = false else delay(FULL_INTERVAL_MS)
                    if (!reader.hasPermissions()) continue
                    repository.syncHealthData(reader.readAll(includeBodyComposition = false).toSyncJson())
                } catch (error: Exception) {
                    Log.w(TAG, "Samsung Health 全量同步失败: ${error.message}")
                }
            }
        }
        bodyJob = scope.launch {
            var firstRun = true
            while (isActive) {
                try {
                    if (firstRun) firstRun = false else delay(BODY_INTERVAL_MS)
                    if (!reader.hasPermissions()) continue
                    repository.syncHealthData(reader.readBodyComposition().toSyncJson())
                } catch (error: Exception) {
                    Log.w(TAG, "Samsung Health 体成分同步失败: ${error.message}")
                }
            }
        }
    }

    fun stop() {
        vitalsJob?.cancel()
        fullJob?.cancel()
        bodyJob?.cancel()
        vitalsJob = null
        fullJob = null
        bodyJob = null
    }

    companion object {
        private const val VITALS_FOREGROUND_MS = 20 * 1000L
        private const val VITALS_BACKGROUND_MS = 60 * 1000L
        private const val FULL_INTERVAL_MS = 30 * 60 * 1000L
        private const val BODY_INTERVAL_MS = 24 * 60 * 60 * 1000L
        private const val TAG = "AvelineFG"
    }
}
