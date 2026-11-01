package com.scmtips.field.app.decisions

import com.scmtips.field.app.jobs.Speaker
import com.scmtips.field.feature.decisions.api.NextItem
import com.scmtips.field.core.wearables.AudioOut
import com.scmtips.field.core.wearables.EarconCue
import com.scmtips.field.feature.decisions.brief.SpokenBrief
import com.scmtips.field.feature.decisions.flow.DecisionCard
import com.scmtips.field.feature.decisions.flow.DecisionDisplay
import com.scmtips.field.feature.decisions.flow.FlowState
import com.scmtips.field.feature.decisions.flow.Outcome
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withTimeoutOrNull

/**
 * The app's text-to-speech as the approver flow's [AudioOut]: [playSpeech] queues the words on the
 * phone's TTS (which plays on the glasses' open-ear speakers when they are the Bluetooth audio device,
 * else the phone speaker) and returns when the TTS reports the queue spoken, so the flow listens only
 * after its words are out. A TTS that never reports is waited for at most [estimateMs].
 */
class SpeechWaiter(
    private val out: Speaker,
    private val signals: TtsSignals,
    private val estimateMs: (String) -> Long = { (2_000 + it.length * 90L).coerceAtMost(60_000) },
    private val settleMs: Long = 250,
) : AudioOut {
    override suspend fun playSpeech(text: String, flushQueue: Boolean) {
        if (text.isBlank()) return
        val before = signals.quiet.value
        if (flushQueue) out.say(text) else out.queue(text)
        withTimeoutOrNull(estimateMs(text)) {
            signals.quiet.first { it > before }
            while (true) { // another utterance may follow straight on: wait until the TTS stays quiet
                delay(settleMs)
                if (!signals.speaking.value) break
                signals.speaking.first { !it }
            }
        }
    }

    override suspend fun playEarcon(cue: EarconCue) = out.earcon(cue)

    override fun stopAudio() = Unit
}

/** What the TTS reports: speaking now, and how many times it went quiet (FieldController feeds both). */
class TtsSignals {
    private val _speaking = MutableStateFlow(false)
    private val _quiet = MutableStateFlow(0L)
    val speaking: StateFlow<Boolean> = _speaking.asStateFlow()
    val quiet: StateFlow<Long> = _quiet.asStateFlow()

    fun onSpeaking(on: Boolean) {
        _speaking.value = on
        if (!on) _quiet.value = _quiet.value + 1
    }
}

/**
 * The decision card on the phone (Ray-Ban Meta Gen 2 has no display). Nothing is shown in audio-only
 * mode ([visible] false): the flow is then voice only.
 */
class PhoneCardDisplay(private val visible: () -> Boolean) : DecisionDisplay {
    private val _card = MutableStateFlow<DecisionCard?>(null)
    val card: StateFlow<DecisionCard?> = _card.asStateFlow()
    private var onButton: ((String) -> Unit)? = null

    override suspend fun show(card: DecisionCard, onButton: (String) -> Unit): Boolean {
        if (!visible()) return false
        this.onButton = onButton
        _card.value = card
        return true
    }

    override suspend fun clear() {
        onButton = null
        _card.value = null
    }

    /** A button on the phone card; false when no card is up (a stale tap). */
    fun press(id: String): Boolean {
        val b = onButton ?: return false
        if (_card.value?.buttons?.none { it.id == id } != false) return false
        b(id)
        return true
    }
}

/** Everything the phone shows about decisions (Today's card and the review screen). */
data class DecisionsView(
    /** Null until asked; the count of decisions waiting for this approver. */
    val waiting: Int? = null,
    val reviewing: Boolean = false,
    val state: String = "",
    val card: DecisionCard? = null,
    val listening: Boolean = false,
    val briefSource: String? = null,
    val stepUp: StepUpAsk? = null,
    val last: String? = null,
    /**
     * M5-U06: the core's next decision as `GET /v1/wearable/next` last answered it when the waiting count was
     * refreshed (title, options with their titles and amounts, deadline); null when nothing waits or it was not asked.
     * Drawn only (the Approvals home's card, the option cards); the review fetches its own item as before.
     */
    val next: NextItem? = null,
)

data class StepUpAsk(val retryMessage: String?)

object DecisionText {
    /** "1 decision waiting. Say decisions to hear it." (the work session's announcement). */
    fun waiting(n: Int): String? = when {
        n <= 0 -> null
        n == 1 -> "1 decision is waiting for you. Say decisions to hear it."
        else -> "$n decisions are waiting for you. Say decisions to hear the first."
    }

    fun chip(n: Int?): String = when (n) {
        null -> "Decisions: checking…"
        0 -> "Nothing waiting for your approval"
        1 -> "1 decision waiting"
        else -> "$n decisions waiting"
    }

    fun state(s: FlowState): String = when (s) {
        FlowState.Idle -> ""
        FlowState.Fetching -> "Getting the next decision…"
        is FlowState.Presenting -> if (s.briefSource == SpokenBrief.MODEL) "Speaking the brief" else "Speaking the brief (SCMTIPS template)"
        FlowState.Listening -> "Listening · say approve option one or two, reject, or repeat"
        is FlowState.Sending -> "Sending “${s.transcript}”"
        FlowState.AwaitingStepUp -> "Verify on this phone"
        is FlowState.Finished -> when (s.outcome) {
            Outcome.EXECUTED -> "Committed"
            Outcome.CANCELLED -> "Cancelled · nothing changed"
            Outcome.NOTHING_WAITING -> "Nothing is waiting"
            Outcome.ABANDONED -> "Stopped · nothing changed"
            Outcome.ENDED -> "Ended"
        }
        FlowState.NeedsSignIn -> "Sign in again"
        is FlowState.Failed -> "SCMTIPS: ${s.message}"
    }
}
