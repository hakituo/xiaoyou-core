import SwiftUI

// MARK: - Common Components 通用组件

// MARK: - Tag 标签
struct Tag: View {
    let text: String
    let color: Color
    let size: TagSize
    
    enum TagSize {
        case small
        case normal
    }
    
    init(text: String, color: Color, size: TagSize = .normal) {
        self.text = text
        self.color = color
        self.size = size
    }
    
    var body: some View {
        Text(text)
            .font(.system(size: size == .small ? 9 : 10, weight: .medium, design: .monospaced))
            .padding(.horizontal, size == .small ? 6 : 8)
            .padding(.vertical, size == .small ? 3 : 4)
            .background(
                RoundedRectangle(cornerRadius: size == .small ? 4 : 6)
                    .fill(color.opacity(0.1))
            )
            .overlay(
                RoundedRectangle(cornerRadius: size == .small ? 4 : 6)
                    .stroke(color.opacity(0.2), lineWidth: 1)
            )
            .foregroundColor(color)
    }
}

// MARK: - Info Card 信息卡片
struct InfoCard<Content: View>: View {
    let title: String
    let icon: String?
    let content: Content
    
    init(title: String, icon: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.icon = icon
        self.content = content()
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                if let icon = icon {
                    Image(systemName: icon)
                        .foregroundColor(.yellow.opacity(0.6))
                }
                Text(title)
                    .font(.system(size: 11, weight: .bold, design: .default))
                    .foregroundColor(.secondary)
                    .tracking(2)
            }
            
            content
        }
        .padding()
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(.yellow.opacity(0.05))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(.yellow.opacity(0.1), lineWidth: 1)
        )
    }
}

// MARK: - Header View 头部视图
struct HeaderView: View {
    let title: String
    let subtitle: String?
    let accentColor: Color
    
    init(title: String, subtitle: String? = nil, accentColor: Color = .green) {
        self.title = title
        self.subtitle = subtitle
        self.accentColor = accentColor
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let subtitle = subtitle {
                HStack(spacing: 4) {
                    Text(subtitle)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
            Text(title)
                .font(.title2)
                .fontWeight(.bold)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Section Header 区域头部
struct SectionHeader: View {
    let title: String
    let icon: String?
    let color: Color
    
    init(title: String, icon: String? = nil, color: Color = .secondary) {
        self.title = title
        self.icon = icon
        self.color = color
    }
    
    var body: some View {
        HStack(spacing: 8) {
            if let icon = icon {
                Image(systemName: icon)
                    .font(.caption)
                    .foregroundColor(color)
            }
            Text(title)
                .font(.system(size: 11, weight: .bold, design: .default))
                .foregroundColor(color)
                .tracking(2)
        }
    }
}

// MARK: - Previews
#Preview {
    VStack(spacing: 20) {
        HStack(spacing: 8) {
            Tag(text: "ACTIVE", color: .cyan)
            Tag(text: "BACKGROUND", color: .pink)
            Tag(text: "normal", color: .gray, size: .small)
        }
        
        InfoCard(title: "INTERACTION GUIDE", icon: "info.circle") {
            Text("This is an info card with some helpful information.")
                .font(.caption)
                .foregroundColor(.secondary)
        }
        
        HeaderView(title: "系统状态", subtitle: "SYSTEM STATUS", accentColor: .green)
        
        SectionHeader(title: "CORE MODULES", icon: "cpu", color: .cyan.opacity(0.6))
    }
    .padding()
    .preferredColorScheme(.dark)
}
