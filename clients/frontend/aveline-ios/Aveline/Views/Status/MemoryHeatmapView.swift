import SwiftUI

// MARK: - Memory Heatmap View 记忆热力图视图

struct MemoryHeatmapView: View {
    let gridSize: Int = 6
    let scale: CGFloat
    
    @State private var activations: [Double]
    @State private var timer: Timer?
    
    init(scale: CGFloat = 1.0) {
        self.scale = scale
        self._activations = State(initialValue: (0..<36).map { _ in Double.random(in: 0.1...1.0) })
    }
    
    var body: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 2 * scale), count: gridSize), spacing: 2 * scale) {
            ForEach(0..<36, id: \.self) { index in
                RoundedRectangle(cornerRadius: 2 * scale)
                    .fill(heatmapColor(for: activations[index]))
                    .opacity(0.1 + activations[index] * 0.7)
                    .animation(
                        Animation.easeInOut(duration: 2 + Double.random(in: 0...3))
                            .repeatForever(autoreverses: true)
                            .delay(Double.random(in: 0...2)),
                        value: activations[index]
                    )
            }
        }
        .onAppear {
            startAnimation()
        }
        .onDisappear {
            stopAnimation()
        }
    }
    
    private func startAnimation() {
        timer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { _ in
            for index in 0..<36 {
                if Double.random(in: 0...1) > 0.7 {
                    activations[index] = Double.random(in: 0.1...1.0)
                }
            }
        }
    }
    
    private func stopAnimation() {
        timer?.invalidate()
        timer = nil
    }
    
    private func heatmapColor(for value: Double) -> Color {
        if value > 0.8 {
            return .green
        } else if value > 0.5 {
            return .blue
        } else {
            return .white
        }
    }
}

// MARK: - Preview
#Preview {
    VStack(spacing: 40) {
        MemoryHeatmapView(scale: 1.0)
            .frame(width: 120, height: 120)
        
        MemoryHeatmapView(scale: 2.0)
            .frame(width: 240, height: 240)
    }
    .padding()
    .preferredColorScheme(.dark)
}
