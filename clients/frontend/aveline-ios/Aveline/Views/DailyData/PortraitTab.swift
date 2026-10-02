import SwiftUI

// MARK: - Portrait Tab 用户画像标签页

struct PortraitTab: View {
    @Binding var portraitDate: String
    @Binding var loadingPortrait: Bool
    @Binding var portraitMessage: String
    @Binding var weightInput: String
    @Binding var drinkUnits: Int
    @Binding var studySubject: String
    @Binding var studyDuration: Int
    @Binding var studyNote: String
    let onRefreshPortrait: () -> Void
    let onSaveWeight: () -> Void
    let onRecordDrink: (Int) -> Void
    let onStartStudy: () -> Void
    let onFinishStudy: () -> Void
    
    var body: some View {
        VStack(spacing: 16) {
            PortraitCard(
                portraitDate: portraitDate,
                loading: loadingPortrait,
                onRefresh: onRefreshPortrait
            )
            
            WeightManagementCard(
                weightInput: $weightInput,
                onSave: onSaveWeight
            )
            
            QuickDrinkCard(
                drinkUnits: $drinkUnits,
                onDrink: onRecordDrink
            )
            
            StudyRecordCard(
                studySubject: $studySubject,
                studyDuration: $studyDuration,
                studyNote: $studyNote,
                onStartStudy: onStartStudy,
                onFinishStudy: onFinishStudy
            )
            
            if !portraitMessage.isEmpty {
                SuccessMessage(message: portraitMessage)
            }
        }
        .padding(.horizontal)
    }
}

// MARK: - Portrait Card 用户画像卡片
struct PortraitCard: View {
    let portraitDate: String
    let loading: Bool
    let onRefresh: () -> Void
    
    var body: some View {
        GlassCard(title: "用户画像（今日）", icon: "person.text.rectangle") {
            VStack(spacing: 12) {
                HStack {
                    Text("SYSTEM CORE")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    
                    Spacer()
                    
                    Button(action: onRefresh) {
                        Text("Refresh")
                            .font(.caption)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(.white.opacity(0.1))
                            .cornerRadius(6)
                    }
                }
                
                if loading {
                    HStack {
                        Spacer()
                        ProgressView()
                        Spacer()
                    }
                    .padding(.vertical, 20)
                } else {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 2), spacing: 12) {
                        PortraitItem(label: "日期", value: portraitDate)
                        PortraitItem(label: "打扰级别", value: "普通")
                        PortraitItem(label: "今日饮水", value: "0 ml (0 次)")
                        PortraitItem(label: "今日学习", value: "0 分钟 (0 次)")
                        PortraitItem(label: "当前体重", value: "未设置")
                        PortraitItem(label: "起床", value: "未记录")
                        PortraitItem(label: "睡觉", value: "未记录")
                    }
                }
            }
        }
    }
}

struct PortraitItem: View {
    let label: String
    let value: String
    
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.caption)
                .foregroundColor(.secondary)
            Text(value)
                .font(.caption)
                .fontWeight(.medium)
                .foregroundColor(.green)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(.black.opacity(0.2))
        )
    }
}

// MARK: - Weight Management Card 体重管理卡片
struct WeightManagementCard: View {
    @Binding var weightInput: String
    let onSave: () -> Void
    
    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.green)
                    Text("体重管理")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundColor(.green)
                }
                
                HStack(spacing: 8) {
                    TextField("输入 kg", text: $weightInput)
                        .keyboardType(.decimalPad)
                        .padding()
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .fill(.black.opacity(0.3))
                        )
                    
                    Button(action: onSave) {
                        Text("保存")
                            .font(.caption)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 14)
                            .background(.green.opacity(0.2))
                            .foregroundColor(.green)
                            .cornerRadius(12)
                    }
                }
            }
        }
    }
}

// MARK: - Quick Drink Card 快捷喝水卡片
struct QuickDrinkCard: View {
    @Binding var drinkUnits: Int
    let onDrink: (Int) -> Void
    
    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "drop.fill")
                        .foregroundColor(.cyan)
                    Text("快捷喝水")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundColor(.cyan)
                }
                
                HStack(spacing: 8) {
                    ForEach([1, 2, 3], id: \.self) { units in
                        Button(action: { onDrink(units) }) {
                            Text("+\(units * 250)ml")
                                .font(.caption)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 12)
                                .background(.cyan.opacity(0.15))
                                .foregroundColor(.cyan)
                                .cornerRadius(12)
                        }
                    }
                }
                
                HStack(spacing: 8) {
                    TextField("", value: $drinkUnits, format: .number)
                        .keyboardType(.numberPad)
                        .frame(width: 60)
                        .padding()
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .fill(.black.opacity(0.3))
                        )
                    
                    Button(action: { onDrink(drinkUnits) }) {
                        Text("记录 \(drinkUnits * 250)ml")
                            .font(.caption)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(.green.opacity(0.2))
                            .foregroundColor(.green)
                            .cornerRadius(12)
                    }
                }
            }
        }
    }
}

// MARK: - Study Record Card 学习记录卡片
struct StudyRecordCard: View {
    @Binding var studySubject: String
    @Binding var studyDuration: Int
    @Binding var studyNote: String
    let onStartStudy: () -> Void
    let onFinishStudy: () -> Void
    
    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "brain.head.profile")
                        .foregroundColor(.green)
                    Text("学习记录")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundColor(.green)
                }
                
                VStack(spacing: 8) {
                    TextField("科目，例如：线代 / 英语 / 前端", text: $studySubject)
                        .padding()
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .fill(.black.opacity(0.3))
                        )
                    
                    TextField("", value: $studyDuration, format: .number)
                        .keyboardType(.numberPad)
                        .padding()
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .fill(.black.opacity(0.3))
                        )
                    
                    TextField("备注（可选）", text: $studyNote)
                        .padding()
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .fill(.black.opacity(0.3))
                        )
                    
                    Button(action: onStartStudy) {
                        Text("开始学习并进入低打扰")
                            .font(.caption)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(.blue.opacity(0.2))
                            .foregroundColor(.blue)
                            .cornerRadius(12)
                    }
                    
                    Button(action: onFinishStudy) {
                        Text("结束学习并恢复普通模式")
                            .font(.caption)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(.white.opacity(0.1))
                            .foregroundColor(.white.opacity(0.8))
                            .cornerRadius(12)
                    }
                }
            }
        }
    }
}

// MARK: - Success Message 成功消息
struct SuccessMessage: View {
    let message: String
    
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundColor(.green)
            Text(message)
                .font(.caption)
                .foregroundColor(.green)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(.green.opacity(0.1))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(.green.opacity(0.2), lineWidth: 1)
        )
    }
}

// MARK: - Preview
#Preview {
    ScrollView {
        PortraitTab(
            portraitDate: .constant(Date().formatted(date: .numeric, time: .omitted)),
            loadingPortrait: .constant(false),
            portraitMessage: .constant("体重已更新：65kg"),
            weightInput: .constant(""),
            drinkUnits: .constant(1),
            studySubject: .constant(""),
            studyDuration: .constant(45),
            studyNote: .constant(""),
            onRefreshPortrait: {},
            onSaveWeight: {},
            onRecordDrink: { _ in },
            onStartStudy: {},
            onFinishStudy: {}
        )
    }
    .preferredColorScheme(.dark)
}
