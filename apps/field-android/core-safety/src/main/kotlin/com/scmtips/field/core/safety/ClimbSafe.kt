package com.scmtips.field.core.safety

/**
 * Climb-Safe Mode Controller and Structure Presence Manager (Task T4.043 / FR4.045 / TC4.141).
 *
 * Rules:
 * - Activates automatically when altitude exceeds baseline + 2.0 m or on a climb edge.
 * - Disabling climb-safe is refused while on structure; the disable control is hidden then.
 */
class ClimbSafeController(
    private val baselineAltitudeM: Double = 0.0,
    private val activationThresholdM: Double = 2.0,
    private val groundReturnM: Double = 0.5,
) {
    var isClimbSafeActive: Boolean = false
        private set

    var isOnStructure: Boolean = false
        private set

    val isDisableAllowed: Boolean
        get() = !isOnStructure

    /**
     * On structure is entered above baseline + 2 m or on a climb edge, and left only when back
     * within 0.5 m of the baseline and off the climb edge (hysteresis: the bottom of a ladder is
     * still on structure on the way down).
     */
    fun updateAltitude(altitudeM: Double, isClimbEdge: Boolean = false): Boolean {
        val heightAboveGround = altitudeM - baselineAltitudeM
        if (heightAboveGround > activationThresholdM || isClimbEdge) {
            isOnStructure = true
        } else if (heightAboveGround <= groundReturnM) {
            isOnStructure = false
        }
        if (isOnStructure) isClimbSafeActive = true
        return isClimbSafeActive
    }

    /**
     * Manual disable attempt: permitted ONLY if not on structure.
     */
    fun attemptDisable(): Boolean {
        if (isOnStructure) {
            // Cannot disable on structure
            return false
        }
        isClimbSafeActive = false
        return true
    }

    fun forceActivate() {
        isClimbSafeActive = true
    }
}
