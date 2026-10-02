import SwiftUI

// MARK: - Core LLM Section 核心 LLM 配置区域

struct CoreLLMSection: View {
    @Binding var selectedModel: String
    @Binding var responseLength: String
    @Binding var currentModelType: String
    @Binding var studyMode: Bool
    @Binding var sensitiveEnabled: Bool
    let breathingRate: Double
    let onToggleStudyMode: () -> Void
    let onToggleSensitive: () -> Void
    
    private let responseLengthOptions = ["short", "normal", "long"]
    
    var body: some View {
        GlassCard(title: "CORE LLM CONFIGURATION", icon: "cpu") {
            VStack(alignment: .leading, spacing: 20) {
                modelTypeSelector
                modelSelector
                responseLengthSelector
                breathingRateSlider
                studyModeToggle
                sensitiveModeToggle
            }
        }
    }
    
    private var modelTypeSelector: some View {
        HStack(spacing: 12) {
            ModelTypeButton(
                type: "cloud",
                name: "DeepSeek",
                currentType: $currentModelType
            )
            
            ModelTypeButton(
                type: "local",
                name: "Local Model",
                currentType: $currentModelType
            )
        }
    }
    
    private var modelSelector: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "cpu")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Text("ACTIVE MODEL SYSTEM")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            
            Picker("Select Model", selection: $selectedModel) {
                Text("Select a model...").tag("")
                Text("DeepSeek-V3").tag("deepseek-v3")
                Text("Qwen3-72B").tag("qwen3-72b")
                Text("Local Model").tag("local-llm")
            }
            .pickerStyle(.menu)
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(.black.opacity(0.3))
            )
        }
    }
    
    private var responseLengthSelector: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "command")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Text("RESPONSE PARAMS")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            
            HStack(spacing: 8) {
                ForEach(responseLengthOptions, id: \.self) { length in
                    ResponseLengthButton(
                        length: length,
                        selected: $responseLength
                    )
                }
            }
        }
    }
    
    private var breathingRateSlider: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "sparkles")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Text("ATMOSPHERE RATE")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            
            HStack(spacing: 12) {
                Slider(value: .constant(breathingRate), in: 0.1...3.0, step: 0.1)
                    .tint(.green)
                
                Text(String(format: "%.1fx", breathingRate))
                    .font(.caption)
                    .foregroundColor(.green)
                    .frame(width: 40, alignment: .trailing)
            }
        }
    }
    
    private var studyModeToggle: some View {
        VStack(spacing: 12) {
            Divider()
            
            HStack {
                HStack(spacing: 12) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 8)
                            .fill(studyMode ? .cyan.opacity(0.2) : .white.opacity(0.05))
                            .frame(width: 32, height: 32)
                        
                        Image(systemName: "book.closed")
                            .foregroundColor(studyMode ? .cyan : .white.opacity(0.4))
                            .font(.caption)
                    }
                    
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Study Mode")
                            .font(.caption)
                            .foregroundColor(.white.opacity(0.3))
                            .tracking(2)
                        Text("Structured Learning")
                            .font(.caption)
                            .foregroundColor(.white.opacity(0.7))
                    }
                }
                
                Spacer()
                
                Toggle("", isOn: $studyMode)
                    .labelsHidden()
                    .onChange(of: studyMode) { _ in
                        onToggleStudyMode()
                    }
            }
        }
    }
    
    private var sensitiveModeToggle: some View {
        VStack(spacing: 12) {
            Divider()
            
            HStack {
                HStack(spacing: 12) {
                    Circle()
                        .fill(sensitiveEnabled ? .red : .white.opacity(0.2))
                        .frame(width: 8, height: 8)
                        .shadow(color: sensitiveEnabled ? .red.opacity(0.6) : .clear, radius: 8)
                    
                    Text("Local Mode Override")
                        .font(.caption)
                        .foregroundColor(.white.opacity(0.3))
                        .tracking(2)
                }
                
                Spacer()
                
                Toggle("", isOn: $sensitiveEnabled)
                    .labelsHidden()
                    .onChange(of: sensitiveEnabled) { _ in
                        onToggleSensitive()
                    }
            }
            
            Text(sensitiveEnabled ? "LOCAL MODE ACTIVE // FULL CONTENT ACCESS" : "CLOUD MODE ACTIVE // STANDARD FILTERING")
                .font(.system(size: 10))
                .foregroundColor(.white.opacity(0.4))
                .tracking(-0.5)
        }
    }
}

// MARK: - Model Type Button 模型类型按钮
struct ModelTypeButton: View {
    let type: String
    let name: String
    @Binding var currentType: String
    
    var isSelected: Bool { currentType == type }
    
    var body: some View {
        Button(action: {
            currentType = type
        }) {
            VStack(alignment: .leading, spacing: 4) {
                Text(type == "cloud" ? "CLOUD API" : "LOCAL GPU")
                    .font(.system(size: 10))
                    .foregroundColor(isSelected ? .green.opacity(0.6) : .white.opacity(0.6))
                    .tracking(2)
                
                Text(name)
                    .font(.subheadline)
                    .fontWeight(.bold)
                    .foregroundColor(isSelected ? .green : .white.opacity(0.6))
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(isSelected ? .green.opacity(0.1) : .black.opacity(0.2))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(isSelected ? .green.opacity(0.3) : .white.opacity(0.1), lineWidth: 1)
            )
            .overlay(
                isSelected ?
                    Circle()
                        .fill(.green)
                        .frame(width: 6, height: 6)
                        .padding(8)
                        .position(x: 60, y: 10)
                        .shadow(color: .green.opacity(0.6), radius: 8)
                : nil
            )
        }
        .buttonStyle(PlainButtonStyle())
    }
}

// MARK: - Response Length Button 回复长度按钮
struct ResponseLengthButton: View {
    let length: String
    @Binding var selected: String
    
    var isSelected: Bool { selected == length }
    
    var body: some View {
        Button(action: {
            selected = length
        }) {
            Text(length.uppercased())
                .font(.caption)
                .fontWeight(.medium)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(isSelected ? .green.opacity(0.1) : .black.opacity(0.2))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(isSelected ? .green.opacity(0.3) : .white.opacity(0.1), lineWidth: 1)
                )
                .foregroundColor(isSelected ? .green : .white.opacity(0.4))
        }
        .buttonStyle(PlainButtonStyle())
    }
}

// MARK: - Preview
#Preview {
    ScrollView {
        CoreLLMSection(
            selectedModel: .constant("deepseek-v3"),
            responseLength: .constant("normal"),
            currentModelType: .constant("cloud"),
            studyMode: .constant(false),
            sensitiveEnabled: .constant(false),
            breathingRate: 1.0,
            onToggleStudyMode: {},
            onToggleSensitive: {}
        )
    }
    .padding()
    .preferredColorScheme(.dark)
}
