import SwiftUI

// MARK: - Schedule Tab 时间表标签页

struct ScheduleTab: View {
    var body: some View {
        VStack(spacing: 16) {
            ScheduleCard()
            SignalsCard()
        }
        .padding(.horizontal)
    }
}

// MARK: - Schedule Card 时间表卡片
struct ScheduleCard: View {
    var body: some View {
        GlassCard(title: "Dynamic Active Care", icon: "clock") {
            VStack(alignment: .leading, spacing: 16) {
                Text("当前采用动态检查与上下文驱动策略，不再依赖固定时段 schedule 文件。实际触发会结合你今天记录到的作息、最近互动、低打扰状态和节流规则实时调整。")
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .padding()
                    .background(
                        RoundedRectangle(cornerRadius: 12)
                            .fill(.black.opacity(0.2))
                    )
                
                HStack(spacing: 12) {
                    ScheduleItem(label: "今日起床", value: "未记录")
                    ScheduleItem(label: "最近睡觉", value: "未记录")
                }
            }
        }
    }
}

struct ScheduleItem: View {
    let label: String
    let value: String
    
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.caption)
                .foregroundColor(.secondary)
            Text(value)
                .font(.caption)
                .fontWeight(.medium)
                .foregroundColor(.green)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(.black.opacity(0.2))
        )
    }
}

// MARK: - Signals Card 信号卡片
struct SignalsCard: View {
    var body: some View {
        GlassCard(title: "Dynamic Signals", icon: "waveform") {
            VStack(spacing: 0) {
                SignalRow(label: "作息来源", value: "daily portrait")
                SignalRow(label: "调度模式", value: "context-driven")
                SignalRow(label: "偏好模式", value: "normal")
                SignalRow(label: "低打扰", value: "false")
                SignalRow(label: "低打扰原因", value: "none")
            }
        }
    }
}

struct SignalRow: View {
    let label: String
    let value: String
    
    var body: some View {
        HStack {
            Text(label)
                .font(.caption)
                .foregroundColor(.secondary)
            Spacer()
            Text(value)
                .font(.caption)
                .foregroundColor(.white.opacity(0.7))
        }
        .padding(.vertical, 8)
        .padding(.horizontal)
        .background(
            Rectangle()
                .fill(.white.opacity(0.02))
        )
        .overlay(
            Rectangle()
                .fill(.white.opacity(0.05))
                .frame(height: 1),
            alignment: .bottom
        )
    }
}

// MARK: - Preview
#Preview {
    ScrollView {
        ScheduleTab()
    }
    .preferredColorScheme(.dark)
}
