package com.scmtips.field.app.signin

import com.scmtips.field.app.shell.FirstRunStep
import com.scmtips.field.feature.decisions.api.SignInMethod
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** M5-L04 (contract §5, §6, §7): the App Links on app.scmtips.com, the manifest's verified filter, and what each opens. */
class AppLinksTest {
    private val token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"

    private fun run(v: AccountView, e: AccountEvent): Pair<AccountView, List<AccountEffect>> = AccountFlow.reduce(v, e).let { it.view to it.effects }

    private fun method(effects: List<AccountEffect>) = effects.filterIsInstance<AccountEffect.SignIn>().single().method

    @Test
    fun m5L04_theThreeAppLinks_parse_andNothingElseDoes() {
        val reset = SignInLinks.parse("https://app.scmtips.com/reset/confirm?token=$token", setOf(SignInLinks.WEB_HOST))
        assertTrue(reset is AppLink.Reset && reset.token == token)
        val invite = SignInLinks.parse("https://app.scmtips.com/invite/$token/", setOf(SignInLinks.WEB_HOST))
        assertTrue(invite is AppLink.Invite && invite.token == token)
        val pair = SignInLinks.parse("https://APP.scmtips.com/pair?code=AB12CD34&x=1", setOf(SignInLinks.WEB_HOST))
        assertTrue(pair is AppLink.Pair && pair.code == "AB12CD34")
        listOf(
            "https://app.scmtips.com/reset/confirm?token=short",
            "https://app.scmtips.com/reset?token=$token",
            "https://app.scmtips.com/invite/",
            "https://app.scmtips.com/invite/$token/extra",
            "https://app.scmtips.com/pair",
            "https://app.scmtips.com/pair?code=has%20space",
            "https://evil.example/invite/$token",
            "scmtipsfield://registration?x=1",
            "",
            null,
        ).forEach { assertNull(it, SignInLinks.parse(it, setOf(SignInLinks.WEB_HOST))) }
        // Pasted or scanned (any host): a stand-in core's own web app link works too.
        assertTrue(SignInLinks.parse("http://192.168.1.20:3000/invite/$token") is AppLink.Invite)
        assertFalse(AppLink.Reset(token).toString().contains(token))
    }

    /** The manifest's App Link filter (CI's Gradle build merges it) names exactly the three paths, verified. */
    @Test
    fun m5L04_theManifest_hasTheAutoVerifiedAppLinkFilter_forTheThreePaths() {
        val manifest = listOf("src/main/AndroidManifest.xml", "apps/field-android/app/src/main/AndroidManifest.xml").map(::File).first { it.isFile }
        val xml = manifest.readText()
        val filter = Regex("<intent-filter android:autoVerify=\"true\">(.*?)</intent-filter>", RegexOption.DOT_MATCHES_ALL).find(xml)?.groupValues?.get(1)
            ?: throw AssertionError("no autoVerify intent filter in $manifest")
        listOf("android.intent.action.VIEW", "android.intent.category.DEFAULT", "android.intent.category.BROWSABLE",
            "android:scheme=\"https\"", "android:host=\"${SignInLinks.WEB_HOST}\"", "android:path=\"/reset/confirm\"",
            "android:pathPrefix=\"/invite/\"", "android:path=\"/pair\"").forEach { assertTrue(it, filter.contains(it)) }
        assertFalse("App Links are https only", filter.contains("android:scheme=\"http\""))
    }

    @Test
    fun m5L04_appLinks_openTheirScreens_andASignedInPhoneIsToldToSignOutFirst() {
        val (inv, fx) = run(AccountView(), AccountEvent.Link(AppLink.Invite(token), signedIn = false))
        assertEquals(SignInStage.INVITE, inv.stage)
        assertEquals(listOf(AccountEffect.Show(FirstRunStep.SIGN_IN), AccountEffect.LoadInvite(token)), fx)
        val pair = run(AccountView(stage = SignInStage.EMAIL), AccountEvent.Link(AppLink.Pair("AB12CD34"), signedIn = false))
        assertEquals(SignInStage.CHOOSE, pair.first.stage)
        assertEquals(AccountEffect.Show(FirstRunStep.SIGN_IN), pair.second.first())
        assertEquals("AB12CD34", (method(pair.second) as SignInMethod.PairingCode).code)
        val (busy, none) = run(AccountView(), AccountEvent.Link(AppLink.Reset(token), signedIn = true))
        assertEquals(AccountText.SIGNED_IN_ALREADY, busy.error)
        assertTrue(none.isEmpty())
    }
}
