import SwiftUI

struct MemoryView: View {
    @StateObject private var viewModel = MemoryViewModel()
    
    var body: some View {
        List(viewModel.memories) { memory in
            VStack(alignment: .leading, spacing: 8) {
                Text(memory.content)
                    .font(.body)
                
                HStack {
                    if let category = memory.category {
                        Text(category)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }

                    Spacer()

                    if let weight = memory.weight {
                        Text(String(format: "%.2f", weight))
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
            .padding(.vertical, 4)
        }
        .navigationTitle("Memory")
        .task {
            await viewModel.loadMemories()
        }
    }
}

#Preview {
    NavigationStack {
        MemoryView()
    }
}
