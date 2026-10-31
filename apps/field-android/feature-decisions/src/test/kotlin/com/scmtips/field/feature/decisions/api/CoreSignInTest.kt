package com.scmtips.field.feature.decisions.api

import com.scmtips.field.feature.decisions.ScriptedHttp
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.util.Base64

/** F2 sign-in against `POST {core}/v1/auth/app/token` (handover 01): request, answer, refusals. */
class CoreSignInTest {
    private val http = ScriptedHttp()
    private val deviceId = "3f1c2a9e-5b7d-4c11-9e2f-0a1b2c3d4e5f"

    private fun jwt(claims: String): String {
        val enc = Base64.getUrlEncoder().withoutPadding()
        return enc.encodeToString("""{"alg":"EdDSA","kid":"scmtips-core-ed25519-1"}""".toByteArray()) + "." +
            enc.encodeToString(claims.toByteArray()) + ".sig"
    }

    private val claims = """{"iss":"scmtips-core","aud":"scmtips-core","sub":"u-1","tenant_id":"t-1","roles":["approver"],"sites":["site-1","site-2"],"permissions":["voice.approve"],"email":"approver@sample.test","device_id":"$deviceId"}"""

    private fun answer(withClaims: Boolean = true) = """{"access_token":"${jwt(claims)}","token_type":"Bearer","expires_in":3600,
        ${if (withClaims) "\"claims\":$claims," else ""}
        "wearable":{"session_id":"ws-1","token":"scmw_secret","expires_at":"2026-11-03T20:00:00Z","device_id":"$deviceId"},
        "user":{"id":"u-1","display_name":"Approver Sample","email":"approver@sample.test"},
        "capabilities":{"approve_decisions":true,"field_operator":false},"future":1}"""

    @Test
    fun passwordSignIn_postsTheHandoverBody_withTheLrHeader_andReadsTheAnswer() = runBlocking {
        http.reply(200, answer())
        val t = CoreSignIn("http://192.168.1.20:8011/", http).signIn(SignInMethod.Password(" approver@sample.test ", "pw"), deviceId, DeviceModel.RAYBAN_META_GEN2)
        val call = http.calls.single()
        assertEquals("POST", call.method)
        assertEquals("http://192.168.1.20:8011/v1/auth/app/token", call.url)
        assertEquals("lr", call.headers["X-Requested-With"])
        assertNull(call.headers["Authorization"])
        val body = Json.parseToJsonElement((call.body as HttpBody.Json).text).jsonObject
        assertEquals("approver@sample.test", body["email"]!!.jsonPrimitive.content)
        assertEquals("pw", body["password"]!!.jsonPrimitive.content)
        assertEquals(deviceId, body["device_id"]!!.jsonPrimitive.content)
        assertEquals("RAYBAN_META_GEN2", body["device_model"]!!.jsonPrimitive.content)
        assertEquals(false, body["display_capable"]!!.jsonPrimitive.boolean)
        assertEquals("scmtips-field", body["client"]!!.jsonPrimitive.content)
        assertNull(body["pairing_code"])

        assertEquals("t-1", t.tenantId)
        assertEquals(listOf("site-1", "site-2"), t.sites)
        assertEquals(listOf("voice.approve"), t.permissions)
        assertEquals("scmw_secret", t.wearable.token)
        assertEquals(deviceId, t.wearable.deviceId)
        assertEquals("ws-1", t.wearable.sessionId)
        assertEquals(CoreUser("u-1", "Approver Sample", "approver@sample.test"), t.user)
        assertEquals(Capabilities(approveDecisions = true, fieldOperator = false), t.capabilities)
        assertEquals(3600, t.expiresInSeconds)
        // Nothing secret in the texts the app could log.
        val logged = t.toString() + call.toString() + SignInMethod.Password("a@b", "pw").toString()
        assertFalse(logged, listOf("scmw_secret", t.accessToken, "\"pw\"", "password=pw").any { it in logged })
    }

    @Test
    fun pairingCodeSignIn_sendsTheCodeInsteadOfEmailAndPassword_phoneOnly() = runBlocking {
        http.reply(200, answer(withClaims = false))
        val t = CoreSignIn("http://core.test", http).signIn(SignInMethod.PairingCode(" AB12CD34 "), deviceId, DeviceModel.PHONE_ONLY)
        val body = Json.parseToJsonElement((http.calls.single().body as HttpBody.Json).text).jsonObject
        assertEquals("AB12CD34", body["pairing_code"]!!.jsonPrimitive.content)
        assertEquals("PHONE_ONLY", body["device_model"]!!.jsonPrimitive.content)
        assertNull(body["email"])
        assertNull(body["password"])
        // Without a "claims" object the claims come from the token itself.
        assertEquals("t-1", t.tenantId)
        assertEquals(listOf("site-1", "site-2"), t.sites)
        assertFalse(SignInMethod.PairingCode("AB12CD34").toString().contains("AB12CD34"))
    }

    @Test
    fun refusalsBecomeWordsThePersonCanActOn() = runBlocking {
        val cases = listOf(
            401 to """{"title":"Unauthorized","status":401,"code":"invalid_credentials"}""",
            403 to """{"detail":{"code":"pairing_required","message":"strict sign-in"}}""",
            429 to """{"title":"Too Many Requests"}""",
            503 to """{"code":"core_tokens_unavailable"}""",
        )
        val texts = cases.map { (status, body) ->
            http.reply(status, body)
            try {
                CoreSignIn("http://core.test", http).signIn(SignInMethod.Password("a@b.c", "x"), deviceId, DeviceModel.PHONE_ONLY)
                throw AssertionError("no refusal for $status")
            } catch (e: SignInException) {
                assertEquals(status, e.status)
                e.code to e.message!!
            }
        }
        assertEquals("The e-mail or password is not right.", texts[0].second)
        assertEquals("invalid_credentials", texts[0].first)
        assertEquals("pairing_required", texts[1].first)
        assertTrue(texts[1].second.contains("pairing code"))
        assertTrue(texts[2].second.startsWith("Too many tries"))
        assertTrue(texts[3].second.contains("core_tokens_unavailable"))
    }

    @Test
    fun badInputIsRefusedBeforeAnythingIsSent() = runBlocking {
        val bad = listOf(
            SignInMethod.Password("not-an-email", "pw") to deviceId,
            SignInMethod.Password("a@b.c", "") to deviceId,
            SignInMethod.PairingCode("  ") to deviceId,
            SignInMethod.PairingCode("AB 12") to deviceId,
            SignInMethod.Password("a@b.c", "pw") to "short",
            SignInMethod.Password("a@b.c", "pw") to "bad id with spaces!",
        )
        for ((m, id) in bad) {
            try {
                CoreSignIn("http://core.test", http).signIn(m, id, DeviceModel.PHONE_ONLY); fail("$m $id")
            } catch (e: SignInException) {
                assertEquals(0, e.status)
            }
        }
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun noAnswer_orAnAnswerWithoutTheWearableSession_isAClearRefusal() = runBlocking {
        http.fail()
        http.reply(200, """{"access_token":"x.e30.y","user":{"id":"u"}}""")
        val messages = (1..2).map {
            try {
                CoreSignIn("http://core.test:8011", http).signIn(SignInMethod.Password("a@b.c", "x"), deviceId, DeviceModel.PHONE_ONLY); fail(); ""
            } catch (e: SignInException) {
                e.message!!
            }
        }
        assertTrue(messages[0], messages[0].contains("Cannot reach SCMTIPS at http://core.test:8011"))
        assertTrue(messages[1], messages[1].contains("wearable"))
    }
}
