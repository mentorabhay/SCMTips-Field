package com.scmtips.field.core.wearables.audio

import com.scmtips.field.core.wearables.AudioOut
import com.scmtips.field.core.wearables.EarconCue
import com.scmtips.field.core.wearables.LensState

data class AudioCueMapping(
    val earcon: EarconCue?,
    val spokenPhrase: String?,
    val isSilentInWalkingQuiet: Boolean = true,
)

/**
 * Audio-only cue set for glasses without a display, e.g. Ray-Ban Meta Gen 2 (T2.015; FR2.014; SCR2.08).
 *
 * Ready and moving are silent. Tie, duplicate, offline-queued and error carry the SCR2.08 phrases;
 * captured is an earcon only. In walking-quiet mode phrases are suppressed except for errors.
 */
class AudioCueManager(
    private val audioOut: AudioOut,
    private val isWalkingQuietActive: () -> Boolean = { false },
) {
    companion object {
        val STATE_CUE_MAP: Map<LensState, AudioCueMapping> = mapOf(
            LensState.READY to AudioCueMapping(earcon = null, spokenPhrase = null),
            LensState.MOVING to AudioCueMapping(earcon = null, spokenPhrase = null),
            LensState.TIE to AudioCueMapping(EarconCue.CONFIRM_PROMPT, "Two items. Left or right?"),
            LensState.CAPTURED to AudioCueMapping(EarconCue.CAPTURED, null),
            LensState.DUPLICATE to AudioCueMapping(EarconCue.DUPLICATE, "Already captured"),
            LensState.OFFLINE_QUEUED to AudioCueMapping(EarconCue.OFFLINE_QUEUED, "Saved offline"),
            LensState.ERROR to AudioCueMapping(EarconCue.ERROR, "Problem. Check phone.", isSilentInWalkingQuiet = false),
        )
    }

    suspend fun emitStateCue(state: LensState) {
        val mapping = STATE_CUE_MAP[state] ?: return
        mapping.earcon?.let { audioOut.playEarcon(it) }
        val phrase = mapping.spokenPhrase ?: return
        if (!isWalkingQuietActive() || !mapping.isSilentInWalkingQuiet) {
            audioOut.playSpeech(phrase)
        }
    }
}
