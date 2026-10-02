package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable

// ==================== 食物 DTO (旧,保留兼容) ====================

@Serializable
data class NutritionProfileDto(
    val hunger: Float,
    val thirst: Float,
    val energy: Float = 0f,
    val health: Float = 0f
)

@Serializable
data class TasteProfileDto(
    val sweet: Float = 0f,
    val sour: Float = 0f,
    val bitter: Float = 0f,
    val spicy: Float = 0f,
    val salty: Float = 0f,
    val umami: Float = 0f,
    val temperature: String = "room"
)

@Serializable
data class FoodItemDto(
    val id: String,
    val name: String,
    val description: String,
    val price: Int,
    val type: String,
    val icon: String,
    val nutrition: NutritionProfileDto,
    val taste: TasteProfileDto,
    val expire_hours: Int = 24,
    val min_level: Int = 1,
    val rarity: String = "common",
    val buff_desc: String = ""
) {
    fun toDomainModel(): com.aveline.ai.mobile.domain.models.ShopItem {
        return com.aveline.ai.mobile.domain.models.ShopItem(
            id = id,
            name = name,
            description = description,
            category = com.aveline.ai.mobile.domain.models.ShopCategory.FOOD,
            foodType = com.aveline.ai.mobile.domain.models.FoodType.fromString(type),
            price = price,
            icon = icon,
            nutrition = com.aveline.ai.mobile.domain.models.NutritionProfile(
                hunger = nutrition.hunger,
                thirst = nutrition.thirst,
                energy = nutrition.energy,
                health = nutrition.health
            ),
            rarity = com.aveline.ai.mobile.domain.models.ItemRarity.fromString(rarity),
            minLevel = min_level,
            isAvailable = true
        )
    }
}

@Serializable
data class FoodInventoryItemDto(
    val food_id: String,
    val name: String,
    val icon: String,
    val quantity: Int,
    val expire_at: Double? = null
)

@Serializable
data class FoodInventoryResponse(
    val success: Boolean? = null,
    val data: List<FoodInventoryItemDto> = emptyList()
)

@Serializable
data class FoodActionResponse(
    val success: Boolean? = null,
    val message: String? = null,
    val food_id: String? = null,
    val quantity: Int? = null,
    val coins_spent: Int? = null
)

// ==================== 商城 DTO (新) ====================

/**
 * 商城商品 DTO (统一格式,食物和非食物共用)
 */
@Serializable
data class ShopMenuItemDto(
    val id: String,
    val name: String,
    val description: String = "",
    val price: Int = 0,
    val category: String = "food",
    val sub_type: String = "",
    val icon: String = "",
    val nutrition: NutritionProfileDto? = null,
    val taste: TasteProfileDto? = null,
    val expire_hours: Int = 24,
    val min_level: Int = 1,
    val rarity: String = "common",
    val buff_desc: String = "",
    val effect_desc: String = ""
) {
    fun toDomainModel(): com.aveline.ai.mobile.domain.models.ShopItem {
        val cat = com.aveline.ai.mobile.domain.models.ShopCategory.fromString(category)
            ?: com.aveline.ai.mobile.domain.models.ShopCategory.FOOD
        return com.aveline.ai.mobile.domain.models.ShopItem(
            id = id,
            name = name,
            description = description,
            category = cat,
            foodType = if (cat == com.aveline.ai.mobile.domain.models.ShopCategory.FOOD)
                com.aveline.ai.mobile.domain.models.FoodType.fromString(sub_type) else null,
            price = price,
            icon = icon.ifEmpty { cat.icon },
            nutrition = nutrition?.let { n ->
                com.aveline.ai.mobile.domain.models.NutritionProfile(
                    hunger = n.hunger,
                    thirst = n.thirst,
                    energy = n.energy,
                    health = n.health
                )
            },
            effectDesc = effect_desc,
            rarity = com.aveline.ai.mobile.domain.models.ItemRarity.fromString(rarity),
            minLevel = min_level,
            isAvailable = true
        )
    }
}

/**
 * 商城分页响应。
 * coins / unlimited_coins 由后端商城域提供，是商城余额的唯一权威来源。
 */
@Serializable
data class ShopMenuResponse(
    val items: List<ShopMenuItemDto> = emptyList(),
    val total: Int = 0,
    val page: Int = 1,
    val page_size: Int = 20,
    val has_more: Boolean = false,
    val coins: Int = 0,
    val unlimited_coins: Boolean = false
)

/**
 * 购买响应 (带 recipient)
 */
@Serializable
data class ShopBuyResponse(
    val success: Boolean? = null,
    val message: String? = null,
    val item_id: String? = null,
    val item_name: String? = null,
    val category: String? = null,
    val quantity: Int? = null,
    val coins_spent: Int? = null,
    val unlimited_coins: Boolean? = null,
    val recipient: String? = null
)

/**
 * 礼物库存物品 DTO
 */
@Serializable
data class GiftInventoryItemDto(
    val item_id: String,
    val item_name: String,
    val category: String = "",
    val quantity: Int = 1,
    val recipient: String = "self",
    val effect_desc: String = "",
    val purchased_at: Double = 0.0
) {
    fun toDomainModel(): com.aveline.ai.mobile.domain.models.GiftInventoryItem {
        return com.aveline.ai.mobile.domain.models.GiftInventoryItem(
            itemId = item_id,
            itemName = item_name,
            category = category,
            quantity = quantity,
            recipient = recipient,
            effectDesc = effect_desc,
            purchasedAt = purchased_at
        )
    }
}

/**
 * 礼物库存响应
 */
@Serializable
data class GiftInventoryResponse(
    val success: Boolean? = null,
    val data: List<GiftInventoryItemDto> = emptyList()
)

/**
 * 使用礼物响应
 */
@Serializable
data class UseGiftResponse(
    val success: Boolean? = null,
    val message: String? = null,
    val item_id: String? = null,
    val item_name: String? = null,
    val icon: String? = null,
    val category: String? = null,
    val rarity: String? = null,
    val recipient: String? = null,
    val applied_effects: Map<String, Double>? = null,
    val neuro_effects: Map<String, String>? = null
)
