package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.domain.models.*
import com.aveline.ai.mobile.domain.repository.ToolsRepository
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ToolsRepositoryImpl @Inject constructor(
    private val apiService: AvelineApiService
) : ToolsRepository {
    override suspend fun getImageModels(): Result<JsonElement?> {
        return runCatching { apiService.getImageModels().data }
    }

    override suspend fun generateImage(
        prompt: String,
        modelPath: String?,
        negativePrompt: String?
    ): Result<Pair<String?, String?>> {
        return runCatching {
            val payload = buildJsonObject {
                put("prompt", JsonPrimitive(prompt))
                if (!modelPath.isNullOrBlank()) {
                    put("model_path", JsonPrimitive(modelPath))
                }
                if (!negativePrompt.isNullOrBlank()) {
                    put("negative_prompt", JsonPrimitive(negativePrompt))
                }
            }
            val response = apiService.generateImage(payload)
            val url = response.url ?: response.image_url ?: response.images.firstOrNull()?.url
            val base64 = response.images.firstOrNull()?.image_base64
            Pair(url, base64)
        }
    }

    override suspend fun describeVision(imageInput: String, prompt: String?): Result<String> {
        return runCatching {
            val payload = buildJsonObject {
                val trimmed = imageInput.trim()
                // 以 / 开头的是后端下发的图片路径（如上传得到的
                // /output/image/uploads/xxx.jpg），必须走 image_path，
                // 否则后端会把它当 base64 解析而失败。
                val isPath = trimmed.startsWith("/") || trimmed.startsWith("output/")
                val isDataUri = trimmed.startsWith("data:", ignoreCase = true)
                if (!isPath && (isDataUri || trimmed.length > 200)) {
                    put("image_base64", JsonPrimitive(trimmed))
                } else {
                    put("image_path", JsonPrimitive(trimmed))
                }
                if (!prompt.isNullOrBlank()) {
                    put("prompt", JsonPrimitive(prompt))
                }
            }
            val response = apiService.describeVision(payload)
            response.description ?: response.message ?: ""
        }
    }

    override suspend fun getFoodMenu(type: String?): Result<List<FoodItem>> {
        return runCatching {
            apiService.getFoodMenu(type).map { dto ->
                FoodItem(
                    id = dto.id,
                    name = dto.name,
                    description = dto.description,
                    price = dto.price,
                    type = dto.type,
                    icon = dto.icon,
                    nutrition = NutritionProfile(
                        hunger = dto.nutrition.hunger,
                        thirst = dto.nutrition.thirst,
                        energy = dto.nutrition.energy,
                        health = dto.nutrition.health
                    ),
                    taste = TasteProfile(
                        sweet = dto.taste.sweet,
                        sour = dto.taste.sour,
                        bitter = dto.taste.bitter,
                        spicy = dto.taste.spicy,
                        salty = dto.taste.salty,
                        umami = dto.taste.umami,
                        temperature = dto.taste.temperature
                    ),
                    expireHours = dto.expire_hours,
                    minLevel = dto.min_level,
                    rarity = dto.rarity,
                    buffDesc = dto.buff_desc
                )
            }
        }
    }

    override suspend fun getFoodInventory(): Result<List<FoodInventoryItem>> {
        return runCatching {
            apiService.getFoodInventory().data.map { item ->
                FoodInventoryItem(
                    foodId = item.food_id,
                    name = item.name,
                    icon = item.icon,
                    quantity = item.quantity,
                    expireAt = item.expire_at
                )
            }
        }
    }

    override suspend fun buyFood(foodId: String, quantity: Int): Result<FoodActionResult> {
        return runCatching {
            val response = apiService.buyFood(foodId, quantity)
            FoodActionResult(
                success = response.success == true,
                message = response.message ?: "",
                foodId = response.food_id,
                quantity = response.quantity,
                coinsSpent = response.coins_spent
            )
        }
    }

    override suspend fun eatFood(foodId: String, fromInventory: Boolean): Result<FoodActionResult> {
        return runCatching {
            val response = apiService.eatFood(foodId, fromInventory)
            FoodActionResult(
                success = response.success == true,
                message = response.message ?: "",
                foodId = response.food_id,
                quantity = response.quantity,
                coinsSpent = response.coins_spent
            )
        }
    }

    override suspend fun getNotifications(userId: String): Result<List<NotificationItem>> {
        return runCatching {
            apiService.getNotifications(userId).data.map { dto ->
                NotificationItem(
                    id = dto.id.orEmpty(),
                    type = dto.type.orEmpty(),
                    title = dto.title.orEmpty(),
                    content = dto.content.orEmpty(),
                    payload = dto.payload,
                    timestamp = dto.timestamp ?: 0.0,
                    read = dto.read ?: false
                )
            }
        }
    }

    override suspend fun classifyIntent(text: String): Result<IntentResult> {
        return runCatching {
            val payload: JsonObject = buildJsonObject {
                put("text", JsonPrimitive(text))
            }
            val response = apiService.classifyIntent(payload)
            IntentResult(
                intent = response.intent ?: "NONE",
                confidence = response.confidence ?: 0f,
                slots = response.slots,
                raw = response.raw
            )
        }
    }

    override suspend fun getSystemPreferences(): Result<SystemPreferences> {
        return runCatching {
            val data = apiService.getSystemPreferences().data
            SystemPreferences(
                mode = data?.mode ?: "normal",
                activeCareEnabled = data?.active_care_enabled ?: true,
                responseLength = data?.response_length ?: "normal",
                conversationStyle = data?.conversation_style ?: "natural",
                sensitivity = data?.sensitivity ?: "medium",
                debugVisible = data?.debug_visible ?: false
            )
        }
    }

    override suspend fun updateSystemPreferences(update: SystemPreferencesUpdate): Result<SystemPreferences> {
        return runCatching {
            val payload = buildJsonObject {
                update.mode?.let { put("mode", JsonPrimitive(it)) }
                update.activeCareEnabled?.let { put("active_care_enabled", JsonPrimitive(it)) }
                update.responseLength?.let { put("response_length", JsonPrimitive(it)) }
                update.conversationStyle?.let { put("conversation_style", JsonPrimitive(it)) }
                update.sensitivity?.let { put("sensitivity", JsonPrimitive(it)) }
                update.debugVisible?.let { put("debug_visible", JsonPrimitive(it)) }
            }
            val data = apiService.updateSystemPreferences(payload).data
            SystemPreferences(
                mode = data?.mode ?: update.mode ?: "normal",
                activeCareEnabled = data?.active_care_enabled ?: update.activeCareEnabled ?: true,
                responseLength = data?.response_length ?: update.responseLength ?: "normal",
                conversationStyle = data?.conversation_style ?: update.conversationStyle ?: "natural",
                sensitivity = data?.sensitivity ?: update.sensitivity ?: "medium",
                debugVisible = data?.debug_visible ?: update.debugVisible ?: false
            )
        }
    }

    override suspend fun getSystemResources(): Result<JsonElement?> {
        return runCatching { apiService.getSystemResources().data }
    }

    override suspend fun getSystemStats(): Result<JsonElement?> {
        return runCatching {
            val response = apiService.getSystemStats()
            response.data ?: response.metrics
        }
    }

    override suspend fun getSensitiveStatus(userId: String): Result<Boolean> {
        return runCatching { apiService.getSensitiveStatus(userId).enabled ?: false }
    }

    override suspend fun toggleSensitive(userId: String, enabled: Boolean): Result<Boolean> {
        return runCatching {
            val response = apiService.toggleSensitive(
                com.aveline.ai.mobile.data.remote.dto.SensitiveToggleRequest(
                    enabled = enabled,
                    user_id = userId
                )
            )
            response.enabled ?: enabled
        }
    }
}
