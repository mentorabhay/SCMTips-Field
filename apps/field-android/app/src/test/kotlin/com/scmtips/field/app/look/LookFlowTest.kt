package com.scmtips.field.app.look

import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.LookFill
import com.scmtips.field.app.jobs.RecordingSpeaker
import com.scmtips.field.app.jobs.str
import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The operator's look end to end against the scripted field-api: photo → upload → look → spoken → pre-fill. */
class LookFlowTest {
    private class Setup(shot: Shot = Shot.Taken(photo())) {
        val api = ScriptedFieldApi()
        val voice = RecordingSpeaker()
        val fills = mutableListOf<LookFill>()
        var shots = ArrayDeque(listOf(shot))
        var taken = 0
        val flow = LookFlow(
            camera = { taken += 1; shots.removeFirstOrNull() ?: shot },
            client = LookClient(api, api, { "dev-1" }),
            speaker = voice,
            onLook = { fills += it },
            baseUrl = { "http://pc:8080" },
        )
        val target = LookTarget("t-1", "l-1", "site-1", LookCase.GROCERY)
    }

    companion object {
        fun photo(camera: CameraUsed = CameraUsed.GLASSES) = LookPhoto(byteArrayOf(9, 9), 640, 480, camera, 1L, 1200, 0)
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
}
