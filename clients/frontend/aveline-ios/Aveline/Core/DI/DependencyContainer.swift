import Foundation

// MARK: - Dependency Container

class DependencyContainer {
    static let shared = DependencyContainer()
    
    // Services
    var apiService: AvelineAPIService
    var webSocketManager: WebSocketManager
    var appPreferences: AppPreferences
    
    private init() {
        // Initialize preferences first
        self.appPreferences = AppPreferences()
        
        // Initialize services with preferences
        self.apiService = AvelineAPIService(
            baseURL: appPreferences.backendURL,
            authToken: appPreferences.accessToken
        )
        
        self.webSocketManager = WebSocketManager(
            baseURL: appPreferences.backendURL,
            authToken: appPreferences.accessToken
        )
    }
    
    func updateServices() {
        apiService.updateBaseURL(appPreferences.backendURL)
        apiService.updateAuthToken(appPreferences.accessToken)
        
        webSocketManager.updateBaseURL(appPreferences.backendURL)
        webSocketManager.updateAuthToken(appPreferences.accessToken)
    }
}
