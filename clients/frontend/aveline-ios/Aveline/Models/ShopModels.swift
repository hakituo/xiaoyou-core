import Foundation

// MARK: - Shop Category

/// 商城商品分类，与后端 ShopItem.category 一致。
enum ShopCategory: String, Codable, CaseIterable, Identifiable {
    case food = "food"
    case gift = "gift"
    case toy = "toy"
    case book = "book"
    case clothing = "clothing"
    case tech = "tech"
    case luxury = "luxury"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .food: return "食物"
        case .gift: return "礼物"
        case .toy: return "玩具"
        case .book: return "书籍"
        case .clothing: return "服饰"
        case .tech: return "科技"
        case .luxury: return "奢侈品"
        }
    }

    var icon: String {
        switch self {
        case .food: return "🍔"
        case .gift: return "🎁"
        case .toy: return "🧸"
        case .book: return "📚"
        case .clothing: return "👗"
        case .tech: return "📱"
        case .luxury: return "💎"
        }
    }
}

// MARK: - Food Type

/// 食物子类型（仅 food 类别商品有），与后端 ShopItem.sub_type 一致。
enum FoodType: String, Codable {
    case meal = "meal"
    case snack = "snack"
    case drink = "drink"
    case ingredient = "ingredient"

    var label: String {
        switch self {
        case .meal: return "正餐"
        case .snack: return "零食"
        case .drink: return "饮料"
        case .ingredient: return "食材"
        }
    }
}

// MARK: - Item Rarity

/// 稀有度，与后端 ShopItem.rarity 一致。
enum ItemRarity: String, Codable {
    case common = "common"
    case rare = "rare"
    case epic = "epic"
    case legendary = "legendary"

    var label: String {
        switch self {
        case .common: return "普通"
        case .rare: return "稀有"
        case .epic: return "史诗"
        case .legendary: return "传说"
        }
    }

    var icon: String {
        switch self {
        case .common: return ""
        case .rare: return "⭐"
        case .epic: return "💜"
        case .legendary: return "💛"
        }
    }
}

// MARK: - Nutrition Profile

/// 营养属性，与后端 ShopItem.nutrition 一致（仅食物类商品有）。
struct NutritionProfile: Codable {
    let hunger: Double
    let thirst: Double
    let energy: Double
    let health: Double
}

// MARK: - Shop Item

/// 商城商品数据模型 —— 字段对齐后端 core/food/models.ShopItem。
struct ShopItem: Codable, Identifiable {
    let id: String
    let name: String
    let description: String
    let price: Int

    /// 商城类别: food/gift/toy/book/clothing/tech/luxury
    let category: ShopCategory

    /// 食物子类型(meal/snack/drink/ingredient)；非食物为子类别字符串
    let sub_type: String?

    /// 图标 emoji（或 URL）
    let icon: String?

    // 食物专属字段（非食物为 nil）
    let nutrition: NutritionProfile?

    let expire_hours: Int?
    let min_level: Int?
    let rarity: ItemRarity
    let buff_desc: String?
    /// 非食物商品的使用/赠送效果描述
    let effect_desc: String?

    // MARK: 展示辅助

    /// 食物类型（仅食物类有值）
    var foodType: FoodType? {
        guard category == .food else { return nil }
        return FoodType(rawValue: sub_type ?? "")
    }

    /// 展示用效果文本
    var effectText: String {
        if category == .food {
            if let n = nutrition {
                var parts: [String] = []
                if n.hunger > 0 { parts.append("饥饿+\(Int(n.hunger))") }
                if n.thirst > 0 { parts.append("口渴+\(Int(n.thirst))") }
                if n.energy > 0 { parts.append("能量+\(Int(n.energy))") }
                if n.health > 0 { parts.append("健康+\(Int(n.health))") }
                return parts.joined(separator: " ")
            }
            return "恢复饥饿值"
        }
        return effect_desc ?? ""
    }

    var isFood: Bool { category == .food }
}

// MARK: - Shop Menu Response (分页)

/// 对齐后端 GET /food/shop/menu 返回结构。
struct ShopMenuResponse: Codable {
    let items: [ShopItem]
    let total: Int
    let page: Int
    let page_size: Int
    let has_more: Bool
}

// MARK: - Purchase Request

/// 对齐后端 POST /food/buy/{item_id}（query 参数）。
struct PurchaseRequest: Codable {
    let item_id: String
    let quantity: Int
    /// 给谁买: self/aveline/ling
    let recipient: String
}

// MARK: - Purchase Response

/// 对齐后端 buy() 返回结构。
struct PurchaseResponse: Codable {
    let success: Bool
    let message: String
    let item_id: String?
    let item_name: String?
    let category: String?
    let quantity: Int?
    let coins_spent: Int?
    let unlimited_coins: Bool?
    let recipient: String?
}
