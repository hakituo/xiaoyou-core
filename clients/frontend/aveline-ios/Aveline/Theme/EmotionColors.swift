import SwiftUI

// MARK: - Emotion Colors 情绪颜色系统

struct EmotionData {
    let label: String
    let colors: [Color]  // [主色, 辉光色, 背景氛围色, 底光色]
    let speed: Double
}

struct EmotionColors {
    // 完整的情绪数据，包含10种情绪
    static let emotions: [String: EmotionData] = [
        "neutral": EmotionData(
            label: "Neutral",
            colors: [
                Color(red: 107/255, green: 114/255, blue: 128/255),
                Color(red: 165/255, green: 173/255, blue: 193/255),
                Color(red: 28/255, green: 31/255, blue: 36/255),
                Color(red: 75/255, green: 85/255, blue: 99/255)
            ],
            speed: 5.0
        ),
        "happy": EmotionData(
            label: "Happy",
            colors: [
                Color(red: 242/255, green: 206/255, blue: 119/255),
                Color(red: 255/255, green: 232/255, blue: 178/255),
                Color(red: 58/255, green: 46/255, blue: 19/255),
                Color(red: 211/255, green: 167/255, blue: 79/255)
            ],
            speed: 3.5
        ),
        "shy": EmotionData(
            label: "Shy",
            colors: [
                Color(red: 243/255, green: 184/255, blue: 200/255),
                Color(red: 255/255, green: 216/255, blue: 227/255),
                Color(red: 63/255, green: 27/255, blue: 41/255),
                Color(red: 229/255, green: 138/255, blue: 167/255)
            ],
            speed: 4.0
        ),
        "angry": EmotionData(
            label: "Angry",
            colors: [
                Color(red: 232/255, green: 106/255, blue: 115/255),
                Color(red: 255/255, green: 193/255, blue: 196/255),
                Color(red: 61/255, green: 14/255, blue: 20/255),
                Color(red: 193/255, green: 68/255, blue: 78/255)
            ],
            speed: 2.5
        ),
        "jealous": EmotionData(
            label: "Jealous",
            colors: [
                Color(red: 165/255, green: 138/255, blue: 248/255),
                Color(red: 211/255, green: 198/255, blue: 255/255),
                Color(red: 44/255, green: 36/255, blue: 83/255),
                Color(red: 126/255, green: 106/255, blue: 217/255)
            ],
            speed: 3.0
        ),
        "wronged": EmotionData(
            label: "Grievance",
            colors: [
                Color(red: 140/255, green: 178/255, blue: 255/255),
                Color(red: 205/255, green: 224/255, blue: 255/255),
                Color(red: 27/255, green: 42/255, blue: 76/255),
                Color(red: 91/255, green: 138/255, blue: 224/255)
            ],
            speed: 5.5
        ),
        "coquetry": EmotionData(
            label: "Coquetry",
            colors: [
                Color(red: 246/255, green: 164/255, blue: 198/255),
                Color(red: 255/255, green: 214/255, blue: 236/255),
                Color(red: 56/255, green: 28/255, blue: 44/255),
                Color(red: 207/255, green: 109/255, blue: 154/255)
            ],
            speed: 3.5
        ),
        "lost": EmotionData(
            label: "Depressed",
            colors: [
                Color(red: 163/255, green: 163/255, blue: 173/255),
                Color(red: 216/255, green: 216/255, blue: 226/255),
                Color(red: 24/255, green: 24/255, blue: 27/255),
                Color(red: 110/255, green: 110/255, blue: 120/255)
            ],
            speed: 6.0
        ),
        "excited": EmotionData(
            label: "Excited",
            colors: [
                Color(red: 94/255, green: 227/255, blue: 192/255),
                Color(red: 198/255, green: 255/255, blue: 240/255),
                Color(red: 13/255, green: 46/255, blue: 37/255),
                Color(red: 47/255, green: 179/255, blue: 149/255)
            ],
            speed: 2.0
        ),
        "sad": EmotionData(
            label: "Sad",
            colors: [
                Color(red: 140/255, green: 178/255, blue: 255/255),
                Color(red: 205/255, green: 224/255, blue: 255/255),
                Color(red: 27/255, green: 42/255, blue: 76/255),
                Color(red: 91/255, green: 138/255, blue: 224/255)
            ],
            speed: 5.5
        )
    ]
    
    // 情绪别名映射
    static let emotionAliases: [String: String] = [
        "sad": "lost",
        "upset": "wronged",
        "tsundere": "coquetry",
        "coquette": "coquetry"
    ]
    
    // 规范化情绪名称
    static func normalizeEmotion(_ emotion: String) -> String {
        let lowerEmotion = emotion.lowercased()
        if let alias = emotionAliases[lowerEmotion] {
            return alias
        }
        if emotions[lowerEmotion] != nil {
            return lowerEmotion
        }
        return "neutral"
    }
    
    // 获取情绪数据
    static func getEmotionData(for emotion: String) -> EmotionData {
        let normalized = normalizeEmotion(emotion)
        return emotions[normalized] ?? emotions["neutral"]!
    }
    
    // 获取情绪颜色数组
    static func getColors(for emotion: String) -> [Color] {
        return getEmotionData(for: emotion).colors
    }
    
    // 获取情绪动画速度
    static func getSpeed(for emotion: String) -> Double {
        return getEmotionData(for: emotion).speed
    }
    
    // 从文本推断情绪
    static func inferEmotion(from text: String) -> String {
        let lowerText = text.lowercased()
        
        if lowerText.contains("开心") || lowerText.contains("喜欢") || lowerText.contains("愉快") || lowerText.contains("高兴") || lowerText.contains("满足") || lowerText.contains("喜悦") {
            return "happy"
        }
        if lowerText.contains("生气") || lowerText.contains("愤怒") || lowerText.contains("火大") || lowerText.contains("糟糕") || lowerText.contains("讨厌") || lowerText.contains("不爽") || lowerText.contains("暴躁") {
            return "angry"
        }
        if lowerText.contains("兴奋") || lowerText.contains("激动") || lowerText.contains("期待") || lowerText.contains("迫不及待") || lowerText.contains("心跳") {
            return "excited"
        }
        if lowerText.contains("委屈") || lowerText.contains("难过") || lowerText.contains("伤心") || lowerText.contains("失落") || lowerText.contains("难受") || lowerText.contains("低落") || lowerText.contains("沮丧") {
            return "lost"
        }
        if lowerText.contains("害羞") || lowerText.contains("脸红") || lowerText.contains("不好意思") || lowerText.contains("羞涩") {
            return "shy"
        }
        if lowerText.contains("吃醋") || lowerText.contains("嫉妒") {
            return "jealous"
        }
        if lowerText.contains("撒娇") || lowerText.contains("粘人") || lowerText.contains("傲娇") || lowerText.contains("靠近") || lowerText.contains("拥抱") || lowerText.contains("亲吻") {
            return "coquetry"
        }
        
        return "neutral"
    }
    
    // 从标签解析情绪
    static func resolveEmotion(from label: String) -> String {
        let lowerLabel = label.lowercased()
        
        if lowerLabel.contains("傲娇") || lowerLabel.contains("撒娇") || lowerLabel.contains("娇") || lowerLabel.contains("粘人") {
            return "coquetry"
        }
        if lowerLabel.contains("害羞") || lowerLabel.contains("羞涩") || lowerLabel.contains("脸红") {
            return "shy"
        }
        if lowerLabel.contains("开心") || lowerLabel.contains("愉快") || lowerLabel.contains("高兴") {
            return "happy"
        }
        if lowerLabel.contains("生气") || lowerLabel.contains("愤怒") || lowerLabel.contains("火大") || lowerLabel.contains("暴躁") {
            return "angry"
        }
        if lowerLabel.contains("兴奋") || lowerLabel.contains("激动") || lowerLabel.contains("期待") {
            return "excited"
        }
        if lowerLabel.contains("委屈") {
            return "wronged"
        }
        if lowerLabel.contains("难过") || lowerLabel.contains("伤心") || lowerLabel.contains("失落") {
            return "lost"
        }
        if lowerLabel.contains("嫉妒") || lowerLabel.contains("吃醋") {
            return "jealous"
        }
        if lowerLabel.contains("平静") || lowerLabel.contains("中性") {
            return "neutral"
        }
        
        return normalizeEmotion(label)
    }
    
    // 移除情绪标记
    static func stripEmotionMarkers(_ text: String) -> String {
        var result = text
        
        // 移除 [EMO:xxx] 格式
        result = result.replacingOccurrences(of: "\\[EMO:\\s*[^\\]]*\\]", with: "", options: .regularExpression)
        
        // 移除 {xxx} 格式
        result = result.replacingOccurrences(of: "\\{[^}]+\\}", with: "", options: .regularExpression)
        
        // 移除 *xxx* 格式
        result = result.replacingOccurrences(of: "\\*[^*]+\\*", with: "", options: .regularExpression)
        
        // 移除 「xxx」 和 『xxx』 格式
        result = result.replacingOccurrences(of: "[「『][^」』]+[」』]", with: "", options: .regularExpression)
        
        // 移除 【xxx】 格式
        result = result.replacingOccurrences(of: "【[^】]+】", with: "", options: .regularExpression)
        
        // 清理多余空格
        return result.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "\\s{2,}", with: " ", options: .regularExpression)
    }
    
    // Hex 转 RGB
    static func hexToRGB(_ hex: String) -> (r: CGFloat, g: CGFloat, b: CGFloat) {
        var hexSanitized = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        hexSanitized = hexSanitized.replacingOccurrences(of: "#", with: "")
        
        var rgb: UInt64 = 0
        Scanner(string: hexSanitized).scanHexInt64(&rgb)
        
        let r = CGFloat((rgb & 0xFF0000) >> 16) / 255.0
        let g = CGFloat((rgb & 0x00FF00) >> 8) / 255.0
        let b = CGFloat(rgb & 0x0000FF) / 255.0
        
        return (r, g, b)
    }
    
    // RGB 转 Color
    static func rgbToColor(r: CGFloat, g: CGFloat, b: CGFloat) -> Color {
        return Color(red: Double(r), green: Double(g), blue: Double(b))
    }
    
    // 混合情绪颜色
    static func mixColors(weights: [String: Double]) -> [Color] {
        var mixed: [[Double]] = Array(repeating: [0, 0, 0], count: 4)
        var totalWeight = 0.0
        
        for (key, weight) in weights {
            let normalizedKey = normalizeEmotion(key)
            if let emotion = emotions[normalizedKey], weight > 0 {
                for (index, color) in emotion.colors.enumerated() {
                    let uiColor = UIColor(color)
                    var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
                    uiColor.getRed(&r, green: &g, blue: &b, alpha: &a)
                    mixed[index][0] += Double(r) * weight
                    mixed[index][1] += Double(g) * weight
                    mixed[index][2] += Double(b) * weight
                }
                totalWeight += weight
            }
        }
        
        if totalWeight == 0 {
            return emotions["neutral"]!.colors
        }
        
        return mixed.map { rgb in
            Color(
                red: rgb[0] / totalWeight,
                green: rgb[1] / totalWeight,
                blue: rgb[2] / totalWeight
            )
        }
    }
}

