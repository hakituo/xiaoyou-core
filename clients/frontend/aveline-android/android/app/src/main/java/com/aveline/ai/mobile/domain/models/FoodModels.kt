package com.aveline.ai.mobile.domain.models

data class NutritionProfile(
    val hunger: Float,
    val thirst: Float,
    val energy: Float,
    val health: Float
)

data class TasteProfile(
    val sweet: Float,
    val sour: Float,
    val bitter: Float,
    val spicy: Float,
    val salty: Float,
    val umami: Float,
    val temperature: String
)

data class FoodItem(
    val id: String,
    val name: String,
    val description: String,
    val price: Int,
    val type: String,
    val icon: String,
    val nutrition: NutritionProfile,
    val taste: TasteProfile,
    val expireHours: Int,
    val minLevel: Int,
    val rarity: String,
    val buffDesc: String
)

data class FoodInventoryItem(
    val foodId: String,
    val name: String,
    val icon: String,
    val quantity: Int,
    val expireAt: Double?
)

data class FoodActionResult(
    val success: Boolean,
    val message: String,
    val foodId: String?,
    val quantity: Int?,
    val coinsSpent: Int?
)
