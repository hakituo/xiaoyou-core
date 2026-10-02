import Foundation

@MainActor
class ChatViewModel: ObservableObject {
    @Published var messages: [MessageResponse] = []
    @Published var currentInput: String = ""
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?
    
    private let apiService: AvelineAPIService
    private let preferences: AppPreferences
    
    init() {
        let container = DependencyContainer.shared
        self.apiService = container.apiService
        self.preferences = container.appPreferences
    }
    
    func loadHistory(sessionId: String) async {
        isLoading = true
        errorMessage = nil
        
        do {
            let response = try await apiService.getSessionHistory(sessionId: sessionId)
            messages = response.messages
        } catch {
            errorMessage = "Failed to load history: \(error.localizedDescription)"
        }
        
        isLoading = false
    }
    
    func sendMessage(model: String) async {
        guard !currentInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        
        let userMessage = currentInput
        currentInput = ""
        isLoading = true
        errorMessage = nil
        
        do {
            let request = MessageRequest(
                text: userMessage,
                session_id: preferences.currentSessionId,
                model: model
            )
            
            let response = try await apiService.sendMessage(request)
            messages.append(response)
        } catch {
            errorMessage = "Failed to send message: \(error.localizedDescription)"
        }
        
        isLoading = false
    }
}
