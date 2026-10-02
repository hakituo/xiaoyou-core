import Foundation

// MARK: - Aveline API Service

class AvelineAPIService {
    private let session: URLSession
    private var baseURL: String
    private var authToken: String?
    
    init(baseURL: String, authToken: String? = nil) {
        self.baseURL = baseURL
        self.authToken = authToken
        
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 30
        self.session = URLSession(configuration: config)
    }
    
    func updateAuthToken(_ token: String?) {
        self.authToken = token
    }
    
    func updateBaseURL(_ url: String) {
        self.baseURL = url
    }
    
    // MARK: - Message Endpoints
    // 对齐后端 POST /api/v1/chat/message（请求体为裸 dict，使用 content 字段）
    func sendMessage(_ request: MessageRequest) async throws -> MessageResponse {
        try await performRequest(.POST, path: "/api/v1/chat/message", body: request)
    }
    
    // MARK: - Session Endpoints
    
    func getSessions() async throws -> SessionsResponse {
        try await performRequest(.GET, path: "/api/v1/sessions")
    }
    
    func createSession(_ request: CreateSessionRequest) async throws -> SessionResponse {
        try await performRequest(.POST, path: "/api/v1/sessions", body: request)
    }
    
    func getSessionHistory(sessionId: String) async throws -> HistoryResponse {
        try await performRequest(.GET, path: "/api/v1/sessions/\(sessionId)/history")
    }
    
    // MARK: - Status Endpoints
    // 对齐后端 GET /api/v1/life/status
    func getLifeStatus() async throws -> LifeStatusResponse {
        try await performRequest(.GET, path: "/api/v1/life/status")
    }
    
    // MARK: - Memory Endpoints
    // 对齐后端 GET /api/v1/memories（列表）、DELETE /api/v1/memories/{id}、GET /api/v1/memories/stats、GET /api/v1/memories/tags
    func getMemories(query: String? = nil, category: String? = nil, limit: Int? = nil) async throws -> MemoryListResponse {
        var queryParams: [String: String] = [:]
        if let query = query { queryParams["query"] = query }
        if let category = category { queryParams["category"] = category }
        if let limit = limit { queryParams["limit"] = "\(limit)" }

        return try await performRequest(.GET, path: "/api/v1/memories", queryParams: queryParams)
    }

    func deleteMemory(memoryId: String) async throws {
        try await performVoidRequest(.DELETE, path: "/api/v1/memories/\(memoryId)")
    }

    func getMemoryStats() async throws -> MemoryStatsResponse {
        try await performRequest(.GET, path: "/api/v1/memories/stats")
    }

    func getMemoryTags() async throws -> TagsResponse {
        try await performRequest(.GET, path: "/api/v1/memories/tags")
    }
    
    // MARK: - Study Endpoints
    // 对齐后端 study-daily：calendar / date/{date} / notes / latest-progress
    func getStudyCalendar(year: Int? = nil, month: Int? = nil) async throws -> StudyCalendarResponse {
        var queryParams: [String: String] = [:]
        if let year = year { queryParams["year"] = "\(year)" }
        if let month = month { queryParams["month"] = "\(month)" }
        return try await performRequest(.GET, path: "/api/v1/study-daily/calendar", queryParams: queryParams)
    }

    func getStudyDateContent(date: String) async throws -> StudyDateContentResponse {
        try await performRequest(.GET, path: "/api/v1/study-daily/date/\(date)")
    }

    func getStudyNotes() async throws -> StudyNotesResponse {
        try await performRequest(.GET, path: "/api/v1/study-daily/notes")
    }

    func getLatestStudyProgress() async throws -> StudyProgressResponse {
        try await performRequest(.GET, path: "/api/v1/study-daily/latest-progress")
    }
    
    // MARK: - Persona Endpoints
    // 对齐后端 GET /api/v1/personas、GET /api/v1/personas/active、POST /api/v1/personas/switch
    func getPersonas() async throws -> [Persona] {
        try await performRequest(.GET, path: "/api/v1/personas")
    }
    
    func getActivePersona() async throws -> ActivePersonaResponse {
        try await performRequest(.GET, path: "/api/v1/personas/active")
    }
    
    func selectPersona(_ request: SelectPersonaRequest) async throws {
        try await performVoidRequest(.POST, path: "/api/v1/personas/switch", body: request)
    }
    
    func createPersona(_ request: PersonaRequest) async throws -> Persona {
        try await performRequest(.POST, path: "/api/v1/personas", body: request)
    }
    
    func updatePersona(personaId: String, request: PersonaRequest) async throws -> Persona {
        try await performRequest(.PUT, path: "/api/v1/personas/\(personaId)", body: request)
    }
    
    func deletePersona(personaId: String) async throws {
        try await performVoidRequest(.DELETE, path: "/api/v1/personas/\(personaId)")
    }
    
    // MARK: - Shop Endpoints

    /// 获取商城商品列表（分页 + 按类别过滤），对齐后端 GET /food/shop/menu。
    /// - Parameters:
    ///   - category: 类别(food/gift/toy/book/clothing/tech/luxury)，nil = 全部
    ///   - page: 页码(从 1 开始)
    ///   - pageSize: 每页数量
    func getShopMenu(category: String? = nil, page: Int = 1, pageSize: Int = 20) async throws -> ShopMenuResponse {
        var queryParams: [String: String] = [
            "page": "\(page)",
            "page_size": "\(pageSize)",
        ]
        if let category = category {
            queryParams["category"] = category
        }
        return try await performRequest(.GET, path: "/api/v1/food/shop/menu", queryParams: queryParams)
    }

    /// 购买商品，对齐后端 POST /food/buy/{item_id}。
    func purchaseItem(_ request: PurchaseRequest) async throws -> PurchaseResponse {
        let queryParams: [String: String] = [
            "quantity": "\(request.quantity)",
            "recipient": request.recipient,
        ]
        return try await performRequest(
            .POST,
            path: "/api/v1/food/buy/\(request.item_id)",
            queryParams: queryParams
        )
    }
    
    // MARK: - Health Check
    
    func healthCheck() async throws -> Bool {
        do {
            _ = try await performVoidRequest(.GET, path: "/health")
            return true
        } catch {
            return false
        }
    }
    
    // MARK: - Private Helper Methods
    
    private func performRequest<T: Decodable>(_ method: HTTPMethod, path: String, queryParams: [String: String]? = nil, body: Encodable? = nil) async throws -> T {
        let request = try buildRequest(method, path: path, queryParams: queryParams, body: body)
        let (data, response) = try await session.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        
        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.httpError(statusCode: httpResponse.statusCode, data: data)
        }
        
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .useDefaultKeys
        return try decoder.decode(T.self, from: data)
    }
    
    private func performVoidRequest(_ method: HTTPMethod, path: String, queryParams: [String: String]? = nil, body: Encodable? = nil) async throws {
        let request = try buildRequest(method, path: path, queryParams: queryParams, body: body)
        let (_, response) = try await session.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        
        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.httpError(statusCode: httpResponse.statusCode, data: nil)
        }
    }
    
    private func buildRequest(_ method: HTTPMethod, path: String, queryParams: [String: String]? = nil, body: Encodable? = nil) throws -> URLRequest {
        var components = URLComponents(string: baseURL + path)
        
        if let queryParams = queryParams {
            components?.queryItems = queryParams.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        
        guard let url = components?.url else {
            throw APIError.invalidURL
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        if let token = authToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            request.setValue(token, forHTTPHeaderField: "x-internal-token")
        }
        
        if let body = body {
            let encoder = JSONEncoder()
            request.httpBody = try encoder.encode(body)
        }
        
        return request
    }
}

// MARK: - HTTP Method

enum HTTPMethod: String {
    case GET, POST, PUT, PATCH, DELETE
}

// MARK: - API Error

enum APIError: Error, LocalizedError {
    case invalidURL
    case invalidResponse
    case httpError(statusCode: Int, data: Data?)
    case encodingError
    case decodingError
    
    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid URL"
        case .invalidResponse:
            return "Invalid response from server"
        case .httpError(let statusCode, _):
            return "HTTP error: \(statusCode)"
        case .encodingError:
            return "Failed to encode request"
        case .decodingError:
            return "Failed to decode response"
        }
    }
}
