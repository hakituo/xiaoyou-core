import SwiftUI

struct ShopView: View {
    var body: some View {
        VStack {
            Image(systemName: "cart.fill")
                .font(.system(size: 60))
                .foregroundColor(.secondary)
            
            Text("Shop")
                .font(.title2)
                .padding()
            
            Text("Shop features coming soon")
                .foregroundColor(.secondary)
        }
        .navigationTitle("Shop")
    }
}

#Preview {
    NavigationStack {
        ShopView()
    }
}
