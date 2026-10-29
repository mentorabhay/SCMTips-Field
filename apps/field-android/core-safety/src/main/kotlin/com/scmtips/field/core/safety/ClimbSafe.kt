package com.scmtips.field.core.safety

/**
 * Climb-Safe Mode Controller and Structure Presence Manager (Task T4.043 / FR4.045 / TC4.141).
 *
 * Rules:
 * - Activates automatically when altitude exceeds baseline + 2.0 m or on a climb edge.
 * - Disabling climb-safe is strictly locked and forbidden while on structure (altitude > 2.0 m).
 */
class ClimbSafeController(
    private val baselineAltitudeM: Double = 0.0,
    private val activationThresholdM: Double = 2.0,
) {
    var isClimbSafeActive: Boolean = false
        private set

    var isOnStructure: Boolean = false
        private set

    val isDisableAllowed: Boolean
        get() = !isOnStructure

    fun updateAltitude(altitudeM: Double, isClimbEdge: Boolean = false): Boolean {
        val heightAboveGround = altitudeM - baselineAltitudeM
        isOnStructure = heightAboveGround > activationThresholdM || isClimbEdge

        // Automatic activation rule (FR4.045)
        if (isOnStructure && !isClimbSafeActive) {
            isClimbSafeActive = true
        }

        // Auto deactivation only when back on ground
        if (heightAboveGround <= 0.5 && !isClimbEdge) {
            isOnStructure = false
        }

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
