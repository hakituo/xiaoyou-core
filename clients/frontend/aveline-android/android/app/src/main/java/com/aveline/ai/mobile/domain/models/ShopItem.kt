package com.aveline.ai.mobile.domain.models

/**
 * 商城商品分类 - 食物只是其中一个子集
 */
enum class ShopCategory {
    FOOD,       // 食物
    GIFT,       // 礼物
    TOY,        // 玩具
    BOOK,       // 书籍
    CLOTHING,   // 服饰
    TECH,       // 科技产品
    LUXURY;     // 奢侈品

    val label: String
        get() = when (this) {
            FOOD -> "食物"
            GIFT -> "礼物"
            TOY -> "玩具"
            BOOK -> "书籍"
            CLOTHING -> "服饰"
            TECH -> "科技"
            LUXURY -> "奢侈品"
        }

    val icon: String
        get() = when (this) {
            FOOD -> "🍔"
            GIFT -> "🎁"
            TOY -> "🧸"
            BOOK -> "📚"
            CLOTHING -> "👗"
            TECH -> "📱"
            LUXURY -> "💎"
        }

    companion object {
        fun fromString(cat: String?): ShopCategory? = when (cat?.lowercase()?.trim()) {
            "food" -> FOOD
            "gift" -> GIFT
            "toy" -> TOY
            "book" -> BOOK
            "clothing" -> CLOTHING
            "tech" -> TECH
            "luxury" -> LUXURY
            else -> null
        }
    }
}

/**
 * 食物子类型 (仅 FOOD 类别商品有)
 */
enum class FoodType {
    MEAL,   // 正餐
    SNACK,  // 零食
    DRINK;  // 饮料

    val label: String
        get() = when (this) {
            MEAL -> "正餐"
            SNACK -> "零食"
            DRINK -> "饮料"
        }

    companion object {
        fun fromString(type: String?): FoodType? = when (type?.lowercase()?.trim()) {
            "meal" -> MEAL
            "snack" -> SNACK
            "drink" -> DRINK
            else -> null
        }
    }
}

/**
 * 商品稀有度
 */
enum class ItemRarity {
    COMMON,
    RARE,
    EPIC,
    LEGENDARY;

    val label: String
        get() = when (this) {
            COMMON -> "普通"
            RARE -> "稀有"
            EPIC -> "史诗"
            LEGENDARY -> "传说"
        }

    val icon: String
        get() = when (this) {
            COMMON -> ""
            RARE -> "⭐"
            EPIC -> "💜"
            LEGENDARY -> "💛"
        }

    companion object {
        fun fromString(r: String?): ItemRarity = when (r?.lowercase()?.trim()) {
            "rare" -> RARE
            "epic" -> EPIC
            "legendary" -> LEGENDARY
            else -> COMMON
        }
    }
}

/**
 * 购买 recipient 枚举
 */
enum class PurchaseRecipient(val key: String, val label: String) {
    SELF("self", "给自己"),
    AVELINE("aveline", "给 Aveline"),
    LING("ling", "给Ling");

    companion object {
        fun fromKey(key: String?): PurchaseRecipient = when (key?.lowercase()?.trim()) {
            "aveline" -> AVELINE
            "ling" -> LING
            else -> SELF
        }
    }
}

/**
 * 商城商品数据模型 - 支持食物和非食物
 *
 * @property id 商品 ID
 * @property name 商品名称
 * @property description 商品描述
 * @property category 商城类别 (food/gift/toy/book/clothing/tech/luxury)
 * @property foodType 食物子类型 (仅 food 类别有)
 * @property price 价格
 * @property icon 图标 emoji
 * @property nutrition 营养属性 (仅食物有)
 * @property effectDesc 使用效果描述 (非食物的 "心情+15" 等)
 * @property rarity 稀有度
 * @property minLevel 最低等级要求
 * @property isAvailable 是否可购买
 */
data class ShopItem(
    val id: String,
    val name: String,
    val description: String = "",
    val category: ShopCategory = ShopCategory.FOOD,
    val foodType: FoodType? = null,
    val price: Int = 0,
    val icon: String = "🍽️",
    val nutrition: NutritionProfile? = null,
    val effectDesc: String = "",
    val rarity: ItemRarity = ItemRarity.COMMON,
    val minLevel: Int = 1,
    val isAvailable: Boolean = true
) {
    /** 展示用效果文本 */
    val effectDescription: String
        get() = when (category) {
            ShopCategory.FOOD -> buildString {
                nutrition?.let { n ->
                    if (n.hunger > 0) append("饥饿+${n.hunger.toInt()} ")
                    if (n.thirst > 0) append("口渴+${n.thirst.toInt()} ")
                    if (n.energy > 0) append("能量+${n.energy.toInt()} ")
                    if (n.health > 0) append("健康+${n.health.toInt()}")
                } ?: append("恢复饥饿值")
            }.trim()
            else -> effectDesc
        }

    /** 是否是食物 */
    val isFood: Boolean get() = category == ShopCategory.FOOD

    val canAfford: (Int) -> Boolean
        get() = { balance -> balance >= price }
}

/**
 * 用户余额信息
 */
data class UserBalance(
    val coins: Int = 0,
    val gems: Int = 0,
    val totalEarned: Int = 0,
    val totalSpent: Int = 0
) {
    val canAfford: (Int) -> Boolean
        get() = { price -> coins >= price }
}

/**
 * 购买结果
 */
data class PurchaseResult(
    val success: Boolean,
    val message: String,
    val newBalance: UserBalance? = null
)

/**
 * 礼物库存物品
 */
data class GiftInventoryItem(
    val itemId: String,
    val itemName: String,
    val category: String,
    val quantity: Int,
    val recipient: String,
    val effectDesc: String,
    val purchasedAt: Double = 0.0
)
