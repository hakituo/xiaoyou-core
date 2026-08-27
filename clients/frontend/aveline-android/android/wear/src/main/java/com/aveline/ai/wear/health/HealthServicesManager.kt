package com.aveline.ai.wear.health

import android.content.Context
import androidx.health.services.client.HealthServices
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.PassiveListenerConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * 封装 Wear OS Health Services 的可用性检查与被动监听配置。
 *
 * 使用 [PassiveListenerConfig] 在后台订阅步数和心率,由系统统一调度,
 * 比主动 ExerciseClient 更省电,适合全天候佩戴场景。
 */
class HealthServicesManager(context: Context) {

    private val healthServicesClient = HealthServices.getClient(context)
    private val passiveMonitoringClient = healthServicesClient.passiveMonitoringClient

    /**
     * 检查 Health Services 是否支持被动监听所需的数据类型。
     */
    suspend fun supportsPassiveMonitoring(): Boolean {
        return try {
            val capabilities = withContext(Dispatchers.IO) {
                passiveMonitoringClient.getCapabilitiesAsync().get()
            }
            capabilities.supportedDataTypesPassiveMonitoring.containsAll(REQUIRED_DATA_TYPES)
        } catch (e: Exception) {
            false
        }
    }

    /**
     * 注册被动监听服务。
     *
     * @param serviceClass 继承 [androidx.health.services.client.PassiveListenerService] 的服务类。
     */
    suspend fun subscribe(serviceClass: Class<out androidx.health.services.client.PassiveListenerService>) {
        val config = PassiveListenerConfig.builder()
            .setDataTypes(REQUIRED_DATA_TYPES)
            .build()
        withContext(Dispatchers.IO) {
            passiveMonitoringClient.setPassiveListenerServiceAsync(serviceClass, config).get()
        }
    }

    /**
     * 取消被动监听。
     */
    suspend fun unsubscribe() {
        withContext(Dispatchers.IO) {
            passiveMonitoringClient.clearPassiveListenerServiceAsync().get()
        }
    }

    companion object {
        private val REQUIRED_DATA_TYPES = setOf(
            DataType.STEPS_DAILY,
            DataType.HEART_RATE_BPM
        )
    }
}
