import SwiftUI

// MARK: - Breathing Background 呼吸背景

// 呼吸图案类型
enum BreathingPattern {
    case sine      // 正弦波
    case triangle  // 三角波
    case square    // 方波
    case sawtooth  // 锯齿波
}

struct BreathingBackground: View {
    let emotion: String
    let intensity: CGFloat
    let pattern: BreathingPattern
    
    @State private var time: Double = 0
    @State private var targetColors: [Color]
    @State private var currentColors: [Color]
    
    private let animationSpeed: Double
    private let timer = Timer.publish(every: 0.016, on: .main, in: .common).autoconnect()
    
    init(emotion: String, intensity: CGFloat = 0.8, pattern: BreathingPattern = .sine) {
        self.emotion = emotion
        self.intensity = intensity
        self.pattern = pattern
        
        let initialColors = EmotionColors.getColors(for: emotion)
        self._targetColors = State(initialValue: initialColors)
        self._currentColors = State(initialValue: initialColors)
        self.animationSpeed = EmotionColors.getSpeed(for: emotion)
    }
    
    // 计算呼吸缩放因子
    private func breathingScale(for index: Int) -> CGFloat {
        let t = time * (1.0 / animationSpeed)
        let phase = Double(index) * (Double.pi / 2.0)
        
        let value: Double
        switch pattern {
        case .sine:
            value = (sin(t + phase) + 1.0) / 2.0
        case .triangle:
            let normalized = ((t + phase).truncatingRemainder(dividingBy: 2.0 * Double.pi)) / (2.0 * Double.pi)
            value = normalized < 0.5 ? normalized * 2.0 : (1.0 - normalized) * 2.0
        case .square:
            value = sin(t + phase) >= 0 ? 1.0 : 0.0
        case .sawtooth:
            let normalized = ((t + phase).truncatingRemainder(dividingBy: 2.0 * Double.pi)) / (2.0 * Double.pi)
            value = normalized
        }
        
        let baseScale: CGFloat = 0.7
        let scaleRange: CGFloat = 0.6
        return baseScale + scaleRange * CGFloat(value) * intensity
    }
    
    // 计算位置偏移
    private func positionOffset(for index: Int) -> CGSize {
        let t = time * (0.5 / animationSpeed)
        let baseOffset: CGFloat = 80
        return CGSize(
            width: sin(t + Double(index) * 1.3) * baseOffset,
            height: cos(t + Double(index) * 1.7) * baseOffset * 0.6
        )
    }
    
    // 颜色插值
    private func lerpColor(from start: Color, to end: Color, factor: CGFloat) -> Color {
        let uiStart = UIColor(start)
        let uiEnd = UIColor(end)
        
        var r1: CGFloat = 0, g1: CGFloat = 0, b1: CGFloat = 0, a1: CGFloat = 0
        var r2: CGFloat = 0, g2: CGFloat = 0, b2: CGFloat = 0, a2: CGFloat = 0
        
        uiStart.getRed(&r1, green: &g1, blue: &b1, alpha: &a1)
        uiEnd.getRed(&r2, green: &g2, blue: &b2, alpha: &a2)
        
        return Color(
            red: Double(r1 + (r2 - r1) * factor),
            green: Double(g1 + (g2 - g1) * factor),
            blue: Double(b1 + (b2 - b1) * factor),
            opacity: Double(a1 + (a2 - a1) * factor)
        )
    }
    
    var body: some View {
        ZStack {
            // 背景基色（第4个颜色）
            currentColors[safe: 3]?.opacity(0.3)
                .ignoresSafeArea()
            
            // 呼吸光晕
            ForEach(0..<4) { index in
                Circle()
                    .fill(
                        RadialGradient(
                            gradient: Gradient(
                                colors: [
                                    lerpColor(
                                        from: currentColors[safe: index] ?? .gray,
                                        to: currentColors[safe: 1] ?? .gray,
                                        factor: 0.3
                                    ).opacity(0.4 * intensity),
                                    lerpColor(
                                        from: currentColors[safe: index] ?? .gray,
                                        to: .clear,
                                        factor: 0.5
                                    ).opacity(0)
                                ]
                            ),
                            center: .center,
                            startRadius: 0,
                            endRadius: 400
                        )
                    )
                    .frame(
                        width: 700 * breathingScale(for: index),
                        height: 700 * breathingScale(for: index)
                    )
                    .offset(positionOffset(for: index))
            }
            
            // 中心辉光（第2个颜色）
            Circle()
                .fill(
                    RadialGradient(
                        gradient: Gradient(
                            colors: [
                                (currentColors[safe: 1] ?? .white).opacity(0.25 * intensity),
                                .clear
                            ]
                        ),
                        center: .center,
                        startRadius: 0,
                        endRadius: 250
                    )
                )
                .frame(width: 500, height: 500)
        }
        .ignoresSafeArea()
        .onReceive(timer) { _ in
            time += 0.016
        }
        .onChange(of: emotion) { newEmotion in
            targetColors = EmotionColors.getColors(for: newEmotion)
            // 平滑过渡颜色
            withAnimation(.easeInOut(duration: 1.5)) {
                currentColors = targetColors
            }
        }
    }
}

// 安全数组访问
extension Array {
    subscript(safe index: Int) -> Element? {
        return indices.contains(index) ? self[index] : nil
    }
}

#Preview {
    Group {
        BreathingBackground(emotion: "happy", intensity: 1.0, pattern: .sine)
        BreathingBackground(emotion: "angry", intensity: 1.0, pattern: .triangle)
        BreathingBackground(emotion: "coquetry", intensity: 1.0, pattern: .sine)
    }
}
