import Foundation

// MARK: - App Preferences

class AppPreferences {
    private let defaults: UserDefaults
    
    // Keys
    private enum Keys {
        static let backendURL = "backend_url"
        static let accessToken = "access_token"
        static let currentSessionId = "current_session_id"
        static let currentPersonaId = "current_persona_id"
        static let studyModeEnabled = "study_mode_enabled"
        static let selectedModel = "selected_model"
    }
    
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }
    
    // MARK: - Backend URL
    
    var backendURL: String {
        get {
            defaults.string(forKey: Keys.backendURL) ?? "http://localhost:8000"
        }
        set {
            defaults.set(newValue, forKey: Keys.backendURL)
        }
    }
    
    // MARK: - Access Token
    
    var accessToken: String? {
        get {
            defaults.string(forKey: Keys.accessToken)
        }
        set {
            defaults.set(newValue, forKey: Keys.accessToken)
        }
    }
    
    // MARK: - Current Session
    
    var currentSessionId: String? {
        get {
            defaults.string(forKey: Keys.currentSessionId)
        }
        set {
            defaults.set(newValue, forKey: Keys.currentSessionId)
        }
    }
    
    // MARK: - Current Persona
    
    var currentPersonaId: String? {
        get {
            defaults.string(forKey: Keys.currentPersonaId)
        }
        set {
            defaults.set(newValue, forKey: Keys.currentPersonaId)
        }
    }
    
    // MARK: - Study Mode
    
    var studyModeEnabled: Bool {
        get {
            defaults.bool(forKey: Keys.studyModeEnabled)
        }
        set {
            defaults.set(newValue, forKey: Keys.studyModeEnabled)
        }
    }
    
    // MARK: - Selected Model
    
    var selectedModel: String {
        get {
            defaults.string(forKey: Keys.selectedModel) ?? "default"
        }
        set {
            defaults.set(newValue, forKey: Keys.selectedModel)
        }
    }
    
    // MARK: - Clear All
    
    func clearAll() {
        let dictionary = defaults.dictionaryRepresentation()
        dictionary.keys.forEach { key in
            defaults.removeObject(forKey: key)
        }
    }
}
