package com.scmtips.field.feature.decisions.flow

import com.scmtips.field.core.voice.asr.AsrCandidate
import com.scmtips.field.core.wearables.AudioOut
import com.scmtips.field.core.wearables.EarconCue
import com.scmtips.field.feature.decisions.api.CommandResponse
import com.scmtips.field.feature.decisions.api.CoreException
import com.scmtips.field.feature.decisions.api.DecisionsApi
import com.scmtips.field.feature.decisions.api.NextItem
import com.scmtips.field.feature.decisions.brief.BriefSource
import com.scmtips.field.feature.decisions.brief.SpokenBrief
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
import java.util.UUID

sealed class FlowState {
    data object Idle : FlowState()
    data object Fetching : FlowState()
    data class Presenting(val title: String, val onDisplay: Boolean, val briefSource: String) : FlowState()
    data object Listening : FlowState()
    data class Sending(val transcript: String) : FlowState()
    data object AwaitingStepUp : FlowState()
    data class Finished(val outcome: Outcome, val say: String?) : FlowState()
    data object NeedsSignIn : FlowState()
    data class Failed(val message: String) : FlowState()
}

enum class Outcome { EXECUTED, CANCELLED, NOTHING_WAITING, ABANDONED, ENDED }

data class FlowConfig(
    val maxTurns: Int = 16,
    val maxMisses: Int = 3,
    val maxStepUpAttempts: Int = 3,
)

/**
 * One voice review of the next waiting decision (ported from the core's wearable app flow/ApprovalFlow,
 * rebuilt on Field's ports). Pure Kotlin; every side effect goes through an interface.
 *
 * GET /wearable/next → spoken brief (field-api, the template on any trouble) → POST /voice/challenges
 * → card on the phone (unless audio-only) + brief spoken (glasses speakers through [AudioOut])
 * → loop { listen ([DecisionEar]: glasses mic in a work session, hold-to-talk otherwise) | button
 *          → confidence-floor check → POST /voice/commands → speak `say`
 *          → readback with step_up_required → phone step-up (GET/POST /auth/step-up) → wait for "confirm" }
 * → executed (confirmed by an earcon and the core's words) / cancelled.
 *
 * The core's grammar decides every intent ("approve option two", "reject", "repeat", "confirm").
 * Approve and reject are read back by the core and executed only by a later "confirm" turn; this class
 * never decides an approval, a permission or whether step-up is needed.
 */
class ApprovalFlow(
    private val api: DecisionsApi,
    private val briefs: BriefSource,
    private val display: DecisionDisplay,
    private val voice: AudioOut,
    private val ear: DecisionEar,
    private val stepUp: StepUpPrompter,
    private val onUnauthorized: suspend () -> Unit,
    private val newIdempotencyKey: () -> String = { UUID.randomUUID().toString() },
    private val config: FlowConfig = FlowConfig(),
) {
    private val _state = MutableStateFlow<FlowState>(FlowState.Idle)
    val state: StateFlow<FlowState> = _state.asStateFlow()

    private val buttons = Channel<String>(Channel.CONFLATED)
    private var displayActive = false

    suspend fun run(): FlowState {
        return try {
            runInner()
        } catch (e: CancellationException) {
            withContext(NonCancellable) { clearDisplay() }
            throw e
        } catch (e: CoreException.Unauthorized) {
            clearDisplay()
            onUnauthorized()
            speakSafely(SAY_SIGN_IN)
            FlowState.NeedsSignIn
        } catch (e: CoreException) {
            clearDisplay()
            runCatching { voice.playEarcon(EarconCue.ERROR) }
            speakSafely(SAY_ERROR)
            FlowState.Failed(e.message ?: "Request failed")
        }.also { _state.value = it }
    }

    private suspend fun runInner(): FlowState {
        _state.value = FlowState.Fetching
        val item = api.next()
        if (item == null) {
            speak(SAY_NOTHING)
            return FlowState.Finished(Outcome.NOTHING_WAITING, SAY_NOTHING)
        }
        // The brief first: the challenge's nonce has a short life and must not be spent waiting for a model.
        val brief = spokenBrief(item)
        val challenge = api.createChallenge(item.decisionId)
        val floor = challenge.confidenceFloor

        displayActive = show(CardFormatter.decisionCard(item))
        _state.value = FlowState.Presenting(item.title, displayActive, brief.source)
        speak(brief.text)

        var nonce = challenge.nonce
        var misses = 0
        repeat(config.maxTurns) {
            _state.value = FlowState.Listening
            val transcript: String = when (val input = nextInput()) {
                is Input.Silence -> {
                    if (++misses >= config.maxMisses) return abandon()
                    speak(SAY_NOTHING_HEARD)
                    null
                }
                is Input.Speech -> {
                    if (input.heard.confidence < floor) {
                        // Too uncertain: never sent to the core. Ask again.
                        if (++misses >= config.maxMisses) return abandon()
                        speak(SAY_REPEAT)
                        null
                    } else {
                        misses = 0
                        input.heard.transcript
                    }
                }
                is Input.Button -> {
                    misses = 0
                    when (val action = CardAction.parse(input.id)) {
                        null -> null
                        CardAction.Reject -> askRejectReason(floor)?.let { CardAction.transcript(CardAction.Reject, it) }
                        else -> CardAction.transcript(action)
                    }
                }
            } ?: return@repeat

            _state.value = FlowState.Sending(transcript)
            val r = api.sendCommand(nonce, transcript, newIdempotencyKey())
            when (r.outcome) {
                CommandResponse.EXECUTED -> {
                    clearDisplay()
                    runCatching { voice.playEarcon(EarconCue.CAPTURED) }
                    speak(r.say)
                    return FlowState.Finished(Outcome.EXECUTED, r.say)
                }
                CommandResponse.CANCELLED -> {
                    clearDisplay()
                    speak(r.say)
                    return FlowState.Finished(Outcome.CANCELLED, r.say)
                }
                CommandResponse.READBACK -> {
                    speak(r.say)
                    if (displayActive) show(CardFormatter.confirmCard(item.title, r.say))
                    if (r.stepUpRequired && !challenge.stepUpWaived) {
                        val verified = runStepUp()
                        speak(if (verified) SAY_STEP_UP_OK else SAY_STEP_UP_FAILED)
                    }
                }
                else -> {
                    speak(r.say)
                    if (displayActive) show(CardFormatter.decisionCard(item))
                }
            }
            nonce = r.next?.nonce ?: run {
                clearDisplay()
                return FlowState.Finished(Outcome.ENDED, r.say)
            }
        }
        return abandon()
    }

    private suspend fun spokenBrief(item: NextItem): SpokenBrief {
        val template = item.spoken.ifBlank { item.card }
        return try {
            briefs.spoken(item.decisionId, template).takeIf { it.text.isNotBlank() } ?: SpokenBrief(template, SpokenBrief.TEMPLATE)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            SpokenBrief(template, SpokenBrief.TEMPLATE)
        }
    }

    /** Phone step-up. True when the core reports a fresh (or waived) step-up. */
    private suspend fun runStepUp(): Boolean {
        _state.value = FlowState.AwaitingStepUp
        val status = api.stepUpStatus()
        if (status.fresh || status.waived) return true
        speak(SAY_CHECK_PHONE)
        var retry: String? = null
        repeat(config.maxStepUpAttempts) {
            val entry = stepUp.requestCode(retry) ?: return false
            try {
                val s = api.stepUp(entry.method, entry.code)
                if (s.fresh || s.waived) return true
            } catch (e: CoreException.InvalidStepUpCode) {
                retry = "That code was not accepted. Try again."
            }
        }
        return false
    }

    private suspend fun askRejectReason(floor: Double): String? {
        speak(SAY_REASON)
        repeat(config.maxMisses) {
            val heard = ear.listen()
            if (heard != null && heard.confidence >= floor) return heard.transcript
            speak(SAY_REPEAT)
        }
        return null
    }

    private suspend fun nextInput(): Input = coroutineScope {
        if (!displayActive) return@coroutineScope ear.listen()?.let { Input.Speech(it) } ?: Input.Silence
        val heard = async { ear.listen() }
        select {
            buttons.onReceive { id -> heard.cancel(); Input.Button(id) }
            heard.onAwait { h -> h?.let { Input.Speech(it) } ?: Input.Silence }
        }
    }

    private suspend fun show(card: DecisionCard): Boolean {
        while (buttons.tryReceive().isSuccess) { /* drop stale presses */ }
        return try {
            display.show(card) { id -> buttons.trySend(id) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            false // display trouble never blocks the audio path
        }
    }

    private suspend fun clearDisplay() {
        if (!displayActive) return
        displayActive = false
        runCatching { display.clear() }
    }

    private suspend fun abandon(): FlowState {
        clearDisplay()
        speak(SAY_ABANDON)
        return FlowState.Finished(Outcome.ABANDONED, SAY_ABANDON)
    }

    private suspend fun speak(text: String) {
        if (text.isNotBlank()) voice.playSpeech(text, flushQueue = false)
    }

    private suspend fun speakSafely(text: String) {
        runCatching { speak(text) }
    }

    private sealed class Input {
        data object Silence : Input()
        data class Speech(val heard: AsrCandidate) : Input()
        data class Button(val id: String) : Input()
    }

    companion object {
        const val SAY_NOTHING = "Nothing is waiting for your approval."
        const val SAY_NOTHING_HEARD = "I didn't hear anything. Please say that again."
        const val SAY_REPEAT = "Sorry, I didn't catch that clearly. Please say it again."
        const val SAY_REASON = "What is the reason for rejecting?"
        const val SAY_CHECK_PHONE = "Please enter your verification code on your phone."
        const val SAY_STEP_UP_OK = "Verified. Say confirm to proceed, or cancel."
        const val SAY_STEP_UP_FAILED = "Verification was not completed. Say cancel to stop, or confirm to try again."
        const val SAY_ABANDON = "Let's stop here. Nothing was changed."
        const val SAY_SIGN_IN = "Your SCMTIPS sign-in has ended. Sign in again on the phone."
        const val SAY_ERROR = "Sorry, SCMTIPS could not complete that request."
    }
}
