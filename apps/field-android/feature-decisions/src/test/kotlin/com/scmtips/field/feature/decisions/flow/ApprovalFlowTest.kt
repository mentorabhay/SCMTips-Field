package com.scmtips.field.feature.decisions.flow

import com.scmtips.field.core.wearables.EarconCue
import com.scmtips.field.feature.decisions.DecisionFixtures
import com.scmtips.field.feature.decisions.RecordingDisplay
import com.scmtips.field.feature.decisions.RecordingVoice
import com.scmtips.field.feature.decisions.ScriptedBriefs
import com.scmtips.field.feature.decisions.ScriptedDecisionsApi
import com.scmtips.field.feature.decisions.ScriptedEar
import com.scmtips.field.feature.decisions.ScriptedStepUp
import com.scmtips.field.feature.decisions.Step
import com.scmtips.field.feature.decisions.api.CommandResponse
import com.scmtips.field.feature.decisions.api.CommandResponse.Companion.CANCELLED
import com.scmtips.field.feature.decisions.api.CommandResponse.Companion.CLARIFY
import com.scmtips.field.feature.decisions.api.CommandResponse.Companion.EXECUTED
import com.scmtips.field.feature.decisions.api.CommandResponse.Companion.READBACK
import com.scmtips.field.feature.decisions.api.CommandResponse.Companion.REPEAT
import com.scmtips.field.feature.decisions.api.CoreException
import com.scmtips.field.feature.decisions.api.Problem
import com.scmtips.field.feature.decisions.api.StepUpMethod
import com.scmtips.field.feature.decisions.brief.BriefSource
import com.scmtips.field.feature.decisions.brief.SpokenBrief
import com.scmtips.field.core.wearables.AudioOut
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Ported from the core's wearable app (flow/ApprovalFlowTest), on Field's ports, plus the spoken brief. */
class ApprovalFlowTest {

    private val readbackA = "You are approving option A, expedite by air, twelve thousand. This needs verification. Say confirm."
    private val executedA = "Approved. Option A is committed."

    private fun coreApprovesA(stepUp: Boolean = true): (String, String) -> CommandResponse = { nonce, t ->
        when {
            nonce == "n1" && t == "approve option A" -> DecisionFixtures.response(READBACK, readbackA, "n2", stepUp = stepUp)
            nonce == "n2" && t == "confirm" -> DecisionFixtures.response(EXECUTED, executedA, null, status = "approved")
            else -> error("unexpected $nonce/$t")
        }
    }

    private fun flow(
        api: ScriptedDecisionsApi,
        display: RecordingDisplay,
        voice: RecordingVoice,
        ear: ScriptedEar,
        stepUp: ScriptedStepUp = ScriptedStepUp(),
        briefs: BriefSource = ScriptedBriefs(),
        onUnauthorized: suspend () -> Unit = {},
    ): ApprovalFlow {
        var k = 0
        return ApprovalFlow(api, briefs, display, voice, ear, stepUp, onUnauthorized, newIdempotencyKey = { "key-${++k}" })
    }

    @Test
    fun audioOnly_approveWithStepUp_thenConfirm_executes() = runBlocking {
        val api = ScriptedDecisionsApi(onCommand = coreApprovesA())
        val display = RecordingDisplay(capable = false)
        val voice = RecordingVoice()
        val stepUp = ScriptedStepUp(StepUpEntry(StepUpMethod.TOTP, "123456"))
        val ear = ScriptedEar(display, Step.Say("approve option A", 0.92f), Step.Say("confirm", 0.97f))

        val result = flow(api, display, voice, ear, stepUp).run()

        assertEquals(FlowState.Finished(Outcome.EXECUTED, executedA), result)
        assertEquals(listOf("n1" to "approve option A", "n2" to "confirm"), api.commands)
        assertEquals(listOf("key-1", "key-2"), api.idempotencyKeys)
        // Step-up happened on the phone, before "confirm" was sent.
        assertEquals(listOf(StepUpMethod.TOTP to "123456"), api.stepUps)
        assertTrue(api.log.indexOf("stepUp") < api.log.indexOf("command:confirm"))
        // Audio only: the spoken brief, then the core's own words; committed is confirmed by an earcon and audio.
        assertEquals(DecisionFixtures.item().spoken, voice.spoken.first())
        assertTrue(voice.spoken.contains(readbackA))
        assertEquals(executedA, voice.spoken.last())
        assertEquals(listOf(EarconCue.CAPTURED), voice.earcons)
        assertEquals(0, display.displayCalls)
        assertTrue(display.cards.isEmpty())
    }

    @Test
    fun phoneCard_buttons_approveA_stepUp_confirm_executes() = runBlocking {
        val api = ScriptedDecisionsApi(onCommand = coreApprovesA())
        val display = RecordingDisplay(capable = true)
        val voice = RecordingVoice()
        val stepUp = ScriptedStepUp(StepUpEntry(StepUpMethod.BACKUP_CODE, "123456"))
        val ear = ScriptedEar(display, Step.Press("approve:A"), Step.Press("confirm"))

        val result = flow(api, display, voice, ear, stepUp).run()

        assertEquals(FlowState.Finished(Outcome.EXECUTED, executedA), result)
        // Buttons became phrases the core's grammar understands; the core decided.
        assertEquals(listOf("n1" to "approve option A", "n2" to "confirm"), api.commands)
        assertEquals(listOf(StepUpMethod.BACKUP_CODE to "123456"), api.stepUps)
        val decisionCard = display.cards.first()
        assertEquals(listOf("Approve A", "Approve B", "Reject"), decisionCard.buttons.map { it.label })
        assertTrue(decisionCard.body.length <= 240)
        assertEquals(listOf("Confirm", "Cancel"), display.cards[1].buttons.map { it.label })
        assertEquals(DecisionFixtures.item().spoken, voice.spoken.first())
        assertEquals(executedA, voice.spoken.last())
        assertEquals(1, display.cleared)
    }

    @Test
    fun spokenApproveOptionTwo_isPassedToTheCoreVerbatim() = runBlocking {
        val api = ScriptedDecisionsApi(onCommand = { nonce, t ->
            when {
                nonce == "n1" && t == "approve option two" -> DecisionFixtures.response(READBACK, "Option B. Say confirm.", "n2")
                nonce == "n2" && t == "confirm" -> DecisionFixtures.response(EXECUTED, "Approved. Option B is committed.", null)
                else -> error("unexpected $nonce/$t")
            }
        })
        val d = RecordingDisplay(false)
        val result = flow(api, d, RecordingVoice(), ScriptedEar(d, Step.Say("approve option two"), Step.Say("confirm")), ScriptedStepUp()).run()
        assertEquals(Outcome.EXECUTED, (result as FlowState.Finished).outcome)
        assertEquals(listOf("approve option two", "confirm"), api.commands.map { it.second })
    }

    @Test
    fun theModelBriefIsSpokenWhenFieldApiHasOne_andTheTemplateIsWhatItIsMadeFrom() = runBlocking {
        val briefs = ScriptedBriefs(modelText = "Magnet parts from supplier A are six days late. Air freight costs twelve thousand.")
        val api = ScriptedDecisionsApi(onCommand = { _, _ -> DecisionFixtures.response(CANCELLED, "Cancelled.", null) })
        val d = RecordingDisplay(false)
        val voice = RecordingVoice()
        val f = flow(api, d, voice, ScriptedEar(d, Step.Say("cancel")), briefs = briefs)
        f.run()
        assertEquals(listOf(DecisionFixtures.DECISION_ID to DecisionFixtures.item().spoken), briefs.asked)
        assertEquals("Magnet parts from supplier A are six days late. Air freight costs twelve thousand.", voice.spoken.first())
        // The brief is fetched before the challenge, so the nonce's life is not spent waiting for a model.
        assertEquals(listOf("next", "challenge", "command:cancel"), api.log)
    }

    @Test
    fun aBriefSourceThatFails_speaksTheTemplate() = runBlocking {
        val failing = BriefSource { _, _ -> throw IllegalStateException("boom") }
        val api = ScriptedDecisionsApi(onCommand = { _, _ -> DecisionFixtures.response(CANCELLED, "Cancelled.", null) })
        val d = RecordingDisplay(false)
        val voice = RecordingVoice()
        val f = flow(api, d, voice, ScriptedEar(d, Step.Say("cancel")), briefs = failing)
        f.run()
        assertEquals(DecisionFixtures.item().spoken, voice.spoken.first())
    }

    @Test
    fun presentingSaysWhetherTheBriefIsTheModelsOrTheTemplate() = runBlocking {
        for ((briefs, expected) in listOf(ScriptedBriefs("model text") to SpokenBrief.MODEL, ScriptedBriefs() to SpokenBrief.TEMPLATE)) {
            val api = ScriptedDecisionsApi(onCommand = { _, _ -> DecisionFixtures.response(CANCELLED, "Cancelled.", null) })
            val d = RecordingDisplay(true)
            val states = mutableListOf<FlowState>()
            var f: ApprovalFlow? = null
            val voice = object : AudioOut {
                override suspend fun playEarcon(cue: EarconCue) {}
                override suspend fun playSpeech(text: String, flushQueue: Boolean) { f?.let { states += it.state.value } }
                override fun stopAudio() {}
            }
            f = ApprovalFlow(api, briefs, d, voice, ScriptedEar(d, Step.Say("cancel")), ScriptedStepUp(), {})
            f.run()
            assertEquals(FlowState.Presenting(DecisionFixtures.item().title, true, expected), states.first())
        }
    }

    @Test
    fun card_reject_asksForSpokenReason_thenConfirm() = runBlocking {
        val rejected = "Rejected. The plan goes back to the planner."
        val api = ScriptedDecisionsApi(onCommand = { nonce, t ->
            when {
                nonce == "n1" && t == "reject because the price is above budget" -> DecisionFixtures.response(READBACK, "You are rejecting. Say confirm.", "n2")
                nonce == "n2" && t == "confirm" -> DecisionFixtures.response(EXECUTED, rejected, null, status = "rejected")
                else -> error("unexpected $nonce/$t")
            }
        })
        val display = RecordingDisplay(capable = true)
        val voice = RecordingVoice()
        val ear = ScriptedEar(display, Step.Press("reject"), Step.Say("the price is above budget", 0.9f), Step.Say("confirm", 0.9f))

        val result = flow(api, display, voice, ear).run()

        assertEquals(FlowState.Finished(Outcome.EXECUTED, rejected), result)
        assertTrue(voice.spoken.contains(ApprovalFlow.SAY_REASON))
        assertEquals("reject because the price is above budget", api.commands.first().second)
        assertTrue(api.stepUps.isEmpty())
        assertEquals(rejected, voice.spoken.last())
    }

    @Test
    fun audioOnly_spokenReject_isPassedToTheCoreVerbatim_andCancelEnds() = runBlocking {
        val api = ScriptedDecisionsApi(onCommand = { nonce, t ->
            when {
                nonce == "n1" && t == "reject option B because it is too slow" -> DecisionFixtures.response(READBACK, "Rejecting. Say confirm or cancel.", "n2")
                nonce == "n2" && t == "cancel" -> DecisionFixtures.response(CANCELLED, "Cancelled. Nothing was changed.", null)
                else -> error("unexpected $nonce/$t")
            }
        })
        val display = RecordingDisplay(capable = false)
        val voice = RecordingVoice()
        val ear = ScriptedEar(display, Step.Say("reject option B because it is too slow"), Step.Say("cancel"))

        val result = flow(api, display, voice, ear).run()

        assertEquals(FlowState.Finished(Outcome.CANCELLED, "Cancelled. Nothing was changed."), result)
        assertEquals("Cancelled. Nothing was changed.", voice.spoken.last())
    }

    @Test
    fun repeat_isTheCoresTurn_andSpeaksWhatItSays() = runBlocking {
        val api = ScriptedDecisionsApi(onCommand = { nonce, t ->
            when {
                nonce == "n1" && t == "repeat" -> DecisionFixtures.response(REPEAT, "Supplier A is six days late. Say approve option A, B, or reject.", "n2")
                nonce == "n2" && t == "cancel" -> DecisionFixtures.response(CANCELLED, "Cancelled.", null)
                else -> error("unexpected $nonce/$t")
            }
        })
        val display = RecordingDisplay(capable = true)
        val voice = RecordingVoice()
        val result = flow(api, display, voice, ScriptedEar(display, Step.Say("repeat"), Step.Press("cancel"))).run()
        assertEquals(Outcome.CANCELLED, (result as FlowState.Finished).outcome)
        assertTrue(voice.spoken.contains("Supplier A is six days late. Say approve option A, B, or reject."))
        // The decision card is shown again after a repeat.
        assertEquals(2, display.cards.size)
    }

    @Test
    fun lowConfidence_asksAgain_andSendsNothing() = runBlocking {
        val api = ScriptedDecisionsApi(challenge = DecisionFixtures.challenge(floor = 0.6))
        val display = RecordingDisplay(capable = false)
        val voice = RecordingVoice()
        val ear = ScriptedEar(
            display,
            Step.Say("approve option A", 0.41f), // under the challenge floor
            Step.Say("approve option A", 0.55f),
            Step.Say("a prove option hey", 0.2f),
        )

        val result = flow(api, display, voice, ear).run()

        assertTrue(api.commands.isEmpty())
        assertFalse(api.log.any { it.startsWith("command:") })
        assertEquals(2, voice.spoken.count { it == ApprovalFlow.SAY_REPEAT })
        assertEquals(FlowState.Finished(Outcome.ABANDONED, ApprovalFlow.SAY_ABANDON), result)
    }

    @Test
    fun lowConfidence_thenClear_sendsOnlyTheClearTranscript() = runBlocking {
        val api = ScriptedDecisionsApi(onCommand = coreApprovesA(stepUp = false))
        val display = RecordingDisplay(capable = false)
        val voice = RecordingVoice()
        val ear = ScriptedEar(display, Step.Say("approve option A", 0.3f), Step.Say("approve option A", 0.9f), Step.Say("confirm"))

        val result = flow(api, display, voice, ear).run()

        assertEquals(Outcome.EXECUTED, (result as FlowState.Finished).outcome)
        assertEquals(listOf("n1" to "approve option A", "n2" to "confirm"), api.commands)
        assertEquals(1, voice.spoken.count { it == ApprovalFlow.SAY_REPEAT })
        assertTrue(api.stepUps.isEmpty())
    }

    @Test
    fun unauthorizedOnNext_goesBackToSignIn() = runBlocking {
        val api = ScriptedDecisionsApi().apply { unauthorizedOn = "next" }
        var signIn = 0
        val voice = RecordingVoice()
        val result = flow(api, RecordingDisplay(false), voice, ScriptedEar(null), onUnauthorized = { signIn++ }).run()

        assertEquals(FlowState.NeedsSignIn, result)
        assertEquals(1, signIn)
        assertEquals(listOf(ApprovalFlow.SAY_SIGN_IN), voice.spoken)
    }

    @Test
    fun unauthorizedMidReview_clearsTheCard_andGoesBackToSignIn() = runBlocking {
        val api = ScriptedDecisionsApi().apply { unauthorizedOn = "command:approve option A" }
        val display = RecordingDisplay(capable = true)
        var signIn = 0
        val result = flow(api, display, RecordingVoice(), ScriptedEar(display, Step.Press("approve:A")), onUnauthorized = { signIn++ }).run()

        assertEquals(FlowState.NeedsSignIn, result)
        assertEquals(1, signIn)
        assertEquals(1, display.cleared)
    }

    @Test
    fun executed_speaksTheCoresSayVerbatim() = runBlocking {
        val coreSay = "Approved. Option B is committed; approver B has been notified."
        val api = ScriptedDecisionsApi(onCommand = { nonce, t ->
            if (nonce == "n1") DecisionFixtures.response(READBACK, "Option B. Say confirm.", "n2")
            else if (t == "confirm") DecisionFixtures.response(EXECUTED, coreSay, null) else error(t)
        })
        val voice = RecordingVoice()
        val d = RecordingDisplay(false)
        flow(api, d, voice, ScriptedEar(d, Step.Say("approve option B"), Step.Say("confirm"))).run()
        assertEquals(coreSay, voice.spoken.last())
    }

    @Test
    fun wrongStepUpCode_isRetried_onThePhone() = runBlocking {
        val api = ScriptedDecisionsApi(onCommand = coreApprovesA())
        val stepUp = ScriptedStepUp(StepUpEntry(StepUpMethod.TOTP, "000000"), StepUpEntry(StepUpMethod.TOTP, "123456"))
        val d = RecordingDisplay(false)
        val result = flow(api, d, RecordingVoice(), ScriptedEar(d, Step.Say("approve option A"), Step.Say("confirm")), stepUp).run()

        assertEquals(Outcome.EXECUTED, (result as FlowState.Finished).outcome)
        assertEquals(listOf("000000", "123456"), api.stepUps.map { it.second })
        assertEquals(null, stepUp.prompts[0])
        assertTrue(stepUp.prompts[1]!!.contains("not accepted"))
    }

    @Test
    fun stepUpAlreadyFresh_orWaived_doesNotPrompt() = runBlocking {
        for (setup in listOf<(ScriptedDecisionsApi) -> Unit>({ it.stepUpFresh = true }, { it.stepUpWaived = true })) {
            val api = ScriptedDecisionsApi(onCommand = coreApprovesA()).also(setup)
            val stepUp = ScriptedStepUp()
            val d = RecordingDisplay(false)
            val result = flow(api, d, RecordingVoice(), ScriptedEar(d, Step.Say("approve option A"), Step.Say("confirm")), stepUp).run()
            assertEquals(Outcome.EXECUTED, (result as FlowState.Finished).outcome)
            assertTrue(stepUp.prompts.isEmpty())
            assertTrue(api.stepUps.isEmpty())
        }
    }

    @Test
    fun stepUpCancelled_isSpoken_andTheCoreStillDecides() = runBlocking {
        val api = ScriptedDecisionsApi(onCommand = { nonce, t ->
            when {
                nonce == "n1" -> DecisionFixtures.response(READBACK, readbackA, "n2", stepUp = true)
                nonce == "n2" && t == "cancel" -> DecisionFixtures.response(CANCELLED, "Cancelled.", null)
                else -> error(t)
            }
        })
        val voice = RecordingVoice()
        val d = RecordingDisplay(false)
        val result = flow(api, d, voice, ScriptedEar(d, Step.Say("approve option A"), Step.Say("cancel")), ScriptedStepUp(null)).run()
        assertEquals(Outcome.CANCELLED, (result as FlowState.Finished).outcome)
        assertTrue(voice.spoken.contains(ApprovalFlow.SAY_STEP_UP_FAILED))
    }

    @Test
    fun clarify_keepsTheConversationGoing_withTheNextNonce() = runBlocking {
        val api = ScriptedDecisionsApi(onCommand = { nonce, t ->
            when (nonce) {
                "n1" -> DecisionFixtures.response(CLARIFY, "Which option, A or B?", "n2")
                "n2" -> DecisionFixtures.response(READBACK, readbackA, "n3")
                "n3" -> DecisionFixtures.response(EXECUTED, executedA, null)
                else -> error(t)
            }
        })
        val d = RecordingDisplay(true)
        val result = flow(api, d, RecordingVoice(), ScriptedEar(d, Step.Say("approve it"), Step.Press("approve:A"), Step.Press("confirm"))).run()
        assertEquals(Outcome.EXECUTED, (result as FlowState.Finished).outcome)
        assertEquals(listOf("n1", "n2", "n3"), api.commands.map { it.first })
    }

    @Test
    fun nothingWaiting_isSpoken() = runBlocking {
        val voice = RecordingVoice()
        val result = flow(ScriptedDecisionsApi(nextItem = null), RecordingDisplay(true), voice, ScriptedEar(null)).run()
        assertEquals(FlowState.Finished(Outcome.NOTHING_WAITING, ApprovalFlow.SAY_NOTHING), result)
        assertEquals(listOf(ApprovalFlow.SAY_NOTHING), voice.spoken)
    }

    @Test
    fun coreError_isSpoken_andReported() = runBlocking {
        val api = ScriptedDecisionsApi(onCommand = { _, _ -> throw CoreException.Http(409, Problem(title = "Decision already decided", status = 409, code = "conflict")) })
        val voice = RecordingVoice()
        val d = RecordingDisplay(false)
        val result = flow(api, d, voice, ScriptedEar(d, Step.Say("approve option A"))).run()
        assertEquals(FlowState.Failed("Decision already decided"), result)
        assertEquals(ApprovalFlow.SAY_ERROR, voice.spoken.last())
        assertEquals(listOf(EarconCue.ERROR), voice.earcons)
    }

    @Test
    fun silence_threeTimes_abandons_withoutSending() = runBlocking {
        val api = ScriptedDecisionsApi()
        val d = RecordingDisplay(false)
        val result = flow(api, d, RecordingVoice(), ScriptedEar(d, Step.Silence, Step.Silence, Step.Silence)).run()
        assertEquals(Outcome.ABANDONED, (result as FlowState.Finished).outcome)
        assertTrue(api.commands.isEmpty())
    }

    @Test
    fun stoppingTheReview_clearsTheCard_andSendsNothingMore() = runBlocking {
        val api = ScriptedDecisionsApi()
        val display = RecordingDisplay(true)
        val ear = DecisionEar { kotlinx.coroutines.awaitCancellation() }
        val f = ApprovalFlow(api, ScriptedBriefs(), display, RecordingVoice(), ear, ScriptedStepUp(), {})
        val job = launch { f.run() }
        while (f.state.value !is FlowState.Listening) yield()
        job.cancel()
        job.join()
        assertEquals(1, display.cleared)
        assertTrue(api.commands.isEmpty())
    }

    @Test
    fun spokenBrief_isTheTemplateWhenTheSourceAnswersBlank() = runBlocking {
        val blank = BriefSource { _, t -> SpokenBrief(" ", SpokenBrief.MODEL).also { assertEquals(DecisionFixtures.item().spoken, t) } }
        val api = ScriptedDecisionsApi(onCommand = { _, _ -> DecisionFixtures.response(CANCELLED, "Cancelled.", null) })
        val d = RecordingDisplay(false)
        val voice = RecordingVoice()
        flow(api, d, voice, ScriptedEar(d, Step.Say("cancel")), briefs = blank).run()
        assertEquals(DecisionFixtures.item().spoken, voice.spoken.first())
    }
}
