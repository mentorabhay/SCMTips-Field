package com.scmtips.field.feature.decisions.flow

import com.scmtips.field.core.voice.asr.AsrCandidate
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withTimeoutOrNull

/** A card with buttons: on the phone screen (Ray-Ban Meta Gen 2 has no display), and the HUD simulator. */
data class DecisionCard(val title: String, val body: String, val buttons: List<CardButton>)

data class CardButton(val id: String, val label: String, val primary: Boolean = false)

/**
 * Where the decision card is shown. [show] returns false when nothing can be shown (audio-only mode):
 * then the flow is voice only and offers no buttons. [onButton] gets a [CardButton.id].
 */
interface DecisionDisplay {
    suspend fun show(card: DecisionCard, onButton: (String) -> Unit): Boolean
    suspend fun clear()
}

/**
 * The approver's next utterance as a core-voice candidate (transcript + recogniser confidence), or null
 * when nothing was heard in time. The app feeds it from the work session's microphone (the glasses) or
 * from the phone's hold-to-talk button.
 */
fun interface DecisionEar {
    suspend fun listen(): AsrCandidate?
}

/**
 * The bridge from the app's push-style recognisers to the flow's pull-style [listen]: utterances are
 * [offer]ed as they are recognised; [listen] takes the next one heard after it started (anything heard
 * earlier, e.g. while the brief was being spoken, is dropped) or null after [timeoutMs].
 */
class UtteranceInbox(private val timeoutMs: () -> Long) : DecisionEar {
    private val words = Channel<AsrCandidate>(Channel.CONFLATED)
    private val _waiting = MutableStateFlow(false)

    /** True while the flow waits for words (the phone shows "Listening"). */
    val waiting: StateFlow<Boolean> = _waiting.asStateFlow()

    /** Returns true when the words were taken (a review is listening or about to). */
    fun offer(text: String, confidence: Float): Boolean {
        val t = text.trim()
        if (t.isEmpty()) return false
        return words.trySend(AsrCandidate(t, confidence)).isSuccess
    }

    override suspend fun listen(): AsrCandidate? {
        while (words.tryReceive().isSuccess) { /* stale words */ }
        _waiting.value = true
        return try {
            withTimeoutOrNull(timeoutMs()) { words.receive() }
        } finally {
            _waiting.value = false
        }
    }
}
