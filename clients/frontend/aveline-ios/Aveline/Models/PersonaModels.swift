import Foundation

// MARK: - Persona Models
// 对齐后端 GET /api/v1/personas（list_personas）、GET /api/v1/personas/active、POST /api/v1/personas/switch
// 列表项字段：filename / name / version / path / category / accessible_roles / role

struct Persona: Codable, Identifiable {
    var id: String { filename }

    let filename: String
    let name: String
    let version: String?
    let path: String?
    let category: String?
    let accessibleRoles: [String]?
    let role: String?

    enum CodingKeys: String, CodingKey {
        case filename
        case name
        case version
        case path
        case category
        case accessibleRoles = "accessible_roles"
        case role
    }
}

// GET /api/v1/personas/active 响应：{status, filename, data}
struct ActivePersonaResponse: Codable {
    let status: String?
    let filename: String?
    let data: PersonaDetail?
}

// 单个人格详情（含 system_prompt 等）
struct PersonaDetail: Codable {
    let filename: String?
    let name: String?
    let systemPrompt: String?
    let description: String?

    enum CodingKeys: String, CodingKey {
        case filename
        case name
        case systemPrompt = "system_prompt"
        case description
    }
}

// POST /api/v1/personas/switch 请求体：{filename}
struct SelectPersonaRequest: Codable {
    let filename: String
}

// POST /api/v1/personas（创建）请求体
struct PersonaRequest: Codable {
    let filename: String
    let name: String
    let systemPrompt: String?

    enum CodingKeys: String, CodingKey {
        case filename
        case name
        case systemPrompt = "system_prompt"
    }
}
