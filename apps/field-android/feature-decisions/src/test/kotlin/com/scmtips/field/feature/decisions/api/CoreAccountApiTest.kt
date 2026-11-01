package com.scmtips.field.feature.decisions.api

import com.scmtips.field.feature.decisions.ScriptedHttp
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** M5-L contract §2 and §5: the e-mail code request, the password reset and the invite, as the web pages send them. */
class CoreAccountApiTest {
    private val http = ScriptedHttp()
    private val api = CoreAccountApi("https://api.scmtips.com/", http)
    private val token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde" // 43 URL-safe characters
    private val deviceId = "3f1c2a9e-5b7d-4c11-9e2f-0a1b2c3d4e5f"

    private fun sent(i: Int = 0): JsonObject = Json.parseToJsonElement((http.calls[i].body as HttpBody.Json).text).jsonObject

    @Test
    fun m5L01_codeRequest_postsEmailAndDevice_andIsAcceptedForEveryAnswerOfTheCore() = runBlocking {
        assertEquals(43, token.length)
        listOf(202, 200, 429, 422, 500).forEach { http.reply(it, """{"status":"accepted"}""") }
        val replies = (1..5).map { api.requestCode(" judge01@sample-drone-oem.example ", deviceId) }
        assertTrue(replies.all { it == MailReply.Accepted }) // neutral: unknown, inactive, rate-limited all look the same
        val c = http.calls.first()
        assertEquals("POST", c.method)
        assertEquals("https://api.scmtips.com/v1/auth/app/code/request", c.url)
        assertEquals("lr", c.headers["X-Requested-With"])
        assertNull(c.headers["Authorization"])
        assertEquals("judge01@sample-drone-oem.example", sent()["email"]!!.jsonPrimitive.content)
        assertEquals(deviceId, sent()["device_id"]!!.jsonPrimitive.content)
    }

    @Test
    fun m5L01_aCoreWithoutTheRoute_orNoAnswer_saysSo_insteadOfWaitingForAnEmail() = runBlocking {
        http.reply(404, "")
        http.fail()
        assertEquals(MailReply.NotAvailable, api.requestCode("a@b.c", deviceId))
        val off = api.requestCode("a@b.c", deviceId)
        assertTrue(off is MailReply.Offline && off.message.contains("https://api.scmtips.com"))
    }

    @Test
    fun m5L02_resetRequest_postsTheEmail_andConfirm_postsTokenAndPassword() = runBlocking {
        http.reply(202, "")
        http.reply(204, "")
        assertEquals(MailReply.Accepted, api.requestReset(" ops@acme.example "))
        assertEquals(ResetReply.Done, api.confirmReset(token, "a new long password"))
        assertEquals("https://api.scmtips.com/v1/auth/password/reset/request", http.calls[0].url)
        assertEquals("ops@acme.example", sent(0)["email"]!!.jsonPrimitive.content)
        assertEquals("https://api.scmtips.com/v1/auth/password/reset/confirm", http.calls[1].url)
        assertEquals(token, sent(1)["token"]!!.jsonPrimitive.content)
        assertEquals("a new long password", sent(1)["password"]!!.jsonPrimitive.content)
        assertTrue(http.calls.all { it.headers["X-Requested-With"] == "lr" })
        assertFalse(http.calls[1].toString().contains("a new long password"))
    }

    @Test
    fun m5L02_resetConfirm_mapsTheCoresAnswers_asTheWebPage() = runBlocking {
        http.reply(422, """{"status":422,"code":"validation_error","errors":[{"path":"body.password","code":"too_common","message":"x"},
            {"path":"body.password","code":"breached","message":"y"},{"path":"body.token","code":"bad","message":"z"}]}""")
        http.reply(422, """{"status":422,"errors":[]}""")
        http.reply(400, """{"status":400,"code":"invalid_token"}""")
        http.reply(403, """{"status":403,"code":"sso_required"}""")
        http.reply(429, """{"status":429}""")
        http.reply(503, "")
        http.fail()
        val r = (1..7).map { api.confirmReset(token, "pw") }
        assertEquals(ResetReply.Policy(listOf("This password is too common. Choose a less predictable one.",
            "This password has appeared in a data breach. Choose a different one.")), r[0])
        assertEquals(ResetReply.Policy(listOf(PasswordPolicy.TOO_SHORT)), r[1])
        assertEquals(ResetReply.InvalidLink, r[2])
        assertEquals(ResetReply.Sso, r[3])
        assertEquals(ResetReply.Failed(CoreAccountApi.LOCKED), r[4])
        assertEquals(ResetReply.Failed(CoreAccountApi.UNAVAILABLE), r[5])
        assertTrue((r[6] as ResetReply.Failed).offline)
        // A malformed token is never sent.
        assertEquals(ResetReply.InvalidLink, api.confirmReset("short", "pw"))
        assertEquals(7, http.calls.size)
    }

    @Test
    fun m5L02_invite_readsTheWebPagesPublicInvite() = runBlocking {
        http.reply(200, """{"organisation":"SAMPLE Drone OEM","email":"new.person@sample-drone-oem.example","roles":["approver"],
            "role_names":["Approver","Procurement"],"expires_at":"2026-11-09T10:00:00Z","state":"pending","account_exists":false}""")
        http.reply(200, """{"organisation":"Acme","email":"x@acme.example","roles":["approver"],"state":"expired","account_exists":true}""")
        http.reply(404, "")
        val found = api.invite(token) as InviteReply.Found
        assertEquals(PublicInvite("SAMPLE Drone OEM", "new.person@sample-drone-oem.example", listOf("Approver", "Procurement"),
            "2026-11-09T10:00:00Z", InviteState.PENDING, accountExists = false), found.invite)
        assertEquals("https://api.scmtips.com/v1/invites/$token", http.calls[0].url)
        assertEquals("GET", http.calls[0].method)
        assertEquals("lr", http.calls[0].headers["X-Requested-With"])
        val expired = (api.invite(token) as InviteReply.Found).invite
        assertEquals(InviteState.EXPIRED, expired.state)
        assertEquals(listOf("approver"), expired.roleNames) // no role_names: the role keys
        assertTrue(expired.accountExists)
        assertEquals(InviteReply.Invalid, api.invite(token))
        assertEquals(InviteReply.Invalid, api.invite("not-a-token"))
        assertEquals(3, http.calls.size)
    }

    @Test
    fun m5L02_acceptInvite_newAccount_sendsNameConsentsAndTheCoresVersions_existingOnlyThePassword() = runBlocking {
        http.reply(201, """{"verification_required":false,"mfa_enrolled":false}""")
        http.reply(200, """{"verification_required":false}""")
        val a = api.acceptInvite(token, InviteAcceptance(false, " New Person ", "long enough password", consentTerms = true, consentDpdp = true))
        assertEquals(AcceptReply.Accepted(verificationRequired = false), a)
        assertEquals("https://api.scmtips.com/v1/invites/$token/accept", http.calls[0].url)
        val b = sent(0)
        assertEquals("New Person", b["name"]!!.jsonPrimitive.content)
        assertEquals("long enough password", b["password"]!!.jsonPrimitive.content)
        assertEquals(true, b["consent_terms"]!!.jsonPrimitive.boolean)
        assertEquals(true, b["consent_dpdp"]!!.jsonPrimitive.boolean)
        assertEquals("2026-01", b["terms_version"]!!.jsonPrimitive.content) // apps/web/src/auth/signup-api.ts
        assertEquals("2026-01", b["dpdp_version"]!!.jsonPrimitive.content)
        api.acceptInvite(token, InviteAcceptance(true, "", "existing pw", consentTerms = false, consentDpdp = false))
        assertEquals(setOf("password"), sent(1).keys)
    }

    @Test
    fun m5L02_acceptInvite_refusesMissingConsents_locally_andMapsPolicyErrors() = runBlocking {
        val noConsent = api.acceptInvite(token, InviteAcceptance(false, "N", "pw", consentTerms = true, consentDpdp = false))
        assertEquals(AcceptReply.Failed("Accept the Terms of Service and the DPDP consent to continue."), noConsent)
        assertEquals(AcceptReply.Failed("Enter your name."), api.acceptInvite(token, InviteAcceptance(false, " ", "pw", true, true)))
        assertTrue(http.calls.isEmpty())
        http.reply(422, """{"status":422,"errors":[{"path":"body.password","code":"too_short","message":"x"}]}""")
        http.reply(409, """{"status":409,"code":"invite_used"}""")
        assertEquals(AcceptReply.Policy(listOf(PasswordPolicy.TOO_SHORT)), api.acceptInvite(token, InviteAcceptance(false, "N", "pw", true, true)))
        assertTrue((api.acceptInvite(token, InviteAcceptance(false, "N", "pw", true, true)) as AcceptReply.Failed).message.contains("already used"))
        assertFalse(InviteAcceptance(false, "N", "secret-pw", true, true).toString().contains("secret-pw"))
    }

    @Test
    fun m5L02_localPasswordRules_matchTheWebResetPage() {
        assertEquals(listOf(PasswordPolicy.TOO_SHORT), PasswordPolicy.local("short", "short"))
        assertEquals(listOf("The passwords do not match."), PasswordPolicy.local("twelve chars!", "twelve chars?"))
        assertEquals(emptyList<String>(), PasswordPolicy.local("twelve chars!", "twelve chars!"))
        assertEquals("Choose a different password.", PasswordPolicy.message("something_new"))
    }
}
