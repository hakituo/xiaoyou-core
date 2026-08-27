import Foundation
import Combine

// MARK: - WebSocket Message Types WebSocket 消息类型

// WebSocket 消息协议
protocol WebSocketMessage: Codable {
    var type: String { get }
}

// 基础消息结构
struct BaseMessage: Codable {
    let type: String
    let subtype: String?
    let content: String?
    let data: [String: AnyCodable]?
    let emotion: String?
    let emotion_internal: [String: Double]?
    let message_id: String?
    let messageId: String?
    let id: String?
    let request_id: String?
    let requestId: String?
}

// AnyCodable 用于处理动态数据类型
struct AnyCodable: Codable {
    let value: Any
    
    init(_ value: Any) {
        self.value = value
    }
    
    func encode(to encoder: Encoder) throws {
        // 简单实现，实际项目中可能需要更完善的处理
        var container = encoder.singleValueContainer()
        if let intValue = value as? Int {
            try container.encode(intValue)
        } else if let doubleValue = value as? Double {
            try container.encode(doubleValue)
        } else if let stringValue = value as? String {
            try container.encode(stringValue)
        } else if let boolValue = value as? Bool {
            try container.encode(boolValue)
        } else if let arrayValue = value as? [Any] {
            try container.encode(arrayValue.compactMap { AnyCodable($0) })
        } else if let dictValue = value as? [String: Any] {
            try container.encode(dictValue.mapValues { AnyCodable($0) })
        }
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let intValue = try? container.decode(Int.self) {
            value = intValue
        } else if let doubleValue = try? container.decode(Double.self) {
            value = doubleValue
        } else if let stringValue = try? container.decode(String.self) {
            value = stringValue
        } else if let boolValue = try? container.decode(Bool.self) {
            value = boolValue
        } else if let arrayValue = try? container.decode([AnyCodable].self) {
            value = arrayValue.map { $0.value }
        } else if let dictValue = try? container.decode([String: AnyCodable].self) {
            value = dictValue.mapValues { $0.value }
        } else {
            value = NSNull()
        }
    }
}

// 生命状态
struct LifeStatus: Codable {
    let actor_life_states: [String: AnyCodable]?
    let actor_relationships: [String: Double]?
    let emotion: String?
}

// 系统状态
struct SystemStats: Codable {
    let cpu: Double?
    let gpu: Double?
    let memory: Double?
    let temperature: Double?
    let scheduler: [String: AnyCodable]?
}

// MARK: - WebSocket Manager

@MainActor
class WebSocketManager: ObservableObject {
    enum ConnectionState {
        case connected
        case connecting
        case disconnected
    }
    
    @Published var connectionState: ConnectionState = .disconnected
    
    // 消息发布者
    let messageSubject = PassthroughSubject<BaseMessage, Never>()
    let lifeStatusSubject = PassthroughSubject<LifeStatus, Never>()
    let systemStatsSubject = PassthroughSubject<SystemStats, Never>()
    let emotionSubject = PassthroughSubject<(emotion: String, mix: [String: Double]?), Never>()
    let errorSubject = PassthroughSubject<String, Never>()
    
    private var webSocketTask: URLSessionWebSocketTask?
    private let session: URLSession
    private var baseURL: String
    private var authToken: String?
    private var reconnectTimer: Timer?
    private let reconnectInterval: TimeInterval = 5.0
    private var cancellables = Set<AnyCancellable>()
    
    init(baseURL: String, authToken: String? = nil) {
        self.baseURL = baseURL
        self.authToken = authToken
        let config = URLSessionConfiguration.default
        self.session = URLSession(configuration: config)
    }
    
    func updateAuthToken(_ token: String?) {
        self.authToken = token
    }
    
    func updateBaseURL(_ url: String) {
        self.baseURL = url
    }
    
    func connect() {
        guard connectionState != .connected else { return }
        
        connectionState = .connecting
        
        guard var components = URLComponents(string: baseURL) else {
            connectionState = .disconnected
            return
        }
        
        // 转换 http:// 到 ws:// 或 https:// 到 wss://
        if components.scheme == "http" {
            components.scheme = "ws"
        } else if components.scheme == "https" {
            components.scheme = "wss"
        }
        
        components.path = "/ws"
        
        guard let url = components.url else {
            connectionState = .disconnected
            return
        }
        
        var request = URLRequest(url: url)
        if let token = authToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        
        webSocketTask = session.webSocketTask(with: request)
        webSocketTask?.resume()
        
        connectionState = .connected
        receiveMessage()
    }
    
    func disconnect() {
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        connectionState = .disconnected
        reconnectTimer?.invalidate()
        reconnectTimer = nil
    }
    
    func reconnect() {
        disconnect()
        connect()
    }
    
    // 发送 JSON 消息
    func sendJSONMessage(_ message: [String: Any]) {
        guard connectionState == .connected else { return }
        
        do {
            let data = try JSONSerialization.data(withJSONObject: message)
            if let jsonString = String(data: data, encoding: .utf8) {
                sendMessage(jsonString)
            }
        } catch {
            print("Failed to serialize JSON message: \(error)")
        }
    }
    
    // 发送文本消息
    func sendMessage(_ message: String) {
        guard connectionState == .connected else { return }
        
        let wsMessage = URLSessionWebSocketTask.Message.string(message)
        webSocketTask?.send(wsMessage) { [weak self] error in
            if let error = error {
                print("WebSocket send error: \(error)")
                self?.handleDisconnection()
            }
        }
    }
    
    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            switch result {
            case .failure(let error):
                print("WebSocket receive error: \(error)")
                self?.handleDisconnection()
            case .success(let message):
                switch message {
                case .string(let text):
                    self?.handleMessage(text)
                case .data(let data):
                    self?.handleMessage(String(data: data, encoding: .utf8) ?? "")
                @unknown default:
                    break
                }
                // 继续接收消息
                self?.receiveMessage()
            }
        }
    }
    
    private func handleMessage(_ messageText: String) {
        print("Received WebSocket message: \(messageText)")
        
        guard let data = messageText.data(using: .utf8) else {
            return
        }
        
        do {
            let baseMessage = try JSONDecoder().decode(BaseMessage.self, from: data)
            
            // 发布基础消息
            messageSubject.send(baseMessage)
            
            // 根据消息类型分发处理
            switch baseMessage.type {
            case "life_status":
                handleLifeStatus(baseMessage, data: data)
            case "system_status":
                handleSystemStatus(baseMessage, data: data)
            case "spontaneous_reaction":
                handleSpontaneousReaction(baseMessage)
            case "persona_update":
                handlePersonaUpdate(baseMessage)
            case "preference_update":
                handlePreferenceUpdate(baseMessage)
            case "notification":
                handleNotification(baseMessage)
            case "image_trigger", "image_status", "image_result":
                handleImageMessage(baseMessage)
            case "stream_token", "message":
                handleChatMessage(baseMessage)
            case "tts_audio":
                handleTTSAudio(baseMessage)
            case "vibrate", "haptic":
                handleHaptic()
            case "error":
                handleError(baseMessage)
            case "group_member_message":
                handleGroupMemberMessage(baseMessage)
            default:
                print("Unhandled message type: \(baseMessage.type)")
            }
        } catch {
            print("Failed to parse WebSocket message: \(error)")
        }
    }
    
    // 处理生命状态消息
    private func handleLifeStatus(_ message: BaseMessage, data: Data) {
        do {
            let lifeStatus = try JSONDecoder().decode(LifeStatus.self, from: data)
            lifeStatusSubject.send(lifeStatus)
            
            // 如果有情绪信息，发布情绪更新
            if let emotion = lifeStatus.emotion {
                emotionSubject.send((emotion: emotion, mix: lifeStatus.actor_life_states as? [String: Double]))
            }
        } catch {
            print("Failed to parse life status: \(error)")
        }
    }
    
    // 处理系统状态消息
    private func handleSystemStatus(_ message: BaseMessage, data: Data) {
        do {
            let stats = try JSONDecoder().decode(SystemStats.self, from: data)
            systemStatsSubject.send(stats)
        } catch {
            print("Failed to parse system stats: \(error)")
        }
    }
    
    // 处理自发反应消息
    private func handleSpontaneousReaction(_ message: BaseMessage) {
        // 可以在这里添加处理逻辑
        print("Spontaneous reaction: \(message.content ?? "")")
    }
    
    // 处理角色更新
    private func handlePersonaUpdate(_ message: BaseMessage) {
        // 可以在这里添加处理逻辑
        print("Persona update received")
    }
    
    // 处理偏好更新
    private func handlePreferenceUpdate(_ message: BaseMessage) {
        // 可以在这里添加处理逻辑
        print("Preference update received")
    }
    
    // 处理通知
    private func handleNotification(_ message: BaseMessage) {
        let content = message.content ?? "New Message"
        print("Notification: \(content)")
        // 可以在这里添加本地通知逻辑
    }
    
    // 处理图片消息
    private func handleImageMessage(_ message: BaseMessage) {
        print("Image message: \(message.type)")
    }
    
    // 处理聊天消息
    private func handleChatMessage(_ message: BaseMessage) {
        // 从文本推断情绪
        if let content = message.content {
            let inferredEmotion = EmotionColors.inferEmotion(from: content)
            emotionSubject.send((emotion: inferredEmotion, mix: nil))
        }
    }
    
    // 处理 TTS 音频
    private func handleTTSAudio(_ message: BaseMessage) {
        print("TTS audio received")
    }
    
    // 处理触觉反馈
    private func handleHaptic() {
        print("Haptic feedback requested")
        // 可以在这里添加触觉反馈逻辑
    }
    
    // 处理错误消息
    private func handleError(_ message: BaseMessage) {
        let errorText = message.content ?? "系统处理消息时遇到错误"
        errorSubject.send(errorText)
    }
    
    // 处理群组成员消息
    private func handleGroupMemberMessage(_ message: BaseMessage) {
        print("Group member message received")
    }
    
    private func handleDisconnection() {
        DispatchQueue.main.async { [weak self] in
            self?.connectionState = .disconnected
            self?.scheduleReconnect()
        }
    }
    
    private func scheduleReconnect() {
        reconnectTimer?.invalidate()
        reconnectTimer = Timer.scheduledTimer(withTimeInterval: reconnectInterval, repeats: false) { [weak self] _ in
            DispatchQueue.main.async {
                self?.connect()
            }
        }
    }
    
    // 解析消息 ID
    static func resolveMessageId(_ message: BaseMessage, fallback: String? = nil) -> String {
        let raw = message.message_id ?? message.messageId ?? message.id ?? message.request_id ?? message.requestId ?? fallback
        if let raw = raw, !raw.isEmpty {
            return raw
        }
        return String(Date().timeIntervalSince1970)
    }
}

