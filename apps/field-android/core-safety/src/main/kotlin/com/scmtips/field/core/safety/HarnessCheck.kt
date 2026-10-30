package com.scmtips.field.core.safety

import kotlin.math.abs

/**
 * Harness confirmation and capture gate on structure (T4.041 / FR4.040 / FR4.041 / TC4.135 / TC4.136).
 *
 * - Confirmed only when the phrase "harness clipped" (confidence >= 0.80) and a tap on the glasses
 *   touchpad or phone button occur within 10 s of each other, in either order.
 * - Any CLIMBING or UNKNOWN state clears the confirmation and any pending half (phrase or tap), so
 *   a phrase before a climb cannot pair with a tap after it.
 * - An altitude change > 1.5 m from where the confirmation happened clears it.
 * - Captures and staging on structure are accepted only when STATIONARY and confirmed; otherwise
 *   the decision carries MSG4.07.
 * - Every phrase and tap attempt is logged (TC4.136: "both attempts logged").
 */
data class HarnessAttempt(val kind: String, val timestampMs: Long, val accepted: Boolean)

data class CaptureDecision(val accepted: Boolean, val message: String?)

class HarnessCheck(
    private val maxConfirmationWindowMs: Long = 10000L,
    private val maxAltitudeDeviationM: Double = 1.5,
    private val minConfidence: Double = 0.80,
) {
    private var lastVoicePhraseTimeMs: Long? = null
    private var lastTapTimeMs: Long? = null
    private var lastKnownAltitudeM: Double? = null
    private val log = mutableListOf<HarnessAttempt>()

    var isConfirmed: Boolean = false
        private set

    var confirmedAltitudeM: Double? = null
        private set

    val attempts: List<HarnessAttempt>
        get() = log.toList()

    fun onVoicePhrase(phrase: String, confidence: Double, timestampMs: Long, currentAltitudeM: Double? = null): Boolean {
        currentAltitudeM?.let { lastKnownAltitudeM = it }
        val ok = phrase.trim().lowercase() == PHRASE && confidence >= minConfidence
        log.add(HarnessAttempt("voice", timestampMs, ok))
        if (ok) {
            lastVoicePhraseTimeMs = timestampMs
            checkDualConfirmation()
        }
        return ok
    }

    fun onTap(timestampMs: Long, currentAltitudeM: Double? = null): Boolean {
        currentAltitudeM?.let { lastKnownAltitudeM = it }
        log.add(HarnessAttempt("tap", timestampMs, true))
        lastTapTimeMs = timestampMs
        checkDualConfirmation()
        return true
    }

    private fun checkDualConfirmation() {
        val v = lastVoicePhraseTimeMs ?: return
        val t = lastTapTimeMs ?: return
        if (abs(v - t) <= maxConfirmationWindowMs) {
            isConfirmed = true
            confirmedAltitudeM = lastKnownAltitudeM
        }
    }

    /** Safety monitor tick. Returns whether the harness is (still) confirmed. */
    fun update(currentState: ClimbState, currentAltitudeM: Double): Boolean {
        lastKnownAltitudeM = currentAltitudeM
        if (currentState.isClimbingOrFailSafe) {
            clearConfirmation()
            return false
        }
        val base = confirmedAltitudeM
        if (isConfirmed && base == null) {
            confirmedAltitudeM = currentAltitudeM
        } else if (isConfirmed && base != null && abs(currentAltitudeM - base) > maxAltitudeDeviationM) {
            clearConfirmation()
            return false
        }
        return isConfirmed
    }

    fun canCaptureOnStructure(currentState: ClimbState): Boolean =
        currentState == ClimbState.STATIONARY && isConfirmed

    fun decideCapture(currentState: ClimbState, isOnStructure: Boolean): CaptureDecision =
        if (!isOnStructure || canCaptureOnStructure(currentState)) {
            CaptureDecision(true, null)
        } else {
            CaptureDecision(false, MSG_CAPTURE_PAUSED)
        }

    fun clearConfirmation() {
        isConfirmed = false
        confirmedAltitudeM = null
        lastVoicePhraseTimeMs = null
        lastTapTimeMs = null
    }

    companion object {
        const val PHRASE = "harness clipped"
        /** MSG4.07 */
        const val MSG_CAPTURE_PAUSED = "Capture is paused until your harness is confirmed."
    }
}
