import SwiftUI

// MARK: - Plugins Panel View 插件管理面板 - 重构版本

struct PluginsPanelView: View {
    @EnvironmentObject var mainViewModel: MainViewModel
    
    // 模型选择
    @State private var selectedModel: String = ""
    @State private var responseLength: String = "normal"
    @State private var currentModelType: String = "cloud"
    
    // 音频设置
    @State private var autoTtsEnabled: Bool = false
    @State private var replyDisplayMode: String = "text_and_tts"
    @State private var ttsTextLanguage: String = "中英混合"
    @State private var ttsPromptLanguage: String = "中英混合"
    @State private var ttsSpeed: Double = 1.0
    @State private var ttsPitch: Double = 1.0
    @State private var ttsProvider: String = "local"
    @State private var ttsModel: String = "gpt_sovits"
    
    // 图片生成
    @State private var prompt: String = ""
    @State private var numImages: Int = 1
    @State private var isGeneratingImage: Bool = false
    @State private var imagesBase64: [String] = []
    
    // 其他设置
    @State private var studyMode: Bool = false
    @State private var sensitiveEnabled: Bool = false
    
    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                HeaderView(title: "系统模块", subtitle: "SYSTEM MODULES", accentColor: .green)
                
                HStack(alignment: .top, spacing: 16) {
                    leftColumn
                    rightColumn
                }
            }
            .padding()
        }
        .navigationTitle("插件")
        .navigationBarTitleDisplayMode(.large)
    }
    
    private var leftColumn: some View {
        VStack(spacing: 16) {
            CoreLLMSection(
                selectedModel: $selectedModel,
                responseLength: $responseLength,
                currentModelType: $currentModelType,
                studyMode: $studyMode,
                sensitiveEnabled: $sensitiveEnabled,
                breathingRate: mainViewModel.breathingRate,
                onToggleStudyMode: toggleStudyMode,
                onToggleSensitive: toggleSensitive
            )
            
            AudioSynthesisSection(
                autoTtsEnabled: $autoTtsEnabled,
                replyDisplayMode: $replyDisplayMode,
                ttsTextLanguage: $ttsTextLanguage,
                ttsPromptLanguage: $ttsPromptLanguage,
                ttsSpeed: $ttsSpeed,
                ttsPitch: $ttsPitch,
                ttsProvider: $ttsProvider,
                ttsModel: $ttsModel,
                onPlayTTS: playTTS
            )
        }
        .frame(maxWidth: .infinity)
    }
    
    private var rightColumn: some View {
        VStack(spacing: 16) {
            VisualCortexSection(
                prompt: $prompt,
                numImages: $numImages,
                isGeneratingImage: $isGeneratingImage,
                imagesBase64: $imagesBase64,
                onGenerateImage: generateImage,
                onPlayTTS: playTTS
            )
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - Actions
extension PluginsPanelView {
    private func toggleStudyMode() {
        studyMode.toggle()
    }
    
    private func toggleSensitive() {
        sensitiveEnabled.toggle()
    }
    
    private func generateImage() {
        guard !prompt.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        isGeneratingImage = true
        imagesBase64 = []
        
        // 模拟生成图片
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            isGeneratingImage = false
        }
    }
    
    private func playTTS() {
        guard !prompt.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        // 模拟播放 TTS
    }
}

// MARK: - Header View Extension
private struct HeaderView: View {
    let title: String
    let subtitle: String
    let accentColor: Color
    
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 4) {
                    Text(subtitle)
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text("ACTIVE // READY")
                        .font(.caption)
                        .fontWeight(.medium)
                        .foregroundColor(.green)
                }
                Text(title)
                    .font(.title2)
                    .fontWeight(.bold)
            }
            
            Spacer()
        }
    }
}

// MARK: - Preview
#Preview {
    NavigationStack {
        PluginsPanelView()
            .environmentObject(MainViewModel())
    }
    .preferredColorScheme(.dark)
}
