package com.scmtips.field.app.look

import com.scmtips.field.app.jobs.ApiRequest
import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.JobTransport
import com.scmtips.field.app.jobs.num
import com.scmtips.field.app.jobs.str
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Scripted field-api for M5 (test code only): answers by "METHOD path" from a script, records every
 * request and every PUT. Unscripted calls answer 404 like a field-api that does not have the route yet.
 */
class ScriptedFieldApi : JobTransport, BytesPort {
    val sent = mutableListOf<ApiRequest>()
    val puts = mutableListOf<Pair<String, ByteArray>>()
    private val script = mutableMapOf<String, ArrayDeque<ApiResult>>()

    /** Replaces whatever [route] answered so far. */
    fun reset(route: String) { script.remove(route) }

    fun on(route: String, vararg answers: ApiResult) {
        script.getOrPut(route) { ArrayDeque() }.addAll(answers)
    }

    fun ok(route: String, json: String, etag: String? = null) = on(route, ApiResult.Ok(200, Json.parseToJsonElement(json).jsonObject, etag))

    override suspend fun send(request: ApiRequest): ApiResult {
        sent += request
        val key = "${request.method} ${request.path}"
        val q = script[key] ?: script.entries.firstOrNull { (k, _) -> k.endsWith("*") && key.startsWith(k.dropLast(1)) }?.value
        return q?.let { if (it.size > 1) it.removeFirst() else it.first() } ?: ApiResult.Problem(404, "FIELD-HTTP-404-NOT-FOUND", "Not Found", null)
    }

    override suspend fun put(path: String, bytes: ByteArray, contentType: String): ApiResult {
        puts += path to bytes
        return script["PUT $path"]?.first() ?: ApiResult.Ok(204, JsonObject(emptyMap()))
    }

    fun last(pathPart: String): ApiRequest = sent.last { pathPart in it.path }
    fun paths(): List<String> = sent.map { "${it.method} ${it.path}" }

    /** The happy path of contract §2 for one look (upload session, PUT, capture, look). */
    fun scriptLook(lookJson: String = CONTRACT_LOOK) {
        ok("POST /v1/captures/uploads", """{"upload_id":"up-1","put_url":"/v1/captures/uploads/up-1","method":"PUT"}""")
        ok("POST /v1/captures", """{"id":"cap-1","task_line_id":null,"on_task":false}""")
        ok("POST /v1/vision/looks", lookJson)
    }

    companion object {
        /** The response example of docs/design/M5_CONTRACT.md §2 (instances shortened to three). */
        val CONTRACT_LOOK = """
        {"look_id":"lk-1","source":"model","image":{"capture_id":"cap-1","width":1920,"height":1440},
         "instances":[
           {"n":2,"box":[300,100,500,300],"polygon":null,"score":0.91,"damaged":true,"damage_note":"torn",
            "label":{"read":true,"pieces_per_unit":12,"batch":null,"expiry":null,"raw":"x"}},
           {"n":1,"box":[10,20,210,220],"polygon":[[10,20],[210,20],[210,220],[10,220]],"score":0.93,"damaged":false,"damage_note":null,
            "label":{"read":true,"pieces_per_unit":6,"batch":"B2411","expiry":"2027-03","raw":"..."}},
           {"n":3,"box":[600,100,800,300],"score":0.88,"damaged":false,"label":{"read":false}}],
         "counts":{"expected":20,"seen":20,"damaged":2,"good":18},
         "pack":{"expected_pieces_per_unit":12,"mismatches":[{"n":7,"pieces_per_unit":10}],"pieces_difference":-4},
         "expiry":{"window_days":90,"flagged":[{"n":3,"expiry":"2026-12","reason":"near"}],"batches":["B2411"]},
         "proposal":{"receive":18,"flag":2,"reasons":["2 damaged","2 packs hold 10, not 12: 4 pieces short"]},
         "say":"Twenty of twenty. Two damaged. Two packs hold 10, not 12: 4 pieces short.",
         "models":[{"model":"sam-3.1","purpose":"instances","latency_ms":840,"cost_usd":0.004,"outcome":"ok"}],
         "reasons":[]}
        """.trimIndent()
    }
}

class LookClientTest {
    private val photo = LookPhoto(byteArrayOf(1, 2, 3, 4), 640, 480, CameraUsed.GLASSES, 1_793_000_000_000L, 900, 1)
    private var keys = 0
    private fun client(api: ScriptedFieldApi, device: String? = "dev-1") = LookClient(api, api, { device }, { "key-${++keys}" })

    @Test
    fun m5B01_uploadGoesThroughTheCapturesApi_withBlurAndAUniqueLookCode() = runBlocking {
        val api = ScriptedFieldApi().apply { scriptLook() }
        val r = client(api).upload(photo, "t-1", "site-1", "pack")
        assertEquals(UploadResult.Uploaded("cap-1"), r)
        assertEquals(listOf("POST /v1/captures/uploads", "POST /v1/captures"), api.paths())
        val up = api.sent[0]
        assertEquals("dev-1", up.str("device_id"))
        assertEquals(LookApi.sha256(photo.jpeg), up.str("sha256"))
        assertEquals("9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a", up.str("sha256"))
        assertEquals(4.0, up.num("bytes")); assertEquals("image/jpeg", up.str("content_type"))
        assertEquals("/v1/captures/uploads/up-1", api.puts.single().first)
        assertArrayEquals(photo.jpeg, api.puts.single().second)
        val cap = api.sent[1]
        assertEquals("t-1", cap.str("task_id")); assertEquals("site-1", cap.str("site_id"))
        assertEquals(true, (cap.body!!["blur_applied"] as JsonPrimitive).booleanOrNull)
        assertEquals(1.0, cap.num("bystander_count"))
        assertEquals("look", cap.str("code_type")); assertEquals("look-key-2", cap.str("code_value"))
        assertEquals("pack", cap.str("object_class")); assertEquals("up-1", cap.str("crop_upload_id"))
        assertEquals(1_793_000_000_000.0, cap.num("shutter_timestamp"))
        assertTrue("every write carries an idempotency key", api.sent.all { it.idempotencyKey != null })
    }

    @Test
    fun m5B01_noConsentIsItsOwnAnswer_andConsentIsRecordedForTheSiteAndDevice() = runBlocking {
        val api = ScriptedFieldApi()
        api.ok("POST /v1/captures/uploads", """{"upload_id":"up-1"}""")
        api.on("POST /v1/captures", ApiResult.Problem(403, LookApi.NO_CONSENT, "Privacy consent required", null))
        api.ok("POST /v1/consents", """{"id":"con-1","granted":true}""")
        val c = client(api)
        assertEquals(UploadResult.NeedsConsent, c.upload(photo, "t-1", "site-1", "pack"))
        assertTrue(c.consent("site-1"))
        val con = api.last("/v1/consents")
        assertEquals("site-1", con.str("site_id")); assertEquals("dev-1", con.str("device_id"))
        assertEquals("f1-2026-11", con.str("consent_version")); assertEquals("site_and_bystander_privacy", con.str("consent_type"))
    }

    @Test
    fun m5B01_uploadRefusals() = runBlocking {
        assertTrue(client(ScriptedFieldApi(), device = null).upload(photo, "t", "s", "pack") is UploadResult.Failed)
        val big = LookPhoto(ByteArray(LookApi.MAX_BYTES + 1), 640, 480, CameraUsed.PHONE, 0, 0, 0)
        assertTrue(client(ScriptedFieldApi()).upload(big, "t", "s", "pack") is UploadResult.Failed)
        val offline = ScriptedFieldApi().apply { on("POST /v1/captures/uploads", ApiResult.Offline("no route")) }
        assertEquals(UploadResult.Failed(LookClient.OFFLINE), client(offline).upload(photo, "t", "s", "pack"))
        val putFails = ScriptedFieldApi().apply {
            ok("POST /v1/captures/uploads", """{"upload_id":"up-9"}""")
            on("PUT /v1/captures/uploads/up-9", ApiResult.Problem(422, "FIELD-CAP-422-SHA256", "Crop sha256 mismatch", null))
        }
        assertEquals(UploadResult.Failed("Crop sha256 mismatch"), client(putFails).upload(photo, "t", "s", "pack"))
        assertEquals("no capture without the bytes", listOf("POST /v1/captures/uploads"), putFails.paths())
    }

    @Test
    fun m5B01_lookRequestAndTheContractResponse() = runBlocking {
        val api = ScriptedFieldApi().apply { scriptLook() }
        val r = client(api).look("t-1", "l-1", "cap-1", LookCase.GROCERY) as LookResult.Ok
        val req = api.last("/v1/vision/looks")
        assertEquals("POST", req.method)
        assertEquals("t-1", req.str("task_id")); assertEquals("l-1", req.str("line_id")); assertEquals("cap-1", req.str("capture_id"))
        assertEquals("pack", req.str("object")); assertEquals("grocery", req.str("case"))
        assertTrue(req.idempotencyKey != null)
        val l = r.look
        assertEquals("lk-1", l.lookId); assertEquals("model", l.source); assertEquals("cap-1", l.captureId)
        assertEquals(1920, l.imageWidth); assertEquals(1440, l.imageHeight)
        assertEquals("instances sorted by n", listOf(1, 2, 3), l.instances.map { it.n })
        assertEquals(4, l.instances[0].polygon!!.size)
        assertEquals(listOf(300.0, 100.0, 500.0, 300.0), l.instances[1].box)
        assertTrue(l.instances[1].damaged); assertEquals("torn", l.instances[1].damageNote)
        assertEquals(LabelRead(true, 6, "B2411", "2027-03"), l.instances[0].label)
        assertEquals(LabelRead(false, null, null, null), l.instances[2].label)
        assertEquals(LookCounts(20, 20, 2, 18), l.counts)
        assertEquals(1, l.packMismatches); assertEquals(-4, l.piecesDifference)
        assertEquals(1, l.expiryFlagged); assertEquals(listOf("B2411"), l.batches)
        assertEquals(Proposal(18, 2, listOf("2 damaged", "2 packs hold 10, not 12: 4 pieces short")), l.proposal)
        assertEquals(ModelCall("sam-3.1", "instances", 840, "ok"), l.models.single())
        assertEquals(false, l.rulesOnly)
    }

    @Test
    fun m5B01_rulesOnlyLook_andALookRouteThatIsNotThereYet() = runBlocking {
        val rules = ScriptedFieldApi().apply {
            ok("POST /v1/vision/looks", """{"look_id":"lk-2","source":"rules","image":{"capture_id":"cap-1","width":640,"height":480},
              "instances":[],"counts":{"expected":12,"seen":null,"damaged":null,"good":null},"pack":null,"expiry":null,
              "proposal":null,"say":"No model answered. Count them and say the number.","models":[],"reasons":["no key"]}""")
        }
        val l = (client(rules).look("t", null, "cap-1", LookCase.GENERIC) as LookResult.Ok).look
        assertTrue(l.rulesOnly); assertNull(l.counts.seen); assertNull(l.proposal); assertEquals(listOf("no key"), l.reasons)
        assertEquals("line_id is sent as null", "null", rules.last("/v1/vision/looks").body!!["line_id"].toString())
        assertEquals(LookResult.Failed(LookClient.NOT_YET), client(ScriptedFieldApi()).look("t", null, "c", LookCase.PHARMACY))
    }

    @Test
    fun m5B03_claimsDecisionsConfirmAndList() = runBlocking {
        val api = ScriptedFieldApi()
        api.ok("POST /v1/claims", """{"claim_id":"cl-1","status":"draft","lines":[{"reason":"damaged","units":2,"pieces":null},
            {"reason":"pack_size","units":2,"pieces":4}],"text":"Two packs damaged; two packs hold 10, not 12.","source":"model","reasons":[],
            "evidence_url":"","look_id":"lk-1","version":1}""", etag = "1-aa11")
        api.ok("GET /v1/claims?status=draft&limit=50", """{"items":[{"claim_id":"cl-1","status":"draft","lines":[],"text":"t"}],"count":1}""")
        api.ok("GET /v1/claims/cl-1", """{"claim_id":"cl-1","status":"draft"}""", etag = "1-aa11")
        api.ok("POST /v1/claims/cl-1/decision", """{"status":"pending_confirm","say":"Approve the claim for 2 damaged packs? Say confirm.","confirm_by":"2026-11-01T10:00:10Z"}""", etag = "2-bb22")
        api.ok("POST /v1/claims/cl-1/confirm", """{"status":"approved","say":"Claim approved. Sent to the supplier (simulated)."}""", etag = "3-cc33")
        val c = client(api)
        val claim = (c.claim("lk-1") as ClaimResult.Ok).claim
        assertEquals("lk-1", api.last("/v1/claims").str("look_id"))
        assertEquals(listOf(ClaimLine("damaged", 2, null), ClaimLine("pack_size", 2, 4)), claim.lines)
        assertNull("an empty evidence path is no path", claim.evidenceUrl)
        assertEquals("the ETag header is kept", "1-aa11", claim.etag)
        assertEquals(1, (c.drafts() as ClaimsList.Ok).claims.size)
        assertEquals("1-aa11", c.etag("cl-1"))
        val d = (c.decide("cl-1", approve = false, reason = "photo too dark", etag = "1-aa11") as StepResult.Ok).step
        val dreq = api.last("/decision")
        assertEquals("reject", dreq.str("decision")); assertEquals("photo too dark", dreq.str("reason"))
        assertEquals(mapOf("If-Match" to "1-aa11"), dreq.headers)
        assertEquals("pending_confirm", d.status); assertEquals("2026-11-01T10:00:10Z", d.confirmBy); assertEquals("2-bb22", d.etag)
        c.decide("cl-1", approve = true, reason = null, etag = "1-aa11")
        assertEquals("approve", api.last("/decision").str("decision")); assertNull(api.last("/decision").str("reason"))
        assertEquals("approved", (c.confirm("cl-1", "2-bb22", "confirm") as StepResult.Ok).step.status)
        val creq = api.last("/confirm")
        assertEquals(mapOf("If-Match" to "2-bb22"), creq.headers); assertEquals("confirm", creq.str("words"))
        assertTrue(api.sent.filter { it.method == "POST" }.all { it.idempotencyKey != null })
        assertNull("GET carries no key", api.last("?status=draft").idempotencyKey)
        assertTrue("only decisions and confirms carry If-Match", api.sent.filter { it.headers.isNotEmpty() }.all { it.path.endsWith("/decision") || it.path.endsWith("/confirm") })
    }

    @Test
    fun m5B03_aPersonWhoDoesNotDecideClaimsGetsNoList() = runBlocking {
        val api = ScriptedFieldApi().apply { on("GET /v1/claims?status=draft&limit=50", ApiResult.Problem(403, "FIELD-AUTH-403", "Forbidden", null)) }
        assertEquals(ClaimsList.NotAllowed, client(api).drafts())
        val late = ScriptedFieldApi().apply { on("POST /v1/claims/c/confirm", ApiResult.Problem(422, "FIELD-CLM-422-CONFIRM-EXPIRED", "Confirm window passed", null)) }
        assertEquals(StepResult.Failed("Confirm window passed", 422, "FIELD-CLM-422-CONFIRM-EXPIRED"), client(late).confirm("c", "2-x", null))
    }

    @Test
    fun m5B02_evidenceLinkIsSignedByTheServer_andMadeAbsolute() = runBlocking {
        val api = ScriptedFieldApi().apply {
            ok("POST /v1/evidence/documents/4900000101/link?year=2026", """{"url":"/evidence/tok.sig","path":"/evidence/tok.sig","expires_at":"x"}""")
        }
        val (url, why) = client(api).evidenceLink("4900000101", "2026")
        assertEquals("/evidence/tok.sig", url); assertNull(why)
        assertNull("year is a query parameter", api.last("/link").str("year"))
        assertEquals("http://192.168.1.5:8080/evidence/tok.sig", LookApi.absolute("http://192.168.1.5:8080/", "/evidence/tok.sig"))
        assertEquals("https://x.example/e/1", LookApi.absolute("http://pc:8080", "https://x.example/e/1"))
        val missing = client(ScriptedFieldApi()).evidenceLink("1", null)
        assertNull(missing.first); assertEquals("The evidence page is not available on this server yet.", missing.second)
    }
}
