package com.scmtips.field.app.ui.theme

import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

// M5-U design tokens (blueprint "SCMTips Field: Mobile App Redesign Blueprint", A-07; docs/design/M5_UI_CONTRACT.md §5).
val Ink = Color(0xFF15171C)
val Muted = Color(0xFF5B6170)
val Ground = Color(0xFFF5F6F8)
val Surface = Color(0xFFFFFFFF)
val Border = Color(0xFFE4E7EC)
/** Home headers, welcome and glasses setup. */
val Night = Color(0xFF17181C)
/** Task and camera screens. */
val NightTask = Color(0xFF0F1013)
val NightRaised = Color(0xFF23252B)
val NightButton = Color(0xFF2A2C33)
val NightMuted = Color(0xFFC9CCD3)
val Good = Color(0xFF157A3C)
val Warning = Color(0xFFA15C07)
val Danger = Color(0xFFB3261E)
val AccentInk = Color(0xFF5B21B6)
val AccentTint = Color(0xFFEDE9FE)
val BrandStart = Color(0xFF6D28D9)
val BrandEnd = Color(0xFFC2410C)
/** Only the one main button per screen and the Scan tab. */
val BrandGradient = Brush.horizontalGradient(listOf(BrandStart, BrandEnd))
val BrandGradientDiagonal = Brush.linearGradient(listOf(BrandStart, BrandEnd))
val SwitchOff = Color(0xFFC9CDD5)
val RowDivider = Color(0xFFEEF0F3)

// M2 names, kept as aliases of the M5-U tokens so the older screens (and builder C's) compile and match.
val Primary = BrandStart
val PrimaryPressed = AccentInk
val InfoBg = AccentTint
val Background = Ground
val CardBg = Surface
val Line = Border
val LineStrong = SwitchOff
val Divider = RowDivider
val Ink2 = Color(0xFF4B5160)
val Success = Good
val SuccessBg = Color(0xFFE6F4EA)
val SuccessInk = Color(0xFF14532D)
val WarnText = Warning
val WarnBg = Color(0xFFFFF1E6)
val WarnInk = Color(0xFF7C2D12)
val DangerBg = Color(0xFFFDECEA)
val ScanAreaBg = NightTask
val ScanHint = Color(0xFFB7C0C9)
val Toast = Ink

// Climb-safe: dark, high contrast, amber accent.
val ClimbBg = Color(0xFF101418)
val ClimbCard = Color(0xFF18191A)
val ClimbLine = Color(0xFF3A444F)
val ClimbTrack = Color(0xFF2A333D)
val ClimbMuted = Color(0xFFC9D1D9)
val Amber = Color(0xFFF59E0B)
val AmberText = Color(0xFFFCD34D)
