import Foundation

// MARK: - Study Models
// 对齐后端 study-daily：calendar / date/{date} / notes / latest-progress
// 所有响应均包裹在 {status, data, timestamp} 中

struct StudyCalendarResponse: Codable {
    let status: String?
    let data: StudyCalendarData
    let timestamp: Double?
}

struct StudyCalendarData: Codable {
    let year: Int
    let month: Int
    let days: [StudyDay]
}

struct StudyDay: Codable, Identifiable {
    var id: String { date }
    let date: String
    let day: Int
    let hasDiary: Bool
    let hasPlan: Bool
    let hasProgress: Bool

    enum CodingKeys: String, CodingKey {
        case date
        case day
        case hasDiary = "has_diary"
        case hasPlan = "has_plan"
        case hasProgress = "has_progress"
    }
}

struct StudyDateContentResponse: Codable {
    let status: String?
    let data: StudyDateContent
    let timestamp: Double?
}

struct StudyDateContent: Codable {
    let date: String
    let diary: String?
    let plan: String?
    let progress: String?
}

struct StudyNotesResponse: Codable {
    let status: String?
    let data: [StudyNote]
    let timestamp: Double?
}

struct StudyNote: Codable, Identifiable {
    var id: String { filename }
    let filename: String
    let path: String
    let title: String?
}

struct StudyProgressResponse: Codable {
    let status: String?
    let data: StudyProgressData
    let timestamp: Double?
}

struct StudyProgressData: Codable {
    let content: String?
    let date: String?
}
