package com.scmtips.field.core.safety

import kotlin.math.abs

/**
 * Harness Confirmation and Safe Capture Gate (Task T4.041 / FR4.040 / FR4.041 / PR4.05 / TC4.135 / TC4.136).
 *
 * Rules:
 * - Confirms harness ONLY when spoken phrase 'harness clipped' (>= 0.80) and a physical tap occur within 10 s.
 * - Clears confirmation on any CLIMBING or UNKNOWN state, or altitude change > 1.5 m.
 * - Captures and staging on structure accepted ONLY when STATIONARY and harness is confirmed.
 */
class HarnessCheck(
    private val maxConfirmationWindowMs: Long = 10000L, // 10 seconds
    private val maxAltitudeDeviationM: Double = 1.5,     // 1.5 meters
) {
    private var lastVoicePhraseTimeMs: Long? = null
    private var lastVoiceConfidence: Double = 0.0

    private var lastTapTimeMs: Long? = null

    var isConfirmed: Boolean = false
        private set

    var confirmedAltitudeM: Double? = null
        private set

    /**
     * Ingest voice utterance for harness phrase.
     */
    fun onVoicePhrase(phrase: String, confidence: Double, timestampMs: Long): Boolean {
        val normalized = phrase.trim().lowercase()
        if (normalized == "harness clipped" && confidence >= 0.80) {
            lastVoicePhraseTimeMs = timestampMs
            lastVoiceConfidence = confidence
            checkDualConfirmation(timestampMs)
            return true
        }
        return false
    }

    /**
     * Ingest physical tap event on glasses touchpad or phone button.
     */
    fun onTap(timestampMs: Long, currentAltitudeM: Double? = null): Boolean {
        lastTapTimeMs = timestampMs
        checkDualConfirmation(timestampMs, currentAltitudeM)
        return true
    }

    private fun checkDualConfirmation(nowMs: Long, currentAltitudeM: Double? = null) {
        val vTime = lastVoicePhraseTimeMs
        val tTime = lastTapTimeMs

        if (vTime != null && tTime != null) {
            val deltaMs = abs(vTime - tTime)
            if (deltaMs <= maxConfirmationWindowMs) {
                isConfirmed = true
                confirmedAltitudeM = currentAltitudeM
            }
        }
    }

    /**
     * Periodic safety monitor tick checking altitude deviation and climbing state.
     */
    fun update(currentState: ClimbState, currentAltitudeM: Double): Boolean {
        // Clear on climbing or fail-safe unknown
        if (currentState.isClimbingOrFailSafe) {
            if (isConfirmed) {
                clearConfirmation()
            }
            return false
        }

        // Clear if altitude moved > 1.5m from confirmed altitude
        val baseAlt = confirmedAltitudeM
        if (isConfirmed && baseAlt != null) {
            if (abs(currentAltitudeM - baseAlt) > maxAltitudeDeviationM) {
                clearConfirmation()
                return false
            }
        }

        return isConfirmed
    }

    fun canCaptureOnStructure(currentState: ClimbState): Boolean {
        return (currentState == ClimbState.STATIONARY || currentState == ClimbState.GROUND) && isConfirmed
    }

    fun clearConfirmation() {
        isConfirmed = false
        confirmedAltitudeM = null
        lastVoicePhraseTimeMs = null
        lastTapTimeMs = null
    }
}
