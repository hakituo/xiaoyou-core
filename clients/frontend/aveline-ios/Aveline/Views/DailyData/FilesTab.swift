import SwiftUI

// MARK: - Files Tab 文件标签页

struct FilesTab: View {
    @Binding var currentPath: String
    @Binding var files: [DailyDataEntry]
    @Binding var viewingFile: String?
    @Binding var fileContent: String?
    let onPathSelect: (String) -> Void
    let onFileClick: (DailyDataEntry) -> Void
    let onGoUp: () -> Void
    
    var body: some View {
        VStack(spacing: 0) {
            BreadcrumbsView(
                currentPath: currentPath,
                onPathSelect: onPathSelect
            )
            .padding()
            
            HStack(spacing: 0) {
                FileListView(
                    files: files,
                    currentPath: currentPath,
                    viewingFile: viewingFile,
                    onFileClick: onFileClick,
                    onGoUp: onGoUp
                )
                .frame(width: viewingFile != nil ? UIScreen.main.bounds.width / 3 : nil)
                
                if viewingFile != nil {
                    FilePreviewView(
                        filename: viewingFile ?? "",
                        content: fileContent ?? "",
                        onClose: {
                            viewingFile = nil
                            fileContent = nil
                        }
                    )
                }
            }
        }
    }
}

// MARK: - Breadcrumbs View 面包屑视图
struct BreadcrumbsView: View {
    let currentPath: String
    let onPathSelect: (String) -> Void
    
    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                Button(action: { onPathSelect("") }) {
                    Text("ROOT")
                        .font(.caption)
                        .fontWeight(.medium)
                        .foregroundColor(.white.opacity(0.5))
                }
                
                let parts = currentPath.split(separator: "/")
                ForEach(Array(parts.enumerated()), id: \.offset) { index, part in
                    Image(systemName: "chevron.right")
                        .font(.caption2)
                        .foregroundColor(.white.opacity(0.3))
                    
                    Button(action: {
                        let path = parts.prefix(index + 1).joined(separator: "/")
                        onPathSelect(path)
                    }) {
                        Text(String(part))
                            .font(.caption)
                            .fontWeight(.medium)
                            .foregroundColor(.white.opacity(0.5))
                    }
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
        }
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(.black.opacity(0.2))
        )
    }
}

// MARK: - File List View 文件列表视图
struct FileListView: View {
    let files: [DailyDataEntry]
    let currentPath: String
    let viewingFile: String?
    let onFileClick: (DailyDataEntry) -> Void
    let onGoUp: () -> Void
    
    var body: some View {
        List {
            if !currentPath.isEmpty {
                Button(action: onGoUp) {
                    HStack(spacing: 12) {
                        Image(systemName: "chevron.left")
                            .foregroundColor(.white.opacity(0.5))
                        Text("..")
                            .foregroundColor(.white.opacity(0.5))
                    }
                }
                .listRowBackground(Color.clear)
            }
            
            if files.isEmpty {
                Text("Empty directory")
                    .foregroundColor(.white.opacity(0.2))
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 40)
                    .listRowBackground(Color.clear)
            } else {
                ForEach(files, id: \.name) { file in
                    Button(action: { onFileClick(file) }) {
                        FileRow(file: file, isSelected: viewingFile == file.name)
                    }
                    .listRowBackground(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(viewingFile == file.name ? .green.opacity(0.1) : .clear)
                    )
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
    }
}

// MARK: - File Row 文件行
struct FileRow: View {
    let file: DailyDataEntry
    let isSelected: Bool
    
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: file.type == .dir ? "folder.fill" : "doc.text")
                .foregroundColor(file.type == .dir ? .yellow.opacity(0.8) : .blue.opacity(0.8))
            
            Text(file.name)
                .foregroundColor(isSelected ? .green : .white.opacity(0.7))
            
            Spacer()
            
            if file.type == .dir {
                if let count = file.count {
                    Text("\(count) items")
                        .font(.caption)
                        .foregroundColor(.white.opacity(0.2))
                } else {
                    Text("DIR")
                        .font(.caption)
                        .foregroundColor(.white.opacity(0.2))
                }
            } else {
                if let size = file.size, size > 0 {
                    Text("\(Int(ceil(Double(size) / 1024)))KB")
                        .font(.caption)
                        .foregroundColor(.white.opacity(0.2))
                }
            }
        }
    }
}

// MARK: - File Preview View 文件预览视图
struct FilePreviewView: View {
    let filename: String
    let content: String
    let onClose: () -> Void
    
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                HStack(spacing: 8) {
                    Image(systemName: "doc.text")
                        .foregroundColor(.green.opacity(0.6))
                    Text(filename)
                        .font(.caption)
                        .foregroundColor(.green)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                
                Spacer()
                
                Button(action: onClose) {
                    Image(systemName: "xmark")
                        .foregroundColor(.white.opacity(0.4))
                }
            }
            .padding()
            .background(.white.opacity(0.05))
            
            ScrollView {
                Text(content)
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.8))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding()
            }
        }
        .background(.black.opacity(0.4))
    }
}

// MARK: - Preview
#Preview {
    FilesTab(
        currentPath: .constant("documents/notes"),
        files: .constant([
            DailyDataEntry(name: "2024", type: .dir, size: nil, count: 12),
            DailyDataEntry(name: "readme.txt", type: .file, size: 1024, count: nil)
        ]),
        viewingFile: .constant("readme.txt"),
        fileContent: .constant("这是文件内容预览"),
        onPathSelect: { _ in },
        onFileClick: { _ in },
        onGoUp: {}
    )
    .preferredColorScheme(.dark)
}
