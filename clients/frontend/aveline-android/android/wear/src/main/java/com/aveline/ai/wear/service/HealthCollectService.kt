package com.aveline.ai.wear.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.health.services.client.PassiveListenerService
import androidx.health.services.client.data.DataPointContainer
import androidx.health.services.client.data.DataType
import com.aveline.ai.wear.R
import com.aveline.ai.wear.data.WearDataSender
import com.aveline.ai.wear.health.HealthServicesManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * 手表端健康数据采集前台服务。
 *
 * 继承 [PassiveListenerService],通过 Health Services 被动监听步数和心率,
 * 并通过 [WearDataSender] 将数据同步到手机端。
 */
class HealthCollectService : PassiveListenerService() {

    private val serviceJob = SupervisorJob()
    private val serviceScope = CoroutineScope(Dispatchers.Main + serviceJob)

    private lateinit var healthServicesManager: HealthServicesManager
    private lateinit var dataSender: WearDataSender

    private var latestSteps: Long = 0L
    private var latestHeartRate: Int? = null
    private var latestHeartRateTimestamp: Long? = null

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "onCreate: 服务创建")
        healthServicesManager = HealthServicesManager(this)
        dataSender = WearDataSender(this)
        startForeground(NOTIFICATION_ID, buildNotification())
    }

    override fun onNewDataPointsReceived(dataPoints: DataPointContainer) {
        Log.i(TAG, "onNewDataPointsReceived: 收到数据更新")
        handleDataPoints(dataPoints)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Log.i(TAG, "onStartCommand: 开始订阅被动监听")
        serviceScope.launch {
            try {
                val supported = healthServicesManager.supportsPassiveMonitoring()
                Log.i(TAG, "supportsPassiveMonitoring=$supported")
                if (supported) {
                    healthServicesManager.subscribe(HealthCollectService::class.java)
                    Log.i(TAG, "订阅成功")
                    _healthState.value = _healthState.value.copy(
                        statusMessage = "已订阅,等待数据…"
                    )
                } else {
                    Log.e(TAG, "设备不支持被动监听")
                    _healthState.value = _healthState.value.copy(
                        statusMessage = "设备不支持被动监听"
                    )
                }
            } catch (e: Exception) {
                Log.e(TAG, "订阅失败: ${e.message}", e)
                _healthState.value = _healthState.value.copy(
                    statusMessage = "订阅失败: ${e.message}"
                )
            }
        }
        return START_STICKY
    }

    override fun onPermissionLost() {
        Log.w(TAG, "onPermissionLost: 权限丢失")
        _healthState.value = _healthState.value.copy(
            statusMessage = "权限丢失,请重新授权"
        )
    }

    override fun onDestroy() {
        Log.i(TAG, "onDestroy: 服务销毁")
        serviceScope.launch {
            runCatching { healthServicesManager.unsubscribe() }
            serviceJob.cancel()
        }
        super.onDestroy()
    }

    private fun handleDataPoints(dataPoints: DataPointContainer) {
        // 取当日累计步数
        val stepsList = dataPoints.getData(DataType.STEPS_DAILY)
        Log.i(TAG, "步数数据点数量: ${stepsList.size}")
        stepsList.lastOrNull()?.let {
            latestSteps = it.value
            Log.i(TAG, "最新步数: $latestSteps")
        }

        // 取最新心率
        val hrList = dataPoints.getData(DataType.HEART_RATE_BPM)
        Log.i(TAG, "心率数据点数量: ${hrList.size}")
        hrList.lastOrNull()?.let {
            latestHeartRate = it.value.toInt()
            latestHeartRateTimestamp = System.currentTimeMillis()
            Log.i(TAG, "最新心率: $latestHeartRate")
        }

        // 更新可观察状态,供 UI 实时显示
        _healthState.value = HealthState(
            steps = latestSteps,
            heartRate = latestHeartRate,
            heartRateTimestamp = latestHeartRateTimestamp,
            statusMessage = "已收到数据"
        )

        serviceScope.launch {
            runCatching {
                dataSender.sendHealthData(
                    steps = latestSteps,
                    heartRate = latestHeartRate,
                    heartRateTimestamp = latestHeartRateTimestamp
                )
                Log.i(TAG, "数据已发送到手机")
            }.onFailure { e ->
                Log.e(TAG, "发送数据失败: ${e.message}", e)
            }
        }
    }

    private fun buildNotification(): Notification {
        val channelId = "health_collect"
        val channel = NotificationChannel(
            channelId,
            getString(R.string.app_name),
            NotificationManager.IMPORTANCE_LOW
        )
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.createNotificationChannel(channel)

        return Notification.Builder(this, channelId)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.status_collecting))
            .setSmallIcon(R.drawable.ic_launcher)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "HealthCollectService"
        private const val NOTIFICATION_ID = 1001

        /** UI 可观察的最新健康数据 */
        private val _healthState = MutableStateFlow(HealthState())
        val healthState: StateFlow<HealthState> = _healthState.asStateFlow()

        fun start(context: Context) {
            context.startForegroundService(Intent(context, HealthCollectService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, HealthCollectService::class.java))
        }
    }
}

/** 供 UI 观察的健康数据快照 */
data class HealthState(
    val steps: Long = 0L,
    val heartRate: Int? = null,
    val heartRateTimestamp: Long? = null,
    val statusMessage: String = "",
)
