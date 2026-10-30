package com.scmtips.field.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val LightColors = lightColorScheme(
    primary = Primary,
    onPrimary = Color.White,
    secondary = Primary,
    onSecondary = Color.White,
    background = Background,
    onBackground = Ink,
    surface = CardBg,
    onSurface = Ink,
    surfaceVariant = Background,
    onSurfaceVariant = Muted,
    outline = LineStrong,
    error = Danger,
    onError = Color.White,
)

/** Light theme from the design; the system font (Roboto on Android) throughout. */
@Composable
fun SCMTipsFieldTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = LightColors, content = content)
}
