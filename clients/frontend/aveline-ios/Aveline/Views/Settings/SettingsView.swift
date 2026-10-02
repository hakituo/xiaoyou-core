import SwiftUI

// MARK: - Settings View

struct SettingsView: View {
    @StateObject private var viewModel = SettingsViewModel()
    
    var body: some View {
        Form {
            Section("Backend") {
                TextField("Backend URL", text: $viewModel.backendURL)
                    .textInputAutocapitalization(.never)
                
                Button("Save") {
                    viewModel.saveBackendURL()
                }
            }
            
            Section("Authentication") {
                SecureField("Access Token", text: Binding(
                    get: { viewModel.accessToken ?? "" },
                    set: { viewModel.accessToken = $0 }
                ))
                .textInputAutocapitalization(.never)
                
                Button("Save Token") {
                    viewModel.saveAccessToken()
                }
            }
            
            Section("Data") {
                Button("Clear All Data", role: .destructive) {
                    viewModel.clearAllData()
                }
            }
        }
        .navigationTitle("Settings")
    }
}

#Preview {
    NavigationStack {
        SettingsView()
    }
}
