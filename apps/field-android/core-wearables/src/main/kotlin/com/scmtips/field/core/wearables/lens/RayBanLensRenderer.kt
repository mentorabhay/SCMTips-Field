package com.scmtips.field.core.wearables.lens

import com.scmtips.field.core.wearables.DrawCall
import com.scmtips.field.core.wearables.LensRenderer
import com.scmtips.field.core.wearables.LensState

/** SCR2.07 state copy for the Meta Ray-Ban Display lens. */
object LensCopy {
    val STATE_LINE: Map<LensState, String> = mapOf(
        LensState.READY to "Ready",
        LensState.MOVING to "Hold still",
        LensState.TIE to "Left or right?",
        LensState.CAPTURED to "Captured",
        LensState.DUPLICATE to "Already captured",
        LensState.OFFLINE_QUEUED to "Saved offline",
        LensState.ERROR to "Problem - see phone",
    )
}

/**
 * Lens renderer for glasses with a display (T2.014; FR2.013; SCR2.07): at most 2 lines of 18 characters.
 *
 * Text that does not fit on line 1 is word-wrapped onto an empty line 2 before truncation, so the
 * 19-character SCR2.07 error copy renders as "Problem - see" / "phone". The [drawSink] is the toolkit
 * display adapter; it is required, because the display path is UNVERIFIED on hardware (docs/META_FIELD.md)
 * and there is no built-in no-op. Ray-Ban Meta Gen 2 has no display and uses AudioCueManager instead.
 */
open class RayBanLensRenderer(private val drawSink: (DrawCall) -> Unit) : LensRenderer {

    companion object {
        const val MAX_CHARS_PER_LINE = 18
        const val MAX_LINES = 2

        /** Splits [text] at the last space that keeps line 1 within 18 characters. */
        fun wrap(text: String): Pair<String, String> {
            if (text.length <= MAX_CHARS_PER_LINE) return text to ""
            val cut = text.lastIndexOf(' ', MAX_CHARS_PER_LINE)
            if (cut <= 0) return text to ""
            return text.substring(0, cut).trimEnd() to text.substring(cut + 1).trim()
        }
    }

    /** Renders the SCR2.07 copy for [state]. */
    fun renderState(state: LensState): DrawCall = renderState(state, LensCopy.STATE_LINE.getValue(state))

    override fun renderState(
        state: LensState,
        line1: String,
        line2: String,
        actionPill: String?,
    ): DrawCall {
        val (l1, l2) = if (line2.isEmpty()) wrap(line1) else line1 to line2
        val drawCall = DrawCall(
            state = state,
            line1 = l1.take(MAX_CHARS_PER_LINE),
            line2 = l2.take(MAX_CHARS_PER_LINE),
            actionPill = actionPill?.take(MAX_CHARS_PER_LINE),
            timestampMs = System.currentTimeMillis(),
        )
        drawSink(drawCall)
        return drawCall
    }
}
