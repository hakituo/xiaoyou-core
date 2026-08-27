import SwiftUI

// MARK: - Daily Data Panel View 日常数据面板 - 重构版本

struct DailyDataPanelView: View {
    @EnvironmentObject var mainViewModel: MainViewModel
    
    @State private var activeTab: DailyTab = .portrait
    
    // Portrait
    @State private var portraitDate: String = ""
    @State private var loadingPortrait: Bool = false
    @State private var portraitMessage: String = ""
    
    // Diary
    @State private var diaryDate: Date = Date()
    @State private var diaryEntries: [DiaryEntry] = []
    
    // Files
    @State private var currentPath: String = ""
    @State private var files: [DailyDataEntry] = []
    @State private var viewingFile: String? = nil
    @State private var fileContent: String? = nil
    
    // Inputs
    @State private var weightInput: String = ""
    @State private var drinkUnits: Int = 1
    @State private var studySubject: String = ""
    @State private var studyDuration: Int = 45
    @State private var studyNote: String = ""
    
    enum DailyTab: String, CaseIterable {
        case portrait = "Portrait"
        case schedule = "Schedule"
        case diary = "Diary"
        case files = "Files"
    }
    
    var body: some View {
        VStack(spacing: 0) {
            headerView
            
            TabView(selection: $activeTab) {
                portraitTabView
                    .tag(DailyTab.portrait)
                
                scheduleTabView
                    .tag(DailyTab.schedule)
                
                diaryTabView
                    .tag(DailyTab.diary)
                
                filesTabView
                    .tag(DailyTab.files)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
        }
        .navigationTitle("日常数据")
        .navigationBarTitleDisplayMode(.large)
        .onAppear {
            fetchPortrait()
        }
    }
    
    // 头部视图
    private var headerView: some View {
        VStack(spacing: 12) {
            HeaderView(title: "日常数据中心", subtitle: "DAILY DATA", accentColor: .green)
            
            Picker("", selection: $activeTab) {
                ForEach(DailyTab.allCases, id: \.self) { tab in
                    Text(tab.rawValue).tag(tab)
                }
            }
            .pickerStyle(.segmented)
        }
        .padding()
        .background(
            Rectangle()
                .fill(.ultraThinMaterial)
                .edgesIgnoringSafeArea(.top)
        )
    }
    
    // Portrait 标签页
    private var portraitTabView: some View {
        ScrollView {
            PortraitTab(
                portraitDate: $portraitDate,
                loadingPortrait: $loadingPortrait,
                portraitMessage: $portraitMessage,
                weightInput: $weightInput,
                drinkUnits: $drinkUnits,
                studySubject: $studySubject,
                studyDuration: $studyDuration,
                studyNote: $studyNote,
                onRefreshPortrait: fetchPortrait,
                onSaveWeight: saveWeight,
                onRecordDrink: recordDrink,
                onStartStudy: startStudy,
                onFinishStudy: finishStudy
            )
            .padding(.vertical)
        }
    }
    
    // Schedule 标签页
    private var scheduleTabView: some View {
        ScrollView {
            ScheduleTab()
                .padding(.vertical)
        }
    }
    
    // Diary 标签页
    private var diaryTabView: some View {
        DiaryTab(
            currentDate: $diaryDate,
            diaryEntries: $diaryEntries,
            onDateChange: { days in
                let newDate = Calendar.current.date(byAdding: .day, value: days, to: diaryDate) ?? diaryDate
                diaryDate = newDate
                fetchDiary(newDate)
            },
            onFetchDiary: fetchDiary
        )
    }
    
    // Files 标签页
    private var filesTabView: some View {
        FilesTab(
            currentPath: $currentPath,
            files: $files,
            viewingFile: $viewingFile,
            fileContent: $fileContent,
            onPathSelect: { path in
                currentPath = path
                fetchFiles(path)
            },
            onFileClick: handleFileClick,
            onGoUp: goUp
        )
    }
}

// MARK: - Actions
extension DailyDataPanelView {
    private func fetchPortrait() {
        loadingPortrait = true
        portraitDate = Date().formatted(date: .numeric, time: .omitted)
        loadingPortrait = false
    }
    
    private func saveWeight() {
        portraitMessage = "体重已更新：\(weightInput)kg"
    }
    
    private func recordDrink(units: Int) {
        portraitMessage = "已记录喝水 \(units * 250)ml"
    }
    
    private func startStudy() {
        guard !studySubject.isEmpty else {
            portraitMessage = "请先填写学习科目"
            return
        }
        portraitMessage = "已开始学习：\(studySubject)（\(studyDuration)分钟，低打扰已开启）"
    }
    
    private func finishStudy() {
        portraitMessage = "学习时段已结束，低打扰已关闭"
    }
    
    private func fetchDiary(_ date: Date) {
        diaryEntries = []
    }
    
    private func fetchFiles(_ path: String) {
        files = []
    }
    
    private func handleFileClick(_ entry: DailyDataEntry) {
        if entry.type == .dir {
            currentPath = currentPath.isEmpty ? entry.name : "\(currentPath)/\(entry.name)"
            fetchFiles(currentPath)
        } else {
            viewingFile = entry.name
            fileContent = "File content preview..."
        }
    }
    
    private func goUp() {
        let parts = currentPath.split(separator: "/")
        if parts.count > 0 {
            currentPath = parts.dropLast().joined(separator: "/")
            fetchFiles(currentPath)
        } else {
            currentPath = ""
            fetchFiles("")
        }
    }
}

// MARK: - Preview
#Preview {
    NavigationStack {
        DailyDataPanelView()
            .environmentObject(MainViewModel())
    }
    .preferredColorScheme(.dark)
}
