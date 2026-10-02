import SwiftUI

// MARK: - Diary Tab 日记标签页

struct DiaryTab: View {
    @Binding var currentDate: Date
    @Binding var diaryEntries: [DiaryEntry]
    let onDateChange: (Int) -> Void
    let onFetchDiary: (Date) -> Void
    
    var body: some View {
        VStack(spacing: 0) {
            DateNavigationView(
                currentDate: $currentDate,
                onDateChange: onDateChange
            )
            .padding()
            
            if diaryEntries.isEmpty {
                EmptyDiaryView()
            } else {
                DiaryEntriesList(entries: diaryEntries)
            }
        }
    }
}

// MARK: - Date Navigation View 日期导航视图
struct DateNavigationView: View {
    @Binding var currentDate: Date
    let onDateChange: (Int) -> Void
    
    var body: some View {
        HStack {
            Button(action: { onDateChange(-1) }) {
                Image(systemName: "chevron.left")
                    .font(.title2)
                    .foregroundColor(.white.opacity(0.6))
            }
            
            Spacer()
            
            VStack(spacing: 4) {
                Text(currentDate.formatted(date: .complete, time: .omitted))
                    .font(.headline)
                    .fontWeight(.light)
                    .foregroundColor(.green)
            }
            
            Spacer()
            
            Button(action: { onDateChange(1) }) {
                Image(systemName: "chevron.right")
                    .font(.title2)
                    .foregroundColor(.white.opacity(0.6))
            }
        }
        .padding()
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(.ultraThinMaterial)
        )
    }
}

// MARK: - Empty Diary View 空日记视图
struct EmptyDiaryView: View {
    var body: some View {
        VStack(spacing: 16) {
            Spacer()
            Image(systemName: "book")
                .font(.system(size: 48))
                .foregroundColor(.white.opacity(0.2))
            Text("No diary entries found for this day.")
                .foregroundColor(.white.opacity(0.2))
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Diary Entries List 日记条目列表
struct DiaryEntriesList: View {
    let entries: [DiaryEntry]
    
    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                ForEach(entries, id: \.filename) { entry in
                    DiaryEntryView(entry: entry)
                }
            }
            .padding()
        }
    }
}

// MARK: - Diary Entry View 日记条目视图
struct DiaryEntryView: View {
    let entry: DiaryEntry
    
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Image(systemName: "book")
                    .foregroundColor(.green.opacity(0.6))
                Text(entry.filename)
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.6))
                    .truncationMode(.tail)
                    .lineLimit(1)
            }
            .padding(.horizontal)
            .padding(.vertical, 8)
            .background(.white.opacity(0.05))
            
            Text(entry.content)
                .font(.body)
                .foregroundColor(.white.opacity(0.9))
                .padding()
        }
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(.black.opacity(0.2))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(.white.opacity(0.05), lineWidth: 1)
        )
    }
}

// MARK: - Preview
#Preview {
    ScrollView {
        DiaryTab(
            currentDate: .constant(Date()),
            diaryEntries: .constant([
                DiaryEntry(filename: "2024-01-01_morning.txt", content: "今天天气很好，心情不错！"),
                DiaryEntry(filename: "2024-01-01_evening.txt", content: "晚上学习了 SwiftUI，收获很大。")
            ]),
            onDateChange: { _ in },
            onFetchDiary: { _ in }
        )
    }
    .preferredColorScheme(.dark)
}
