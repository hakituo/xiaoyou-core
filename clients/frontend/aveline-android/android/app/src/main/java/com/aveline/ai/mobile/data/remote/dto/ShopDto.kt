package com.aveline.ai.mobile.data.remote.dto

import com.aveline.ai.mobile.domain.models.FoodType
import com.aveline.ai.mobile.domain.models.PurchaseResult
import com.aveline.ai.mobile.domain.models.ShopCategory
import com.aveline.ai.mobile.domain.models.ShopItem
import com.aveline.ai.mobile.domain.models.UserBalance
import kotlinx.serialization.Serializable

/**
 * Response DTO for shop items.
 * 
 * @property status Response status
 * @property items List of shop item objects
 * @property balance User's current balance
 */
@Serializable
data class ShopItemsResponse(
    val status: String,
    val items: List<ShopItemDto>,
    val balance: UserBalanceDto? = null
)

/**
 * Shop item DTO representing a purchasable item.
 * 
 * @property id Unique item identifier
 * @property name Item name
 * @property description Item description
 * @property price Item price in coins
 * @property category Item category (food, item, decoration)
 * @property icon Item icon identifier
 * @property effects Effects applied when item is used
 * @property isAvailable Whether item is available for purchase
 */
@Serializable
data class ShopItemDto(
    val id: String,
    val name: String,
    val description: String = "",
    val price: Int,
    val category: String,
    val icon: String,
    val effects: Map<String, Float> = emptyMap(),
    val is_available: Boolean = true
) {
    fun toDomainModel(): ShopItem {
        // 将旧分类映射到食物子类型
        val foodType = when (category.lowercase()) {
            "food" -> FoodType.MEAL  // 默认为正餐
            "snack" -> FoodType.SNACK
            "drink" -> FoodType.DRINK
            else -> FoodType.MEAL
        }
        return ShopItem(
            id = id,
            name = name,
            description = description,
            category = ShopCategory.FOOD,
            foodType = foodType,
            price = price,
            icon = icon,
            nutrition = null,
            isAvailable = is_available
        )
    }
}

/**
 * User balance DTO
 */
@Serializable
data class UserBalanceDto(
    val coins: Int = 0,
    val gems: Int = 0,
    val total_earned: Int = 0,
    val total_spent: Int = 0
) {
    fun toDomainModel(): UserBalance {
        return UserBalance(
            coins = coins,
            gems = gems,
            totalEarned = total_earned,
            totalSpent = total_spent
        )
    }
}

/**
 * Request DTO for purchasing an item.
 * 
 * @property item_id The item ID to purchase
 * @property quantity Number of items to purchase
 */
@Serializable
data class PurchaseRequest(
    val item_id: String,
    val quantity: Int = 1
)

/**
 * Response DTO for purchase operations.
 * 
 * @property status Response status
 * @property message Response message
 * @property new_balance User's new coin balance after purchase
 * @property effects_applied Effects that were applied
 * @property balance Full balance info
 */
@Serializable
data class PurchaseResponse(
    val status: String,
    val message: String = "",
    val new_balance: Int = 0,
    val effects_applied: Map<String, Float> = emptyMap(),
    val balance: UserBalanceDto? = null
) {
    fun toDomainModel(): PurchaseResult {
        return PurchaseResult(
            success = status == "success",
            message = message.ifEmpty { if (status == "success") "购买成功" else "购买失败" },
            newBalance = balance?.toDomainModel()
        )
    }
}
