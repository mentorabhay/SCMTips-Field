package com.scmtips.field.core.capture.safety

/**
 * Forklift-zone walking-quiet (Task T3.052 / FR3.052 / TC3.142).
 *
 * Suppression starts once the operator has been in a forklift zone moving faster than
 * FIELD_WQ_SPEED_MPS (default 0.5 m/s) for 1 s. While suppressed: prompts are queued instead of
 * shown, capture is disabled, and the lens shows only [PAUSED_MESSAGE]. Suppression ends after
 * FIELD_WQ_RELEASE_S (default 1.5 s) of not moving in the zone (speed at or below the threshold,
 * or out of the zone); the queued prompts are then released in arrival order.
 */
class WalkingQuietManager(
    private val speedThresholdMps: Float = DEFAULT_SPEED_MPS,
    private val engageAfterMs: Long = 1_000L,
    private val stationaryReleaseDelayMs: Long = DEFAULT_RELEASE_MS
) {
    companion object {
        const val DEFAULT_SPEED_MPS = 0.5f // FIELD_WQ_SPEED_MPS
        const val DEFAULT_RELEASE_MS = 1_500L // FIELD_WQ_RELEASE_S
        const val PAUSED_MESSAGE = "Walking. Prompts paused."
    }

    private var movingSinceMs: Long? = null
    private var stillSinceMs: Long? = null
    private var suppressing = false
    private val queuedPrompts = mutableListOf<String>()

    /**
     * Feed the latest zone membership and speed. Returns the prompts released by this update
     * (empty unless suppression just ended).
     */
    fun update(inForkliftZone: Boolean, speedMps: Float, nowMs: Long): List<String> {
        val moving = inForkliftZone && speedMps > speedThresholdMps
        if (moving) {
            stillSinceMs = null
            val since = movingSinceMs ?: nowMs.also { movingSinceMs = it }
            if (!suppressing && nowMs - since >= engageAfterMs) suppressing = true
            return emptyList()
        }
        movingSinceMs = null
        val since = stillSinceMs ?: nowMs.also { stillSinceMs = it }
        if (suppressing && nowMs - since >= stationaryReleaseDelayMs) {
            suppressing = false
            val released = queuedPrompts.toList()
            queuedPrompts.clear()
            return released
        }
        return emptyList()
    }

    fun shouldSuppressPrompts(): Boolean = suppressing

    fun isCaptureAllowed(): Boolean = !suppressing

    /** The only lens text allowed while suppressed, or null when prompts are shown normally. */
    fun lensMessage(): String? = if (suppressing) PAUSED_MESSAGE else null

    /** Returns true when the prompt may be shown now; otherwise it is queued for release. */
    fun handlePrompt(prompt: String): Boolean {
        if (!suppressing) return true
        queuedPrompts.add(prompt)
        return false
    }

    fun queuedCount(): Int = queuedPrompts.size
}
