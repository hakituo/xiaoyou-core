import Foundation
import Combine

// 系统状态
struct SystemStatsState {
    var cpu: Double = 0
    var gpu: Double = 0
    var memory: Double = 0
    var temperature: Double = 0
    var scheduler: [String: Any]?
}

@MainActor
class MainViewModel: ObservableObject {
    // MARK: - Published Properties
    
    @Published var connectionState: WebSocketManager.ConnectionState = .disconnected
    @Published var sessions: [Session] = []
    @Published var currentSessionId: String?
    @Published var currentEmotion: String = "neutral"
    @Published var emotionMix: [String: Double] = ["neutral": 1.0]
    @Published var lifeStatus: [String: Any] = [:]
    @Published var systemStats: SystemStatsState = SystemStatsState()
    @Published var isTyping: Bool = false
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?
    @Published var studyMode: Bool = false
    @Published var breathingRate: Double = 1.0
    @Published var isConnected: Bool = false
    
    // 情绪锁定时间
    @Published var emotionLockUntil: Date = Date.distantPast
    
    // MARK: - Private Properties
    
    private let apiService: AvelineAPIService
    private let webSocketManager: WebSocketManager
    private let preferences: AppPreferences
    private var cancellables = Set<AnyCancellable>()
    
    // MARK: - Initialization
    
    init() {
        let container = DependencyContainer.shared
        self.apiService = container.apiService
        self.webSocketManager = container.webSocketManager
        self.preferences = container.appPreferences
        self.currentSessionId = preferences.currentSessionId ?? "default_user"
        
        setupBindings()
    }
    
    // MARK: - Bindings
    
    private func setupBindings() {
        // 观察 WebSocket 连接状态
        webSocketManager.$connectionState
            .sink { [weak self] state in
                self?.connectionState = state
                self?.isConnected = state == .connected
            }
            .store(in: &cancellables)
        
        // 观察情绪更新
        webSocketManager.emotionSubject
            .sink { [weak self] emotionData in
                self?.handleEmotionUpdate(emotion: emotionData.emotion, mix: emotionData.mix)
            }
            .store(in: &cancellables)
        
        // 观察生命状态
        webSocketManager.lifeStatusSubject
            .sink { [weak self] lifeStatus in
                self?.handleLifeStatusUpdate(lifeStatus)
            }
            .store(in: &cancellables)
        
        // 观察系统状态
        webSocketManager.systemStatsSubject
            .sink { [weak self] stats in
                self?.handleSystemStatsUpdate(stats)
            }
            .store(in: &cancellables)
        
        // 观察错误消息
        webSocketManager.errorSubject
            .sink { [weak self] error in
                self?.errorMessage = error
            }
            .store(in: &cancellables)
    }
    
    // MARK: - Emotion Handling
    
    private func handleEmotionUpdate(emotion: String, mix: [String: Double]?) {
        // 检查情绪是否被锁定
        if Date() < emotionLockUntil {
            return
        }
        
        // 规范化情绪名称
        let normalizedEmotion = EmotionColors.normalizeEmotion(emotion)
        
        withAnimation(.easeInOut(duration: 1.5)) {
            self.currentEmotion = normalizedEmotion
            
            if let mix = mix, !mix.isEmpty {
                self.emotionMix = mix
            } else {
                self.emotionMix = [normalizedEmotion: 1.0]
            }
        }
        
        // 锁定情绪 45 秒
        emotionLockUntil = Date().addingTimeInterval(45)
    }
    
    // 从文本应用情绪
    func applyEmotionFromText(_ text: String, meta: [String: Any]? = nil) {
        let cleanText = EmotionColors.stripEmotionMarkers(text)
        
        var emotionLabel: String?
        
        // 优先使用元数据中的情绪
        if let explicit = meta?["emotion"] as? String, 
           explicit.lowercased() != "neutral" {
            emotionLabel = explicit
        } else {
            // 尝试从文本中提取情绪标签
            emotionLabel = extractEmotionFromText(text)
        }
        
        // 如果没有明确的情绪，从文本推断
        if emotionLabel == nil || emotionLabel?.lowercased() == "neutral" {
            emotionLabel = EmotionColors.inferEmotion(from: cleanText)
        }
        
        // 处理情绪混合
        if let internalMix = meta?["emotion_internal"] as? [String: Double] {
            self.emotionMix = internalMix
        } else if let label = emotionLabel {
            self.emotionMix = [label: 1.0]
        }
        
        // 设置情绪
        if let label = emotionLabel {
            handleEmotionUpdate(emotion: label, mix: emotionMix)
        }
    }
    
    // 从文本中提取情绪标签
    private func extractEmotionFromText(_ text: String) -> String? {
        // 匹配 [EMO:xxx] 格式
        if let match = text.range(of: "\\[EMO:\\s*\\{?\\s*([a-zA-Z0-9_]+)\\s*\\}?\\]", options: .regularExpression) {
            let label = String(text[match]).replacingOccurrences(of: "\\[EMO:\\s*\\{?\\s*|\\s*\\}?\\]", with: "", options: .regularExpression)
            return label
        }
        
        // 匹配 {xxx} 格式
        if let match = text.range(of: "\\{([^}]+)\\}", options: .regularExpression) {
            let label = String(text[match]).replacingOccurrences(of: "[{}]", with: "", options: .regularExpression)
            return label
        }
        
        // 匹配 [xxx] 格式
        if let match = text.range(of: "\\[([^\\]]+)\\]", options: .regularExpression) {
            let label = String(text[match]).replacingOccurrences(of: "[\\[\\]]", with: "", options: .regularExpression)
            return label
        }
        
        return nil
    }
    
    // MARK: - Life Status Handling
    
    private func handleLifeStatusUpdate(_ lifeStatus: LifeStatus) {
        var statusDict: [String: Any] = [:]
        
        if let actorStates = lifeStatus.actor_life_states {
            statusDict["actor_life_states"] = actorStates.mapValues { $0.value }
        }
        
        if let relationships = lifeStatus.actor_relationships {
            statusDict["actor_relationships"] = relationships
        }
        
        if let emotion = lifeStatus.emotion {
            statusDict["emotion"] = emotion
        }
        
        self.lifeStatus = statusDict
    }
    
    // MARK: - System Stats Handling
    
    private func handleSystemStatsUpdate(_ stats: SystemStats) {
        systemStats.cpu = stats.cpu ?? 0
        systemStats.gpu = stats.gpu ?? 0
        systemStats.memory = stats.memory ?? 0
        systemStats.temperature = stats.temperature ?? 0
        
        if let scheduler = stats.scheduler {
            systemStats.scheduler = scheduler.mapValues { $0.value }
        }
    }
    
    // MARK: - Session Management
    
    func loadSessions() async {
        isLoading = true
        errorMessage = nil
        
        do {
            let response = try await apiService.getSessions()
            sessions = response.sessions
        } catch {
            errorMessage = "Failed to load sessions: \(error.localizedDescription)"
        }
        
        isLoading = false
    }
    
    func createSession() async {
        isLoading = true
        errorMessage = nil
        
        do {
            let request = CreateSessionRequest(title: "New Session")
            let response = try await apiService.createSession(request)
            sessions.insert(response.session, at: 0)
            currentSessionId = response.session.id
            preferences.currentSessionId = response.session.id
        } catch {
            errorMessage = "Failed to create session: \(error.localizedDescription)"
        }
        
        isLoading = false
    }
    
    func switchSession(_ sessionId: String) {
        currentSessionId = sessionId
        preferences.currentSessionId = sessionId
    }
    
    func deleteSession(_ sessionId: String) {
        sessions.removeAll { $0.id == sessionId }
        if currentSessionId == sessionId {
            currentSessionId = sessions.first?.id
            preferences.currentSessionId = currentSessionId
        }
    }
    
    func renameSession(_ sessionId: String, newTitle: String) {
        if let index = sessions.firstIndex(where: { $0.id == sessionId }) {
            sessions[index] = Session(
                id: sessions[index].id,
                title: newTitle,
                created_at: sessions[index].created_at,
                updated_at: sessions[index].updated_at,
                message_count: sessions[index].message_count,
                is_pinned: sessions[index].is_pinned
            )
        }
    }
    
    func toggleSessionPin(_ sessionId: String, isPinned: Bool) {
        if let index = sessions.firstIndex(where: { $0.id == sessionId }) {
            sessions[index] = Session(
                id: sessions[index].id,
                title: sessions[index].title,
                created_at: sessions[index].created_at,
                updated_at: sessions[index].updated_at,
                message_count: sessions[index].message_count,
                is_pinned: isPinned
            )
        }
    }
    
    // MARK: - WebSocket Connection
    
    func reconnect() {
        webSocketManager.reconnect()
    }
    
    func disconnect() {
        webSocketManager.disconnect()
    }
    
    func connect() {
        webSocketManager.connect()
    }
    
    // MARK: - Preferences Loading
    
    func loadPreferences() async {
        do {
            let response = try await apiService.getPreferences()
            if let mode = response.data?["mode"] as? String {
                studyMode = mode == "study"
            }
        } catch {
            print("Failed to load preferences: \(error)")
        }
    }
    
    // MARK: - Device Status Reporting
    
    func reportDeviceStatus() {
        // 模拟设备状态上报
        let deviceStatus: [String: Any] = [
            "type": "device_status",
            "source": "ios_native",
            "metrics": [
                "battery_level": 0.8,
                "is_charging": false,
                "network_type": "wifi"
            ]
        ]
        
        webSocketManager.sendJSONMessage(deviceStatus)
    }
}

