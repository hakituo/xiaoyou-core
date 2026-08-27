import Foundation

@MainActor
class MemoryViewModel: ObservableObject {
    @Published var memories: [Memory] = []
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?
    
    private let apiService: AvelineAPIService
    
    init() {
        let container = DependencyContainer.shared
        self.apiService = container.apiService
    }
    
    func loadMemories() async {
        isLoading = true
        errorMessage = nil

        do {
            let response = try await apiService.getMemories()
            memories = response.data
        } catch {
            errorMessage = "Failed to load memories: \(error.localizedDescription)"
        }

        isLoading = false
    }

    func deleteMemory(_ memoryId: String) async {
        do {
            try await apiService.deleteMemory(memoryId: memoryId)
            memories.removeAll { $0.id == memoryId }
        } catch {
            errorMessage = "Failed to delete memory: \(error.localizedDescription)"
        }
    }
}
