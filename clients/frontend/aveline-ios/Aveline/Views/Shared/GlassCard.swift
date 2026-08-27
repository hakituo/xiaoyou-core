import SwiftUI

// MARK: - Glass Card 玻璃卡片 - 通用组件

struct GlassCard<Content: View>: View {
    let title: String?
    let icon: String?
    let expandable: Bool
    let isExpanded: Binding<Bool>?
    let onToggle: (() -> Void)?
    let content: Content
    
    init(
        title: String? = nil,
        icon: String? = nil,
        expandable: Bool = false,
        isExpanded: Binding<Bool>? = nil,
        onToggle: (() -> Void)? = nil,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.icon = icon
        self.expandable = expandable
        self.isExpanded = isExpanded
        self.onToggle = onToggle
        self.content = content()
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // 头部
            if title != nil || icon != nil {
                Button(action: {
                    if expandable {
                        onToggle?()
                    }
                }) {
                    HStack(spacing: 12) {
                        if let icon = icon {
                            Image(systemName: icon)
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        
                        if let title = title {
                            Text(title)
                                .font(.system(size: 11, weight: .bold, design: .default))
                                .foregroundColor(.secondary)
                                .tracking(2)
                        }
                        
                        Spacer()
                        
                        if expandable {
                            Image(systemName: (isExpanded?.wrappedValue ?? false) ? "chevron.down" : "chevron.right")
                                .foregroundColor(.secondary)
                                .font(.caption)
                        }
                    }
                    .padding()
                    .contentShape(Rectangle())
                }
                .buttonStyle(PlainButtonStyle())
            }
            
            // 内容
            if !expandable || (isExpanded?.wrappedValue ?? true) {
                VStack(alignment: .leading, spacing: 12) {
                    content
                }
                .padding(title != nil || icon != nil ? [.horizontal, .bottom] : .all)
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(.ultraThinMaterial)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(Color.white.opacity(0.05), lineWidth: 1)
        )
        .animation(.easeInOut(duration: 0.2), value: isExpanded?.wrappedValue)
    }
}

// MARK: - Preview
#Preview {
    VStack(spacing: 16) {
        GlassCard(title: "TEST CARD", icon: "cpu") {
            Text("Hello World")
                .foregroundColor(.white)
        }
        
        GlassCard(title: "EXPANDABLE", icon: "list.bullet", expandable: true, isExpanded: .constant(true)) {
            Text("Expandable content")
                .foregroundColor(.white)
        }
    }
    .padding()
    .preferredColorScheme(.dark)
}
