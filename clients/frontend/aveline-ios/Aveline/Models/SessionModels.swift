import Foundation

// MARK: - Session

struct Session: Codable, Identifiable {
    let id: String
    let title: String
    let created_at: String
    let updated_at: String
    let message_count: Int
    let is_pinned: Bool?
}

// MARK: - Sessions Response

struct SessionsResponse: Codable {
    let sessions: [Session]
}

// MARK: - Create Session Request

struct CreateSessionRequest: Codable {
    let title: String
}

// MARK: - Session Response

struct SessionResponse: Codable {
    let session: Session
}

// MARK: - History Response

struct HistoryResponse: Codable {
    let messages: [MessageResponse]
}
