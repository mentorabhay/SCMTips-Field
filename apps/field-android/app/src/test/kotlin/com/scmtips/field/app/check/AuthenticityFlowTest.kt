package com.scmtips.field.app.check

import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.RecordingSpeaker
import com.scmtips.field.app.jobs.str
import com.scmtips.field.app.look.CameraUsed
import com.scmtips.field.app.look.LookApi
import com.scmtips.field.app.look.LookPhoto
import com.scmtips.field.app.look.ScriptedFieldApi
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

/**
 * M5-T05, the C3 phone flow end to end against the scripted field-api: "Show me the seal code." → photo → QR read
 * on the phone → seal photo upload → check → `say` at once → two-step poll → `say_next` once → claim / evidence.
 */
class AuthenticityFlowTest {
    private class Setup(
        shot: SealShot = SealShot.Taken(AuthenticityClientTest.photo(), listOf(SEAL), CameraUsed.GLASSES),
        scope: CoroutineScope = CoroutineScope(Dispatchers.Unconfined),
        sleep: (suspend (Long) -> Unit)? = null,
        scanned: String? = null,
        aimMs: Long = CheckFlow.AIM_MS,
    ) {
        val api = ScriptedFieldApi()
        val voice = RecordingSpeaker()
        var shots = ArrayDeque(listOf(shot))
        var taken = 0
        var scans = 0
        val slept = mutableListOf<Long>()
        private var keys = 0
        val flow = CheckFlow(
            camera = { taken += 1; shots.removeFirstOrNull() ?: shot },
            scanner = { scans += 1; scanned },
            client = CheckClient(api, api, { "dev-1" }, { "key-${++keys}" }),
            speaker = voice,
            baseUrl = { "http://pc:8080" },
            scope = scope,
            sleep = sleep ?: { ms -> slept += ms },
            aimMs = aimMs,
        )

        fun photoOk() {
            api.ok("POST /v1/captures/uploads", """{"upload_id":"up-1"}""")
            api.ok("POST /v1/captures", """{"id":"cap-9"}""")
        }

        fun checks() = api.sent.filter { it.method == "POST" && it.path == CheckApi.CHECKS }
        fun polls() = api.sent.count { it.method == "GET" && it.path.startsWith(CheckApi.CHECKS) }
    }

    companion object {
        const val SEAL = "SEAL1.3f1c0000aaaabbbb.eyJ2IjoxfQ.c2ln"

        val PENDING = AuthenticityClientTest.RETURNED
            .replace("\"final\":true", "\"final\":false").replace("\"tamper\":true", "\"tamper\":null")
            .replace("\"status\":\"done\"", "\"status\":\"pending\"")
            .replace("The seal shows tape over the original.\",\n \"say_next\":\"The seal shows tape over the original.\"",
                "Checking the seal.\",\n \"say_next\":null")
        val FINAL = AuthenticityClientTest.RETURNED
        const val FIRST_SAY = "Code is genuine. But this unit was activated on 12 October and returned on 20 October. It is not a new unit. Checking the seal."
    }

    @Test
    fun m5T05_aOneStepCheck_isAskedForSpokenAndShown() = runBlocking {
        val s = Setup()
        s.photoOk()
        s.api.ok("POST /v1/authenticity/checks", AuthenticityClientTest.minimal("GENUINE_NEW",
            "Code is genuine. This unit is new: it was never activated or returned."))
        s.flow.start("site-1")
        assertEquals(CheckText.SHOW_ME, s.voice.said.first())
        assertEquals("time to turn the seal to the camera before the photo", listOf(CheckFlow.AIM_MS), s.slept)
        assertEquals(listOf("POST /v1/captures/uploads", "POST /v1/captures", "POST /v1/authenticity/checks"), s.api.paths())
        val sent = s.checks().single()
        assertEquals(SEAL, sent.str("code")); assertEquals("cap-9", sent.str("capture_id")); assertEquals("site-1", sent.str("site_id"))
        val v = s.flow.view.value
        assertEquals(CheckState.SHOWN, v.state); assertTrue(v.open)
        assertEquals(Verdict.GENUINE_NEW, v.check!!.verdict); assertEquals(VerdictTone.GREEN, v.check!!.verdict.tone)
        assertEquals(CameraUsed.GLASSES, v.camera); assertEquals(CodeSource.PHOTO, v.codeSource); assertEquals(true, v.photoSent)
        assertFalse("genuine, new, seal not tampered: nothing to claim", v.claimable)
        assertEquals("Code is genuine. This unit is new: it was never activated or returned.", s.voice.said.last())
        assertEquals(listOf(EarconCue.CAPTURED, EarconCue.CAPTURED), s.voice.earcons)
        assertNull("one step: no poll", s.flow.polling)
        assertEquals(0, s.polls())
        assertEquals("a check never posts or claims by itself", 0, s.api.sent.count { it.path == "/v1/claims" })
    }

    @Test
    fun m5T05_twoSteps_theVerdictAtOnce_thenThePollSpeaksTheSealOnce() = runBlocking {
        val s = Setup(scope = this)
        s.photoOk()
        s.api.ok("POST /v1/authenticity/checks", PENDING)
        listOf(PENDING, PENDING, FINAL).forEach { s.api.ok("GET /v1/authenticity/checks/ck-1", it) }
        s.flow.start("site-1")
        val first = s.flow.view.value
        assertTrue(first.visualPending); assertFalse(first.check!!.final); assertNull(first.check!!.tamper)
        assertEquals(listOf(CheckText.SHOW_ME, FIRST_SAY), s.voice.said)
        assertFalse("no claim while the seal is checked (server: 409)", first.claimable)
        s.flow.polling!!.join()
        assertEquals("one GET a second until final", 3, s.polls())
        assertEquals(listOf(CheckFlow.AIM_MS, 1_000L, 1_000L, 1_000L), s.slept)
        assertEquals(listOf(CheckText.SHOW_ME, FIRST_SAY, "The seal shows tape over the original."), s.voice.said)
        val v = s.flow.view.value
        assertFalse(v.visualPending); assertEquals(true, v.check!!.tamper); assertTrue(v.check!!.final)
        assertTrue(v.claimable)
        assertNull(s.flow.polling)
    }

    @Test
    fun m5T05_noFinalCheckWithin45Polls_saysTheSealWasNotChecked_andAFailedPollIsRetried() = runBlocking {
        val s = Setup(scope = this)
        s.photoOk()
        s.api.ok("POST /v1/authenticity/checks", PENDING)
        s.api.on("GET /v1/authenticity/checks/ck-1", ApiResult.Offline("wifi"))
        s.api.ok("GET /v1/authenticity/checks/ck-1", PENDING)
        s.flow.start("site-1")
        s.flow.polling!!.join()
        assertEquals(CheckApi.POLL_MAX, s.polls())
        assertEquals(CheckText.VISUAL_TIMEOUT, s.voice.said.last())
        assertEquals("I couldn't check the seal.", CheckText.VISUAL_TIMEOUT)
        assertEquals(3, s.voice.said.size)
        assertFalse(s.flow.view.value.visualPending)
    }

    @Test
    fun m5T05_leavingDoneOrANewCheck_cancelsThePoll_andNothingMoreIsSaid() = runBlocking {
        val s = Setup(scope = this, sleep = { delay(it) }, aimMs = 0L)
        s.photoOk()
        s.api.ok("POST /v1/authenticity/checks", PENDING)
        s.api.ok("GET /v1/authenticity/checks/ck-1", FINAL)
        s.flow.start("site-1")
        val p = s.flow.polling!!
        s.flow.leave()
        p.join()
        assertTrue(p.isCancelled); assertNull(s.flow.polling)
        assertTrue("the card stays", s.flow.view.value.open)
        assertEquals(0, s.polls())
        assertEquals(2, s.voice.said.size)

        val t = Setup(scope = this, sleep = { delay(it) }, aimMs = 0L)
        t.photoOk()
        t.api.ok("POST /v1/authenticity/checks", PENDING)
        t.flow.start("site-1")
        val first = t.flow.polling!!
        t.api.reset("POST /v1/authenticity/checks")
        t.api.ok("POST /v1/authenticity/checks", AuthenticityClientTest.minimal("LIKELY_COUNTERFEIT",
            "This code is not signed by the maker. This is likely a counterfeit.", code = "bad_signature"))
        t.flow.start("site-1") // "check again": a new check
        first.join()
        assertTrue(first.isCancelled)
        assertEquals(Verdict.LIKELY_COUNTERFEIT, t.flow.view.value.check!!.verdict)
        assertEquals("a new key per check", listOf("key-3", "key-6"), t.checks().map { it.idempotencyKey })
        assertTrue("the old check's seal sentence is never said", t.voice.said.none { it == "The seal shows tape over the original." })
        assertEquals(0, t.polls())

        val u = Setup(scope = this, sleep = { delay(it) }, aimMs = 0L)
        u.photoOk()
        u.api.ok("POST /v1/authenticity/checks", PENDING)
        u.flow.start("site-1")
        val third = u.flow.polling!!
        u.flow.done()
        third.join()
        assertTrue(third.isCancelled); assertFalse(u.flow.view.value.open)
        assertEquals(CheckText.CLOSED, u.voice.said.last())
    }

    @Test
    fun m5T05_noQrInThePhoto_asksToHoldCloser_thenAPhoneScanChecksWithThatPhoto() = runBlocking {
        val s = Setup(SealShot.Taken(AuthenticityClientTest.photo(), emptyList(), CameraUsed.GLASSES), scanned = " $SEAL ")
        s.photoOk()
        s.api.ok("POST /v1/authenticity/checks", AuthenticityClientTest.RETURNED)
        s.flow.start("site-1")
        assertEquals(CheckState.NO_CODE, s.flow.view.value.state)
        assertEquals(CheckText.NO_CODE, s.voice.said.last())
        assertEquals("I can't read the seal code. Hold the seal closer and say check this box, or say scan with the phone.", CheckText.NO_CODE)
        assertEquals(EarconCue.ERROR, s.voice.earcons.last())
        assertTrue("nothing is sent without a code", s.api.sent.isEmpty())
        s.flow.scanWithPhone()
        assertEquals(1, s.scans)
        assertEquals(SEAL, s.checks().single().str("code"))
        assertEquals("the photo taken before goes with it", "cap-9", s.checks().single().str("capture_id"))
        assertEquals(CodeSource.PHONE_SCAN, s.flow.view.value.codeSource)
        assertEquals(CheckState.SHOWN, s.flow.view.value.state)
    }

    @Test
    fun m5T05_noPhotoOrNoScan_isSaid_andNothingIsSent() = runBlocking {
        val s = Setup(SealShot.Failed("No photo was taken."), scanned = null)
        s.flow.start("site-1")
        assertEquals(CheckState.NO_CODE, s.flow.view.value.state)
        assertEquals("No photo was taken. ${CheckText.NO_CODE}", s.voice.said.last())
        s.flow.scanWithPhone()
        assertEquals(CheckText.NO_SCAN, s.voice.said.last())
        assertTrue(s.api.sent.isEmpty())
        assertEquals("the phone camera is shown when it took the photo",
            CameraUsed.PHONE, Setup(SealShot.Taken(null, listOf(SEAL), CameraUsed.PHONE, "Used the phone camera.")).let { t ->
                t.api.ok("POST /v1/authenticity/checks", AuthenticityClientTest.minimal("GENUINE_NEW", "ok"))
                t.flow.start(null)
                assertEquals("Used the phone camera.", t.voice.said[1])
                assertNull("a photo that failed its face check is never uploaded", t.api.sent.firstOrNull { it.path.startsWith("/v1/captures") })
                assertNull("no site linked: the server picks it", t.checks().single().str("site_id"))
                assertEquals(false, t.flow.view.value.photoSent)
                t.flow.view.value.camera
            })
    }

    @Test
    fun m5T05_aPersonWhoMayNotUploadPhotos_isCheckedByCodeOnly() = runBlocking {
        val s = Setup()
        s.api.on("POST /v1/captures/uploads", ApiResult.Problem(403, "FIELD-AUTH-403-FORBIDDEN", "Forbidden", null))
        s.api.ok("POST /v1/authenticity/checks", AuthenticityClientTest.minimal("GENUINE_NEW", "Code is genuine."))
        s.flow.start("site-1")
        assertNull(s.checks().single().str("capture_id"))
        assertTrue(s.voice.said.contains(CheckText.CODE_ONLY))
        assertEquals(CheckState.SHOWN, s.flow.view.value.state); assertEquals(false, s.flow.view.value.photoSent)
    }

    @Test
    fun m5T05_photoConsentIsAskedOnce_thenAgreeOrCodeOnly() = runBlocking {
        val s = Setup()
        s.api.ok("POST /v1/captures/uploads", """{"upload_id":"up-1"}""")
        s.api.on("POST /v1/captures", ApiResult.Problem(403, LookApi.NO_CONSENT, "Privacy consent required", null),
            ApiResult.Ok(201, kotlinx.serialization.json.Json.parseToJsonElement("""{"id":"cap-7"}""") as kotlinx.serialization.json.JsonObject))
        s.api.ok("POST /v1/consents", """{"id":"con-1"}""")
        s.api.ok("POST /v1/authenticity/checks", AuthenticityClientTest.RETURNED)
        s.flow.start("site-1")
        assertEquals(CheckState.CONSENT, s.flow.view.value.state); assertTrue(s.flow.consentPending)
        assertEquals(CheckText.CONSENT_SPOKEN, s.voice.said.last())
        assertTrue(s.checks().isEmpty())
        s.flow.agree()
        assertEquals(1, s.api.sent.count { it.path == "/v1/consents" })
        assertEquals("cap-7", s.checks().single().str("capture_id"))
        assertEquals("one photo taken", 1, s.taken)

        val t = Setup()
        t.api.ok("POST /v1/captures/uploads", """{"upload_id":"up-1"}""")
        t.api.on("POST /v1/captures", ApiResult.Problem(403, LookApi.NO_CONSENT, "Privacy consent required", null))
        t.api.ok("POST /v1/authenticity/checks", AuthenticityClientTest.RETURNED)
        t.flow.start("site-1")
        t.flow.codeOnly()
        assertNull(t.checks().single().str("capture_id"))
        assertEquals(0, t.api.sent.count { it.path == "/v1/consents" })
    }

    @Test
    fun m5T05_networkFailure_tryAgainSendsTheSameKey_checkAgainANewOne() = runBlocking {
        val s = Setup()
        s.photoOk()
        s.api.on("POST /v1/authenticity/checks", ApiResult.Offline("wifi"), ApiResult.Ok(200,
            kotlinx.serialization.json.Json.parseToJsonElement(AuthenticityClientTest.RETURNED) as kotlinx.serialization.json.JsonObject))
        s.flow.start("site-1")
        assertEquals(CheckState.FAILED, s.flow.view.value.state); assertTrue(s.flow.view.value.canRetry)
        assertEquals("I couldn't reach Field. Try again.", s.voice.said.last())
        s.flow.retry()
        assertEquals(CheckState.SHOWN, s.flow.view.value.state)
        val keys = s.checks().map { it.idempotencyKey }
        assertEquals("a retry is the same request with the same key", 2, keys.size); assertEquals(keys[0], keys[1])
        assertEquals(s.checks()[0].body, s.checks()[1].body)
        s.flow.retry()
        assertEquals("nothing to retry after an answer", 2, s.checks().size)
    }

    @Test
    fun m5T05_forbiddenSiteAndAMissingPhoto_saySoAndActSensibly() = runBlocking {
        val s = Setup(SealShot.Taken(null, listOf(SEAL), CameraUsed.GLASSES))
        s.api.on("POST /v1/authenticity/checks", ApiResult.Problem(403, CheckApi.ERR_FORBIDDEN, "Forbidden", null))
        s.flow.start("site-1")
        assertEquals("You are not allowed to check boxes here.", s.voice.said.last())
        assertFalse("Today hides its card after a 403", s.flow.view.value.allowed)
        assertFalse(CheckText.cardVisible(linkedToSite = true, allowed = s.flow.view.value.allowed))
        s.flow.clear()
        assertFalse("a 403 is remembered after done", s.flow.view.value.allowed)
        s.flow.reset()
        assertTrue("another site or sign-in asks again", s.flow.view.value.allowed)

        val t = Setup(SealShot.Taken(null, listOf(SEAL), CameraUsed.GLASSES))
        t.api.on("POST /v1/authenticity/checks", ApiResult.Problem(422, CheckApi.ERR_SITE, "Pick a site", null))
        t.flow.start(null)
        assertEquals(CheckClient.PICK_SITE, t.voice.said.last())
        assertFalse(t.flow.view.value.canRetry)

        val u = Setup()
        u.photoOk()
        u.api.on("POST /v1/authenticity/checks", ApiResult.Problem(404, CheckApi.ERR_CAPTURE, "Capture not found", null),
            ApiResult.Ok(200, kotlinx.serialization.json.Json.parseToJsonElement(AuthenticityClientTest.minimal("GENUINE_NEW", "ok")) as kotlinx.serialization.json.JsonObject))
        u.flow.start("site-1")
        val sent = u.checks()
        assertEquals(listOf("cap-9", null), sent.map { it.str("capture_id") })
        assertTrue("another body gets another key", sent[0].idempotencyKey != sent[1].idempotencyKey)
        assertTrue(u.voice.said.contains(CheckText.PHOTO_GONE))
        assertEquals(CheckState.SHOWN, u.flow.view.value.state)

        val w = Setup(SealShot.Taken(null, listOf("SEAL1." + "x".repeat(1100)), CameraUsed.GLASSES))
        w.flow.start("site-1")
        assertEquals(CheckText.TOO_LONG, w.voice.said.last())
        assertTrue(w.api.sent.isEmpty())
    }

    @Test
    fun m5T05_makeAClaim_readsTheDraft_orSaysThereIsNothingToClaim_andTheEvidencePageOpens() = runBlocking {
        val s = Setup()
        s.flow.claim()
        assertEquals(CheckText.CHECK_FIRST, s.voice.said.last())
        s.photoOk()
        s.api.ok("POST /v1/authenticity/checks", AuthenticityClientTest.RETURNED)
        s.api.ok("POST /v1/claims", """{"claim_id":"cl-9","status":"draft","kind":"authenticity","check_id":"ck-1","look_id":null,
            "lines":[{"reason":"not_new","units":1,"pieces":0}],"text":"The unit was sold as new but was activated and returned.","source":"template"}""")
        s.api.ok("POST /v1/authenticity/checks/ck-1/link", """{"url":"/evidence/check/tok","path":"/evidence/check/tok","expires_at":"x"}""")
        s.flow.start("site-1")
        s.flow.claim()
        assertEquals("ck-1", s.api.last("/v1/claims").str("check_id"))
        assertEquals("Claim drafted. The unit was sold as new but was activated and returned. A supervisor approves it before it is sent.", s.voice.said.last())
        assertEquals("cl-9", s.flow.view.value.claim!!.claimId)
        assertEquals("http://pc:8080/evidence/check/tok", s.flow.evidence())
        assertEquals("http://pc:8080/evidence/check/tok", s.flow.view.value.evidenceUrl)
        assertEquals(CheckText.EVIDENCE_OPEN, s.voice.said.last())
        s.flow.closeEvidence()
        assertNull(s.flow.view.value.evidenceUrl)

        val t = Setup()
        t.photoOk()
        t.api.ok("POST /v1/authenticity/checks", AuthenticityClientTest.minimal("GENUINE_NEW", "ok", tamper = "false"))
        t.api.on("POST /v1/claims", ApiResult.Problem(422, CheckApi.ERR_NOTHING_TO_CLAIM, "Nothing to claim", null))
        t.flow.start("site-1")
        t.flow.claim()
        assertEquals("There is nothing to claim: the unit is new and the seal looks intact.", t.voice.said.last())
        assertNull(t.flow.view.value.claim)
    }

    @Test
    fun m5T05_aClaimWaitsForTheSealCheck() = runBlocking {
        val s = Setup(scope = this, sleep = { delay(it) }, aimMs = 0L)
        s.photoOk()
        s.api.ok("POST /v1/authenticity/checks", PENDING)
        s.flow.start("site-1")
        s.flow.claim()
        assertEquals(CheckText.VISUAL_PENDING, s.voice.said.last())
        assertEquals(0, s.api.sent.count { it.path == "/v1/claims" })
        s.flow.clear()
        assertNull(s.flow.polling)
    }
}
