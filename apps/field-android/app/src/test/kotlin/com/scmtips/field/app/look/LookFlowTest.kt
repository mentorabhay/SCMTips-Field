package com.scmtips.field.app.look

import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.LookFill
import com.scmtips.field.app.jobs.RecordingSpeaker
import com.scmtips.field.app.jobs.str
import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The operator's look end to end against the scripted field-api: photo → upload → look → spoken → pre-fill. */
class LookFlowTest {
    private class Setup(
        shot: Shot = Shot.Taken(photo()),
        scope: CoroutineScope = CoroutineScope(Dispatchers.Unconfined),
        sleep: (suspend (Long) -> Unit)? = null,
    ) {
        val api = ScriptedFieldApi()
        val voice = RecordingSpeaker()
        val fills = mutableListOf<LookFill>()
        var shots = ArrayDeque(listOf(shot))
        var taken = 0
        val slept = mutableListOf<Long>()
        val flow = LookFlow(
            camera = { taken += 1; shots.removeFirstOrNull() ?: shot },
            client = LookClient(api, api, { "dev-1" }),
            speaker = voice,
            onLook = { fills += it },
            baseUrl = { "http://pc:8080" },
            scope = scope,
            sleep = sleep ?: { ms -> slept += ms },
        )
        val target = LookTarget("t-1", "l-1", "site-1", LookCase.GROCERY)
    }

    companion object {
        fun photo(camera: CameraUsed = CameraUsed.GLASSES) = LookPhoto(byteArrayOf(9, 9), 640, 480, camera, 1L, 1200, 0)

        /** M5-S01 first answer: counted, labels not read, nothing proposed. */
        val PENDING_LOOK = """{"look_id":"lk-1","source":"partial","final":false,"say_next":null,
            "image":{"capture_id":"cap-1","width":1600,"height":1200},
            "instances":[{"n":1,"box":[10,20,210,220],"damaged":false,"label":{"read":false}}],
            "counts":{"expected":20,"seen":20,"damaged":null,"good":null},"pack":null,"expiry":null,
            "proposal":{"receive":null,"flag":null,"reasons":[]},"say":"20 of 20 packs. Reading the labels.",
            "models":[{"model":"sam-3.1","purpose":"instances","outcome":"ok"}],"reasons":[]}"""
        val FINAL_LOOK = """{"look_id":"lk-1","source":"model","final":true,
            "image":{"capture_id":"cap-1","width":1600,"height":1200},
            "instances":[{"n":1,"box":[10,20,210,220],"damaged":true,"label":{"read":true,"pieces_per_unit":12}}],
            "counts":{"expected":20,"seen":20,"damaged":2,"good":18},
            "pack":{"expected_pieces_per_unit":12,"mismatches":[{"n":7,"pieces_per_unit":10}],"pieces_difference":-4},
            "expiry":null,"proposal":{"receive":18,"flag":2,"reasons":["2 damaged"]},
            "say":"20 of 20 packs. 2 damaged. 2 packs hold 10, not 12: 4 pieces short. Receive 18, flag 2?",
            "say_next":"2 damaged. 2 packs hold 10, not 12: 4 pieces short. Receive 18, flag 2?",
            "models":[{"model":"sam-3.1","purpose":"instances","outcome":"ok"},{"model":"muse-spark-1.3","purpose":"labels","outcome":"ok"}],
            "reasons":[]}"""
        val FAILED_LOOK = """{"look_id":"lk-1","source":"partial","final":true,
            "instances":[],"counts":{"expected":20,"seen":5,"damaged":0,"good":5},
            "proposal":{"receive":5,"flag":0,"reasons":["5 labels not read"]},
            "say":"I couldn't read the labels. Say your numbers.","say_next":"I couldn't read the labels. Say your numbers.",
            "models":[],"reasons":["labels:muse-spark-1.3:AI_HTTP_500"]}"""
    }

    @Test
    fun m5B01_aLookIsSpokenShownAndPreFillsTheJob() = runBlocking {
        val s = Setup()
        s.api.scriptLook()
        s.flow.look(s.target)
        val v = s.flow.view.value
        assertEquals(LookState.SHOWN, v.state)
        assertEquals(CameraUsed.GLASSES, v.camera)
        assertEquals("lk-1", v.look!!.lookId)
        assertEquals(listOf(LookFill("lk-1", "cap-1", "l-1", 18, 2, "Say receive 18, flag 2. Or say count again.")), s.fills)
        assertEquals("Twenty of twenty. Two damaged. Two packs hold 10, not 12: 4 pieces short. Say receive 18, flag 2. Or say count again.",
            s.voice.said.last())
        assertEquals(EarconCue.CAPTURED, s.voice.earcons.first())
        assertEquals(listOf("POST /v1/captures/uploads", "POST /v1/captures", "POST /v1/vision/looks"), s.api.paths())
        assertEquals("look never stages or posts", 0, s.api.sent.count { "post-requests" in it.path || "count-records" in it.path })
    }

    @Test
    fun m5B01_thePhoneCameraIsUsedAndSaid_whenTheGlassesGiveNone() = runBlocking {
        val s = Setup(Shot.Taken(photo(CameraUsed.PHONE), note = "Used the phone camera."))
        s.api.scriptLook()
        s.flow.look(s.target)
        assertEquals(CameraUsed.PHONE, s.flow.view.value.camera)
        assertEquals("Used the phone camera.", s.voice.said.first())
    }

    @Test
    fun m5B01_noPhoto_saysWhyAndOffersAnotherTry() = runBlocking {
        val s = Setup(Shot.Failed("No photo was taken."))
        s.flow.look(s.target)
        assertEquals(LookState.FAILED, s.flow.view.value.state)
        assertEquals("No photo was taken. Say look again, or count aloud.", s.voice.said.last())
        assertEquals(EarconCue.ERROR, s.voice.earcons.last())
        assertTrue(s.api.sent.isEmpty()); assertTrue(s.fills.isEmpty())
    }

    @Test
    fun m5B01_consentIsAskedOnce_thenTheSamePhotoIsSent() = runBlocking {
        val s = Setup()
        s.api.ok("POST /v1/captures/uploads", """{"upload_id":"up-1"}""")
        s.api.on("POST /v1/captures",
            ApiResult.Problem(403, LookApi.NO_CONSENT, "Privacy consent required", null),
            ApiResult.Ok(201, kotlinx.serialization.json.Json.parseToJsonElement("""{"id":"cap-7"}""") as kotlinx.serialization.json.JsonObject))
        s.api.ok("POST /v1/consents", """{"id":"con-1"}""")
        s.api.ok("POST /v1/vision/looks", ScriptedFieldApi.CONTRACT_LOOK)
        s.flow.look(s.target)
        assertEquals(LookState.CONSENT, s.flow.view.value.state)
        assertTrue(s.flow.consentPending)
        assertEquals(LookFlow.CONSENT_SPOKEN, s.voice.said.last())
        s.flow.agree()
        assertEquals(LookState.SHOWN, s.flow.view.value.state)
        assertEquals("one photo taken", 1, s.taken)
        assertEquals("cap-7", s.api.last("/v1/vision/looks").str("capture_id"))
        assertEquals(1, s.api.sent.count { it.path == "/v1/consents" })
    }

    @Test
    fun m5B01_aRulesOnlyLookAsksForASpokenCount() = runBlocking {
        val s = Setup()
        s.api.ok("POST /v1/captures/uploads", """{"upload_id":"up-1"}""")
        s.api.ok("POST /v1/captures", """{"id":"cap-1"}""")
        s.api.ok("POST /v1/vision/looks", """{"look_id":"lk-r","source":"rules","instances":[],"counts":{"expected":12},
            "say":"No model answered. Count them and say the number."}""")
        s.flow.look(s.target)
        assertEquals("No model answered. Count them and say the number. Say receive and the number you count. Or say look again.", s.voice.said.last())
        assertEquals(null, s.fills.single().receive)
    }

    @Test
    fun m5B02_makeAClaimReadsTheDraft_andTheEvidenceLinkIsOpened() = runBlocking {
        val s = Setup()
        s.api.scriptLook()
        s.flow.claim()
        assertEquals("Take a look first, then say make a claim.", s.voice.said.last())
        s.flow.look(s.target)
        s.api.ok("POST /v1/claims", """{"claim_id":"cl-1","status":"draft","lines":[{"reason":"damaged","units":2}],
            "text":"Two packs arrived damaged","source":"model"}""")
        s.flow.claim()
        assertEquals("lk-1", s.api.last("/v1/claims").str("look_id"))
        assertEquals("Claim drafted. Two packs arrived damaged. A supervisor approves it before it is sent.", s.voice.said.last())
        assertEquals("cl-1", s.flow.view.value.claim!!.claimId)
        s.api.ok("POST /v1/evidence/documents/4900000101/link", """{"url":"/evidence/tok"}""")
        assertEquals("http://pc:8080/evidence/tok", s.flow.evidence("4900000101", null))
        assertEquals("http://pc:8080/evidence/tok", s.flow.view.value.evidenceUrl)
        assertEquals("The evidence page is open on the phone.", s.voice.said.last())
        s.flow.closeEvidence()
        assertNull(s.flow.view.value.evidenceUrl)
    }

    @Test
    fun m5B02_hintsSayTheProposalBack() {
        val base = Look("l", "model", null, null, null, emptyList(), LookCounts(10, 10, 0, 10), 0, null, 0, emptyList(),
            Proposal(10, 0, emptyList()), "", emptyList(), emptyList())
        assertEquals("Say receive 10. Or say count again.", LookFlow.hint(base))
        assertEquals("Say receive 8, flag 2. Or say count again.", LookFlow.hint(base.copy(proposal = Proposal(8, 2, emptyList()))))
        assertEquals("Say receive and the number you count. Or say look again.", LookFlow.hint(base.copy(source = "rules")))
        assertEquals("2 units damaged, 2 units, 4 pieces wrong pack size",
            ClaimText.lines(Claim("c", "draft", listOf(ClaimLine("damaged", 2, null), ClaimLine("pack_size", 2, 4)), "", null, null, null)))
    }

    @Test
    fun m5B05_cameraTestShowsSizeAndDelay_andNothingIsSentByIt() {
        val p = CameraProbe(width = 1280, height = 720, delayMs = 2340)
        assertEquals("1280 × 720 px from the glasses in 2.3 s", p.summary)
        assertNull(CameraProbe(message = "Connect the glasses first").summary)
        assertNull("nothing uploaded until Upload is tapped", p.uploadedCaptureId)
    }

    // ---------------------------------------------------------------- M5-S01 two-step look

    private fun Setup.scriptPending(polls: List<String>) {
        ok("POST /v1/captures/uploads", """{"upload_id":"up-1"}""")
        ok("POST /v1/captures", """{"id":"cap-1"}""")
        ok("POST /v1/vision/looks", PENDING_LOOK)
        polls.forEach { ok("GET /v1/vision/looks/lk-1", it) }
    }

    private fun Setup.ok(route: String, json: String) = api.ok(route, json)

    @Test
    fun m5S01_firstAnswerIsSpokenAtOnce_thenThePollSpeaksTheSecondPartOnce() = runBlocking {
        val s = Setup(scope = this)
        s.scriptPending(listOf(PENDING_LOOK, PENDING_LOOK, FINAL_LOOK))
        s.flow.look(s.target)
        val first = s.flow.view.value
        assertEquals(LookState.SHOWN, first.state)
        assertTrue("labels are being read", first.labelsPending)
        assertFalse(first.look!!.final)
        assertEquals(listOf("20 of 20 packs. Reading the labels."), s.voice.said)
        assertEquals("nothing proposed before the labels", LookFill("lk-1", "cap-1", "l-1", null, null, LookFlow.PENDING_HINT), s.fills.single())
        s.flow.polling!!.join()
        assertEquals("one GET a second until final", 3, s.api.sent.count { it.method == "GET" && it.path == "/v1/vision/looks/lk-1" })
        assertEquals(listOf(1_000L, 1_000L, 1_000L), s.slept)
        assertEquals(listOf("20 of 20 packs. Reading the labels.",
            "2 damaged. 2 packs hold 10, not 12: 4 pieces short. Receive 18, flag 2? Say receive 18, flag 2. Or say count again."),
            s.voice.said)
        val v = s.flow.view.value
        assertFalse(v.labelsPending); assertTrue(v.look!!.final)
        assertEquals(LookCounts(20, 20, 2, 18), v.look!!.counts)
        assertEquals(LookFill("lk-1", "cap-1", "l-1", 18, 2, "Say receive 18, flag 2. Or say count again."), s.fills.last())
        assertNull(s.flow.polling)
    }

    @Test
    fun m5S01_noFinalLookWithin40Polls_saysTheLabelsWereNotRead() = runBlocking {
        val s = Setup(scope = this)
        s.scriptPending(listOf(PENDING_LOOK))
        s.flow.look(s.target)
        s.flow.polling!!.join()
        assertEquals(LookApi.POLL_MAX, s.api.sent.count { it.method == "GET" })
        assertEquals(40, LookApi.POLL_MAX); assertEquals(1_000L, LookApi.POLL_MS)
        assertEquals(LookFlow.LABELS_TIMEOUT_SAY, s.voice.said.last())
        assertEquals("I couldn't read the labels. Say your numbers.", LookFlow.LABELS_TIMEOUT_SAY)
        assertEquals(2, s.voice.said.size)
        assertFalse(s.flow.view.value.labelsPending)
        assertNull(s.fills.last().receive)
    }

    @Test
    fun m5S01_aFailedPollIsRetried_andTheServersOwnLabelFailureIsSpokenOnce() = runBlocking {
        val s = Setup(scope = this)
        s.ok("POST /v1/captures/uploads", """{"upload_id":"up-1"}""")
        s.ok("POST /v1/captures", """{"id":"cap-1"}""")
        s.ok("POST /v1/vision/looks", PENDING_LOOK)
        s.api.on("GET /v1/vision/looks/lk-1", ApiResult.Offline("wifi"))
        s.ok("GET /v1/vision/looks/lk-1", FAILED_LOOK)
        s.flow.look(s.target)
        s.flow.polling!!.join()
        assertEquals(2, s.api.sent.count { it.method == "GET" })
        assertEquals("I couldn't read the labels. Say your numbers. Say receive 5. Or say count again.", s.voice.said.last())
        assertEquals(2, s.voice.said.size)
    }

    @Test
    fun m5S01_leavingTheScreenOrANewLook_cancelsThePoll_andNothingMoreIsSaid() = runBlocking {
        val s = Setup(scope = this, sleep = { delay(it) })
        s.scriptPending(listOf(FINAL_LOOK))
        s.flow.look(s.target)
        val p = s.flow.polling!!
        s.flow.leave()
        p.join()
        assertTrue(p.isCancelled); assertNull(s.flow.polling)
        assertFalse(s.flow.view.value.labelsPending)
        assertEquals("look stays for make a claim", "lk-1", s.flow.lastLookId)
        assertEquals(1, s.voice.said.size)
        assertEquals(0, s.api.sent.count { it.method == "GET" })

        val t = Setup(scope = this, sleep = { delay(it) })
        t.scriptPending(listOf(FINAL_LOOK))
        t.flow.look(t.target)
        val first = t.flow.polling!!
        t.api.reset("POST /v1/vision/looks")
        t.api.ok("POST /v1/vision/looks", ScriptedFieldApi.CONTRACT_LOOK.replace("\"lk-1\"", "\"lk-2\""))
        t.flow.look(t.target) // a new look
        first.join()
        assertTrue(first.isCancelled)
        assertEquals("lk-2", t.flow.lastLookId)
        assertEquals(0, t.api.sent.count { it.method == "GET" })
        assertTrue("the old look's second part is never said", t.voice.said.none { "Receive 18, flag 2?" in it })
    }

    @Test
    fun m5S01_aClaimWaitsForTheFinalLook() = runBlocking {
        val s = Setup(scope = this, sleep = { delay(it) })
        s.scriptPending(listOf(FINAL_LOOK))
        s.flow.look(s.target)
        s.flow.claim()
        assertEquals("Still reading the labels. Say make a claim in a moment.", s.voice.said.last())
        assertEquals(0, s.api.sent.count { it.path == "/v1/claims" })
        s.flow.clear()
        assertNull(s.flow.polling)
    }
}
