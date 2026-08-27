import SwiftUI

struct PersonaView: View {
    var body: some View {
        VStack {
            Image(systemName: "person.fill")
                .font(.system(size: 60))
                .foregroundColor(.secondary)
            
            Text("Persona")
                .font(.title2)
                .padding()
            
            Text("Persona management coming soon")
                .foregroundColor(.secondary)
        }
        .navigationTitle("Persona")
    }
}

#Preview {
    NavigationStack {
        PersonaView()
    }
}
