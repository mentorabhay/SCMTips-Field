package com.scmtips.field.app.look

import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.str
import com.scmtips.field.core.voice.asr.AsrCandidate
import com.scmtips.field.core.wearables.AudioOut
import com.scmtips.field.core.wearables.EarconCue
import com.scmtips.field.feature.decisions.flow.DecisionCard
import com.scmtips.field.feature.decisions.flow.DecisionDisplay
import com.scmtips.field.feature.decisions.flow.DecisionEar
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The supervisor's claims by voice: read → approve/reject → read-back → confirm (10 s) → result. */
class ClaimReviewTest {
    private class Voice : AudioOut {
        val said = mutableListOf<String>()
        val earcons = mutableListOf<EarconCue>()
        override suspend fun playEarcon(cue: EarconCue) { earcons += cue }
        override suspend fun playSpeech(text: String, flushQueue: Boolean) { said += text }
        override fun stopAudio() = Unit
    }

    /** Words in order; null is silence. [onListen] runs before each answer (e.g. to move the clock). */
    private class Ear(vararg words: String?) : DecisionEar {
        val queue = ArrayDeque(words.toList())
        var onListen: () -> Unit = {}
        override suspend fun listen(): AsrCandidate? { onListen(); return queue.removeFirstOrNull()?.let { AsrCandidate(it, 0.92f) } }
    }

    /** The phone card; [presses] are answered instead of words while a card is up. */
    private class Card(vararg presses: String) : DecisionDisplay {
        val shown = mutableListOf<DecisionCard>()
        val queue = ArrayDeque(presses.toList())
        var cleared = 0
        override suspend fun show(card: DecisionCard, onButton: (String) -> Unit): Boolean {
            shown += card
            queue.removeFirstOrNull()?.let(onButton)
            return true
        }
        override suspend fun clear() { cleared += 1 }
    }

    private class NoCard : DecisionDisplay {
        override suspend fun show(card: DecisionCard, onButton: (String) -> Unit) = false
        override suspend fun clear() = Unit
    }

    private class Setup(ear: Ear, display: DecisionDisplay = NoCard(), drafts: String = TWO_DRAFTS) {
        val api = ScriptedFieldApi().apply {
            ok("GET /v1/claims?status=draft&limit=50", drafts)
            ok("GET /v1/claims/cl-2", """{"claim_id":"cl-2","status":"draft"}""", etag = "1-c2")
            ok("POST /v1/claims/cl-1/decision", """{"status":"pending_confirm","say":"Approve claim for 2 damaged packs, delivery 1800 0000 22? Say confirm.","confirm_by":"x"}""", etag = "2-c1")
            ok("POST /v1/claims/cl-1/confirm", """{"status":"approved","say":"Claim approved. Sent to the supplier, simulated."}""", etag = "3-c1")
            ok("POST /v1/claims/cl-2/decision", """{"status":"pending_confirm","say":"Reject claim for 1 expired box? Say confirm."}""", etag = "2-c2")
            ok("POST /v1/claims/cl-2/confirm", """{"status":"rejected","say":"Claim rejected."}""", etag = "3-c2")
        }
        var now = 1_000L
        val voice = Voice()
        val flow = ClaimReview(LookClient(api, api, { "dev-1" }), voice, ear, display, clock = { now })
        fun decisions() = api.sent.filter { it.path.endsWith("/decision") }
        fun confirms() = api.sent.filter { it.path.endsWith("/confirm") }
    }

    companion object {
        const val TWO_DRAFTS = """{"items":[
            {"claim_id":"cl-1","status":"draft","etag":"1-c1","title":"Delivery 1800000022","lines":[{"reason":"damaged","units":2}],"text":"Two packs arrived damaged."},
            {"claim_id":"cl-2","status":"draft","lines":[{"reason":"expired","units":1}],"text":""}]}"""
    }

    @Test
    fun m5B03_approveThenConfirm_postsBothAndSpeaksTheServersWords() = runBlocking {
        val s = Setup(Ear("approve", "confirm", "stop"))
        val end = s.flow.run()
        assertEquals(ClaimFlowState.Finished(ClaimOutcome.STOPPED, 1), end)
        assertEquals("Claim 1 of 2. Delivery 1800000022. Two packs arrived damaged. Say approve, reject, next claim, or stop.", s.voice.said[0])
        assertEquals("Approve claim for 2 damaged packs, delivery 1800 0000 22? Say confirm.", s.voice.said[1])
        assertEquals("Claim approved. Sent to the supplier, simulated.", s.voice.said[2])
        assertTrue("the next draft is read", s.voice.said[3].startsWith("Claim 2 of 2. 1 unit expired."))
        assertEquals("approve", s.decisions().single().str("decision"))
        assertEquals("If-Match from the list item", mapOf("If-Match" to "1-c1"), s.decisions().single().headers)
        assertEquals(listOf("/v1/claims/cl-1/confirm"), s.confirms().map { it.path })
        assertEquals("the decision's new ETag confirms", mapOf("If-Match" to "2-c1"), s.confirms().single().headers)
        assertEquals("confirm", s.confirms().single().str("words"))
        assertEquals(EarconCue.CAPTURED, s.voice.earcons.last())
    }

    @Test
    fun m5B03_rejectWithAReason_thenConfirm() = runBlocking {
        val s = Setup(Ear("next claim", "reject because the box is fine", "confirm"))
        val end = s.flow.run()
        assertEquals(ClaimFlowState.Finished(ClaimOutcome.DONE, 1), end)
        val d = s.decisions().single()
        assertEquals("/v1/claims/cl-2/decision", d.path)
        assertEquals("reject", d.str("decision")); assertEquals("the box is fine", d.str("reason"))
        assertEquals("no ETag in the list: fetched first", mapOf("If-Match" to "1-c2"), d.headers)
        assertTrue(s.api.paths().contains("GET /v1/claims/cl-2"))
        assertEquals("Claim rejected.", s.voice.said[s.voice.said.size - 2])
        assertEquals("That was the last claim.", s.voice.said.last())
    }

    @Test
    fun m5B03_cancelOrSilenceAfterTheReadBack_changesNothing() = runBlocking {
        val s = Setup(Ear("approve", "cancel", "approve", null, "stop"))
        s.flow.run()
        assertEquals(2, s.decisions().size)
        assertTrue("never confirmed", s.confirms().isEmpty())
        assertTrue(s.voice.said.contains("Not confirmed. Nothing changed."))
        assertTrue(s.voice.said.contains("No confirm heard. Nothing changed."))
    }

    @Test
    fun m5B03_aConfirmAfterTenSeconds_isNotSent() = runBlocking {
        val ear = Ear("approve", "confirm", "stop")
        val s = Setup(ear)
        var listens = 0
        ear.onListen = { listens += 1; if (listens == 2) s.now += 10_001 }
        s.flow.run()
        assertEquals(1, s.decisions().size)
        assertTrue(s.confirms().isEmpty())
        assertTrue(s.voice.said.contains("Too late to confirm. Nothing changed. Say approve or reject again."))
    }

    @Test
    fun m5B03_buttonsOnThePhoneCardDoTheSame() = runBlocking {
        val card = Card(ClaimGrammar.APPROVE_ID, ClaimGrammar.CONFIRM_ID, ClaimGrammar.STOP_ID)
        val s = Setup(Ear(null, null, null, null), display = card)
        assertEquals(ClaimFlowState.Finished(ClaimOutcome.STOPPED, 1), s.flow.run())
        assertEquals(listOf("SAMPLE claim 1 of 2 · Delivery 1800000022", "Approve this claim?", "SAMPLE claim 2 of 2"), card.shown.map { it.title })
        assertEquals(listOf("Approve", "Reject", "Next claim", "Stop"), card.shown[0].buttons.map { it.label })
        assertEquals(1, s.confirms().size)
        assertTrue(card.cleared >= 1)
    }

    @Test
    fun m5B03_nothingWaiting_notAllowed_andSilenceEndTheReview() = runBlocking {
        val none = Setup(Ear(), drafts = """{"items":[]}""")
        assertEquals(ClaimFlowState.Finished(ClaimOutcome.NOTHING_WAITING, 0), none.flow.run())
        assertEquals(listOf(ClaimReview.SAY_NONE), none.voice.said)

        val forbiddenApi = ScriptedFieldApi().apply { on("GET /v1/claims?status=draft&limit=50", ApiResult.Problem(403, "FIELD-AUTH-403", "Forbidden", null)) }
        val voice = Voice()
        val forbidden = ClaimReview(LookClient(forbiddenApi, forbiddenApi, { "dev-1" }), voice, Ear(), NoCard())
        assertEquals(ClaimFlowState.Finished(ClaimOutcome.NOT_ALLOWED, 0), forbidden.run())
        assertEquals(listOf(ClaimReview.SAY_NOT_ALLOWED), voice.said)

        val quiet = Setup(Ear(null, null, null))
        assertEquals(ClaimFlowState.Finished(ClaimOutcome.ABANDONED, 0), quiet.flow.run())
        assertEquals(ClaimReview.SAY_ABANDON, quiet.voice.said.last())
        assertTrue(quiet.decisions().isEmpty())
    }

    @Test
    fun m5B03_unclearWordsAreNeverActedOn() = runBlocking {
        val s = Setup(Ear("ship it", "approve maybe", "stop"))
        s.flow.run()
        assertTrue(s.decisions().isEmpty())
        assertEquals(2, s.voice.said.count { it == ClaimReview.SAY_OPTIONS })
    }

    @Test
    fun m5B03_aStaleETagOrAnExpiredConfirm_changesNothingAndFetchesAgain() = runBlocking {
        val s = Setup(Ear("approve", "approve", "confirm", "stop"))
        s.api.reset("POST /v1/claims/cl-1/decision"); s.api.reset("POST /v1/claims/cl-1/confirm")
        s.api.on("POST /v1/claims/cl-1/decision",
            ApiResult.Problem(412, "FIELD-CLM-412-STALE", "Precondition failed", null),
            ApiResult.Ok(200, kotlinx.serialization.json.Json.parseToJsonElement("""{"status":"pending_confirm","say":"Approve? Say confirm."}""") as kotlinx.serialization.json.JsonObject, "5-c1"))
        s.api.ok("GET /v1/claims/cl-1", """{"claim_id":"cl-1","status":"draft"}""", etag = "4-c1")
        s.api.on("POST /v1/claims/cl-1/confirm", ApiResult.Problem(422, ClaimReview.CONFIRM_EXPIRED, "Confirm window passed", null))
        s.flow.run()
        val d = s.api.sent.filter { it.path.endsWith("/v1/claims/cl-1/decision") }
        assertEquals(listOf("1-c1", "4-c1"), d.map { it.headers["If-Match"] })
        assertEquals("5-c1", s.confirms().single().headers["If-Match"])
        assertTrue(s.voice.said.contains("The claim changed meanwhile. Nothing was decided. Say approve or reject again."))
        assertTrue(s.voice.said.contains("Too late to confirm. Nothing changed. Say approve or reject again."))
    }

    @Test
    fun m5T05_anAuthenticityClaimIsReadWithItsKind_andDecidedTheSameWay() = runBlocking {
        val card = Card()
        val s = Setup(Ear("approve", "confirm", "stop"), display = card, drafts = """{"items":[
            {"claim_id":"cl-1","status":"draft","etag":"1-c1","kind":"authenticity","check_id":"ck-1","look_id":null,
             "lines":[{"reason":"not_new","units":1,"pieces":0},{"reason":"tampered_seal","units":1,"pieces":0}],"text":""}]}""")
        assertEquals(ClaimFlowState.Finished(ClaimOutcome.DONE, 1), s.flow.run())
        assertEquals("SAMPLE claim 1 of 1 · Box check", card.shown[0].title)
        assertEquals("Not a new unit, seal tampered.", card.shown[0].body)
        assertEquals("Claim 1 of 1. Box check. Not a new unit, seal tampered. Say approve, reject, next claim, or stop.", s.voice.said[0])
        assertEquals("1-c1", s.decisions().single().headers["If-Match"])
        assertEquals(1, s.confirms().size)
    }
}
