import SwiftUI

// MARK: - Metric Components 指标组件

// MARK: - Metric Item
struct MetricItem: View {
    let label: String
    let value: String
    let color: Color
    
    init(label: String, value: String, color: Color = .blue) {
        self.label = label
        self.value = value
        self.color = color
    }
    
    init(label: String, value: Int, color: Color = .blue) {
        self.label = label
        self.value = "\(value)"
        self.color = color
    }
    
    init(label: String, value: Double, color: Color = .blue) {
        self.label = label
        self.value = String(format: "%.0f", value)
        self.color = color
    }
    
    var body: some View {
        VStack(spacing: 4) {
            Text(label)
                .font(.caption2)
                .foregroundColor(.secondary)
            Text(value)
                .font(.title3)
                .fontWeight(.bold)
                .foregroundColor(color)
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - Metric Card
struct MetricCard: View {
    let title: String
    let value: String
    let color: Color
    
    init(title: String, value: String, color: Color = .green) {
        self.title = title
        self.value = value
        self.color = color
    }
    
    init(title: String, value: Int, color: Color = .green) {
        self.title = title
        self.value = "\(value)"
        self.color = color
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption)
                .foregroundColor(.secondary)
            Text(value)
                .font(.title2)
                .fontWeight(.bold)
                .foregroundColor(color)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(.white.opacity(0.05))
        )
    }
}

// MARK: - Metric Row
struct MetricRow: View {
    let label: String
    let value: String
    
    init(label: String, value: String) {
        self.label = label
        self.value = value
    }
    
    init(label: String, value: Int) {
        self.label = label
        self.value = "\(value)"
    }
    
    init(label: String, value: Double) {
        self.label = label
        self.value = String(format: "%.0f", value)
    }
    
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
    }
}

// MARK: - Metric Bar
struct MetricBar: View {
    let label: String
    let value: Double
    let color: Color
    let maxValue: Double
    
    init(label: String, value: Double, color: Color = .green, maxValue: Double = 100) {
        self.label = label
        self.value = value
        self.color = color
        self.maxValue = maxValue
    }
    
    var body: some View {
        VStack(spacing: 4) {
            HStack {
                Text(label)
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                Text("\(Int(value))")
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.7))
            }
            
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(.white.opacity(0.05))
                        .frame(height: 6)
                    
                    RoundedRectangle(cornerRadius: 4)
                        .fill(color)
                        .frame(width: geometry.size.width * CGFloat(min(maxValue, max(0, value)) / maxValue), height: 6)
                        .animation(.easeInOut(duration: 0.5), value: value)
                }
            }
            .frame(height: 6)
        }
    }
}

// MARK: - Quick Metric
struct QuickMetric: View {
    let icon: String
    let label: String
    let value: String
    let color: Color
    
    init(icon: String, label: String, value: String, color: Color) {
        self.icon = icon
        self.label = label
        self.value = value
        self.color = color
    }
    
    init(icon: String, label: String, value: Int, color: Color) {
        self.icon = icon
        self.label = label
        self.value = "\(value)"
        self.color = color
    }
    
    var body: some View {
        VStack(spacing: 4) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)
                Text(label)
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)
            }
            Text(value)
                .font(.title3)
                .fontWeight(.bold)
                .foregroundColor(color)
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - Previews
#Preview {
    VStack(spacing: 20) {
        HStack(spacing: 12) {
            MetricItem(label: "CPU", value: 45, color: .blue)
            MetricItem(label: "GPU", value: 72, color: .green)
            MetricItem(label: "MEM", value: 58, color: .purple)
        }
        
        HStack(spacing: 12) {
            MetricCard(title: "RUNNING", value: 5, color: .green)
            MetricCard(title: "QUEUE", value: 12, color: .blue)
        }
        
        VStack(spacing: 12) {
            MetricRow(label: "STATUS", value: "ACTIVE")
            MetricRow(label: "COUNT", value: 156)
        }
        
        MetricBar(label: "ENERGY", value: 85, color: .yellow)
        
        HStack(spacing: 12) {
            QuickMetric(icon: "bolt", label: "ENERGY", value: "100", color: .yellow)
            QuickMetric(icon: "heart", label: "MOOD", value: "80", color: .pink)
        }
    }
    .padding()
    .preferredColorScheme(.dark)
}
