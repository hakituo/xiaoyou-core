package com.aveline.ai.mobile.services.foreground

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.domain.repository.ContextRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** 管理前台服务的五分钟设备上下文同步循环。 */
class ContextSyncController(
    private val scope: CoroutineScope,
    private val repository: ContextRepository,
    private val preferences: AppPreferences
) {
    private var job: Job? = null

    fun start() {
        if (job?.isActive == true) return
        job = scope.launch {
            while (isActive) {
                try {
                    delay(CONTEXT_SYNC_INTERVAL_MS)
                    if (!preferences.isContextSyncEnabled) continue
                    repository.syncToBackend(repository.getFullContext())
                    preferences.lastSyncTimestamp = System.currentTimeMillis()
                } catch (error: Exception) {
                    Log.e(TAG, "上下文同步失败", error)
                }
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    companion object {
        private const val CONTEXT_SYNC_INTERVAL_MS = 5 * 60 * 1000L
        private const val TAG = "AvelineForegroundService"
    }
}
