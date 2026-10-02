import Foundation

// MARK: - Message Models
// 对齐后端 POST /api/v1/chat/message
// 请求体为裸 dict：content / conversation_id / persona_filename / user_name / stream

struct MessageRequest: Codable {
    let content: String
    var conversationId: String?
    var personaFilename: String?
    var userName: String?
    var stream: Bool?

    enum CodingKeys: String, CodingKey {
        case content
        case conversationId = "conversation_id"
        case personaFilename = "persona_filename"
        case userName = "user_name"
        case stream
    }
}

// 后端响应：{status, response, request_id, timestamp, message_id, conversation_id, ...}
struct MessageResponse: Codable {
    let status: String?
    let response: String
    let requestId: String?
    let timestamp: Double?
    let messageId: String?
    let conversationId: String?

    enum CodingKeys: String, CodingKey {
        case status
        case response
        case requestId = "request_id"
        case timestamp
        case messageId = "message_id"
        case conversationId = "conversation_id"
    }
}
