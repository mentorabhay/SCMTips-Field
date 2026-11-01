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
import org.junit.Test

/** M5-L contract §1: the two new ways into `POST /v1/auth/app/token` (e-mail code, demo) and their neutral refusals. */
class CoreSignInWaysTest {
    private val http = ScriptedHttp()
    private val deviceId = "3f1c2a9e-5b7d-4c11-9e2f-0a1b2c3d4e5f"
    private val url = "http://core.test/v1/auth/app/token"

    private fun body(m: SignInMethod) =
        Json.parseToJsonElement((CoreSignIn.request(url, m, deviceId, DeviceModel.PHONE_ONLY).body as HttpBody.Json).text).jsonObject

    @Test
    fun m5L01_emailCode_sendsEmailAndEmailCode_only_withTheDeviceFields() {
        val b = body(SignInMethod.EmailCode(" judge01@sample-drone-oem.example ", "123 456"))
        assertEquals("judge01@sample-drone-oem.example", b["email"]!!.jsonPrimitive.content)
        assertEquals("123456", b["email_code"]!!.jsonPrimitive.content)
        assertNull(b["password"]); assertNull(b["pairing_code"]); assertNull(b["demo"])
        assertEquals(deviceId, b["device_id"]!!.jsonPrimitive.content)
        assertEquals("PHONE_ONLY", b["device_model"]!!.jsonPrimitive.content)
        assertEquals(false, b["display_capable"]!!.jsonPrimitive.boolean)
        assertEquals("scmtips-field", b["client"]!!.jsonPrimitive.content)
        assertFalse(SignInMethod.EmailCode("a@b.c", "123456").toString().contains("123456"))
    }

    @Test
    fun m5L01_demo_sendsDemoTrue_andNoCredentials() {
        val b = body(SignInMethod.Demo)
        assertEquals(true, b["demo"]!!.jsonPrimitive.boolean)
        assertNull(b["email"]); assertNull(b["password"]); assertNull(b["email_code"]); assertNull(b["pairing_code"])
        assertEquals(deviceId, b["device_id"]!!.jsonPrimitive.content)
        assertEquals("lr", CoreSignIn.request(url, SignInMethod.Demo, deviceId, DeviceModel.PHONE_ONLY).headers["X-Requested-With"])
    }

    @Test
    fun m5L01_aCodeThatIsNotSixDigits_orNoEmail_isRefusedBeforeAnythingIsSent() = runBlocking {
        for (m in listOf(SignInMethod.EmailCode("a@b.c", "12345"), SignInMethod.EmailCode("a@b.c", "12345a"),
            SignInMethod.EmailCode("a@b.c", "1234567"), SignInMethod.EmailCode("nobody", "123456"))) {
            val e = runCatching { CoreSignIn("http://core.test", http).signIn(m, deviceId, DeviceModel.PHONE_ONLY) }.exceptionOrNull()
            assertTrue("$m", e is SignInException && e.status == 0)
        }
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun m5L01_refusalsOfTheNewWays_areNeutral_andKeepTheCoresCode() = runBlocking {
        val code = SignInMethod.EmailCode("a@b.c", "123456")
        val cases = listOf(
            Triple(code, 401, """{"status":401,"code":"invalid_code"}"""),
            Triple(code, 429, """{"status":429,"code":"locked"}"""),
            Triple(SignInMethod.Demo, 403, """{"status":403,"code":"demo_off"}"""),
            Triple(SignInMethod.Password("a@b.c", "pw"), 403, """{"detail":{"code":"sso_required"}}"""),
        )
        val out = cases.map { (m, status, json) ->
            http.reply(status, json)
            runCatching { CoreSignIn("http://core.test", http).signIn(m, deviceId, DeviceModel.PHONE_ONLY) }.exceptionOrNull() as SignInException
        }
        assertEquals(listOf("invalid_code", "locked", "demo_off", "sso_required"), out.map { it.code })
        assertEquals("That code is not right or has expired. Check the e-mail, or ask for a new code.", out[0].message)
        assertEquals("Too many wrong tries for that code. Ask for a new code.", out[1].message)
        assertEquals("The SAMPLE demo is not available on this SCMTIPS server.", out[2].message)
        assertTrue(out[3].message!!, out[3].message!!.contains("single sign-on"))
        // Neutral: no sentence says whether the e-mail has an account.
        out.forEach { e -> assertFalse(e.message!!, listOf("no account", "not found", "unknown", "does not exist").any { e.message!!.contains(it, true) }) }
    }

    @Test
    fun m5L01_noAnswerAtAll_isMarkedOffline() = runBlocking {
        http.fail()
        val e = runCatching { CoreSignIn("http://core.test", http).signIn(SignInMethod.Demo, deviceId, DeviceModel.PHONE_ONLY) }.exceptionOrNull() as SignInException
        assertEquals(0, e.status)
        assertEquals(CoreSignIn.OFFLINE, e.code)
    }
}
