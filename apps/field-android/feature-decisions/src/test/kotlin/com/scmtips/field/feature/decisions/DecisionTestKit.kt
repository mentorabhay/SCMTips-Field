package com.scmtips.field.feature.decisions

import com.scmtips.field.core.voice.asr.AsrCandidate
import com.scmtips.field.core.wearables.AudioOut
import com.scmtips.field.core.wearables.EarconCue
import com.scmtips.field.feature.decisions.api.Band
import com.scmtips.field.feature.decisions.api.Challenge
import com.scmtips.field.feature.decisions.api.CommandResponse
import com.scmtips.field.feature.decisions.api.CoreCredentials
import com.scmtips.field.feature.decisions.api.CoreException
import com.scmtips.field.feature.decisions.api.CoreHttp
import com.scmtips.field.feature.decisions.api.DecisionRef
import com.scmtips.field.feature.decisions.api.DecisionsApi
import com.scmtips.field.feature.decisions.api.DeviceSessionInfo
import com.scmtips.field.feature.decisions.api.HttpCall
import com.scmtips.field.feature.decisions.api.HttpReply
import com.scmtips.field.feature.decisions.api.ItemOption
import com.scmtips.field.feature.decisions.api.NextItem
import com.scmtips.field.feature.decisions.api.NextTurn
import com.scmtips.field.feature.decisions.api.PhotoEvidence
import com.scmtips.field.feature.decisions.api.PhotoUpload
import com.scmtips.field.feature.decisions.api.Problem
import com.scmtips.field.feature.decisions.api.StepUpMethod
import com.scmtips.field.feature.decisions.api.StepUpStatus
import com.scmtips.field.feature.decisions.brief.BriefSource
import com.scmtips.field.feature.decisions.brief.SpokenBrief
import com.scmtips.field.feature.decisions.flow.DecisionCard
import com.scmtips.field.feature.decisions.flow.DecisionDisplay
import com.scmtips.field.feature.decisions.flow.DecisionEar
import com.scmtips.field.feature.decisions.flow.StepUpEntry
import com.scmtips.field.feature.decisions.flow.StepUpPrompter
import kotlinx.coroutines.awaitCancellation
import kotlinx.serialization.json.JsonObject
import java.io.IOException
import java.util.Collections

// Test doubles for the approver flow (test code only; ported from the core's wearable app sharedTest).
// Fixture labels only: no real company or person names.

object DecisionFixtures {
    const val DECISION_ID = "11111111-1111-4111-8111-111111111111"
    const val OPTION_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    const val OPTION_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    fun item(card: String = "Magnet supplier A is 6 days late on part 4471. Option A expedites by air; option B qualifies supplier B.") = NextItem(
        decisionId = DECISION_ID,
        title = "Late inbound from supplier A",
        card = card,
        spoken = "Supplier A is six days late. Option A: air freight, twelve thousand. Option B: supplier B, nine thousand, two weeks. Say approve option A, approve option B, or reject.",
        options = listOf(
            ItemOption("A", OPTION_A, "Expedite by air", "12,000", "-3,000"),
            ItemOption("B", OPTION_B, "Qualify supplier B", "9,000", "-1,500"),
        ),
        band = Band("Over 10k", stepUp = true, approvers = 1),
        deadlineAt = "2026-11-03T17:00:00Z",
        waiting = 2,
    )

    fun challenge(floor: Double = 0.6, waived: Boolean = false) = Challenge(
        nonce = "n1", decisionId = DECISION_ID, expiresAt = "2026-11-03T12:05:00Z", ttlSeconds = 300, turn = 1,
        status = "open", title = "Late inbound from supplier A", brief = "brief", confidenceFloor = floor, stepUpWaived = waived,
    )

    fun response(outcome: String, say: String, next: String?, stepUp: Boolean = false, status: String = "open") = CommandResponse(
        outcome = outcome,
        say = say,
        stepUpRequired = stepUp,
        next = next?.let { NextTurn(it, null, 0) },
        decision = DecisionRef(DECISION_ID, status, null),
        approvalId = if (outcome == CommandResponse.EXECUTED) "99999999-9999-4999-8999-999999999999" else null,
    )
}

/** Scripted core. [onCommand] maps (nonce, transcript) to the core's answer. */
class ScriptedDecisionsApi(
    var nextItem: NextItem? = DecisionFixtures.item(),
    var challenge: Challenge = DecisionFixtures.challenge(),
    var onCommand: (nonce: String, transcript: String) -> CommandResponse = { _, _ -> error("unexpected command") },
) : DecisionsApi {
    val log: MutableList<String> = Collections.synchronizedList(mutableListOf())
    val commands = mutableListOf<Pair<String, String>>()
    val idempotencyKeys = mutableListOf<String>()
    var stepUpFresh = false
    var stepUpWaived = false
    var validCode = "123456"
    val stepUps = mutableListOf<Pair<StepUpMethod, String>>()
    var unauthorizedOn: String? = null

    private fun check(op: String) {
        log += op
        if (unauthorizedOn == op) throw CoreException.Unauthorized(Problem(title = "Unauthorized", status = 401, code = "token_expired"))
    }

    override suspend fun next(): NextItem? { check("next"); return nextItem }
    override suspend fun brief(decisionId: String): JsonObject { check("brief"); return JsonObject(emptyMap()) }
    override suspend fun createChallenge(decisionId: String): Challenge { check("challenge"); return challenge }

    override suspend fun sendCommand(nonce: String, transcript: String, idempotencyKey: String): CommandResponse {
        check("command:$transcript")
        commands += nonce to transcript
        idempotencyKeys += idempotencyKey
        return onCommand(nonce, transcript)
    }

    override suspend fun stepUpStatus(): StepUpStatus { check("stepUpStatus"); return StepUpStatus(fresh = stepUpFresh, waived = stepUpWaived) }

    override suspend fun stepUp(method: StepUpMethod, code: String): StepUpStatus {
        check("stepUp")
        stepUps += method to code
        if (code != validCode) throw CoreException.InvalidStepUpCode(Problem(title = "Invalid code", status = 401, code = "invalid_code"))
        stepUpFresh = true
        return StepUpStatus(fresh = true, method = method.wire, verifiedAt = "2026-11-03T12:01:00Z")
    }

    override suspend fun uploadPhoto(upload: PhotoUpload): PhotoEvidence { check("uploadPhoto"); return PhotoEvidence("e1", upload.subjectKind.wire, upload.subjectId, upload.label) }
    override suspend fun sessions(): List<DeviceSessionInfo> { check("sessions"); return emptyList() }
    override suspend fun revoke(sessionId: String) { check("revoke") }
}

/** Speech out: records what was spoken (in order) and the earcons. */
class RecordingVoice : AudioOut {
    val spoken: MutableList<String> = Collections.synchronizedList(mutableListOf())
    val earcons = mutableListOf<EarconCue>()
    override suspend fun playEarcon(cue: EarconCue) { earcons += cue }
    override suspend fun playSpeech(text: String, flushQueue: Boolean) { spoken += text }
    override fun stopAudio() {}
}

/** The phone card. When not [capable] (audio-only mode) nothing is shown and no buttons exist. */
class RecordingDisplay(private val capable: Boolean) : DecisionDisplay {
    val cards = mutableListOf<DecisionCard>()
    var displayCalls = 0
    var cleared = 0
    private var onButton: ((String) -> Unit)? = null

    override suspend fun show(card: DecisionCard, onButton: (String) -> Unit): Boolean {
        if (!capable) return false
        displayCalls++
        cards += card
        this.onButton = onButton
        return true
    }

    override suspend fun clear() { cleared++ }

    fun press(id: String) = onButton?.invoke(id) ?: error("no card on display")
}

sealed class Step {
    data class Say(val text: String, val confidence: Float = 0.95f) : Step()
    data object Silence : Step()

    /** Presses a card button while the flow is listening (the listen itself never returns). */
    data class Press(val id: String) : Step()
}

class ScriptedEar(private val display: RecordingDisplay?, vararg steps: Step) : DecisionEar {
    private val steps = ArrayDeque(steps.toList())
    var calls = 0

    override suspend fun listen(): AsrCandidate? {
        calls++
        return when (val s = steps.removeFirstOrNull() ?: error("listener script exhausted")) {
            is Step.Say -> AsrCandidate(s.text, s.confidence)
            Step.Silence -> null
            is Step.Press -> {
                display!!.press(s.id)
                awaitCancellation()
            }
        }
    }
}

class ScriptedStepUp(vararg entries: StepUpEntry?) : StepUpPrompter {
    private val queue = ArrayDeque(entries.toList())
    val prompts = mutableListOf<String?>()
    override suspend fun requestCode(retryMessage: String?): StepUpEntry? {
        prompts += retryMessage
        return queue.removeFirstOrNull()
    }
}

/** The spoken-brief source: the template as is, or a scripted model text. */
class ScriptedBriefs(private val modelText: String? = null) : BriefSource {
    val asked = mutableListOf<Pair<String, String>>()
    override suspend fun spoken(decisionId: String, templateText: String): SpokenBrief {
        asked += decisionId to templateText
        return modelText?.let { SpokenBrief(it, SpokenBrief.MODEL) } ?: SpokenBrief(templateText, SpokenBrief.TEMPLATE)
    }
}

/** The network as a script: records every call, answers from a queue (an [IOException] entry fails the call). */
class ScriptedHttp : CoreHttp {
    val calls = mutableListOf<HttpCall>()
    private val replies = ArrayDeque<Any>()

    fun reply(status: Int, body: String = "") { replies += HttpReply(status, body) }
    fun fail(message: String = "connect timed out") { replies += IOException(message) }

    override suspend fun execute(call: HttpCall): HttpReply {
        calls += call
        return when (val r = replies.removeFirstOrNull() ?: error("no scripted reply for ${call.method} ${call.url}")) {
            is HttpReply -> r
            is IOException -> throw r
            else -> error("bad script entry")
        }
    }
}

class FixedCredentials(override val deviceId: String = "3f1c2a9e-5b7d-4c11-9e2f-0a1b2c3d4e5f", override var token: String? = "scmw_test_token") : CoreCredentials
