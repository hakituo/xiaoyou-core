package com.aveline.ai.mobile.services.widget

import android.content.Context
import android.util.Log
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.StatusRepository
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.flow.firstOrNull
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Widget 后台更新 Worker
 *
 * 定期更新 Widget 数据，保持与应用状态同步
 */
@HiltWorker
class AvelineWidgetWorker @AssistedInject constructor(
    @Assisted private val context: Context,
    @Assisted workerParams: WorkerParameters,
    private val statusRepository: StatusRepository,
    private val chatRepository: ChatRepository,
    private val webSocketManager: WebSocketManager,
    private val appPreferences: AppPreferences
) : CoroutineWorker(context, workerParams) {

    companion object {
        private const val TAG = "AvelineWidgetWorker"
        private const val WORK_NAME = "aveline_widget_update"
        private const val UPDATE_INTERVAL_MINUTES = 15L

        /**
         * 启动定期更新
         */
        fun start(context: Context) {
            val workRequest = PeriodicWorkRequestBuilder<AvelineWidgetWorker>(
                UPDATE_INTERVAL_MINUTES, TimeUnit.MINUTES
            ).build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                workRequest
            )

            Log.d(TAG, "Widget 更新服务已启动")
        }

        /**
         * 停止定期更新
         */
        fun stop(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
            Log.d(TAG, "Widget 更新服务已停止")
        }
    }

    override suspend fun doWork(): Result {
        return try {
            updateWidgetData()
            Result.success()
        } catch (e: Exception) {
            Log.e(TAG, "更新 Widget 数据失败", e)
            Result.retry()
        }
    }

    private suspend fun updateWidgetData() {
        val prefs = context.getSharedPreferences("widget_data", Context.MODE_PRIVATE)

        // 获取连接状态
        val connectionState = webSocketManager.connectionState.firstOrNull()
        val isConnected = connectionState == WebSocketManager.ConnectionState.CONNECTED

        // 获取生命状态（getLifeStatus 返回 Result<LifeStatus>，不是 Flow）
        val lifeStatus = statusRepository.getLifeStatus().getOrNull()

        // 获取最近消息（currentSessionId 是 String?，需要空判断；ChatRepository 无 getMessages，用 loadHistoryFromApi）
        val currentSessionId = appPreferences.currentSessionId
        val lastMessage = if (!currentSessionId.isNullOrBlank()) {
            chatRepository.loadHistoryFromApi(currentSessionId).getOrNull()?.lastOrNull()
        } else {
            null
        }

        // LifeStatus 是 data class(health/hunger/happiness/energy),不是 Map
        val emotionPrimary = deriveEmotionFromHappiness(lifeStatus?.happiness)
        val widgetData = WidgetData(
            aiName = appPreferences.userName.ifBlank { "Aveline" },
            emotionPrimary = emotionPrimary,
            emotionIntensity = lifeStatus?.happiness ?: 0.5f,
            emotionText = getEmotionText(emotionPrimary),
            health = lifeStatus?.health ?: 0.8f,
            happiness = lifeStatus?.happiness ?: 0.7f,
            energy = lifeStatus?.energy ?: 0.6f,
            hunger = lifeStatus?.hunger ?: 0.5f,
            lastMessage = lastMessage?.text?.take(50) ?: "",
            lastMessageTime = lastMessage?.let {
                SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(it.timestamp))
            } ?: "",
            isConnected = isConnected,
            connectionState = if (isConnected) "已连接" else "未连接"
        )

        // 保存到 SharedPreferences
        widgetData.toPreferences(prefs)

        // 触发 Widget 更新
        AvelineWidgetProvider.updateAllWidgets(context)

        Log.d(TAG, "Widget 数据已更新")
    }

    private fun getEmotionText(emotion: String?): String {
        return when (emotion?.lowercase()) {
            "happy" -> "心情愉快"
            "sad" -> "心情低落"
            "excited" -> "心情激动"
            "calm" -> "心情平静"
            "angry" -> "心情愤怒"
            "surprised" -> "心情惊讶"
            else -> "心情平静"
        }
    }

    /** 根据 happiness 值推导情绪标签(LifeStatus 无 mood 字段) */
    private fun deriveEmotionFromHappiness(happiness: Float?): String {
        val h = happiness ?: 0.5f
        return when {
            h >= 0.8f -> "happy"
            h >= 0.6f -> "calm"
            h >= 0.4f -> "neutral"
            h >= 0.2f -> "sad"
            else -> "angry"
        }
    }
}
