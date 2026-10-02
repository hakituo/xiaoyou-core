package com.aveline.ai.mobile.data.repository

import android.util.Log
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.CharacterDailyPlan
import com.aveline.ai.mobile.domain.models.CharacterDailySlot
import com.aveline.ai.mobile.domain.models.LifeStatus
import com.aveline.ai.mobile.domain.repository.StatusRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class StatusRepositoryImpl @Inject constructor(
    private val apiService: AvelineApiService,
    private val webSocketManager: WebSocketManager
) : StatusRepository {

    private val scope = CoroutineScope(Dispatchers.IO)

    private val _cachedLifeStatus = MutableStateFlow<LifeStatus?>(null)
    val cachedLifeStatus: StateFlow<LifeStatus?> = _cachedLifeStatus.asStateFlow()

    private var lastRefreshTime: Long = 0
    private var lastWsUpdateTime: Long = 0
    private var _cachedPersona: String? = null

    companion object {
        private const val TAG = "StatusRepositoryImpl"
        private const val FALLBACK_API_INTERVAL_MS = 60_000L
        private const val WS_THROTTLE_INTERVAL_MS = 5_000L
        private const val SIGNIFICANT_CHANGE_THRESHOLD = 0.05f
    }

    init {
        observeLifeStatusFromWebSocket()
    }

    private fun observeLifeStatusFromWebSocket() {
        scope.launch {
            webSocketManager.messages.collect { message ->
                when (message) {
                    is WebSocketMessage.LifeStatusUpdate -> {
                        val now = System.currentTimeMillis()
                        val current = _cachedLifeStatus.value

                        val newStatus = LifeStatus(
                            health = message.life["energy"] ?: 0.5f,
                            hunger = message.life["hunger"] ?: 0.5f,
                            happiness = message.life["mood_score"] ?: 0.5f,
                            energy = message.life["energy"] ?: 0.5f,
                            timestamp = message.timestamp,
                            scope = current?.scope,
                            activity = current?.activity ?: "idle",
                            activityChatEligible = current?.activityChatEligible ?: true,
                            replyMode = current?.replyMode ?: "immediate",
                            replyDelayMinSeconds = current?.replyDelayMinSeconds,
                            replyDelayMaxSeconds = current?.replyDelayMaxSeconds,
                            isSleeping = current?.isSleeping ?: false,
                            sleepPhase = current?.sleepPhase,
                            dailyPlan = current?.dailyPlan
                        )

                        val hasSignificantChange = current == null ||
                            kotlin.math.abs(current.health - newStatus.health) > SIGNIFICANT_CHANGE_THRESHOLD ||
                            kotlin.math.abs(current.hunger - newStatus.hunger) > SIGNIFICANT_CHANGE_THRESHOLD ||
                            kotlin.math.abs(current.happiness - newStatus.happiness) > SIGNIFICANT_CHANGE_THRESHOLD ||
                            kotlin.math.abs(current.energy - newStatus.energy) > SIGNIFICANT_CHANGE_THRESHOLD

                        if (hasSignificantChange || now - lastWsUpdateTime >= WS_THROTTLE_INTERVAL_MS) {
                            _cachedLifeStatus.value = newStatus
                            lastWsUpdateTime = now
                            lastRefreshTime = now
                        }
                    }
                    is WebSocketMessage.ReconnectSync -> {
                        message.lifeStatus?.let { lifeMap ->
                            val status = LifeStatus(
                                health = lifeMap["health"] ?: 0.5f,
                                hunger = lifeMap["hunger"] ?: 0.5f,
                                happiness = lifeMap["happiness"] ?: 0.5f,
                                energy = lifeMap["energy"] ?: 0.5f,
                                timestamp = System.currentTimeMillis(),
                                scope = _cachedLifeStatus.value?.scope,
                                activity = _cachedLifeStatus.value?.activity ?: "idle",
                                activityChatEligible = _cachedLifeStatus.value?.activityChatEligible ?: true,
                                replyMode = _cachedLifeStatus.value?.replyMode ?: "immediate",
                                replyDelayMinSeconds = _cachedLifeStatus.value?.replyDelayMinSeconds,
                                replyDelayMaxSeconds = _cachedLifeStatus.value?.replyDelayMaxSeconds,
                                isSleeping = _cachedLifeStatus.value?.isSleeping ?: false,
                                sleepPhase = _cachedLifeStatus.value?.sleepPhase,
                                dailyPlan = _cachedLifeStatus.value?.dailyPlan
                            )
                            _cachedLifeStatus.value = status
                            lastWsUpdateTime = System.currentTimeMillis()
                            lastRefreshTime = System.currentTimeMillis()
                        }
                    }
                    else -> Unit
                }
            }
        }
    }

    override suspend fun getLifeStatus(persona: String?): Result<LifeStatus> {
        val currentTime = System.currentTimeMillis()

        _cachedLifeStatus.value?.let { cached ->
            // 缓存只能服务于创建它的同一个 persona。旧判断只比较 cached.scope 与
            // _cachedPersona，没有比较“这次请求的 persona”，切角色后仍可能命中上一个角色缓存。
            if (
                currentTime - lastRefreshTime < FALLBACK_API_INTERVAL_MS &&
                persona == _cachedPersona &&
                cached.scope == persona
            ) {
                return Result.success(cached)
            }
        }

        return try {
            val response = apiService.getLifeStatus(persona = persona)
            val life = response.life_status?.life
            val lifeStatus = LifeStatus(
                health = (life?.energy ?: 100f) / 100f,
                hunger = (life?.hunger ?: 0f) / 100f,
                happiness = (life?.mood_score ?: 80f) / 100f,
                energy = (life?.energy ?: 100f) / 100f,
                timestamp = System.currentTimeMillis(),
                scope = persona,
                activity = response.activity,
                activityChatEligible = response.activity_chat_eligible,
                replyMode = response.reply_policy?.mode ?: "immediate",
                replyDelayMinSeconds = response.reply_policy?.min_seconds,
                replyDelayMaxSeconds = response.reply_policy?.max_seconds,
                isSleeping = response.sleep_summary?.is_sleeping ?: false,
                sleepPhase = response.sleep_summary?.phase,
                dailyPlan = response.daily_plan?.let { plan ->
                    CharacterDailyPlan(
                        roleId = plan.role_id,
                        date = plan.date,
                        currentActivity = plan.current_activity,
                        slots = plan.slots.map { slot ->
                            CharacterDailySlot(
                                activity = slot.activity,
                                plannedStart = slot.planned_start,
                                plannedEnd = slot.planned_end,
                                flexible = slot.flexible,
                                executionStatus = slot.execution_status
                            )
                        }
                    )
                }
            )

            _cachedLifeStatus.value = lifeStatus
            _cachedPersona = persona
            lastRefreshTime = currentTime

            Result.success(lifeStatus)
        } catch (e: Exception) {
            Log.e(TAG, "从API获取生命状态失败", e)

            _cachedLifeStatus.value?.let { cached ->
                return Result.success(cached)
            }

            Result.failure(e)
        }
    }

    override fun observeEmotion(): Flow<Emotion> {
        return webSocketManager.messages
            .filterIsInstance<WebSocketMessage.EmotionUpdate>()
            .map { emotionUpdate ->
                Emotion(
                    primary = emotionUpdate.primary,
                    intensity = emotionUpdate.intensity,
                    colors = emotionUpdate.colors
                )
            }
    }

    override suspend fun wakeCompanion(
        persona: String?,
        conversationId: String?
    ): Result<String> = runControlRequest("唤醒") {
        apiService.wakeCompanion(controlPayload(persona, conversationId, "Android 状态面板立即唤醒"))
    }

    override suspend fun interruptCompanion(
        persona: String?,
        conversationId: String?
    ): Result<String> = runControlRequest("打断") {
        apiService.interruptCompanion(controlPayload(persona, conversationId, "Android 状态面板打断活动"))
    }

    override suspend fun skipCompanionActivity(
        persona: String?,
        conversationId: String?
    ): Result<String> = runControlRequest("跳过") {
        apiService.skipCompanionActivity(controlPayload(persona, conversationId, "Android 状态面板跳过活动"))
    }

    private fun controlPayload(
        persona: String?,
        conversationId: String?,
        message: String
    ): JsonObject = buildJsonObject {
        put("persona_filename", persona.orEmpty())
        put("conversation_id", conversationId.orEmpty())
        put("message", message)
    }

    private suspend fun runControlRequest(
        label: String,
        request: suspend () -> JsonObject
    ): Result<String> = try {
        val response = request()
        val backendMessage = response["message"]?.jsonPrimitive?.contentOrNull
        val status = response["status"]?.jsonPrimitive?.contentOrNull
        if (status != null && status != "success") {
            throw IllegalStateException(backendMessage ?: "$label 操作失败")
        }
        val action = response["action"]?.jsonPrimitive?.contentOrNull
        val message = when (action) {
            "woken_up" -> "已经唤醒，现在可以继续聊了。"
            "already_awake" -> "现在没有在睡觉。"
            "interrupted" -> "已经打断当前活动，接下来会优先回复你。"
            "already_available" -> "当前本来就可以直接聊天。"
            "already_skipped" -> "当前活动已经处于跳过状态。"
            "skipped", "auto_skipped" -> "已经跳过当前活动，不会再提醒返回。"
            "sleeping_use_wake" -> "当前仍在睡眠状态，请先唤醒。"
            else -> backendMessage ?: "$label 操作已完成。"
        }
        lastRefreshTime = 0
        Result.success(message)
    } catch (e: Exception) {
        Log.e(TAG, "$label 角色状态失败", e)
        Result.failure(e)
    }

    fun observeLifeStatus(): StateFlow<LifeStatus?> {
        return cachedLifeStatus
    }

    suspend fun forceRefreshLifeStatus(persona: String? = null): Result<LifeStatus> {
        lastRefreshTime = 0
        return getLifeStatus(persona)
    }

    fun clearCache() {
        _cachedLifeStatus.value = null
        _cachedPersona = null
        lastRefreshTime = 0
        lastWsUpdateTime = 0
    }

    override suspend fun detectEmotion(text: String): Result<JsonObject> {
        return try {
            val payload = buildJsonObject { put("text", text) }
            Result.success(apiService.detectEmotion(payload))
        } catch (e: Exception) {
            Log.e(TAG, "检测情绪失败", e)
            Result.failure(e)
        }
    }

    override suspend fun getActiveCareStatus(): Result<JsonObject> {
        return try {
            Result.success(apiService.getActiveCareStatus())
        } catch (e: Exception) {
            Log.e(TAG, "获取主动关怀状态失败", e)
            Result.failure(e)
        }
    }

    override suspend fun triggerActiveCareCheck(): Result<JsonObject> {
        return try {
            Result.success(apiService.triggerActiveCareCheck())
        } catch (e: Exception) {
            Log.e(TAG, "触发主动关怀检查失败", e)
            Result.failure(e)
        }
    }
}
