package com.scmtips.field.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily

private val LightColors = lightColorScheme(
    primary = BrandStart,
    onPrimary = Color.White,
    secondary = AccentInk,
    onSecondary = Color.White,
    background = Ground,
    onBackground = Ink,
    surface = Surface,
    onSurface = Ink,
    surfaceVariant = Ground,
    onSurfaceVariant = Muted,
    outline = SwitchOff,
    error = Danger,
    onError = Color.White,
)

private val SystemSans: Typography = Typography().let { t ->
    Typography(
        displayLarge = t.displayLarge.copy(fontFamily = FontFamily.SansSerif),
        headlineLarge = t.headlineLarge.copy(fontFamily = FontFamily.SansSerif),
        headlineMedium = t.headlineMedium.copy(fontFamily = FontFamily.SansSerif),
        titleLarge = t.titleLarge.copy(fontFamily = FontFamily.SansSerif),
        titleMedium = t.titleMedium.copy(fontFamily = FontFamily.SansSerif),
        bodyLarge = t.bodyLarge.copy(fontFamily = FontFamily.SansSerif),
        bodyMedium = t.bodyMedium.copy(fontFamily = FontFamily.SansSerif),
        bodySmall = t.bodySmall.copy(fontFamily = FontFamily.SansSerif),
        labelLarge = t.labelLarge.copy(fontFamily = FontFamily.SansSerif),
        labelMedium = t.labelMedium.copy(fontFamily = FontFamily.SansSerif),
    )
}

/** The M5-U light theme: SCMTIPS purple-orange accents, the system sans font throughout (no font files). */
@Composable
fun SCMTipsFieldTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = LightColors, typography = SystemSans, content = content)
}
