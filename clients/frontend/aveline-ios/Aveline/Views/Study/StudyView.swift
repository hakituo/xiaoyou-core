import SwiftUI

struct StudyView: View {
    var body: some View {
        VStack {
            Image(systemName: "book.fill")
                .font(.system(size: 60))
                .foregroundColor(.secondary)
            
            Text("Study Mode")
                .font(.title2)
                .padding()
            
            Text("Study features coming soon")
                .foregroundColor(.secondary)
        }
        .navigationTitle("Study")
    }
}

#Preview {
    NavigationStack {
        StudyView()
    }
}
