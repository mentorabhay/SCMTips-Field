package com.scmtips.field.app.signin

import com.scmtips.field.feature.decisions.api.CoreSignIn
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** M5-L contract §7: App Links, pasted and scanned codes, the 6-box code, the resend timer, the demo and the errors. */
class SignInLinksTest {
    private val token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"

    @Test
    fun m5L01_aScan_isTheConsoleQr_aBareCode_orTheOldPcPairingQr() {
        val link = SignInLinks.scanned("https://app.scmtips.com/pair?code=AB12CD34")
        assertTrue(link is SignInLinks.Scanned.Link && (link.link as AppLink.Pair).code == "AB12CD34")
        val bare = SignInLinks.scanned("  AB12CD34 ")
        assertTrue(bare is SignInLinks.Scanned.Code && bare.code == "AB12CD34")
        // The field-api PC pairing QR (slice/PairingPayloadTest's producer format) still goes to the PC pairing.
        val pc = """{"v":1,"api":"http://192.168.1.23:8000/","token":"tok","tenant":"t-1","site":"s-1","site_name":"SAMPLE warehouse"}"""
        assertEquals(SignInLinks.Scanned.PcPairing(pc), SignInLinks.scanned(pc))
        assertEquals(SignInLinks.Scanned.NotACode, SignInLinks.scanned("hello world"))
        assertEquals(SignInLinks.Scanned.NotACode, SignInLinks.scanned("{}"))
    }

    @Test
    fun m5L02_pastedInvite_isTheLink_theLinkInsideText_orTheBareToken() {
        assertTrue(SignInLinks.pasted("https://app.scmtips.com/invite/$token") is AppLink.Invite)
        assertTrue(SignInLinks.pasted("Join here: <https://app.scmtips.com/invite/$token>.") is AppLink.Invite)
        assertTrue(SignInLinks.pasted("  $token  ") is AppLink.Invite)
        assertTrue(SignInLinks.pasted("https://app.scmtips.com/reset/confirm?token=$token") is AppLink.Reset)
        assertNull(SignInLinks.pasted("my invite"))
        assertNull(SignInLinks.pasted("https://app.scmtips.com/invite/abc"))
    }

    @Test
    fun m5L01_codeEntry_digitsOnly_pasteTakesTheSixDigitRun_andAutoSubmitsOnce() {
        assertEquals("123456", CodeEntry.clean("123 456"))
        assertEquals("123456", CodeEntry.clean("Your SCMTIPS sign-in code is 123456. It works for 10 minutes."))
        assertEquals("482913", CodeEntry.clean("Code for 2026: 482913"))
        assertEquals("12", CodeEntry.clean("1a2"))
        assertEquals("123456", CodeEntry.clean("12345678"))
        assertEquals("", CodeEntry.clean("١٢٣٤٥٦")) // other scripts' digits are not the core's code
        assertEquals(listOf('1', '2', null, null, null, null), CodeEntry.boxes("12"))
        assertEquals(2, CodeEntry.focus("12"))
        assertEquals(5, CodeEntry.focus("123456"))
        assertTrue(CodeEntry.shouldSubmit("123456", null, busy = false))
        assertFalse(CodeEntry.shouldSubmit("123456", "123456", busy = false))
        assertFalse(CodeEntry.shouldSubmit("123456", null, busy = true))
        assertFalse(CodeEntry.shouldSubmit("12345", null, busy = false))
    }

    @Test
    fun m5L01_resend_waits30Seconds() {
        val sent = 1_000_000L
        assertEquals(30, ResendTimer.secondsLeft(sent, sent))
        assertEquals(30, ResendTimer.secondsLeft(sent, sent + 1))
        assertEquals(1, ResendTimer.secondsLeft(sent, sent + 29_999))
        assertEquals(0, ResendTimer.secondsLeft(sent, sent + 30_000))
        assertEquals("Resend code in 0:27", ResendTimer.label(sent, sent + 3_000))
        assertEquals("Resend code", ResendTimer.label(sent, sent + 31_000))
        assertTrue(ResendTimer.canResend(null, 0))
        assertFalse(ResendTimer.canResend(sent, sent + 10_000))
    }

    @Test
    fun m5L01_theDemo_isShownForTheHostedDemoAndStandIns_untilTheServerSaysDemoOff() {
        assertTrue(DemoOffer.shown("https://api.scmtips.com/", emptySet()))
        assertTrue(DemoOffer.shown("http://127.0.0.1:8011", emptySet()))
        assertTrue(DemoOffer.shown("http://192.168.1.20:8011", emptySet()))
        assertFalse(DemoOffer.shown("https://api.acme.example", emptySet()))
        assertFalse(DemoOffer.shown("not a url", emptySet()))
        assertFalse(DemoOffer.shown("https://api.scmtips.com", setOf("https://api.scmtips.com")))
        assertEquals(listOf(SignInWay.EMAIL, SignInWay.SCAN, SignInWay.INVITE, SignInWay.DEMO), SignInWay.shown(demo = true))
        assertEquals(listOf(SignInWay.EMAIL, SignInWay.SCAN, SignInWay.INVITE), SignInWay.shown(demo = false))
    }

    @Test
    fun m5L01_errorKinds_areNeutral_andOfferTheWayOn() {
        assertEquals(SignInProblem.WRONG, SignInProblem.of(401, "invalid_credentials"))
        assertEquals(SignInProblem.WRONG, SignInProblem.of(401, "invalid_code"))
        assertEquals(SignInProblem.LOCKED, SignInProblem.of(429, "locked"))
        assertEquals(SignInProblem.SSO, SignInProblem.of(403, "sso_required"))
        assertEquals(SignInProblem.DEMO_OFF, SignInProblem.of(403, "demo_off"))
        assertEquals(SignInProblem.OFFLINE, SignInProblem.of(0, CoreSignIn.OFFLINE))
        assertEquals(SignInProblem.NO_FIELD_ROLE, SignInProblem.of(403, FieldAccess.NO_FIELD_ROLE))
        assertEquals(SignInProblem.OTHER, SignInProblem.of(0, "email"))
        assertTrue(SignInProblem.NO_FIELD_ROLE.offersDemo)
        assertTrue(SignInProblem.SSO.offersScan)
        assertFalse(SignInProblem.WRONG.offersDemo || SignInProblem.WRONG.offersScan)
    }
}
