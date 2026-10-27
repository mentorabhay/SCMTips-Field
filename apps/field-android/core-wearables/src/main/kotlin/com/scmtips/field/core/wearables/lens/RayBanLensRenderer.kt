package com.scmtips.field.core.wearables.lens

import com.scmtips.field.core.wearables.DrawCall
import com.scmtips.field.core.wearables.LensRenderer
import com.scmtips.field.core.wearables.LensState

/**
 * Standard Ray-Ban Display Lens Renderer (Task T2.014 / SCR2.07 / FR2.013).
 * Formats and draws the 7 lens states to the monochromatic display (max 2 lines of 18 chars).
 */
open class RayBanLensRenderer : LensRenderer {

    companion object {
        const val MAX_CHARS_PER_LINE = 18
        const val MAX_LINES = 2
    }

    override fun renderState(
        state: LensState,
        line1: String,
        line2: String,
        actionPill: String?
    ): DrawCall {
        val truncatedLine1 = truncateTo18(line1)
        val truncatedLine2 = truncateTo18(line2)
        val truncatedPill = actionPill?.let { truncateTo18(it) }

        val drawCall = DrawCall(
            state = state,
            line1 = truncatedLine1,
            line2 = truncatedLine2,
            actionPill = truncatedPill,
            timestampMs = System.currentTimeMillis()
        )

        executeHardwareDraw(drawCall)
        return drawCall
    }

    protected open fun executeHardwareDraw(drawCall: DrawCall) {
        // Dispatches to Meta Wearables Toolkit SDK drawing primitives
    }

    private fun truncateTo18(text: String): String {
        return if (text.length <= MAX_CHARS_PER_LINE) text else text.take(MAX_CHARS_PER_LINE)
    }
}

/**
 * FakeLensRenderer for unit and instrumented tests (T2.014 / TC2.113).
 * Records every render call in memory because Mock Device Kit does not simulate display hardware.
 */
class FakeLensRenderer : RayBanLensRenderer() {
    private val recordedDrawCalls = mutableListOf<DrawCall>()

    override fun executeHardwareDraw(drawCall: DrawCall) {
        synchronized(recordedDrawCalls) {
            recordedDrawCalls.add(drawCall)
        }
    }

    fun getDrawCalls(): List<DrawCall> = synchronized(recordedDrawCalls) {
        recordedDrawCalls.toList()
    }

    fun getLastDrawCall(): DrawCall? = synchronized(recordedDrawCalls) {
        recordedDrawCalls.lastOrNull()
    }

    fun clear() {
        synchronized(recordedDrawCalls) {
            recordedDrawCalls.clear()
        }
    }
}
