package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.domain.models.*
import kotlinx.serialization.json.JsonElement

interface ToolsRepository {
    suspend fun getImageModels(): Result<JsonElement?>
    suspend fun generateImage(prompt: String, modelPath: String?, negativePrompt: String?): Result<Pair<String?, String?>>
    suspend fun describeVision(imageInput: String, prompt: String?): Result<String>
    suspend fun getFoodMenu(type: String?): Result<List<FoodItem>>
    suspend fun getFoodInventory(): Result<List<FoodInventoryItem>>
    suspend fun buyFood(foodId: String, quantity: Int): Result<FoodActionResult>
    suspend fun eatFood(foodId: String, fromInventory: Boolean): Result<FoodActionResult>
    suspend fun getNotifications(userId: String): Result<List<NotificationItem>>
    suspend fun classifyIntent(text: String): Result<IntentResult>
    suspend fun getSystemPreferences(): Result<SystemPreferences>
    suspend fun updateSystemPreferences(update: SystemPreferencesUpdate): Result<SystemPreferences>
    suspend fun getSystemResources(): Result<JsonElement?>
    suspend fun getSystemStats(): Result<JsonElement?>
    suspend fun getSensitiveStatus(userId: String): Result<Boolean>
    suspend fun toggleSensitive(userId: String, enabled: Boolean): Result<Boolean>
}
