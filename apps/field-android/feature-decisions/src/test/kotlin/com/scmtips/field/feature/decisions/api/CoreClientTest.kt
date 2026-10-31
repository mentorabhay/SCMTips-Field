package com.scmtips.field.feature.decisions.api

import com.scmtips.field.feature.decisions.FixedCredentials
import com.scmtips.field.feature.decisions.ScriptedHttp
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * Ported from the core's wearable app (api/OkHttpScmtipsApiTest). MockWebServer is not a resolved
 * dependency of this build (rule 2.4), so the wire is pinned one layer up: every [HttpCall] the client
 * makes (method, URL, headers, body) and how it reads every answer. OkHttpCoreHttpTest (Gradle) pins
 * the OkHttp layer.
 */
class CoreClientTest {
    private val deviceId = "3f1c2a9e-5b7d-4c11-9e2f-0a1b2c3d4e5f"
    private val token = "scmw_test_token"
    private val http = ScriptedHttp()
    private val creds = FixedCredentials(deviceId, token)

    private fun api(base: String = "http://core.test:8011/"): CoreClient = CoreClient(base, creds, http)

    private fun HttpCall.assertDeviceHeaders() {
        assertEquals("Bearer $token", headers["Authorization"])
        assertEquals(deviceId, headers["X-Device-Id"])
        assertEquals("lr", headers["X-Requested-With"])
    }

    private fun HttpCall.json(): JsonObject = Json.parseToJsonElement((body as HttpBody.Json).text).jsonObject

    @Test
    fun next_sendsDeviceHeaders_andParsesNullItem() = runBlocking {
        http.reply(200, """{"item":null}""")
        assertNull(api().next())
        val req = http.calls.single()
        assertEquals("GET", req.method)
        assertEquals("http://core.test:8011/v1/wearable/next", req.url)
        assertNull(req.body)
        req.assertDeviceHeaders()
    }

    @Test
    fun next_parsesItem_andIgnoresUnknownFields() = runBlocking {
        http.reply(200, """{"item":{"decision_id":"d1","title":"Late inbound","card":"Supplier A late","spoken":"brief","options":[{"letter":"A","option_id":"o1","title":"Air","committed":"12k","net":"-3k"}],"band":{"label":"Over 10k","step_up":true,"approvers":2},"deadline_at":"2026-11-03T17:00:00Z","waiting":3,"future_field":1}}""")
        val item = api().next()!!
        assertEquals("d1", item.decisionId)
        assertEquals("brief", item.spoken)
        assertEquals("A", item.options.single().letter)
        assertEquals(true, item.band!!.stepUp)
        assertEquals(2, item.band!!.approvers)
        assertEquals(3, item.waiting)
    }

    @Test
    fun briefDocument_isGetByDecisionId() = runBlocking {
        http.reply(200, """{"decision_id":"d1","template_text":"Supplier A is six days late."}""")
        val b = api().brief("d1")
        assertEquals("Supplier A is six days late.", b["template_text"]!!.jsonPrimitive.content)
        assertEquals("http://core.test:8011/v1/briefs/decision/d1", http.calls.single().url)
    }

    @Test
    fun challenge_and_command_sendIdempotencyKeyOnCommandsOnly() = runBlocking {
        http.reply(201, """{"nonce":"n1","expires_at":"x","ttl_seconds":120,"turn":1,"decision_id":"d1","status":"open","title":"t","brief":"b","options":[{"letter":"A","option_id":"o1","title":"Air","cost_total":12000,"committed_spend":{"amount":1},"band":{"label":"x"},"details":"d"}],"step_up_fresh":false,"step_up_waived":false,"confidence_floor":0.62}""")
        http.reply(200, """{"outcome":"readback","say":"Say confirm.","pending":{"intent":"approve"},"step_up_required":true,"next":{"nonce":"n2","expires_at":"x","turn":2},"decision":{"id":"d1","status":"open","version":4},"approval_id":null,"parsed":{"intent":"approve","slots":{"option":"A"},"normalized":"approve option a","score":0.9,"clarifier":null,"clarifier_slot":null}}""")
        val api = api()
        val ch = api.createChallenge("d1")
        assertEquals(0.62, ch.confidenceFloor, 1e-9)
        assertEquals("12000", ch.options.single().costTotal.toString())
        val r = api.sendCommand("n1", "approve option A", "idem-123")
        assertEquals("readback", r.outcome)
        assertTrue(r.stepUpRequired)
        assertEquals("n2", r.next!!.nonce)
        assertEquals("d1", r.decision!!.id)
        assertNull(r.approvalId)

        val c = http.calls[0]
        assertEquals("POST", c.method)
        assertEquals("http://core.test:8011/v1/voice/challenges", c.url)
        c.assertDeviceHeaders()
        assertNull(c.headers["Idempotency-Key"])
        assertEquals("d1", c.json()["decision_id"]!!.jsonPrimitive.content)

        val cmd = http.calls[1]
        assertEquals("http://core.test:8011/v1/voice/commands", cmd.url)
        cmd.assertDeviceHeaders()
        assertEquals("idem-123", cmd.headers["Idempotency-Key"])
        assertEquals("n1", cmd.json()["nonce"]!!.jsonPrimitive.content)
        assertEquals("approve option A", cmd.json()["transcript"]!!.jsonPrimitive.content)
    }

    @Test
    fun anyOther401_isUnauthorized() = runBlocking {
        http.reply(401, """{"type":"about:blank","title":"Unauthorized","status":401,"detail":"token expired","code":"token_expired"}""")
        try {
            api().next(); fail()
        } catch (e: CoreException.Unauthorized) {
            assertEquals("token_expired", e.problem?.code)
        }
    }

    @Test
    fun stepUp_wrongCode_isInvalidStepUpCode_notUnauthorized() = runBlocking {
        http.reply(401, """{"type":"about:blank","title":"Invalid code","status":401,"code":"invalid_code"}""")
        http.reply(200, """{"fresh":true,"method":"totp","verified_at":"2026-11-03T12:00:00Z","waived":false}""")
        val api = api()
        try {
            api.stepUp(StepUpMethod.TOTP, "000000"); fail()
        } catch (e: CoreException.InvalidStepUpCode) { /* expected */ }
        val ok = api.stepUp(StepUpMethod.BACKUP_CODE, " abcd-efgh ")
        assertTrue(ok.fresh)
        val first = http.calls[0]
        assertEquals("http://core.test:8011/v1/auth/step-up", first.url)
        assertEquals("POST", first.method)
        first.assertDeviceHeaders()
        val b = http.calls[1].json()
        assertEquals("backup_code", b["method"]!!.jsonPrimitive.content)
        assertEquals("abcd-efgh", b["code"]!!.jsonPrimitive.content)
    }

    @Test
    fun stepUpStatus_get() = runBlocking {
        http.reply(200, """{"fresh":false,"method":null,"verified_at":null,"waived":true}""")
        val s = api().stepUpStatus()
        assertTrue(s.waived)
        assertFalse(s.fresh)
        assertEquals("GET", http.calls.single().method)
        assertEquals("http://core.test:8011/v1/auth/step-up", http.calls.single().url)
    }

    @Test
    fun revoke_isDeleteWithBearer_204() = runBlocking {
        http.reply(204)
        api().revoke("sess-1")
        val req = http.calls.single()
        assertEquals("DELETE", req.method)
        assertEquals("http://core.test:8011/v1/wearable/sessions/sess-1", req.url)
        req.assertDeviceHeaders()
    }

    @Test
    fun sessions_readsItemsOrABareList() = runBlocking {
        http.reply(200, """{"items":[{"session_id":"s1","device_id":"d","device_model":"RAYBAN_META_GEN2","expires_at":"x","current":true},{"id":"s2"}]}""")
        http.reply(200, """[{"session_id":"s3"}]""")
        val api = api()
        assertEquals(listOf("s1", "s2"), api.sessions().map { it.sessionId })
        assertEquals(listOf("s3"), api.sessions().map { it.sessionId })
        assertEquals("http://core.test:8011/v1/wearable/sessions", http.calls[0].url)
    }

    @Test
    fun photo_isMultipart_withConsentAndAllFields() = runBlocking {
        http.reply(201, """{"id":"e1","subject_kind":"recovery_plan","subject_id":"22222222-2222-4222-8222-222222222222","label":"damaged shipment","faces_blurred":true,"mask":true,"created_at":"2026-11-03T12:00:00Z"}""")
        val jpeg = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 1, 2, 3)
        val r = api().uploadPhoto(PhotoUpload(jpeg, "image/jpeg", SubjectKind.RECOVERY_PLAN, "22222222-2222-4222-8222-222222222222", "damaged shipment", "pallet"))
        assertTrue(r.facesBlurred)
        assertTrue(r.mask)
        val req = http.calls.single()
        assertEquals("POST", req.method)
        assertEquals("http://core.test:8011/v1/evidence/photos", req.url)
        req.assertDeviceHeaders()
        val parts = (req.body as HttpBody.Multipart).parts
        val image = parts.first()
        assertEquals("image", image.name)
        assertEquals("evidence.jpg", image.fileName)
        assertEquals("image/jpeg", image.mimeType)
        assertTrue(image.bytes!!.contentEquals(jpeg))
        val fields = parts.drop(1).associate { it.name to it.value }
        assertEquals(mapOf("subject_kind" to "recovery_plan", "subject_id" to "22222222-2222-4222-8222-222222222222",
            "label" to "damaged shipment", "consent" to "true", "segment_prompt" to "pallet"), fields)
        assertTrue(parts.none { it.name.contains("audio") || it.name.contains("video") })
    }

    @Test
    fun photo_withoutSegmentPrompt_omitsThatField_andRejectsOversizeAndBadInput() = runBlocking {
        http.reply(201, """{"id":"e1","subject_kind":"action","subject_id":"s","label":"missing part","faces_blurred":false,"mask":false,"created_at":"x"}""")
        val png = byteArrayOf(0x89.toByte(), 'P'.code.toByte(), 'N'.code.toByte(), 'G'.code.toByte())
        api().uploadPhoto(PhotoUpload(png, "image/png", SubjectKind.ACTION, "s", "missing part"))
        val parts = (http.calls.single().body as HttpBody.Multipart).parts
        assertEquals("evidence.png", parts.first().fileName)
        assertTrue(parts.none { it.name == "segment_prompt" })
        for (bad in listOf(
            PhotoUpload(ByteArray(8 * 1024 * 1024 + 1), "image/jpeg", SubjectKind.ACTION, "s", "x"),
            PhotoUpload(png, "image/gif", SubjectKind.ACTION, "s", "x"),
            PhotoUpload(png, "image/png", SubjectKind.ACTION, "s", " "),
            PhotoUpload(png, "image/png", SubjectKind.ACTION, "s", "x", "p".repeat(81)),
        )) {
            try {
                api().uploadPhoto(bad); fail()
            } catch (e: CoreException.Invalid) { /* expected */ }
        }
        assertEquals(1, http.calls.size)
    }

    @Test
    fun baseUrlWithPathPrefix_isKept() = runBlocking {
        http.reply(200, """{"item":null}""")
        api("https://core.test/scmtips/").next()
        assertEquals("https://core.test/scmtips/v1/wearable/next", http.calls.single().url)
    }

    @Test
    fun problemDocument_isSurfaced_onOtherErrors() = runBlocking {
        http.reply(409, """{"type":"about:blank","title":"Challenge expired","status":409,"detail":"ask again","code":"challenge_expired"}""")
        try {
            api().sendCommand("n1", "confirm", "k"); fail()
        } catch (e: CoreException.Http) {
            assertEquals(409, e.status)
            assertEquals("challenge_expired", e.problem?.code)
            assertEquals("Challenge expired", e.message)
        }
    }

    @Test
    fun noToken_meansUnauthorized_withoutNetwork() = runBlocking {
        creds.token = null
        try {
            api().next(); fail()
        } catch (e: CoreException.Unauthorized) { /* expected */ }
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun noAnswer_orAnUnreadableOne_isNetwork() = runBlocking {
        http.fail()
        http.reply(200, "<html>proxy</html>")
        http.reply(200, """{"item":{"title":"no id"}}""")
        repeat(3) {
            try {
                api().next(); fail()
            } catch (e: CoreException.Network) { /* expected */ }
        }
    }

    @Test
    fun secretsNeverAppearInACallsText() {
        val call = HttpCall("POST", "http://x/v1/briefs/spoken", mapOf("Authorization" to "Bearer secret-1", "X-Core-Token" to "secret-2", "X-Device-Id" to "dev"),
            HttpBody.Json("""{"password":"secret-3"}"""))
        val text = call.toString() + HttpReply(200, """{"access_token":"secret-4"}""").toString()
        assertFalse(text, listOf("secret-1", "secret-2", "secret-3", "secret-4").any { it in text })
        assertTrue(text.contains("dev"))
    }
}
