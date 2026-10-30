package com.scmtips.field.core.safety

import kotlin.math.abs

/**
 * Rest Platform Checkpoints and Barometric Re-calibration (Task T4.042 / FR4.042 / TC4.137).
 *
 * Rules:
 * - Matches current altitude to rest platform heights within +/- 1.5 m when STATIONARY.
 * - Shows MSG4.08 "Rest platform L{n}. Clip in before you continue." (platform name is e.g. "L2").
 * - Recalibrates barometric baseline to prevent weather pressure drift.
 */
data class RestPlatform(
    val id: String,
    val name: String,
    val heightM: Double,
)

data class CheckpointDetection(
    val platform: RestPlatform,
    val measuredAltitudeM: Double,
    val message: String,
    val recalibratedBaselineM: Double,
)

class RestPlatformDetector(
    private val platforms: List<RestPlatform>,
    private val toleranceM: Double = 1.5,
) {
    private val visitedPlatformIds = mutableSetOf<String>()
    var currentBaselineM: Double = 0.0

    fun evaluate(
        currentState: ClimbState,
        currentAltitudeM: Double,
        currentPressureHpa: Double? = null,
    ): CheckpointDetection? {
        if (currentState != ClimbState.STATIONARY) {
            return null
        }

        // Find matching platform within tolerance
        val match = platforms.firstOrNull { platform ->
            abs(currentAltitudeM - platform.heightM) <= toleranceM
        } ?: return null

        // Avoid re-triggering repeatedly while resting on same platform
        if (visitedPlatformIds.contains(match.id)) {
            return null
        }

        visitedPlatformIds.add(match.id)

        // Re-calibrate baseline: drift compensation
        val driftM = currentAltitudeM - match.heightM
        currentBaselineM += driftM

        val msg = "Rest platform ${match.name}. Clip in before you continue."

        return CheckpointDetection(
            platform = match,
            measuredAltitudeM = currentAltitudeM,
            message = msg,
            recalibratedBaselineM = currentBaselineM,
        )
    }

    fun reset() {
        visitedPlatformIds.clear()
        currentBaselineM = 0.0
    }
}
