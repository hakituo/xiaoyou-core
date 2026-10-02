import Foundation

// MARK: - Life Status Models
// 对齐后端 GET /api/v1/life/status
// 响应：{status, data: LifeStatusState, life_status, emotion, emotion_mix, timestamp}

struct LifeStatusResponse: Codable {
    let status: String?
    let data: LifeStatusState
    let lifeStatus: LifeStatusSummary?
    let emotion: EmotionInfo?
    let emotionMix: [String: Double]?
    let timestamp: String?

    enum CodingKeys: String, CodingKey {
        case status
        case data
        case lifeStatus = "life_status"
        case emotion
        case emotionMix = "emotion_mix"
        case timestamp
    }
}

struct LifeStatusState: Codable {
    let cpuTemp: Double?
    let ramUsage: Double?
    let battery: Double?
    let networkLatency: Double?
    let mood: String?
    let activity: String?
    let visionSummary: String?
    let isRunning: Bool?
    let life: LifeStatsInfo?
    let bio: BioStats?
    let immune: ImmuneStatus?

    enum CodingKeys: String, CodingKey {
        case cpuTemp = "cpu_temp"
        case ramUsage = "ram_usage"
        case battery
        case networkLatency = "network_latency"
        case mood
        case activity
        case visionSummary = "vision_summary"
        case isRunning = "is_running"
        case life
        case bio
        case immune
    }
}

struct LifeStatsInfo: Codable {
    let energy: Double?
    let hunger: Double?
    let thirst: Double?
    let hygiene: Double?
    let happiness: Double?
    let social: Double?
    let health: Double?
}

struct BioStats: Codable {
    let heartRate: Double?
    let bodyTemp: Double?
    let bloodOxygen: Double?

    enum CodingKeys: String, CodingKey {
        case heartRate = "heart_rate"
        case bodyTemp = "body_temp"
        case bloodOxygen = "blood_oxygen"
    }
}

struct ImmuneStatus: Codable {
    let level: String?
    let strength: Double?
}

struct LifeStatusSummary: Codable {
    let energy: Double?
    let mood: String?
    let health: Double?
}

struct EmotionInfo: Codable {
    let current: EmotionCurrent?
    let mix: EmotionMix?
}

struct EmotionCurrent: Codable {
    let name: String?
    let intensity: Double?
}

struct EmotionMix: Codable {
    let joy: Double?
    let trust: Double?
    let fear: Double?
    let surprise: Double?
    let sadness: Double?
    let disgust: Double?
    let anger: Double?
    let anticipation: Double?
}
