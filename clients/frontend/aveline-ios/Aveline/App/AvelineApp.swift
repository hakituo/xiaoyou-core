import SwiftUI

@main
struct AvelineApp: App {
    @StateObject private var mainViewModel = MainViewModel()
    @State private var showDrawer = false
    @State private var currentRoute = "chat"
    
    // 计算混合后的颜色
    private var mixedColors: [Color] {
        if mainViewModel.emotionMix.count > 1 {
            return EmotionColors.mixColors(weights: mainViewModel.emotionMix)
        }
        return EmotionColors.getColors(for: mainViewModel.currentEmotion)
    }
    
    var body: some Scene {
        WindowGroup {
            NavigationDrawer(
                isShowing: $showDrawer,
                currentEmotion: mainViewModel.currentEmotion,
                sessions: mainViewModel.sessions,
                currentSessionId: mainViewModel.currentSessionId,
                isConnected: mainViewModel.isConnected,
                systemStats: mainViewModel.systemStats,
                onSessionSelect: { sessionId in
                    mainViewModel.switchSession(sessionId)
                },
                onNewSession: {
                    Task {
                        await mainViewModel.createSession()
                    }
                },
                onNavigate: { route in
                    currentRoute = route
                }
            ) {
                mainContent
            }
            .onAppear {
                Task {
                    await mainViewModel.loadSessions()
                    await mainViewModel.loadPreferences()
                    mainViewModel.connect()
                    
                    // 延迟上报设备状态
                    DispatchQueue.main.asyncAfter(deadline: .now() + 5) {
                        mainViewModel.reportDeviceStatus()
                    }
                }
            }
            .alert("错误", isPresented: .constant(mainViewModel.errorMessage != nil)) {
                Button("确定") {
                    mainViewModel.errorMessage = nil
                }
            } message: {
                Text(mainViewModel.errorMessage ?? "")
            }
        }
    }
    
    @ViewBuilder
    private var mainContent: some View {
        ZStack {
            // 使用情绪混合颜色的呼吸背景
            BreathingBackground(
                emotion: mainViewModel.currentEmotion,
                intensity: 0.8,
                pattern: .sine
            )
            
            // 连接状态指示
            VStack {
                HStack {
                    Spacer()
                    ConnectionStateBadge(
                        connectionState: mainViewModel.connectionState,
                        systemStats: mainViewModel.systemStats
                    )
                    .padding()
                }
                Spacer()
            }
            
            Group {
                switch currentRoute {
                case "chat":
                    ChatView()
                        .environmentObject(mainViewModel)
                case "circle":
                    CirclePanelView()
                        .environmentObject(mainViewModel)
                case "status":
                    StatusPanelView()
                        .environmentObject(mainViewModel)
                case "persona":
                    PersonaView()
                        .environmentObject(mainViewModel)
                case "memory":
                    MemoryView()
                        .environmentObject(mainViewModel)
                case "dailydata":
                    DailyDataPanelView()
                        .environmentObject(mainViewModel)
                case "study":
                    StudyView()
                        .environmentObject(mainViewModel)
                case "shop":
                    ShopView()
                        .environmentObject(mainViewModel)
                case "plugins":
                    PluginsPanelView()
                        .environmentObject(mainViewModel)
                case "settings":
                    SettingsView()
                        .environmentObject(mainViewModel)
                default:
                    ChatView()
                        .environmentObject(mainViewModel)
                }
            }
        }
    }
    
    // 占位视图
    @ViewBuilder
    private func placeholderView(title: String, icon: String) -> some View {
        VStack(spacing: 20) {
            Image(systemName: icon)
                .font(.system(size: 60))
                .foregroundColor(.secondary)
            
            Text(title)
                .font(.title2)
                .fontWeight(.medium)
                .foregroundColor(.secondary)
            
            Text("功能开发中...")
                .font(.subheadline)
                .foregroundColor(.tertiary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Connection State Badge 连接状态徽章
struct ConnectionStateBadge: View {
    let connectionState: WebSocketManager.ConnectionState
    let systemStats: SystemStatsState
    
    private var stateColor: Color {
        switch connectionState {
        case .connected:
            return .green
        case .connecting:
            return .yellow
        case .disconnected:
            return .red
        }
    }
    
    private var stateText: String {
        switch connectionState {
        case .connected:
            return "已连接"
        case .connecting:
            return "连接中..."
        case .disconnected:
            return "已断开"
        }
    }
    
    var body: some View {
        VStack(alignment: .trailing, spacing: 4) {
            HStack(spacing: 6) {
                Circle()
                    .fill(stateColor)
                    .frame(width: 8, height: 8)
                Text(stateText)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            
            if connectionState == .connected {
                HStack(spacing: 12) {
                    if systemStats.cpu > 0 {
                        HStack(spacing: 2) {
                            Image(systemName: "cpu")
                                .font(.system(size: 10))
                            Text("\(Int(systemStats.cpu))%")
                                .font(.caption2)
                        }
                        .foregroundColor(.secondary)
                    }
                    
                    if systemStats.memory > 0 {
                        HStack(spacing: 2) {
                            Image(systemName: "memorychip")
                                .font(.system(size: 10))
                            Text("\(Int(systemStats.memory))%")
                                .font(.caption2)
                        }
                        .foregroundColor(.secondary)
                    }
                    
                    if systemStats.temperature > 0 {
                        HStack(spacing: 2) {
                            Image(systemName: "thermometer")
                                .font(.system(size: 10))
                            Text("\(Int(systemStats.temperature))°")
                                .font(.caption2)
                        }
                        .foregroundColor(.secondary)
                    }
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(.ultraThinMaterial)
        )
    }
}

#Preview {
    AvelineApp()
}

