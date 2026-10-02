import Foundation

// MARK: - Memory Models
// 对齐后端 GET /api/v1/memories（列表）、GET /api/v1/memories/stats、GET /api/v1/memories/tags
// 列表响应：{status, data: [Memory], timestamp}
// 记忆对象字段：content / weight / category / topics / timestamp / source / emotions

struct MemoryListResponse: Codable {
    let status: String?
    let data: [Memory]
    let timestamp: Double?
}

struct Memory: Codable, Identifiable {
    // 后端记忆对象可能没有稳定 id，用 content+timestamp 兜底
    var id: String {
        (timestamp?.description ?? "") + "_" + String(content.prefix(16))
    }

    let content: String
    let weight: Double?
    let category: String?
    let topics: [String]?
    let timestamp: Double?
    let source: String?
    let emotions: [String: Double]?

    enum CodingKeys: String, CodingKey {
        case content
        case weight
        case category
        case topics
        case timestamp
        case source
        case emotions
    }
}

struct MemoryStatsResponse: Codable {
    let status: String?
    let data: [String: Double]?
    let timestamp: Double?
}

struct TagsResponse: Codable {
    let status: String?
    let data: [MemoryTag]
    let timestamp: Double?
}

struct MemoryTag: Codable, Identifiable {
    let id: String
    let name: String
    let weight: Double
}
