import Foundation

@MainActor
class SettingsViewModel: ObservableObject {
    @Published var backendURL: String
    @Published var accessToken: String?
    
    private let preferences: AppPreferences
    
    init() {
        let container = DependencyContainer.shared
        self.preferences = container.appPreferences
        self.backendURL = preferences.backendURL
        self.accessToken = preferences.accessToken
    }
    
    func saveBackendURL() {
        preferences.backendURL = backendURL
        DependencyContainer.shared.updateServices()
    }
    
    func saveAccessToken() {
        preferences.accessToken = accessToken
        DependencyContainer.shared.updateServices()
    }
    
    func clearAllData() {
        preferences.clearAll()
        backendURL = "http://localhost:8000"
        accessToken = nil
    }
}
