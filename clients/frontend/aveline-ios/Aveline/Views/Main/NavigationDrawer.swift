import SwiftUI

// MARK: - Navigation Drawer 导航抽屉

struct NavigationDrawer<Content: View>: View {
    @Binding var isShowing: Bool
    let currentEmotion: String
    let sessions: [Session]
    let currentSessionId: String?
    let isConnected: Bool
    let systemStats: SystemStatsState
    let onSessionSelect: (String) -> Void
    let onNewSession: () -> Void
    let onNavigate: (String) -> Void
    let content: Content
    
    init(
        isShowing: Binding<Bool>,
        currentEmotion: String,
        sessions: [Session],
        currentSessionId: String?,
        isConnected: Bool = false,
        systemStats: SystemStatsState = SystemStatsState(),
        onSessionSelect: @escaping (String) -> Void,
        onNewSession: @escaping () -> Void,
        onNavigate: @escaping (String) -> Void,
        @ViewBuilder content: () -> Content
    ) {
        self._isShowing = isShowing
        self.currentEmotion = currentEmotion
        self.sessions = sessions
        self.currentSessionId = currentSessionId
        self.isConnected = isConnected
        self.systemStats = systemStats
        self.onSessionSelect = onSessionSelect
        self.onNewSession = onNewSession
        self.onNavigate = onNavigate
        self.content = content()
    }
    
    var body: some View {
        ZStack {
            // Main content 主内容
            content
                .disabled(isShowing)
            
            // Overlay 覆盖层
            if isShowing {
                Color.black.opacity(0.4)
                    .ignoresSafeArea()
                    .onTapGesture {
                        withAnimation {
                            isShowing = false
                        }
                    }
                
                // Drawer 抽屉
                HStack {
                    drawerContent
                        .frame(width: 280)
                        .background(AppColors.surface)
                        .shadow(radius: 10)
                    
                    Spacer()
                }
                .transition(.move(edge: .leading))
                .animation(.easeInOut, value: isShowing)
            }
        }
    }
    
    @ViewBuilder
    private var drawerContent: some View {
        VStack(spacing: 0) {
            // Header 头部
            VStack(alignment: .leading, spacing: 12) {
                Text("Aveline")
                    .font(.title2)
                    .fontWeight(.bold)
                    .foregroundColor(AppColors.textPrimary)
                
                // 当前情绪显示
                HStack {
                    Text("当前情绪:")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text(EmotionColors.getEmotionData(for: currentEmotion).label)
                        .font(.caption)
                        .fontWeight(.medium)
                        .foregroundColor(EmotionColors.getColors(for: currentEmotion)[0])
                }
                
                // 简化的连接状态
                HStack {
                    Circle()
                        .fill(isConnected ? .green : .red)
                        .frame(width: 8, height: 8)
                    Text(isConnected ? "已连接" : "已断开")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
            .padding()
            .background(AppColors.surfaceVariant)
            
            // New Session Button 新建会话按钮
            Button(action: onNewSession) {
                Label("新建会话", systemImage: "plus")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding()
            }
            .buttonStyle(.plain)
            
            Divider()
            
            // Sessions List 会话列表
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(sessions) { session in
                        sessionRow(session)
                    }
                }
            }
            
            Spacer()
            
            // Navigation Menu 导航菜单
            VStack(spacing: 0) {
                Divider()
                
                drawerMenuItem(icon: "message", title: "聊天", route: "chat")
                drawerMenuItem(icon: "person.2", title: "圈子", route: "circle")
                drawerMenuItem(icon: "chart.bar", title: "状态", route: "status")
                drawerMenuItem(icon: "person", title: "角色", route: "persona")
                drawerMenuItem(icon: "brain", title: "记忆", route: "memory")
                drawerMenuItem(icon: "calendar", title: "日常", route: "dailydata")
                drawerMenuItem(icon: "book", title: "学习", route: "study")
                drawerMenuItem(icon: "fork.knife", title: "食物", route: "shop")
                drawerMenuItem(icon: "square.grid.2x2", title: "插件", route: "plugins")
                drawerMenuItem(icon: "gearshape", title: "设置", route: "settings")
            }
        }
    }
    
    private func sessionRow(_ session: Session) -> some View {
        Button(action: {
            onSessionSelect(session.id)
            withAnimation {
                isShowing = false
            }
        }) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(session.title)
                        .font(.body)
                        .foregroundColor(AppColors.textPrimary)
                        .lineLimit(1)
                    
                    Text("\(session.message_count) 条消息")
                        .font(.caption)
                        .foregroundColor(AppColors.textSecondary)
                }
                
                Spacer()
                
                if session.id == currentSessionId {
                    Circle()
                        .fill(AppColors.primary)
                        .frame(width: 8, height: 8)
                }
            }
            .padding()
            .background(session.id == currentSessionId ? AppColors.surfaceVariant : Color.clear)
        }
        .buttonStyle(.plain)
    }
    
    private func drawerMenuItem(icon: String, title: String, route: String) -> some View {
        Button(action: {
            onNavigate(route)
            withAnimation {
                isShowing = false
            }
        }) {
            Label(title, systemImage: icon)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
                .foregroundColor(AppColors.textPrimary)
        }
        .buttonStyle(.plain)
    }
}

#Preview {
    NavigationDrawer(
        isShowing: .constant(true),
        currentEmotion: "happy",
        sessions: [
            Session(id: "1", title: "测试会话", created_at: Date(), updated_at: Date(), message_count: 10, is_pinned: false)
        ],
        currentSessionId: "1",
        isConnected: true,
        systemStats: SystemStatsState(),
        onSessionSelect: { _ in },
        onNewSession: {},
        onNavigate: { _ in }
    ) {
        Text("Main Content")
    }
}

