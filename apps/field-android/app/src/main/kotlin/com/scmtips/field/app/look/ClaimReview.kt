package com.scmtips.field.app.look

import com.scmtips.field.app.jobs.JobGrammar
import com.scmtips.field.core.voice.asr.AsrCandidate
import com.scmtips.field.core.wearables.AudioOut
import com.scmtips.field.core.wearables.EarconCue
import com.scmtips.field.feature.decisions.flow.CardButton
import com.scmtips.field.feature.decisions.flow.DecisionCard
import com.scmtips.field.feature.decisions.flow.DecisionDisplay
import com.scmtips.field.feature.decisions.flow.DecisionEar
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.withContext

/** What a supervisor can say while claims are read (the phone's own small grammar; the server decides). */
object ClaimGrammar {
    sealed interface Said {
        data object Approve : Said
        data class Reject(val reason: String?) : Said
        data object Confirm : Said
        data object Cancel : Said
        data object Next : Said
        data object Repeat : Said
        data object Stop : Said
    }

    private val APPROVE = setOf("approve", "approve it", "approve claim", "approve the claim", "approve this claim", "approved")
    private val CONFIRM = setOf("confirm", "yes", "yes confirm", "confirm it", "confirmed")
    private val CANCEL = setOf("cancel", "no", "cancel that", "dont", "do not")
    private val NEXT = setOf("next", "next claim", "skip", "the next claim", "another claim")
    private val REPEAT = setOf("repeat", "say again", "again", "read it again")
    private val STOP = setOf("stop", "stop claims", "done", "thats all", "that is all", "finish", "end claims")
    private val REJECT = Regex("^reject(?: it| claim| the claim| this claim)?(?: (?:because|as|for) )?(.*)$")

    fun parse(text: String, confidence: Float): Said? {
        if (confidence < JobGrammar.FLOOR) return null
        val t = JobGrammar.normalise(text)
        return when {
            t.isEmpty() -> null
            t in APPROVE -> Said.Approve
            t in CONFIRM -> Said.Confirm
            t in CANCEL -> Said.Cancel
            t in NEXT -> Said.Next
            t in REPEAT -> Said.Repeat
            t in STOP -> Said.Stop
            else -> REJECT.matchEntire(t)?.let { m -> Said.Reject(m.groupValues[1].trim().ifEmpty { null }) }
        }
    }

    /** The phone card's buttons, as the words they stand for. */
    fun button(id: String): Said? = when (id) {
        APPROVE_ID -> Said.Approve
        REJECT_ID -> Said.Reject(null)
        CONFIRM_ID -> Said.Confirm
        CANCEL_ID -> Said.Cancel
        NEXT_ID -> Said.Next
        STOP_ID -> Said.Stop
        else -> null
    }

    const val APPROVE_ID = "claim.approve"
    const val REJECT_ID = "claim.reject"
    const val CONFIRM_ID = "claim.confirm"
    const val CANCEL_ID = "claim.cancel"
    const val NEXT_ID = "claim.next"
    const val STOP_ID = "claim.stop"
}

sealed class ClaimFlowState {
    data object Idle : ClaimFlowState()
    data object Fetching : ClaimFlowState()
    data class Presenting(val claimId: String, val index: Int, val total: Int) : ClaimFlowState()
    data object Listening : ClaimFlowState()
    data class Sending(val what: String) : ClaimFlowState()
    data class AwaitingConfirm(val claimId: String, val readBack: String) : ClaimFlowState()
    data class Finished(val outcome: ClaimOutcome, val decided: Int) : ClaimFlowState()
    data class Failed(val text: String) : ClaimFlowState()
}

enum class ClaimOutcome { DONE, NOTHING_WAITING, NOT_ALLOWED, STOPPED, ABANDONED }

/**
 * The supervisor's claims by voice (contract §3, M4 approval-flow structure on Field's own API):
 * `GET /v1/claims?status=draft` → each draft read out → "approve" / "reject [reason]" → `/decision`
 * (If-Match: the claim's ETag) → the server's read-back spoken → "confirm" within [confirmWindowMs] →
 * `/confirm` (If-Match: the ETag the decision answered; body {words}) → the result spoken → the next draft.
 * The claims endpoints are called directly; the assistant's server-side claim intents are not used. "next claim" skips, "repeat" reads again, "stop" ends. Nothing is approved without the
 * spoken (or tapped) confirm; a late or missing confirm changes nothing. Sending to the supplier is the
 * server's (simulated) outbox.
 *
 * Reuses feature-decisions' ports: [DecisionEar] (UtteranceInbox: the work session's glasses microphone or
 * hold-to-talk) and [DecisionDisplay] (the phone card); [AudioOut] speaks on the glasses' speakers.
 */
class ClaimReview(
    private val client: LookClient,
    private val voice: AudioOut,
    private val ear: DecisionEar,
    private val display: DecisionDisplay,
    private val clock: () -> Long = System::currentTimeMillis,
    private val confirmWindowMs: Long = 10_000L,
    private val maxMisses: Int = 3,
) {
    private val _state = MutableStateFlow<ClaimFlowState>(ClaimFlowState.Idle)
    val state: StateFlow<ClaimFlowState> = _state.asStateFlow()
    private val buttons = Channel<String>(Channel.CONFLATED)
    private var shown = false

    /** The newest ETag per claim (If-Match); a 412 drops it so the next decision fetches a fresh one. */
    private val etags = mutableMapOf<String, String>()
    private val stale = mutableSetOf<String>()

    suspend fun run(): ClaimFlowState = try {
        runInner()
    } catch (e: CancellationException) {
        withContext(NonCancellable) { clear() }
        throw e
    }.also { clear(); _state.value = it }

    private suspend fun runInner(): ClaimFlowState {
        _state.value = ClaimFlowState.Fetching
        val claims = when (val r = client.drafts()) {
            ClaimsList.NotAllowed -> { speak(SAY_NOT_ALLOWED); return ClaimFlowState.Finished(ClaimOutcome.NOT_ALLOWED, 0) }
            is ClaimsList.Failed -> { voice.playEarcon(EarconCue.ERROR); speak("Claims could not be fetched. ${r.text}"); return ClaimFlowState.Failed(r.text) }
            is ClaimsList.Ok -> r.claims
        }
        if (claims.isEmpty()) { speak(SAY_NONE); return ClaimFlowState.Finished(ClaimOutcome.NOTHING_WAITING, 0) }
        var decided = 0
        var i = 0
        var misses = 0
        present(claims[i], i, claims.size)
        while (i < claims.size) {
            val c = claims[i]
            _state.value = ClaimFlowState.Listening
            val said = when (val input = nextInput()) {
                is Input.Said -> input.said
                Input.Silence, Input.Unclear -> {
                    if (++misses >= maxMisses) { speak(SAY_ABANDON); return ClaimFlowState.Finished(ClaimOutcome.ABANDONED, decided) }
                    speak(if (input == Input.Silence) SAY_NOTHING_HEARD else SAY_OPTIONS)
                    continue
                }
            }
            misses = 0
            when (said) {
                ClaimGrammar.Said.Repeat -> present(c, i, claims.size)
                ClaimGrammar.Said.Stop -> { speak(SAY_STOPPED); return ClaimFlowState.Finished(ClaimOutcome.STOPPED, decided) }
                ClaimGrammar.Said.Next -> {
                    i += 1
                    if (i < claims.size) present(claims[i], i, claims.size)
                }
                ClaimGrammar.Said.Confirm -> speak("Say approve or reject first.")
                ClaimGrammar.Said.Cancel -> speak("Nothing to cancel. $SAY_OPTIONS")
                ClaimGrammar.Said.Approve, is ClaimGrammar.Said.Reject -> {
                    val approve = said == ClaimGrammar.Said.Approve
                    when (decide(c, approve, (said as? ClaimGrammar.Said.Reject)?.reason)) {
                        Decided.YES -> { decided += 1; i += 1; if (i < claims.size) present(claims[i], i, claims.size) }
                        Decided.NO -> present(c, i, claims.size)
                        Decided.NOT_ALLOWED -> { speak(SAY_NOT_ALLOWED); return ClaimFlowState.Finished(ClaimOutcome.NOT_ALLOWED, decided) }
                    }
                }
            }
        }
        speak(if (decided > 0) "That was the last claim." else "No more claims.")
        return ClaimFlowState.Finished(ClaimOutcome.DONE, decided)
    }

    private enum class Decided { YES, NO, NOT_ALLOWED }

    /** One decision: the server's read-back, then the supervisor's confirm within the window. */
    private suspend fun decide(c: Claim, approve: Boolean, reason: String?): Decided {
        _state.value = ClaimFlowState.Sending(if (approve) "approve" else "reject")
        val etag = etags[c.claimId] ?: c.etag?.takeIf { c.claimId !in stale } ?: client.etag(c.claimId)
            ?: run { speak("This claim could not be read. Try again."); return Decided.NO }
        val readBack = when (val r = client.decide(c.claimId, approve, reason, etag)) {
            is StepResult.Failed -> {
                voice.playEarcon(EarconCue.ERROR)
                if (r.status == 403) return Decided.NOT_ALLOWED
                if (r.status == 412) {
                    etags.remove(c.claimId); stale += c.claimId
                    speak("The claim changed meanwhile. Nothing was decided. Say approve or reject again.")
                } else speak("Not sent. ${r.text}")
                return Decided.NO
            }
            is StepResult.Ok -> r.step
        }
        val confirmEtag = readBack.etag ?: etag
        etags[c.claimId] = confirmEtag
        val asked = clock()
        speak(readBack.say.ifBlank { if (approve) "Approve this claim? Say confirm or cancel." else "Reject this claim? Say confirm or cancel." })
        show(DecisionCard(if (approve) "Approve this claim?" else "Reject this claim?", readBack.say.take(240), listOf(
            CardButton(ClaimGrammar.CONFIRM_ID, "Confirm", primary = true), CardButton(ClaimGrammar.CANCEL_ID, "Cancel"),
        )))
        _state.value = ClaimFlowState.AwaitingConfirm(c.claimId, readBack.say)
        val answer = nextInput()
        val words = (answer as? Input.Said)?.words
        if ((answer as? Input.Said)?.said != ClaimGrammar.Said.Confirm) {
            speak(if (answer == Input.Silence) "No confirm heard. Nothing changed." else "Not confirmed. Nothing changed.")
            return Decided.NO
        }
        if (clock() - asked > confirmWindowMs) {
            speak("Too late to confirm. Nothing changed. Say approve or reject again.")
            return Decided.NO
        }
        _state.value = ClaimFlowState.Sending("confirm")
        return when (val r = client.confirm(c.claimId, confirmEtag, words)) {
            is StepResult.Ok -> {
                r.step.etag?.let { etags[c.claimId] = it }
                voice.playEarcon(EarconCue.CAPTURED)
                speak(r.step.say.ifBlank { if (r.step.status == "approved") "Claim approved." else "Claim rejected." })
                Decided.YES
            }
            is StepResult.Failed -> {
                voice.playEarcon(EarconCue.ERROR)
                etags.remove(c.claimId); stale += c.claimId // the claim is back to draft or changed: fetch again next time
                speak(when {
                    r.code == CONFIRM_EXPIRED || r.status == 422 -> "Too late to confirm. Nothing changed. Say approve or reject again."
                    r.status == 403 -> "Only the supervisor who decided can confirm. Nothing changed."
                    else -> "Not confirmed. ${r.text}"
                })
                Decided.NO
            }
        }
    }

    private suspend fun present(c: Claim, i: Int, n: Int) {
        _state.value = ClaimFlowState.Presenting(c.claimId, i, n)
        val body = sentence(ClaimText.body(c))
        // M5-T05: an authenticity claim names its kind ("Box check"); a look claim's card and words are unchanged.
        val heading = listOfNotNull(c.kindLabel, c.title)
        show(DecisionCard("SAMPLE claim ${i + 1} of $n${heading.joinToString("") { " · $it" }}", body.take(240), listOf(
            CardButton(ClaimGrammar.APPROVE_ID, "Approve", primary = true), CardButton(ClaimGrammar.REJECT_ID, "Reject"),
            CardButton(ClaimGrammar.NEXT_ID, "Next claim"), CardButton(ClaimGrammar.STOP_ID, "Stop"),
        )))
        speak("Claim ${i + 1} of $n. ${heading.joinToString("") { sentence(it) + " " }}$body $SAY_OPTIONS")
    }

    private sealed interface Input {
        data object Silence : Input
        /** Words below the 0.80 floor or outside [ClaimGrammar]: never acted on. */
        data object Unclear : Input
        data class Said(val said: ClaimGrammar.Said, val words: String? = null) : Input
    }

    /** The next words or button press. */
    private suspend fun nextInput(): Input = coroutineScope {
        val heard = async { ear.listen() }
        val r: Any? = if (!shown) heard.await() else select<Any?> {
            buttons.onReceive { id -> heard.cancel(); id }
            heard.onAwait { it }
        }
        when (r) {
            is String -> ClaimGrammar.button(r)?.let { Input.Said(it) } ?: Input.Unclear
            is AsrCandidate -> ClaimGrammar.parse(r.transcript, r.confidence)?.let { Input.Said(it, r.transcript) } ?: Input.Unclear
            else -> Input.Silence
        }
    }

    private suspend fun show(card: DecisionCard) {
        while (buttons.tryReceive().isSuccess) { /* stale presses */ }
        shown = try {
            display.show(card) { id -> buttons.trySend(id) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            false
        }
    }

    private suspend fun clear() {
        if (!shown) return
        shown = false
        runCatching { display.clear() }
    }

    private suspend fun speak(text: String) {
        if (text.isNotBlank()) voice.playSpeech(text, flushQueue = false)
    }

    companion object {
        const val CONFIRM_EXPIRED = "FIELD-CLM-422-CONFIRM-EXPIRED"
        const val SAY_NONE = "No claims are waiting."
        const val SAY_NOT_ALLOWED = "Your role does not decide claims."
        const val SAY_OPTIONS = "Say approve, reject, next claim, or stop."
        const val SAY_NOTHING_HEARD = "I didn't hear anything. Please say that again."
        const val SAY_ABANDON = "Let's stop here. Nothing more was changed."
        const val SAY_STOPPED = "Stopped. Nothing more was changed."
    }
}
