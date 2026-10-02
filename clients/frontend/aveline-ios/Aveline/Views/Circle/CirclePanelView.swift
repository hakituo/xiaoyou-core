import SwiftUI

// MARK: - Circle Panel View 圈子面板 - 重构版本

struct CirclePanelView: View {
    @EnvironmentObject var mainViewModel: MainViewModel
    
    @State private var groupMode = false
    @State private var expandedMember: String? = "aveline"
    @State private var sections: [CircleSection: Bool] = [
        .members: true,
        .relationship: true,
        .stats: true
    ]
    
    enum CircleSection: String, CaseIterable {
        case members
        case relationship
        case stats
    }
    
    // 模拟数据
    @State private var avelineStats: ActorLifeState = .init(hunger: 100, energy: 100, mood_score: 80)
    @State private var lingStats: ActorLifeState = .init(hunger: 85, energy: 95, mood_score: 75)
    @State private var relationshipScore: Double = 65
    
    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                HeaderView(title: "社交互动系统", subtitle: "CIRCLE MATRIX", accentColor: .cyan)
                
                GroupModeToggle(enabled: groupMode, onToggle: { groupMode.toggle() })
                
                CollapsibleSection(
                    title: "MEMBER STATUS",
                    icon: "person.2",
                    isOpen: sections[.members] ?? true,
                    onToggle: { sections[.members]?.toggle() }
                ) {
                    MemberStatusList(
                        avelineStats: avelineStats,
                        lingStats: lingStats,
                        expandedMember: $expandedMember
                    )
                }
                
                CollapsibleSection(
                    title: "RELATIONSHIP BOND",
                    icon: "heart.fill",
                    isOpen: sections[.relationship] ?? true,
                    onToggle: { sections[.relationship]?.toggle() }
                ) {
                    RelationshipMeter(score: relationshipScore)
                }
                
                CollapsibleSection(
                    title: "SESSION STATISTICS",
                    icon: "clock",
                    isOpen: sections[.stats] ?? true,
                    onToggle: { sections[.stats]?.toggle() }
                ) {
                    MessageStats(avelineCount: 156, lingCount: 42)
                }
                
                InfoCard(title: "INTERACTION GUIDE", icon: "info.circle") {
                    InteractionGuide()
                }
            }
            .padding()
        }
        .navigationTitle("圈子")
        .navigationBarTitleDisplayMode(.large)
    }
}

// MARK: - Group Mode Toggle 群聊模式开关
struct GroupModeToggle: View {
    let enabled: Bool
    let onToggle: () -> Void
    
    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    HStack(spacing: 12) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 12)
                                .fill(enabled ? Color.cyan.opacity(0.2) : Color.white.opacity(0.05))
                                .frame(width: 40, height: 40)
                            
                            Image(systemName: "person.2")
                                .foregroundColor(enabled ? .cyan : .white.opacity(0.4))
                        }
                        
                        VStack(alignment: .leading, spacing: 4) {
                            Text("群聊模式")
                                .font(.subheadline)
                                .fontWeight(.semibold)
                            Text(enabled ? "ENABLED · 多成员可见" : "DISABLED · 单成员模式")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                    }
                    
                    Spacer()
                    
                    Toggle("", isOn: .constant(enabled))
                        .labelsHidden()
                        .onChange(of: enabled) { _ in
                            onToggle()
                        }
                }
                
                if enabled {
                    GroupModeTags()
                        .transition(.opacity.combined(with: .scale))
                }
            }
        }
    }
}

struct GroupModeTags: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider()
            
            HStack(spacing: 8) {
                Tag(text: "你", color: .blue)
                Tag(text: "Aveline", color: .cyan)
                Tag(text: "Ling", color: .pink)
            }
            
            Text("QQ 端仍仅显示 Aveline 回复")
                .font(.caption)
                .foregroundColor(.secondary)
        }
    }
}

// MARK: - Member Status List 成员状态列表
struct MemberStatusList: View {
    let avelineStats: ActorLifeState
    let lingStats: ActorLifeState
    @Binding var expandedMember: String?
    
    var body: some View {
        VStack(spacing: 12) {
            MemberStatusCard(
                name: "Aveline",
                role: "ACTIVE",
                color: .cyan,
                stats: avelineStats,
                messageCount: 156,
                isExpanded: expandedMember == "aveline",
                onToggle: {
                    expandedMember = expandedMember == "aveline" ? nil : "aveline"
                }
            )
            
            MemberStatusCard(
                name: "Ling",
                role: "BACKGROUND",
                color: .pink,
                stats: lingStats,
                messageCount: 42,
                isExpanded: expandedMember == "ling",
                onToggle: {
                    expandedMember = expandedMember == "ling" ? nil : "ling"
                }
            )
        }
    }
}

// MARK: - Member Status Card 成员状态卡片
struct MemberStatusCard: View {
    let name: String
    let role: String
    let color: Color
    let stats: ActorLifeState
    let messageCount: Int
    let isExpanded: Bool
    let onToggle: () -> Void
    
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button(action: onToggle) {
                MemberStatusCardHeader(
                    name: name,
                    role: role,
                    color: color,
                    messageCount: messageCount,
                    moodScore: stats.mood_score,
                    isExpanded: isExpanded
                )
            }
            .buttonStyle(PlainButtonStyle())
            
            if isExpanded {
                MemberStatusCardContent(
                    color: color,
                    stats: stats
                )
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(color.opacity(0.05))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(color.opacity(0.1), lineWidth: 1)
        )
    }
}

struct MemberStatusCardHeader: View {
    let name: String
    let role: String
    let color: Color
    let messageCount: Int
    let moodScore: Double
    let isExpanded: Bool
    
    var body: some View {
        HStack(spacing: 12) {
            AvatarView(name: name, color: color)
            
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(name)
                        .font(.subheadline)
                        .fontWeight(.semibold)
                    Tag(text: role, color: color)
                }
                
                MemberSummaryInfo(messageCount: messageCount, moodScore: moodScore)
            }
            
            Spacer()
            
            Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                .foregroundColor(.secondary)
        }
        .padding()
    }
}

struct AvatarView: View {
    let name: String
    let color: Color
    
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12)
                .fill(
                    LinearGradient(
                        colors: [color.opacity(0.3), color.opacity(0.1)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: 40, height: 40)
            
            Text(String(name.prefix(1)))
                .font(.headline)
                .fontWeight(.bold)
                .foregroundColor(color)
        }
    }
}

struct MemberSummaryInfo: View {
    let messageCount: Int
    let moodScore: Double
    
    var body: some View {
        HStack(spacing: 16) {
            HStack(spacing: 4) {
                Image(systemName: "message")
                    .font(.system(size: 10))
                Text("\(messageCount) msgs")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            
            HStack(spacing: 4) {
                Image(systemName: "face.smiling")
                    .font(.system(size: 10))
                Text("\(Int(moodScore))% mood")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
    }
}

struct MemberStatusCardContent: View {
    let color: Color
    let stats: ActorLifeState
    
    var body: some View {
        VStack(spacing: 16) {
            Divider()
            
            QuickMetricsRow(color: color, stats: stats)
            
            MetricBarsView(color: color, stats: stats)
            
            if stats.happiness != nil || stats.social_desire != nil {
                AdditionalMetricsView(stats: stats)
            }
        }
        .padding(.horizontal)
        .padding(.bottom)
    }
}

struct QuickMetricsRow: View {
    let color: Color
    let stats: ActorLifeState
    
    var body: some View {
        HStack(spacing: 12) {
            QuickMetric(icon: "fork.knife", label: "SATIETY", value: Int(stats.hunger), color: color)
            QuickMetric(icon: "bolt", label: "ENERGY", value: Int(stats.energy), color: color)
            QuickMetric(icon: "face.smiling", label: "MOOD", value: Int(stats.mood_score), color: color)
        }
    }
}

struct MetricBarsView: View {
    let color: Color
    let stats: ActorLifeState
    
    var body: some View {
        VStack(spacing: 12) {
            MetricBar(label: "SATIETY", value: stats.hunger, color: color)
            MetricBar(label: "ENERGY", value: stats.energy, color: color)
            MetricBar(label: "MOOD", value: stats.mood_score, color: color)
        }
    }
}

struct AdditionalMetricsView: View {
    let stats: ActorLifeState
    
    var body: some View {
        HStack(spacing: 12) {
            if let happiness = stats.happiness {
                MetricBar(label: "HAPPINESS", value: happiness, color: .yellow)
            }
            if let socialDesire = stats.social_desire {
                MetricBar(label: "SOCIAL_DESIRE", value: socialDesire, color: .purple)
            }
        }
    }
}

// MARK: - Relationship Meter 关系亲密度
struct RelationshipMeter: View {
    let score: Double
    
    private var relationshipInfo: (label: String, emoji: String) {
        if score >= 80 {
            return ("SOULMATE", "💕")
        } else if score >= 60 {
            return ("CLOSE", "💖")
        } else if score >= 40 {
            return ("F{"file_path": 