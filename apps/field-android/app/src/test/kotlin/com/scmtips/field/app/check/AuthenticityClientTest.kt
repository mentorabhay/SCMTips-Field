package com.scmtips.field.app.check

import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.str
import com.scmtips.field.app.look.CameraUsed
import com.scmtips.field.app.look.ClaimText
import com.scmtips.field.app.look.LookJson
import com.scmtips.field.app.look.LookPhoto
import com.scmtips.field.app.look.ScriptedFieldApi
import com.scmtips.field.app.look.UploadResult
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M5-T05: the C3 calls against docs/design/M5_C3_CONTRACT.md §4 with a scripted field-api (the server side is built
 * in parallel on feat/m5-c3-authenticity; its routes were not called).
 */
class AuthenticityClientTest {
    private var keys = 0
    private fun client(api: ScriptedFieldApi, device: String? = "dev-1") = CheckClient(api, api, { device }, { "key-${++keys}" })

    companion object {
        fun photo() = LookPhoto(byteArrayOf(1, 2, 3), 1600, 1200, CameraUsed.GLASSES, 7L, 900, 1)

        /** The response example of contract §4.1, events written out. */
        val RETURNED = """
        {"check_id":"ck-1","final":true,"verdict":"RETURNED_REFURBISHED","tamper":true,
         "reasons":["history:activated","history:returned","visual:tape_over_seal"],
         "signals":{
           "code":{"status":"valid","oem":"kestrel-sample","oem_name":"Kestrel Optics (SAMPLE)","kid":"3f1c0000aaaabbbb",
                   "serial":"KSO-24-000102","sku":"KSO-BINO-842","sealed_at":"2026-09-30"},
           "registry":{"status":"found","sku":"KSO-BINO-842",
                       "events":[{"type":"manufactured","at":"2026-09-30","area":null},{"type":"shipped_to_seller","at":"2026-10-02","area":"Pune"},
                                 {"type":"delivered","at":"2026-10-05","area":null},{"type":"activated","at":"2026-10-12","area":null},
                                 {"type":"returned","at":"2026-10-20","area":null}],
                       "activated_at":"2026-10-12","returned_at":"2026-10-20","refurbished_at":null},
           "first_check":{"status":"first","first_checked_at":"2026-11-01T10:12:03Z","area":null},
           "visual":{"status":"done","capture_id":"cap-9","seal_found":true,"box":[100,200,500,400],"score":0.9,
                     "signs":["tape_over_seal"],"image":{"width":1600,"height":1200}}},
         "say":"Code is genuine. But this unit was activated on 12 October and returned on 20 October. It is not a new unit. The seal shows tape over the original.",
         "say_next":"The seal shows tape over the original.",
         "models":[{"model":"sam-3.1","purpose":"seal","latency_ms":640,"cost_usd":0.004,"outcome":"ok"},
                   {"model":"muse-spark-1.3","purpose":"seal_tamper","latency_ms":1900,"cost_usd":0.001,"outcome":"ok"}],
         "evidence_url":"/v1/authenticity/checks/ck-1/evidence","claim_id":null,
         "site_id":"site-1","capture_id":"cap-9","created_at":"2026-11-01T10:12:03Z","checked_by":"p-1"}
        """.trimIndent()

        /** A body per verdict, as small as the contract allows (R14, R12, R1, R6, R13). */
        fun minimal(verdict: String, say: String, tamper: String = "null", code: String = "valid", firstCheck: String = "first") = """
        {"check_id":"ck-$verdict","final":true,"verdict":"$verdict","tamper":$tamper,"reasons":[],
         "signals":{"code":{"status":"$code","oem":null,"oem_name":null,"kid":null,"serial":null,"sku":null,"sealed_at":null},
                    "registry":{"status":"not_asked","sku":null,"events":[],"activated_at":null,"returned_at":null,"refurbished_at":null},
                    "first_check":{"status":"$firstCheck","first_checked_at":"2026-10-28T09:00:00Z","area":null},
                    "visual":{"status":"none","capture_id":null,"seal_found":null,"box":null,"score":null,"signs":[],"image":null}},
         "say":"$say","say_next":null,"models":[],"evidence_url":"/v1/authenticity/checks/ck-$verdict/evidence","claim_id":null,
         "site_id":"site-1","capture_id":null,"created_at":"2026-11-01T10:00:00Z","checked_by":"p-1"}
        """.trimIndent()

        fun parsed(json: String): AuthenticityCheck = CheckJson.check(Json.parseToJsonElement(json).jsonObject)!!
    }

    @Test
    fun m5T05_theCheckRequest_carriesTheCodeAndNullsButNoArea() = runBlocking {
        val api = ScriptedFieldApi().apply { ok("POST /v1/authenticity/checks", RETURNED) }
        val r = client(api).check("key-own", "SEAL1.3f1c0000aaaabbbb.eyJ2IjoxfQ.c2ln", "cap-9", "site-1")
        assertTrue(r is CheckResult.Ok)
        val sent = api.last("/v1/authenticity/checks")
        assertEquals("POST", sent.method)
        assertEquals("the caller's key, so a retry sends the same one", "key-own", sent.idempotencyKey)
        assertEquals("SEAL1.3f1c0000aaaabbbb.eyJ2IjoxfQ.c2ln", sent.str("code"))
        assertEquals("cap-9", sent.str("capture_id")); assertEquals("site-1", sent.str("site_id"))
        assertFalse("the owner has not decided to send an area", "area" in sent.body!!)

        val bare = CheckApi.check("k", "QR-TEXT", null, null)
        assertEquals(JsonNull, bare.body!!["capture_id"]); assertEquals(JsonNull, bare.body!!["site_id"])
        assertEquals("GET", CheckApi.checkById("ck 1").method)
        assertEquals("/v1/authenticity/checks/ck+1", CheckApi.checkById("ck 1").path)
        assertEquals("/v1/authenticity/checks/ck-1/link", CheckApi.link("k", "ck-1").path)
        assertEquals("ck-1", CheckApi.claim("k", "ck-1").str("check_id"))
        assertNull("exactly one of look_id / check_id", CheckApi.claim("k", "ck-1").body!!["look_id"])
        assertEquals(45, CheckApi.POLL_MAX); assertEquals(1_000L, CheckApi.POLL_MS)
    }

    @Test
    fun m5T05_theSealPhotoGoesThroughTheCapturesApi_asASealPhotoWithoutATask() = runBlocking {
        val api = ScriptedFieldApi().apply {
            ok("POST /v1/captures/uploads", """{"upload_id":"up-1"}""")
            ok("POST /v1/captures", """{"id":"cap-9"}""")
        }
        assertEquals(UploadResult.Uploaded("cap-9"), client(api).uploadSeal(photo(), "site-1"))
        val cap = api.last("/v1/captures")
        assertEquals("seal_photo", cap.str("code_type")); assertEquals("authenticity", cap.str("code_value"))
        assertEquals("site-1", cap.str("site_id")); assertNull("no task", cap.body!!["task_id"])
        assertEquals("true", cap.body!!["blur_applied"].toString())
        assertEquals("1", cap.body!!["bystander_count"].toString())
        assertEquals("up-1", cap.str("crop_upload_id"))
        assertEquals(listOf("/v1/captures/uploads/up-1"), api.puts.map { it.first })
    }

    @Test
    fun m5T05_theContractBodyIsReadInFull() {
        val c = parsed(RETURNED)
        assertEquals("ck-1", c.checkId); assertTrue(c.final)
        assertEquals(Verdict.RETURNED_REFURBISHED, c.verdict); assertEquals(VerdictTone.AMBER, c.verdict.tone)
        assertEquals(true, c.tamper)
        assertEquals(listOf("history:activated", "history:returned", "visual:tape_over_seal"), c.reasons)
        assertEquals("Kestrel Optics (SAMPLE)", c.code!!.oemName); assertEquals("KSO-24-000102", c.code!!.serial)
        assertEquals(5, c.registry!!.events.size); assertEquals("Pune", c.registry!!.events[1].area)
        assertEquals("2026-10-20", c.registry!!.returnedAt); assertNull(c.registry!!.refurbishedAt)
        assertEquals("first", c.firstCheck!!.status)
        assertEquals(listOf(100.0, 200.0, 500.0, 400.0), c.visual!!.box); assertEquals(1600, c.visual!!.imageWidth)
        assertEquals(listOf("tape_over_seal"), c.visual!!.signs)
        assertEquals("The seal shows tape over the original.", c.sayNext)
        assertEquals(listOf("sam-3.1", "muse-spark-1.3"), c.models.map { it.model })
        assertEquals("/v1/authenticity/checks/ck-1/evidence", c.evidenceUrl); assertNull(c.claimId)
    }

    @Test
    fun m5T05_allFiveVerdictsParse_withTheirColours() {
        val cases = listOf(
            Triple("GENUINE_NEW", VerdictTone.GREEN, "Genuine and new"),
            Triple("GENUINE_PREVIOUSLY_ACTIVATED", VerdictTone.AMBER, "Genuine, but not new: activated before"),
            Triple("RETURNED_REFURBISHED", VerdictTone.AMBER, "Genuine, but not new: returned or refurbished"),
            Triple("CANNOT_VERIFY", VerdictTone.GREY, "Cannot verify"),
            Triple("LIKELY_COUNTERFEIT", VerdictTone.RED, "Likely counterfeit"),
        )
        for ((wire, tone, headline) in cases) {
            val c = parsed(minimal(wire, "Spoken."))
            assertEquals(wire, c.verdict.wire); assertEquals(tone, c.verdict.tone); assertEquals(headline, c.verdict.headline)
            assertEquals("Spoken.", c.say)
            assertNull("no photo: tamper null", c.tamper)
            assertEquals("none", c.visual!!.status)
        }
        val odd = parsed(minimal("SOMETHING_NEW", ""))
        assertEquals("an unknown verdict is never shown green", Verdict.UNKNOWN, odd.verdict)
        assertEquals(VerdictTone.GREY, odd.verdict.tone); assertEquals("SOMETHING_NEW", odd.verdictWire)
        assertEquals("Unknown answer.", CheckText.fallbackSay(odd))
        assertNull("a body without check_id is no check", CheckJson.check(Json.parseToJsonElement("""{"verdict":"GENUINE_NEW"}""").jsonObject))
        assertTrue("a body without final is final", parsed("""{"check_id":"c","verdict":"GENUINE_NEW"}""").final)
    }

    @Test
    fun m5T05_errorCodesBecomeTheContractsWords() = runBlocking {
        fun problem(status: Int, code: String?) = ApiResult.Problem(status, code, "x", null)
        val cases = listOf(
            problem(403, CheckApi.ERR_FORBIDDEN) to (CheckError.FORBIDDEN to "You are not allowed to check boxes here."),
            problem(422, CheckApi.ERR_SITE) to (CheckError.SITE to CheckClient.PICK_SITE),
            problem(404, CheckApi.ERR_CAPTURE) to (CheckError.CAPTURE_GONE to "The seal photo was not found on the server."),
            problem(404, CheckApi.ERR_CHECK) to (CheckError.OTHER to "That check is not there any more. Say check this box again."),
            problem(404, "FIELD-HTTP-404-NOT-FOUND") to (CheckError.NOT_ON_SERVER to "Box checks are not available on this server yet."),
            problem(422, CheckApi.ERR_VALIDATION) to (CheckError.INVALID to "The server could not read this code. Scan it again."),
        )
        for ((answer, expected) in cases) {
            val api = ScriptedFieldApi().apply { on("POST /v1/authenticity/checks", answer) }
            assertEquals(answer.code, CheckResult.Failed(expected.first, expected.second), client(api).check("k", "SEAL1.x", null, null))
        }
        val off = ScriptedFieldApi().apply { on("POST /v1/authenticity/checks", ApiResult.Offline("wifi")) }
        assertEquals(CheckResult.Failed(CheckError.OFFLINE, "I couldn't reach Field. Try again."), client(off).check("k", "SEAL1.x", null, null))
        val empty = ScriptedFieldApi().apply { ok("POST /v1/authenticity/checks", "{}") }
        assertEquals(CheckError.EMPTY, (client(empty).check("k", "c", null, null) as CheckResult.Failed).error)
        assertTrue(client(ScriptedFieldApi().apply { ok("GET /v1/authenticity/checks/ck-1", RETURNED) }).checkNow("ck-1") is CheckResult.Ok)
    }

    @Test
    fun m5T05_aClaimFromACheck_isAnAuthenticityClaimWithANullLookId() = runBlocking {
        val api = ScriptedFieldApi().apply {
            ok("POST /v1/claims", """{"claim_id":"cl-9","status":"draft","kind":"authenticity","check_id":"ck-1","look_id":null,
                "lines":[{"reason":"not_new","units":1,"pieces":0},{"reason":"tampered_seal","units":1,"pieces":0}],
                "text":"","source":"template","reasons":[],"evidence_url":"/v1/authenticity/checks/ck-1/evidence"}""", etag = "1-c9")
        }
        val r = client(api).claim("ck-1") as CheckClaimResult.Ok
        assertEquals("ck-1", api.last("/v1/claims").str("check_id"))
        assertEquals("authenticity", r.claim.kind); assertTrue(r.claim.authenticity)
        assertEquals("ck-1", r.claim.checkId); assertNull(r.claim.lookId)
        assertEquals("1-c9", r.claim.etag); assertEquals("Box check", r.claim.kindLabel)
        assertEquals("one unit: the reasons only, never 0 pieces", "not a new unit, seal tampered", ClaimText.lines(r.claim))
        assertEquals("Claim drafted. Not a new unit, seal tampered. A supervisor approves it before it is sent.", ClaimText.drafted(r.claim))

        fun refused(status: Int, code: String) = ScriptedFieldApi().apply { on("POST /v1/claims", ApiResult.Problem(status, code, "x", null)) }
        assertEquals(CheckClaimResult.NothingToClaim, client(refused(422, CheckApi.ERR_NOTHING_TO_CLAIM)).claim("ck-1"))
        assertEquals(CheckClaimResult.Pending, client(refused(409, CheckApi.ERR_CLAIM_PENDING)).claim("ck-1"))
        assertEquals(CheckClaimResult.Failed("Claims from a box check are not available on this server yet."),
            client(refused(422, CheckApi.ERR_VALIDATION)).claim("ck-1"))
    }

    @Test
    fun m5T05_lookClaimsParseAsBefore_andListsMixBothKinds() {
        val list = LookJson.claims(Json.parseToJsonElement("""{"items":[
            {"claim_id":"cl-1","status":"draft","look_id":"lk-1","title":"Delivery 1800000022","lines":[{"reason":"damaged","units":2}],"text":"Two packs arrived damaged."},
            {"claim_id":"cl-2","status":"draft","kind":"look","look_id":"lk-2","check_id":null,"lines":[{"reason":"pack_size","units":2,"pieces":4}],"text":""},
            {"claim_id":"cl-3","status":"draft","kind":"authenticity","look_id":null,"check_id":"ck-3","lines":[{"reason":"counterfeit","units":1,"pieces":0}],"text":""}],"count":3}""").jsonObject)
        assertEquals(listOf("look", "look", "authenticity"), list.map { it.kind })
        assertEquals(listOf("lk-1", "lk-2", null), list.map { it.lookId })
        assertEquals(listOf(null, null, "ck-3"), list.map { it.checkId })
        assertEquals(listOf(null, null, "Box check"), list.map { it.kindLabel })
        assertEquals("a look claim's lines are unchanged", "2 units, 4 pieces wrong pack size", ClaimText.lines(list[1]))
        assertEquals("likely counterfeit", ClaimText.lines(list[2]))
        assertEquals("Delivery 1800000022", list[0].title)
    }

    @Test
    fun m5T05_theEvidenceLinkIsSigned_andMadeAbsoluteByTheFlow() = runBlocking {
        val api = ScriptedFieldApi().apply { ok("POST /v1/authenticity/checks/ck-1/link", """{"url":"/evidence/check/tok","path":"/evidence/check/tok","expires_at":"x"}""") }
        assertEquals("/evidence/check/tok" to null, client(api).evidenceLink("ck-1"))
        assertTrue(api.last("/link").idempotencyKey!!.startsWith("key-"))
        assertEquals(null to "The evidence page is not available on this server yet.", client(ScriptedFieldApi()).evidenceLink("ck-1"))
    }
}
