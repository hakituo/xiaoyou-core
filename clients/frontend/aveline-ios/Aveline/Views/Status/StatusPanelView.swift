import SwiftUI

// MARK: - Status Panel View 状态监控面板 - 重构版本

struct StatusPanelView: View {
    @EnvironmentObject var mainViewModel: MainViewModel
    @State private var selectedSection: StatusSection? = nil
    @State private var sections: [StatusSection: Bool] = [
        .overview: true,
        .scheduler: true,
        .bio: false,
        .memory: false
    ]
    
    enum StatusSection: String, CaseIterable {
        case overview = "overview"
        case scheduler = "scheduler"
        case bio = "bio"
        case memory = "memory"
    }
    
    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                HeaderView(title: "系统状态监控", subtitle: "SYSTEM CORE", accentColor: .green)
                
                if let section = selectedSection {
                    StatusSectionDetailView(section: section, onBack: { selectedSection = nil })
                        .transition(.opacity.combined(with: .scale))
                } else {
                    StatusOverviewCards(
                        systemStats: mainViewModel.systemStats,
                        sections: $sections,
                        onSectionSelect: { section in
                            withAnimation {
                                selectedSection = section
                            }
                        }
                    )
                }
            }
            .padding()
        }
        .navigationTitle("状态")
        .navigationBarTitleDisplayMode(.large)
    }
}

// MARK: - Status Overview Cards 状态概览卡片
struct StatusOverviewCards: View {
    let systemStats: SystemStatsState
    @Binding var sections: [StatusPanelView.StatusSection: Bool]
    let onSectionSelect: (StatusPanelView.StatusSection) -> Void
    
    var body: some View {
        VStack(spacing: 16) {
            SystemCoreCard(systemStats: systemStats)
            
            SchedulerCard(
                isExpanded: sections[.scheduler] ?? true,
                onToggle: { sections[.scheduler]?.toggle() },
                onExpand: { onSectionSelect(.scheduler) }
            )
            
            BioEmotionCard(
                isExpanded: sections[.bio] ?? false,
                onToggle: { sections[.bio]?.toggle() },
                onExpand: { onSectionSelect(.bio) }
            )
            
            MemorySnapshotCard(
                isExpanded: sections[.memory] ?? false,
                onToggle: { sections[.memory]?.toggle() },
                onExpand: { onSectionSelect(.memory) }
            )
        }
    }
}

// MARK: - System Core Card 系统核心卡片
struct SystemCoreCard: View {
    let systemStats: SystemStatsState
    
    var body: some View {
        GlassCard(title: "SYSTEM CORE", icon: "cpu") {
            HStack(spacing: 16) {
                MetricItem(label: "CPU", value: Int(systemStats.cpu), color: .blue)
                MetricItem(label: "GPU", value: Int(systemStats.gpu), color: .green)
                MetricItem(label: "MEMORY", value: Int(systemStats.memory), color: .purple)
            }
        }
    }
}

// MARK: - Scheduler Card 调度器卡片
struct SchedulerCard: View {
    let isExpanded: Bool
    let onToggle: () -> Void
    let onExpand: () -> Void
    
    var body: some View {
        GlassCard(
            title: "C++ SCHEDULER",
            icon: "list.checkmark",
            expandable: true,
            isExpanded: .constant(isExpanded),
            onToggle: onToggle
        ) {
            SchedulerCardContent(onExpand: onExpand)
        }
    }
}

struct SchedulerCardContent: View {
    let onExpand: () -> Void
    
    var body: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                MetricCard(title: "RUNNING", value: 0, color: .green)
                MetricCard(title: "QUEUE", value: 0, color: .blue)
            }
            
            ExpandButton(title: "OPEN SCHEDULER VIEW", icon: "list.checkmark", action: onExpand)
        }
    }
}

// MARK: - Bio & Emotion Card 生物与情绪卡片
struct BioEmotionCard: View {
    let isExpanded: Bool
    let onToggle: () -> Void
    let onExpand: () -> Void
    
    var body: some View {
        GlassCard(
            title: "BIO & EMOTION",
            icon: "heart.fill",
            expandable: true,
            isExpanded: .constant(isExpanded),
            onToggle: onToggle
        ) {
            BioEmotionCardContent(onExpand: onExpand)
        }
    }
}

struct BioEmotionCardContent: View {
    let onExpand: () -> Void
    
    var body: some View {
        VStack(spacing: 12) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 2), spacing: 12) {
                MetricCard(title: "DOPAMINE", value: "80%", color: .pink)
                MetricCard(title: "ENERGY", value: "100%", color: .yellow)
                MetricCard(title: "HUNGER", value: "0%", color: .orange)
                MetricCard(title: "THIRST", value: "0%", color: .blue)
            }
            
            ExpandButton(title: "OPEN BIO VIEW", icon: "heart.fill", action: onExpand)
        }
    }
}

// MARK: - Memory Snapshot Card 记忆快照卡片
struct MemorySnapshotCard: View {
    let isExpanded: Bool
    let onToggle: () -> Void
    let onExpand: () -> Void
    
    var body: some View {
        GlassCard(
            title: "MEMORY SNAPSHOT",
            icon: "memorychip",
            expandable: true,
            isExpanded: .constant(isExpanded),
            onToggle: onToggle
        ) {
            MemorySnapshotCardContent(onExpand: onExpand)
        }
    }
}

struct MemorySnapshotCardContent: View {
    let onExpand: () -> Void
    
    var body: some View {
        VStack(spacing: 12) {
            HStack(spacing: 16) {
                MemoryHeatmapView(scale: 1.0)
                    .frame(width: 80, height: 80)
                
                VStack(alignment: .leading, spacing: 4) {
                    Text("WEIGHTED MEMORY")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text("HEATMAP SNAPSHOT")
                        .font(.caption2)
                        .foregroundColor(.tertiary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            
            ExpandButton(title: "OPEN MEMORY VIEW", icon: "memorychip", action: onExpand)
        }
    }
}

// MARK: - Expand Button 展开按钮
struct ExpandButton: View {
    let title: String
    let icon: String
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .font(.caption)
                Text(title)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(.white.opacity(0.1))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(.white.opacity(0.1), lineWidth: 1)
            )
            .foregroundColor(.white.opacity(0.8))
        }
        .buttonStyle(PlainButtonStyle())
    }
}

// MARK: - Status Section Detail View 状态区域详情视图
struct StatusSectionDetailView: View {
    let section: StatusPanelView.StatusSection
    let onBack: () -> Void
    
    var body: some View {
        VStack(spacing: 20) {
            // 返回按钮
            HStack {
                Button(action: onBack) {
                    HStack(spacing: 8) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.title2)
                            .foregroundColor(.secondary)
                    }
                }
                Spacer()
            }
            
            // 内容
            switch section {
            case .overview:
                EmptyView()
            case .scheduler:
                SchedulerDetailView()
            case .bio:
                BioDetailView()
            case .memory:
                MemoryDetailView()
            }
        }
    }
}

// MARK: - Scheduler Detail View 调度器详情
struct SchedulerDetailView: View {
    var body: some View {
        VStack(spacing: 20) {
            HeaderView(title: "C++ SCHEDULER ENGINE", subtitle: "", accentColor: .green)
            
            GlassCard(title: "TASK PIPELINE", icon: "list.checkmark") {
                VStack(spacing: 16) {
                    HStack(spacing: 12) {
                        MetricCard(title: "RUNNING", value: 0, color: .green)
                        MetricCard(title: "QUEUE", value: 0, color: .blue)
                    }
                    
                    VStack(spacing: 8) {
                        MetricRow(label: "COMPLETED", value: 0)
                        MetricRow(label: "FAILED", value: 0)
                    }
                }
            }
        }
    }
}

// MARK: - Bio Detail View 生物详情
struct BioDetailView: View {
    var body: some View {
        VStack(spacing: 20) {
            HeaderView(title: "BIOLOGICAL SYSTEM", subtitle: "", accentColor: .pink)
            
            HStack(alignment: .top, spacing: 24) {
                VStack(alignment: .leading, spacing: 16) {
                    SectionHeader(title: "NEUROTRANSMITTERS", icon: "brain.head.profile", color: .pink.opacity(0.6))
                    
                    VStack(spacing: 12) {
                        MetricRow(label: "DOPAMINE", value: "80%")
                        MetricRow(label: "SEROTONIN", value: "85%")
                        MetricRow(label: "NOREPINEPHRINE", value: "70%")
                        MetricRow(label: "OXYTOCIN", value: "90%")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                
                VStack(alignment: .leading, spacing: 16) {
                    SectionHeader(title: "PHYSIOLOGY", icon: "heart.fill", color: .yellow.opacity(0.6))
                    
                    VStack(spacing: 12) {
                        MetricRow(label: "ENERGY", value: "100%")
                        MetricRow(label: "HUNGER", value: "0%")
                        MetricRow(label: "THIRST", value: "0%")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

// MARK: - Memory Detail View 记忆详情
struct MemoryDetailView: View {
    var body: some View {
        VStack(spacing: 30) {
            HeaderView(title: "MEMORY MATRIX", subtitle: "", accentColor: .green)
            
            MemoryHeatmapView(scale: 2.0)
                .padding(.vertical, 20)
            
            HStack(spacing: 32) {
                MetricRow(label: "Retrieval", value: "98 ms")
                MetricRow(label: "Fragments", value: 12)
                MetricRow(label: "Coherence", value: "0.94")
            }
        }
    }
}

// MARK: - Preview
#Preview {
    NavigationStack {
        StatusPanelView()
            .environmentObject(MainViewModel())
    }
    .preferredColorScheme(.dark)
}
