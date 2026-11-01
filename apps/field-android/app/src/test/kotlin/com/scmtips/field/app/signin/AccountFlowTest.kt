package com.scmtips.field.app.signin

import com.scmtips.field.app.shell.FirstRunStep
import com.scmtips.field.feature.decisions.api.AcceptReply
import com.scmtips.field.feature.decisions.api.InviteReply
import com.scmtips.field.feature.decisions.api.InviteState
import com.scmtips.field.feature.decisions.api.MailReply
import com.scmtips.field.feature.decisions.api.PasswordPolicy
import com.scmtips.field.feature.decisions.api.PublicInvite
import com.scmtips.field.feature.decisions.api.ResetReply
import com.scmtips.field.feature.decisions.api.SignInMethod
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** M5-L contract §7: the in-app sign-in stages, invite and reset as a pure reducer (FieldController runs the effects). */
class AccountFlowTest {
    private val token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"
    private val email = "judge01@sample-drone-oem.example"

    private fun run(v: AccountView, vararg events: AccountEvent): Pair<AccountView, List<AccountEffect>> {
        var view = v
        val effects = mutableListOf<AccountEffect>()
        events.forEach { e -> AccountFlow.reduce(view, e).let { view = it.view; effects += it.effects } }
        return view to effects
    }

    private fun method(effects: List<AccountEffect>) = effects.filterIsInstance<AccountEffect.SignIn>().single().method

    @Test
    fun m5L01_continueWithEmail_thenPassword_signsInWithEmailAndPassword() {
        val (v, fx) = run(AccountView(), AccountEvent.Open(SignInStage.EMAIL), AccountEvent.Email(" $email "), AccountEvent.UsePassword,
            AccountEvent.Password("pw"))
        assertEquals(SignInStage.PASSWORD, v.stage)
        val m = method(fx) as SignInMethod.Password
        assertEquals(email, m.email)
        assertEquals("pw", m.password)
        // No e-mail: the password stage is not reached.
        val (bad, none) = run(AccountView(), AccountEvent.Open(SignInStage.EMAIL), AccountEvent.UsePassword)
        assertEquals(SignInStage.EMAIL, bad.stage)
        assertEquals(AccountText.ENTER_EMAIL, bad.error)
        assertTrue(none.isEmpty())
    }

    @Test
    fun m5L01_emailMeACode_isNeutral_thenSixDigitsSignInByThemselves_once() {
        val start = AccountView(stage = SignInStage.EMAIL, email = email)
        val (asked, fx1) = run(start, AccountEvent.SendCode(1_000))
        assertTrue(asked.busy)
        assertEquals(listOf(AccountEffect.RequestCode(email)), fx1)
        val (code, _) = run(asked, AccountEvent.CodeSent(MailReply.Accepted, 1_000))
        assertEquals(SignInStage.CODE, code.stage)
        assertEquals(AccountText.CODE_ON_ITS_WAY, code.notice)
        assertEquals(1_000L, code.codeSentAtMs)
        // Typing: nothing until six digits, then one sign-in by e-mail code.
        val (_, partial) = run(code, AccountEvent.Code("123"))
        assertTrue(partial.isEmpty())
        val (_, full) = run(code, AccountEvent.Code("Your code is 123456"))
        val m = method(full) as SignInMethod.EmailCode
        assertEquals(email, m.email); assertEquals("123456", m.code)
        // Refused: the same code is not sent again until the boxes change.
        val (refused, _) = run(code, AccountEvent.SignInFailed("https://api.scmtips.com", demoOff = false, method = m))
        assertTrue(refused.codeRefused)
        assertTrue(run(refused, AccountEvent.Code("123456")).second.isEmpty())
        val (again, retry) = run(refused, AccountEvent.Code(""), AccountEvent.Code("654321"))
        assertFalse(again.codeRefused)
        assertEquals("654321", (method(retry) as SignInMethod.EmailCode).code)
    }

    @Test
    fun m5L01_resend_onlyAfter30Seconds_andAnOldCoreOrOfflineSaySo() {
        val code = AccountView(stage = SignInStage.CODE, email = email, codeSentAtMs = 10_000)
        assertTrue(run(code, AccountEvent.SendCode(39_999)).second.isEmpty())
        assertEquals(listOf(AccountEffect.RequestCode(email)), run(code, AccountEvent.SendCode(40_000)).second)
        val asked = AccountView(stage = SignInStage.EMAIL, email = email, busy = true)
        assertEquals(AccountText.NO_CODE_ROUTE, run(asked, AccountEvent.CodeSent(MailReply.NotAvailable, 0)).first.error)
        val off = run(asked, AccountEvent.CodeSent(MailReply.Offline("Cannot reach SCMTIPS"), 0)).first
        assertEquals("Cannot reach SCMTIPS", off.error)
        assertEquals(SignInStage.EMAIL, off.stage)
        assertFalse(off.busy)
    }

    @Test
    fun m5L01_demoAndScan_signInWithTheirMethods_andDemoOffHidesTheButtonForThatServer() {
        assertEquals(SignInMethod.Demo, method(run(AccountView(), AccountEvent.Demo).second))
        val (v, _) = run(AccountView(), AccountEvent.SignInFailed("https://api.scmtips.com", demoOff = true, method = SignInMethod.Demo))
        assertFalse(DemoOffer.shown("https://api.scmtips.com", v.demoOff))
        val scanned = run(AccountView(), AccountEvent.Scanned("https://app.scmtips.com/pair?code=AB12CD34")).second
        assertEquals("AB12CD34", (method(scanned) as SignInMethod.PairingCode).code)
        assertEquals("ZX98YT76", (method(run(AccountView(), AccountEvent.Scanned("ZX98YT76")).second) as SignInMethod.PairingCode).code)
        assertEquals(AccountText.NOT_A_CODE, run(AccountView(), AccountEvent.Scanned("hello there")).first.error)
    }

    @Test
    fun m5L01_backWalksTheStages_thenLeavesItToTheShell() {
        assertEquals(SignInStage.EMAIL, AccountFlow.back(AccountView(stage = SignInStage.CODE))?.stage)
        assertEquals(SignInStage.EMAIL, AccountFlow.back(AccountView(stage = SignInStage.PASSWORD))?.stage)
        assertEquals(SignInStage.CHOOSE, AccountFlow.back(AccountView(stage = SignInStage.EMAIL))?.stage)
        assertEquals(SignInStage.CHOOSE, AccountFlow.back(AccountView(stage = SignInStage.CREATE))?.stage)
        assertNull(AccountFlow.back(AccountView(stage = SignInStage.CHOOSE)))
    }

    @Test
    fun m5L02_createAccount_withoutAnInvite_explains_andOffersTheInvite() {
        val (v, fx) = run(AccountView(), AccountEvent.Open(SignInStage.CREATE))
        assertEquals(SignInStage.CREATE, v.stage)
        assertTrue(fx.isEmpty()) // nothing opens: no browser, no call
        assertEquals(SignInStage.INVITE_ENTER, run(v, AccountEvent.Open(SignInStage.INVITE_ENTER)).first.stage)
        assertEquals(SignInMethod.Demo, method(run(v, AccountEvent.Demo).second))
    }

    @Test
    fun m5L02_invite_pastedOrOpenedByItsLink_readsTheInvite_acceptsIt_thenSignsInWithEmailAndPassword() {
        val (loading, fx) = run(AccountView(), AccountEvent.Open(SignInStage.INVITE_ENTER), AccountEvent.Pasted("https://app.scmtips.com/invite/$token"))
        assertEquals(SignInStage.INVITE, loading.stage)
        assertTrue(loading.busy)
        assertEquals(listOf(AccountEffect.Show(FirstRunStep.SIGN_IN), AccountEffect.LoadInvite(token)), fx)
        val invite = PublicInvite("SAMPLE Drone OEM", "new@sample-drone-oem.example", listOf("Approver"), "2026-11-09T10:00:00Z", InviteState.PENDING, false)
        val (read, _) = run(loading, AccountEvent.InviteRead(token, InviteReply.Found(invite)))
        assertEquals(invite, read.invite)
        assertNull(read.error)
        assertEquals("You are invited to SAMPLE Drone OEM as Approver.", AccountText.invited(invite))
        // Consents missing: refused here, nothing sent.
        val (noConsent, none) = run(read, AccountEvent.Accept("New Person", "long password", terms = true, dpdp = false))
        assertTrue(none.isEmpty())
        assertEquals("Accept the Terms of Service and the DPDP consent to continue.", noConsent.error)
        val (accepting, acc) = run(read, AccountEvent.Accept("New Person", "long password", terms = true, dpdp = true))
        assertTrue(accepting.busy)
        val a = acc.single() as AccountEffect.AcceptInvite
        assertEquals(token, a.token); assertEquals("new@sample-drone-oem.example", a.email); assertFalse(a.acceptance.existing)
        val (joined, signIn) = run(accepting, AccountEvent.InviteAccepted(AcceptReply.Accepted(false), a.email, "long password"))
        val m = method(signIn) as SignInMethod.Password
        assertEquals("new@sample-drone-oem.example", m.email); assertEquals("long password", m.password)
        assertEquals(SignInStage.PASSWORD, joined.stage) // the sign-in's answer shows with the e-mail filled
        assertEquals("You joined SAMPLE Drone OEM. Signing you in…", joined.notice)
        // A password the core refuses: its messages under the field.
        val policy = run(accepting, AccountEvent.InviteAccepted(AcceptReply.Policy(listOf(PasswordPolicy.TOO_SHORT)), a.email, "x")).first
        assertEquals(listOf(PasswordPolicy.TOO_SHORT), policy.policy)
    }

    @Test
    fun m5L02_invite_closedOrInvalid_saysWhy_andALateAnswerForAnotherInviteIsIgnored() {
        val loading = AccountView(stage = SignInStage.INVITE, inviteToken = token, busy = true)
        val used = PublicInvite("Acme", "x@acme.example", emptyList(), null, InviteState.ACCEPTED, true)
        assertEquals(AccountText.inviteClosed(InviteState.ACCEPTED), run(loading, AccountEvent.InviteRead(token, InviteReply.Found(used))).first.error)
        assertEquals(AccountText.INVITE_INVALID, run(loading, AccountEvent.InviteRead(token, InviteReply.Invalid)).first.error)
        val other = run(loading, AccountEvent.InviteRead("Z".repeat(43), InviteReply.Invalid)).first
        assertEquals(loading, other)
        assertEquals(AccountText.NOT_AN_INVITE, run(AccountView(stage = SignInStage.INVITE_ENTER), AccountEvent.Pasted("hello")).first.error)
        // Accept on a used invite does nothing.
        assertTrue(run(loading.copy(invite = used, busy = false), AccountEvent.Accept("n", "p", true, true)).second.isEmpty())
    }

    @Test
    fun m5L02_reset_inTheApp_requestThenCheckYourEmail_thenTheLinkOpensSetANewPassword_thenSignIn() {
        val (req, fx) = run(AccountView(email = email), AccountEvent.Forgot)
        assertEquals(ResetStage.REQUEST, req.reset)
        assertEquals(listOf(AccountEffect.Show(FirstRunStep.FORGOT)), fx)
        val (sending, send) = run(req, AccountEvent.ResetEmail(email))
        assertEquals(listOf(AccountEffect.RequestReset(email)), send)
        val sent = run(sending, AccountEvent.ResetSent(MailReply.Accepted)).first
        assertEquals(ResetStage.SENT, sent.reset)
        assertEquals(AccountText.RESET_ON_ITS_WAY, sent.notice)
        assertTrue(sent.notice!!.startsWith("If that e-mail has an account"))
        // The e-mail's link (App Link) opens "Set a new password".
        val (set, show) = run(sent, AccountEvent.Link(AppLink.Reset(token), signedIn = false))
        assertEquals(ResetStage.SET, set.reset)
        assertEquals(token, set.resetToken)
        assertEquals(listOf(AccountEffect.Show(FirstRunStep.FORGOT)), show)
        // Twice, with the web page's local rules first.
        assertEquals(listOf(PasswordPolicy.TOO_SHORT), run(set, AccountEvent.NewPassword("short", "short")).first.policy)
        assertEquals(listOf("The passwords do not match."), run(set, AccountEvent.NewPassword("a long password!", "a long password?")).first.policy)
        val (saving, confirm) = run(set, AccountEvent.NewPassword("a long password!", "a long password!"))
        val c = confirm.single() as AccountEffect.ConfirmReset
        assertEquals(token, c.token); assertEquals("a long password!", c.password)
        assertFalse(c.toString().contains("a long password"))
        val (done, back) = run(saving, AccountEvent.ResetDone(ResetReply.Done))
        assertEquals(listOf(AccountEffect.Show(FirstRunStep.SIGN_IN)), back)
        assertEquals(SignInStage.PASSWORD, done.stage) // the e-mail filled from the request
        assertEquals(email, done.email)
        assertEquals(AccountText.PASSWORD_CHANGED, done.notice)
        assertNull(done.resetToken)
    }

    @Test
    fun m5L02_reset_answers_policyInvalidSso_andTheCoreWithoutTheRoute() {
        val set = AccountView(reset = ResetStage.SET, resetToken = token, busy = true)
        assertEquals(listOf("x"), run(set, AccountEvent.ResetDone(ResetReply.Policy(listOf("x")))).first.policy)
        assertEquals(AccountText.RESET_INVALID, run(set, AccountEvent.ResetDone(ResetReply.InvalidLink)).first.error)
        assertEquals(AccountText.RESET_SSO, run(set, AccountEvent.ResetDone(ResetReply.Sso)).first.error)
        assertEquals(AccountText.NO_RESET_ROUTE, run(AccountView(busy = true), AccountEvent.ResetSent(MailReply.NotAvailable)).first.error)
        assertEquals(AccountText.ENTER_EMAIL, run(AccountView(), AccountEvent.ResetEmail("nobody")).first.error)
        // Done without a known e-mail: the e-mail stage.
        assertEquals(SignInStage.EMAIL, run(set, AccountEvent.ResetDone(ResetReply.Done)).first.stage)
    }

    @Test
    fun m5L01_noSecretIsKeptInTheView_orPrintedByAnEvent() {
        val v = AccountView(email = email, resetToken = token, inviteToken = token)
        assertFalse(v.toString().contains(token))
        listOf(AccountEvent.Password("pw-secret"), AccountEvent.Code("123456"), AccountEvent.NewPassword("pw-secret", "pw-secret"),
            AccountEvent.Accept("n", "pw-secret", true, true), AccountEvent.InviteAccepted(AcceptReply.Accepted(false), email, "pw-secret"))
            .forEach { e -> assertFalse("$e", e.toString().contains("pw-secret") || e.toString().contains("123456")) }
    }
}
