package com.scmtips.field.core.capture.safety

/**
 * WalkingQuiet Manager (Task T3.052 / FR3.052 / PR3.10 / TC3.142).
 *
 * Suppresses smart-glasses audio/visual prompts and camera captures
 * when moving at speed > 1.2 m/s inside a forklift or high-traffic zone.
 */
class WalkingQuietManager(
    private val speedThresholdMps: Float = 1.2f,
    private val stationaryReleaseDelayMs: Long = 1500L
) {
    private var inForkliftZone: Boolean = false
    private var currentSpeedMps: Float = 0.0f
    private val queuedPrompts = mutableListOf<String>()

    fun updateZoneState(inZone: Boolean) {
        this.inForkliftZone = inZone
    }

    fun updateSpeed(speedMps: Float) {
        this.currentSpeedMps = speedMps
    }

    fun shouldSuppressPrompts(): Boolean {
        return inForkliftZone && (currentSpeedMps > speedThresholdMps)
    }

    fun handlePrompt(prompt: String): Boolean {
        return if (shouldSuppressPrompts()) {
            queuedPrompts.add(prompt)
            false
        } else {
            true
        }
    }

    fun releaseQueuedPrompts(): List<String> {
        val released = queuedPrompts.toList()
        queuedPrompts.clear()
        return released
    }
}
