import SwiftUI

// MARK: - Chat View

struct ChatView: View {
    @StateObject private var viewModel = ChatViewModel()
    @State private var selectedModel: String = "default"
    
    var body: some View {
        VStack(spacing: 0) {
            // Messages list
            ScrollView {
                LazyVStack(spacing: 12) {
                    ForEach(viewModel.messages.indices, id: \.self) { index in
                        messageBubble(viewModel.messages[index])
                    }
                    
                    if viewModel.isLoading {
                        loadingIndicator()
                    }
                }
                .padding()
            }
            
            Divider()
            
            // Input area
            inputArea
        }
        .navigationTitle("Chat")
        .toolbar {
            ToolbarItem(placement: .navigationBarLeading) {
                Button(action: {
                    // Menu action will be handled by parent
                }) {
                    Image(systemName: "line.horizontal.3")
                }
            }
        }
    }
    
    @ViewBuilder
    private func messageBubble(_ message: MessageResponse) -> some View {
        HStack {
            if message.reply.isEmpty {
                // User message
                Spacer()
                Text(message.reply)
                    .padding()
                    .background(AppColors.primary.opacity(0.2))
                    .cornerRadius(16)
                    .frame(maxWidth: 250, alignment: .trailing)
            } else {
                // AI message
                Text(message.reply)
                    .padding()
                    .background(AppColors.surfaceVariant)
                    .cornerRadius(16)
                    .frame(maxWidth: 250, alignment: .leading)
                Spacer()
            }
        }
    }
    
    private func loadingIndicator() -> some View {
        HStack {
            ProgressView()
                .padding()
            Spacer()
        }
    }
    
    private var inputArea: some View {
        HStack(spacing: 12) {
            TextField("Type a message...", text: $viewModel.currentInput, axis: .vertical)
                .textFieldStyle(.plain)
                .padding()
                .background(AppColors.surfaceVariant)
                .cornerRadius(20)
                .lineLimit(1...3)
            
            Button(action: {
                Task {
                    await viewModel.sendMessage(model: selectedModel)
                }
            }) {
                Image(systemName: "paperplane.fill")
                    .font(.title2)
                    .foregroundColor(viewModel.currentInput.isEmpty ? .gray : AppColors.primary)
            }
            .disabled(viewModel.currentInput.isEmpty || viewModel.isLoading)
        }
        .padding()
    }
}

#Preview {
    NavigationStack {
        ChatView()
    }
}
