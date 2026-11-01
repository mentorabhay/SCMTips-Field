package com.scmtips.field.app.ui.theme

import androidx.compose.runtime.staticCompositionLocalOf

/**
 * True when Android's "Remove animations" is on (Settings.Global.ANIMATOR_DURATION_SCALE == 0, read in
 * MainActivity.onResume into AppUi.shell.reduceMotion; AppRoot provides it). Hint animations draw one still frame
 * when it is true (docs/design/M5_UI_CONTRACT.md §5).
 */
val LocalReduceMotion = staticCompositionLocalOf { false }
