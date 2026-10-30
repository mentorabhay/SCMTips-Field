package com.scmtips.field.feature.towerAudit.lens

data class SectorChecklistState(
    val sectorName: String,
    val levelName: String,
    val capturedCount: Int,
    val expectedCount: Int,
    val missingClasses: List<String>,
    val isHarnessConfirmed: Boolean,
    val loneWorkerTimerMinutes: Int,
    val isClimbing: Boolean,
    val lastUpdateTimestampMs: Long = System.currentTimeMillis()
)

data class LensDisplayOutput(
    val title: String,
    val counterText: String,
    val missingText: String,
    val harnessIconVisible: Boolean,
    val timerText: String,
    val minTextSizeSp: Int = 24,
    val isHighContrast: Boolean = true,
    val rendered: Boolean,
    /** Measured render time; FR4.015 budget is [SectorChecklistRenderer.MAX_UPDATE_BUDGET_MS]. */
    val renderNanos: Long = 0L,
)

/**
 * Lens Sector Checklist Renderer (Task T4.031 / FR4.015, FR4.068 / TC4.113).
 * Renders SCR4.02 when stationary, capping missing classes at 4, enforcing >= 24 sp text,
 * and reporting its render time against the 400 ms update budget (no throw on a slow frame).
 */
class SectorChecklistRenderer {

    companion object {
        const val MAX_MISSING_CLASSES_SHOWN = 4
        const val MAX_UPDATE_BUDGET_MS = 400L
    }

    /**
     * FR4.015 / TC4.113: Evaluates state and generates lens display.
     * Only rendered through climb prompt gate (i.e. when stationary / NOT climbing).
     */
    fun renderChecklist(state: SectorChecklistState): LensDisplayOutput {
        val startNs = System.nanoTime()

        // Climb prompt gate: suppress checklist while climbing
        if (state.isClimbing) {
            return LensDisplayOutput(
                title = "Climbing in progress",
                counterText = "",
                missingText = "Display held while climbing",
                harnessIconVisible = state.isHarnessConfirmed,
                timerText = "${state.loneWorkerTimerMinutes}m",
                rendered = false
            )
        }

        val truncatedMissing = state.missingClasses.take(MAX_MISSING_CLASSES_SHOWN)
        val missingStr = if (truncatedMissing.isEmpty()) {
            "All expected items captured"
        } else {
            "Missing: " + truncatedMissing.joinToString(", ")
        }

        return LensDisplayOutput(
            title = "${state.sectorName} • ${state.levelName}",
            counterText = "${state.capturedCount} of ${state.expectedCount}",
            missingText = missingStr,
            harnessIconVisible = state.isHarnessConfirmed,
            timerText = "${state.loneWorkerTimerMinutes}m",
            minTextSizeSp = 24,
            isHighContrast = true,
            rendered = true,
            renderNanos = System.nanoTime() - startNs,
        )
    }
}
