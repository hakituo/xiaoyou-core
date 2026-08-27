import SwiftUI

// MARK: - App Colors

struct AppColors {
    // Primary colors
    static let primary = Color("PrimaryColor")
    static let primaryLight = Color("PrimaryColorLight")
    static let primaryDark = Color("PrimaryColorDark")
    
    // Background colors
    static let background = Color("BackgroundColor")
    static let surface = Color("SurfaceColor")
    static let surfaceVariant = Color("SurfaceVariantColor")
    
    // Text colors
    static let textPrimary = Color("TextPrimaryColor")
    static let textSecondary = Color("TextSecondaryColor")
    static let textTertiary = Color("TextTertiaryColor")
    
    // Status colors
    static let success = Color.green
    static let warning = Color.orange
    static let error = Color.red
    static let info = Color.blue
}

// MARK: - Color Assets Extension

extension Color {
    init(_ name: String) {
        self.init(name, bundle: .main)
    }
}
