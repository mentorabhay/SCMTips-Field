package com.scmtips.field.core.wearables

import com.scmtips.field.core.wearables.audio.AudioCueManager
import com.scmtips.field.core.wearables.lens.LensCopy

/**
 * Routes per-look feedback (FR2.013, FR2.014): the lens on glasses that report a display, the
 * SCR2.08 audio cue set on glasses without one (Ray-Ban Meta Gen 2) or when MDM sets force_audio_only.
 */
class LookFeedback(
    private val session: GlassesSession,
    private val audioCues: AudioCueManager,
    private val forceAudioOnly: () -> Boolean = { false },
) {
    fun usesLens(): Boolean = session.isDisplayAvailable() && !forceAudioOnly()

    suspend fun show(state: LensState) {
        if (usesLens()) {
            session.lensRenderer.renderState(state, LensCopy.STATE_LINE.getValue(state))
        } else {
            audioCues.emitStateCue(state)
        }
    }
}
