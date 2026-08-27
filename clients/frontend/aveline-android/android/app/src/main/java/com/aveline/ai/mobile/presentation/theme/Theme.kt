@file:Suppress("DEPRECATION")

package com.aveline.ai.mobile.presentation.theme

import android.app.Activity
import android.os.Build
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat

/**
 * Aveline dark color scheme.
 * The app primarily uses dark theme.
 */
private val AvelineDarkColorScheme = darkColorScheme(
    primary = Primary,
    onPrimary = Color.White,
    primaryContainer = SurfaceVariant,
    onPrimaryContainer = TextPrimary,
    
    secondary = InteractiveSecondary,
    onSecondary = Color.White,
    secondaryContainer = SurfaceVariant,
    onSecondaryContainer = TextPrimary,
    
    tertiary = EmotionGreen,
    onTertiary = Color.White,
    tertiaryContainer = SurfaceVariant,
    onTertiaryContainer = TextPrimary,
    
    background = Background,
    onBackground = TextPrimary,
    
    surface = Surface,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceVariant,
    onSurfaceVariant = TextSecondary,
    
    outline = BorderColor,
    outlineVariant = BorderLight,
    
    error = EmotionRed,
    onError = Color.White,
    errorContainer = Color(0xFF3D1F1F),
    onErrorContainer = Color(0xFFFFDAD6),
    
    inverseSurface = SurfaceLight,
    inverseOnSurface = Background,
    inversePrimary = PrimaryVariant
)

/**
 * Aveline light color scheme.
 * Provided for completeness, but the app primarily uses dark theme.
 */
private val AvelineLightColorScheme = lightColorScheme(
    primary = InteractivePrimary,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD0E4FF),
    onPrimaryContainer = Color(0xFF001D36),
    
    secondary = InteractiveSecondary,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE8DEF8),
    onSecondaryContainer = Color(0xFF1D192B),
    
    tertiary = EmotionGreen,
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFD1F8E7),
    onTertiaryContainer = Color(0xFF00210F),
    
    background = Color(0xFFFDFCFF),
    onBackground = Color(0xFF1A1C1E),
    
    surface = Color(0xFFFDFCFF),
    onSurface = Color(0xFF1A1C1E),
    surfaceVariant = Color(0xFFE1E2EC),
    onSurfaceVariant = Color(0xFF43474E),
    
    outline = Color(0xFF73777F),
    outlineVariant = Color(0xFFC3C6CF),
    
    error = EmotionRed,
    onError = Color.White,
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF410002),
    
    inverseSurface = Color(0xFF2F3033),
    inverseOnSurface = Color(0xFFF1F0F4),
    inversePrimary = Color(0xFF9ECAFF)
)

/**
 * Aveline theme composable.
 * 
 * @param darkTheme Whether to use dark theme (defaults to system setting)
 * @param dynamicColor Whether to use dynamic colors (Android 12+)
 * @param content The content to theme
 */
@Composable
fun AvelineTheme(
    darkTheme: Boolean = true, // Always use dark theme by default
    dynamicColor: Boolean = false, // Disable dynamic color to maintain brand identity
    content: @Composable () -> Unit
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> AvelineDarkColorScheme
        else -> AvelineLightColorScheme
    }
    
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = android.graphics.Color.TRANSPARENT
            window.navigationBarColor = android.graphics.Color.TRANSPARENT
            
            val windowInsetsController = WindowCompat.getInsetsController(window, view)
            windowInsetsController.isAppearanceLightStatusBars = false
            windowInsetsController.isAppearanceLightNavigationBars = false
        }
    }
    
    MaterialTheme(
        colorScheme = colorScheme,
        typography = AvelineTypography,
        content = content
    )
}

/**
 * Spacing constants for consistent layout.
 */
object Spacing {
    val xxs = 2.dp
    val xs = 4.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
    val xxl = 32.dp
    val xxxl = 48.dp
}

/**
 * Corner radius constants.
 */
object CornerRadius {
    val small = 4.dp
    val medium = 8.dp
    val large = 12.dp
    val xlarge = 16.dp
    val xxlarge = 24.dp
    val round = 999.dp
}

/**
 * Animation duration constants.
 */
object AnimationDuration {
    const val fast = 150
    const val normal = 300
    const val slow = 500
}

/**
 * Elevation constants.
 */
object Elevation {
    val none = 0.dp
    val low = 2.dp
    val medium = 4.dp
    val high = 8.dp
}
