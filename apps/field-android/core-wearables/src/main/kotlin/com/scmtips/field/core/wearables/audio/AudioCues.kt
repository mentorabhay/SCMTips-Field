package com.scmtips.field.core.wearables.audio

import com.scmtips.field.core.wearables.AudioOut
import com.scmtips.field.core.wearables.EarconCue
import com.scmtips.field.core.wearables.LensState

data class AudioCueMapping(
    val earcon: EarconCue?,
    val spokenPhrase: String?,
    val isSilentInWalkingQuiet: Boolean = true
)

/**
 * Maps lens states to earcons and optional spoken phrases for audio-only glasses (Task T2.015 / SCR2.08 / FR2.014).
 * Suppresses spoken phrases during walking-quiet mode except for critical errors.
 */
class AudioCueManager(
    private val audioOut: AudioOut,
    private val isWalkingQuietActive: () -> Boolean = { false }
) {
    companion object {
        val STATE_CUE_MAP = mapOf(
            LensState.READY to AudioCueMapping(
                earcon = null,
                spokenPhrase = null, // Ready is silent
                isSilentInWalkingQuiet = true
            ),
            LensState.MOVING to AudioCueMapping(
                earcon = null,
                spokenPhrase = null, // Moving is silent
                isSilentInWalkingQuiet = true
            ),
            LensState.TIE to AudioCueMapping(
                earcon = EarconCue.CONFIRM_PROMPT,
                spokenPhrase = "Two found. Say left or right.",
                isSilentInWalkingQuiet = true
            ),
            LensState.CAPTURED to AudioCueMapping(
                earcon = EarconCue.CAPTURED,
                spokenPhrase = "Captured",
                isSilentInWalkingQuiet = true
            ),
            LensState.DUPLICATE to AudioCueMapping(
                earcon = EarconCue.DUPLICATE,
                spokenPhrase = "Already counted",
                isSilentInWalkingQuiet = true
            ),
            LensState.OFFLINE_QUEUED to AudioCueMapping(
                earcon = EarconCue.OFFLINE_QUEUED,
                spokenPhrase = "Saved offline",
                isSilentInWalkingQuiet = true
            ),
            LensState.ERROR to AudioCueMapping(
                earcon = EarconCue.ERROR,
                spokenPhrase = "Error. Check display.",
                isSilentInWalkingQuiet = false // Never suppressed, even in walking-quiet mode (SCR2.08)
            )
        )
    }

    suspend fun emitStateCue(state: LensState) {
        val mapping = STATE_CUE_MAP[state] ?: return

        // 1. Play 16-bit PCM earcon (under 300 ms)
        mapping.earcon?.let { earcon ->
            audioOut.playEarcon(earcon)
        }

        // 2. Play spoken phrase if not suppressed
        val walkingQuiet = isWalkingQuietActive()
        val shouldSpeak = mapping.spokenPhrase != null && (!walkingQuiet || !mapping.isSilentInWalkingQuiet)

        if (shouldSpeak) {
            audioOut.playSpeech(mapping.spokenPhrase!!)
        }
    }
}
