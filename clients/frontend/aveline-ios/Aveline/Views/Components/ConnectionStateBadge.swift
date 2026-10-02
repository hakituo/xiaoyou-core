import SwiftUI

// MARK: - Connection State Badge

struct ConnectionStateBadge: View {
    let state: WebSocketManager.ConnectionState
    
    private var color: Color {
        switch state {
        case .connected:
            return .green
        case .connecting:
            return .orange
        case .disconnected:
            return .red
        }
    }
    
    private var text: String {
        switch state {
        case .connected:
            return "Connected"
        case .connecting:
            return "Connecting..."
        case .disconnected:
            return "Disconnected"
        }
    }
    
    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 8, height: 8)
            
            Text(text)
                .font(.caption2)
                .foregroundColor(.secondary)
        }
    }
}

#Preview {
    VStack(spacing: 10) {
        ConnectionStateBadge(state: .connected)
        ConnectionStateBadge(state: .connecting)
        ConnectionStateBadge(state: .disconnected)
    }
}
