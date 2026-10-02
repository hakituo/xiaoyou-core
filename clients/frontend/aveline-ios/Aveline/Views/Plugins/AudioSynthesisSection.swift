import SwiftUI

// MARK: - Audio Synthesis Section 音频合成区域

struct AudioSynthesisSection: View {
    @Binding var autoTtsEnabled: Bool
    @Binding var replyDisplayMode: String
    @Binding var ttsTextLanguage: String
    @Binding var ttsPromptLanguage: String
    @Binding var ttsSpeed: Double
    @Binding var ttsPitch: Double
    @Binding var ttsProvider: String
    @Binding var ttsModel: String
    let onPlayTTS: () -> Void
    
    private let languageOptions = ["中英混合", "中文", "英文", "日文"]
    private let ttsProviderOptions = ["local", "siliconflow", "openai", "custom"]
    private let ttsLocalModelOptions = ["gpt_sovits", "qwen3"]
    
    var body: some View {
        GlassCard(title: "AUDIO SYNTHESIS (TTS)", icon: "speaker.wave.2") {
            VStack(alignment: .leading, spacing: 20) {
                replyModeAndAutoPlay
                ttsProviderAndModel
                languageSettings
                speedAndPitchSliders
            }
        }
    }
    
    private var replyModeAndAutoPlay: some View {
        HStack(spacing: 12) {
            replyModeSelector
            autoPlayToggle
        }
    }
    
    private var replyModeSelector: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("REPLY MODE")
                .font(.caption)
                .foregroundColor(.secondary)
            
            Picker("Reply Mode", selection: $replyDisplayMode) {
                Text("文字+语音").tag("text_and_tts")
                Text("仅语音").tag("tts_only")
            }
            .pickerStyle(.menu)
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(.black.opacity(0.3))
            )
        }
        .frame(maxWidth: .infinity)
    }
    
    private var autoPlayToggle: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("AUTO PLAY")
                .font(.caption)
                .foregroundColor(.secondary)
            
            HStack {
                Text("自动播放")
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.6))
                
                Spacer()
                
                Toggle("", isOn: $autoTtsEnabled)
                    .labelsHidden()
            }
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(.black.opacity(0.3))
            )
        }
        .frame(maxWidth: .infinity)
    }
    
    private var ttsProviderAndModel: some View {
        HStack(spacing: 12) {
            ttsProviderSelector
            ttsModelSelector
        }
    }
    
    private var ttsProviderSelector: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("TTS PROVIDER")
                .font(.caption)
                .foregroundColor(.secondary)
            
            Picker("TTS Provider", selection: $ttsProvider) {
                ForEach(ttsProviderOptions, id: \.self) { provider in
                    Text(provider == "local" ? "本地" : provider).tag(provider)
                }
            }
            .pickerStyle(.menu)
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(.black.opacity(0.3))
            )
        }
        .frame(maxWidth: .infinity)
    }
    
    private var ttsModelSelector: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("TTS MODEL")
                .font(.caption)
                .foregroundColor(.secondary)
            
            if ttsProvider == "local" {
                Picker("TTS Model", selection: $ttsModel) {
                    ForEach(ttsLocalModelOptions, id: \.self) { model in
                        Text(model == "gpt_sovits" ? "GPT-SoVITS" : "Qwen3-TTS").tag(model)
                    }
                }
                .pickerStyle(.menu)
                .padding()
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(.black.opacity(0.3))
                )
            } else {
                TextField("Model Name", text: $ttsModel)
                    .padding()
                    .background(
                        RoundedRectangle(cornerRadius: 12)
                            .fill(.black.opacity(0.3))
                    )
            }
        }
        .frame(maxWidth: .infinity)
    }
    
    private var languageSettings: some View {
        HStack(spacing: 12) {
            textLanguageSelector
            promptLanguageSelector
        }
    }
    
    private var textLanguageSelector: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("TEXT LANG")
                .font(.caption)
                .foregroundColor(.secondary)
            
            Picker("Text Language", selection: $ttsTextLanguage) {
                ForEach(languageOptions, id: \.self) { lang in
                    Text(lang).tag(lang)
                }
            }
            .pickerStyle(.menu)
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(.black.opacity(0.3))
            )
        }
        .frame(maxWidth: .infinity)
    }
    
    private var promptLanguageSelector: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("PROMPT LANG")
                .font(.caption)
                .foregroundColor(.secondary)
            
            Picker("Prompt Language", selection: $ttsPromptLanguage) {
                ForEach(languageOptions, id: \.self) { lang in
                    Text(lang).tag(lang)
                }
            }
            .pickerStyle(.menu)
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(.black.opacity(0.3))
            )
        }
        .frame(maxWidth: .infinity)
    }
    
    private var speedAndPitchSliders: some View {
        VStack(spacing: 16) {
            speedSlider
            pitchSlider
        }
    }
    
    private var speedSlider: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("SPEED")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                Text(String(format: "%.2fx", ttsSpeed))
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.3))
            }
            
            Slider(value: $ttsSpeed, in: 0.6...1.4, step: 0.02)
                .tint(.green)
        }
    }
    
    private var pitchSlider: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("PITCH")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                Text(String(format: "%.2f", ttsPitch))
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.3))
            }
            
            Slider(value: $ttsPitch, in: 0.8...1.2, step: 0.02)
                .tint(.green)
        }
    }
}

// MARK: - Preview
#Preview {
    ScrollView {
        AudioSynthesisSection(
            autoTtsEnabled: .constant(false),
            replyDisplayMode: .constant("text_and_tts"),
            ttsTextLanguage: .constant("中英混合"),
            ttsPromptLanguage: .constant("中英混合"),
            ttsSpeed: .constant(1.0),
            ttsPitch: .constant(1.0),
            ttsProvider: .constant("local"),
            ttsModel: .constant("gpt_sovits"),
            onPlayTTS: {}
        )
    }
    .padding()
    .preferredColorScheme(.dark)
}
