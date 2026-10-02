import SwiftUI

// MARK: - Visual Cortex Section 视觉皮层区域

struct VisualCortexSection: View {
    @Binding var prompt: String
    @Binding var numImages: Int
    @Binding var isGeneratingImage: Bool
    @Binding var imagesBase64: [String]
    let onGenerateImage: () -> Void
    let onPlayTTS: () -> Void
    
    var body: some View {
        GlassCard(title: "VISUAL CORTEX (IMAGE GEN)", icon: "photo") {
            VStack(alignment: .leading, spacing: 20) {
                modelSelectorPlaceholder
                promptInput
                batchSizeSlider
                actionButtons
                generatedImagesPreview
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(.purple.opacity(0.05))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(.purple.opacity(0.1), lineWidth: 1)
        )
    }
    
    private var modelSelectorPlaceholder: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Image Model Selector")
                .font(.caption)
                .foregroundColor(.purple.opacity(0.5))
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(.purple.opacity(0.05))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(.purple.opacity(0.1), lineWidth: 1)
        )
    }
    
    private var promptInput: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "wand.and.stars")
                    .font(.caption)
                    .foregroundColor(.purple.opacity(0.5))
                Text("PROMPT MATRIX")
                    .font(.caption)
                    .foregroundColor(.purple.opacity(0.5))
            }
            
            TextEditor(text: $prompt)
                .frame(height: 96)
                .padding(8)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(.black.opacity(0.3))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(.purple.opacity(0.1), lineWidth: 1)
                )
                .foregroundColor(.white)
        }
    }
    
    private var batchSizeSlider: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                HStack(spacing: 8) {
                    Image(systemName: "square.3.layers.3d")
                        .font(.caption)
                        .foregroundColor(.purple.opacity(0.5))
                    Text("BATCH SIZE")
                        .font(.caption)
                        .foregroundColor(.purple.opacity(0.5))
                }
                
                Spacer()
                
                Text("\(numImages)")
                    .font(.caption)
                    .foregroundColor(.purple)
            }
            
            Slider(value: Binding(
                get: { Double(numImages) },
                set: { numImages = Int($0) }
            ), in: 1...4, step: 1)
                .tint(.purple)
        }
    }
    
    private var actionButtons: some View {
        HStack(spacing: 12) {
            generateImageButton
            synthesizeAudioButton
        }
    }
    
    private var generateImageButton: some View {
        Button(action: onGenerateImage) {
            HStack(spacing: 8) {
                if isGeneratingImage {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                        .scaleEffect(0.8)
                } else {
                    Image(systemName: "photo")
                        .font(.caption)
                }
                Text("GENERATE_IMG")
                    .font(.caption)
                    .fontWeight(.medium)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(.white.opacity(0.1))
            .foregroundColor(.white.opacity(0.8))
            .cornerRadius(12)
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(.white.opacity(0.1), lineWidth: 1)
            )
        }
        .disabled(isGeneratingImage || prompt.trimmingCharacters(in: .whitespaces).isEmpty)
        .buttonStyle(PlainButtonStyle())
    }
    
    private var synthesizeAudioButton: some View {
        Button(action: onPlayTTS) {
            HStack(spacing: 8) {
                Image(systemName: "volume.2")
                    .font(.caption)
                Text("SYNTHESIZE_AUDIO")
                    .font(.caption)
                    .fontWeight(.medium)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(.green.opacity(0.1))
            .foregroundColor(.green)
            .cornerRadius(12)
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(.green.opacity(0.2), lineWidth: 1)
            )
        }
        .disabled(prompt.trimmingCharacters(in: .whitespaces).isEmpty)
        .buttonStyle(PlainButtonStyle())
    }
    
    private var generatedImagesPreview: some View {
        Group {
            if !imagesBase64.isEmpty {
                LazyVGrid(
                    columns: Array(
                        repeating: GridItem(.flexible(), spacing: 8),
                        count: imagesBase64.count > 1 ? 2 : 1
                    ),
                    spacing: 8
                ) {
                    ForEach(Array(imagesBase64.enumerated()), id: \.offset) { index, _ in
                        GeneratedImagePlaceholder(index: index)
                    }
                }
            }
        }
    }
}

// MARK: - Generated Image Placeholder 生成图片占位符
struct GeneratedImagePlaceholder: View {
    let index: Int
    
    var body: some View {
        RoundedRectangle(cornerRadius: 8)
            .fill(.purple.opacity(0.1))
            .frame(height: 150)
            .overlay(
                Text("Generated Image \(index + 1)")
                    .font(.caption)
                    .foregroundColor(.purple.opacity(0.5))
            )
    }
}

// MARK: - Preview
#Preview {
    ScrollView {
        VisualCortexSection(
            prompt: .constant("一只可爱的猫在草地上"),
            numImages: .constant(1),
            isGeneratingImage: .constant(false),
            imagesBase64: .constant([]),
            onGenerateImage: {},
            onPlayTTS: {}
        )
    }
    .padding()
    .preferredColorScheme(.dark)
}
