package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.ModelDto
import com.aveline.ai.mobile.data.remote.dto.SwitchModelRequest
import com.aveline.ai.mobile.domain.models.*
import com.aveline.ai.mobile.domain.repository.PluginsRepository
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import org.json.JSONObject
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 插件和设置仓库实现
 *
 * 管理模型切换和设置
 *
 * Requirements: 12.1, 12.2, 12.3, 12.4, 12.5
 */
@Singleton
class PluginsRepositoryImpl @Inject constructor(
    private val apiService: AvelineApiService,
    private val appPreferences: AppPreferences,
    private val webSocketManager: WebSocketManager
) : PluginsRepository {

    private val _modelsFlow = MutableSharedFlow<List<AIModel>>(replay = 1)
    private val _settingsFlow = MutableSharedFlow<PluginSettings>(replay = 1)

    @Volatile
    private var cachedModels: List<AIModel> = emptyList()
    @Volatile
    private var backendSelectedModelId: String? = null
    @Volatile
    private var cachedModelRoutes: Map<String, String> = emptyMap()
    @Volatile
    private var cachedSettings: PluginSettings = PluginSettings()

    override suspend fun getModels(): List<AIModel> {
        return try {
            val response = apiService.getModels()
            val models = response.models.map { it.toDomain() }
            // 后端返回全局默认模型，手机明确保存的选择由聊天请求单独携带。
            // 模型 id 是显示名，而 selected_model_id/path 是路由名，两者不能直接硬比较。
            backendSelectedModelId = response.models
                .firstOrNull { it.matchesBackendSelection(response.selectedModelId) }
                ?.id
            cachedModelRoutes = response.models.associate { model ->
                model.id to (model.path?.takeIf { it.isNotBlank() } ?: model.id)
            }
            cachedModels = models
            // 兼容旧版本仅保存展示 id 的偏好，为它补齐实际调用路由。
            cachedModelRoutes[appPreferences.selectedModelId]?.let {
                appPreferences.selectedModelRoute = it
            }
            _modelsFlow.tryEmit(models)
            models
        } catch (e: Exception) {
            cachedModels
        }
    }

    override suspend fun getSelectedModel(): AIModel? {
        val savedId = appPreferences.selectedModelId
        if (savedId.isNotBlank()) {
            return cachedModels.find { it.id == savedId }
        }
        val serverSelected = backendSelectedModelId
        if (!serverSelected.isNullOrBlank()) {
            return cachedModels.find { it.id == serverSelected }
        }

        // 无法匹配时保持未选择，不伪装成列表第一项。
        return null
    }

    override suspend fun switchModel(modelId: String): Result<Unit> {
        return try {
            val model = cachedModels.firstOrNull { it.id == modelId }
                ?: cachedModels.firstOrNull { it.name == modelId }
            if (model == null) {
                return Result.failure(Exception("模型列表中没有找到: $modelId"))
            }
            val modelPath = cachedModelRoutes[modelId]?.takeIf { it.isNotBlank() } ?: modelId
            val isCloud = model.type == ModelType.CLOUD || modelPath.startsWith("cloud:")

            // 走 REST /api/v1/models/switch：真正修改后端全局配置，
            // 而不是 WebSocket 的会话级锁定（locked 只在 WS 连接上，HTTP SSE 聊天不消费）。
            val provider = if (isCloud) {
                // path 形如 cloud:provider[:alias]:model，提取 provider
                val parts = modelPath.split(":")
                parts.getOrNull(1) ?: "cloud"
            } else {
                "local"
            }
            val modelName = if (isCloud) {
                // 后端用 model_name 查 model_info；cloud 模型名取 path 最后一段
                modelPath.substringAfterLast(":")
            } else {
                modelId
            }
            val response = apiService.switchModel(
                SwitchModelRequest(modelName = modelName, provider = provider)
            )
            if (!response.success) {
                val errMsg = response.error ?: "切换失败"
                return Result.failure(Exception(errMsg))
            }

            // 后端切换成功：本地持久化
            appPreferences.selectedModelId = modelId
            appPreferences.selectedModelRoute = modelPath
            backendSelectedModelId = modelId

            // 更新缓存
            cachedSettings = cachedSettings.copy(selectedModelId = modelId)
            _settingsFlow.tryEmit(cachedSettings)

            // 通知 WebSocket 会话级锁定（作为附加手段；HTTP SSE 聊天以后端全局配置为准）
            runCatching {
                val message = JSONObject().apply {
                    put("type", "mobile_switch_model")
                    put("model", cachedModelRoutes[modelId] ?: modelId)
                }
                webSocketManager.sendMessage(message.toString())
            }

            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getSettings(): PluginSettings {
        return PluginSettings(
            selectedModelId = appPreferences.selectedModelId,
            responseLength = appPreferences.responseLength,
            breathingRate = appPreferences.breathingRate,
            manualEmotion = appPreferences.manualEmotion,
            autoEmotion = appPreferences.autoEmotion
        ).also {
            cachedSettings = it
            _settingsFlow.tryEmit(it)
        }
    }

    override suspend fun setResponseLength(length: ResponseLength): Result<Unit> {
        return try {
            appPreferences.responseLength = length

            // 通知后端
            val message = JSONObject().apply {
                put("type", "update_settings")
                put("response_length", length.name.lowercase())
            }
            webSocketManager.sendMessage(message.toString())

            cachedSettings = cachedSettings.copy(responseLength = length)
            _settingsFlow.tryEmit(cachedSettings)

            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun setBreathingRate(rate: Float): Result<Unit> {
        return try {
            val clampedRate = rate.coerceIn(0.5f, 2.0f)
            appPreferences.breathingRate = clampedRate

            cachedSettings = cachedSettings.copy(breathingRate = clampedRate)
            _settingsFlow.tryEmit(cachedSettings)

            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun setManualEmotion(emotion: EmotionType?): Result<Unit> {
        return try {
            appPreferences.manualEmotion = emotion

            // 通知后端
            val message = JSONObject().apply {
                put("type", "set_emotion")
                put("emotion", emotion?.name?.lowercase() ?: "auto")
            }
            webSocketManager.sendMessage(message.toString())

            cachedSettings = cachedSettings.copy(manualEmotion = emotion)
            _settingsFlow.tryEmit(cachedSettings)

            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun setAutoEmotion(enabled: Boolean): Result<Unit> {
        return try {
            appPreferences.autoEmotion = enabled

            cachedSettings = cachedSettings.copy(autoEmotion = enabled)
            _settingsFlow.tryEmit(cachedSettings)

            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override fun observeModels(): Flow<List<AIModel>> = _modelsFlow.asSharedFlow()

    override fun observeSettings(): Flow<PluginSettings> = _settingsFlow.asSharedFlow()
}

/**
 * 扩展函数：DTO 转换为 Domain
 */
private fun ModelDto.toDomain(): AIModel {
    return AIModel(
        id = id,
        name = name ?: id,
        route = path?.takeIf { it.isNotBlank() } ?: id,
        type = when (category?.lowercase()) {
            "cloud" -> ModelType.CLOUD
            "local" -> ModelType.LOCAL
            else -> when {
                path?.startsWith("cloud:") == true -> ModelType.CLOUD
                type?.lowercase() == "local" -> ModelType.LOCAL
                else -> ModelType.UNKNOWN
            }
        },
        description = description ?: "",
        provider = provider ?: "",
        contextLength = contextLength ?: 4096,
        isAvailable = isAvailable ?: true
    )
}

/** 将后端当前模型路由与列表项的展示 id/path 对齐。 */
private fun ModelDto.matchesBackendSelection(selectedModelId: String?): Boolean {
    val selected = selectedModelId?.trim()?.takeIf { it.isNotEmpty() } ?: return false
    val modelPath = path.orEmpty()
    if (id == selected || modelPath == selected) return true
    if (modelPath == "cloud:$selected") return true

    // 多 API Key 的路径会多一段 alias：cloud:provider:alias:model。
    val selectedParts = selected.split(":", limit = 2)
    if (selectedParts.size == 2 && modelPath.startsWith("cloud:${selectedParts[0]}:")) {
        return modelPath.endsWith(":${selectedParts[1]}")
    }
    return selected == "local" && category.equals("local", ignoreCase = true)
}
