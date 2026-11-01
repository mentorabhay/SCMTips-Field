package com.scmtips.field.app.signin

import com.scmtips.field.app.slice.PairingPayload
import com.scmtips.field.feature.decisions.api.CoreSignIn
import com.scmtips.field.feature.decisions.api.CoreUrls
import com.scmtips.field.feature.decisions.api.AccountTokens
import java.net.URI
import java.net.URLDecoder

// Pure rules of the M5-L sign-in screens (docs/design/M5_SIGNIN_CONTRACT.md §7): which ways in are shown, the App
// Links and pasted or scanned codes, the 6-box code entry, the resend timer and the neutral error kinds. The Compose
// screens in ui/firstrun only draw them; every rule here is JVM-tested (SignInLinksTest).

/** An e-mail or console link the app opens itself (Android App Links on app.scmtips.com, contract §5, §4). */
sealed interface AppLink {
    /** `https://app.scmtips.com/reset/confirm?token=<43>`: "Set a new password". */
    class Reset(val token: String) : AppLink {
        override fun toString(): String = "Reset(<redacted>)"
    }

    /** `https://app.scmtips.com/invite/<43>`: the invite screen. */
    class Invite(val token: String) : AppLink {
        override fun toString(): String = "Invite(<redacted>)"
    }

    /** `https://app.scmtips.com/pair?code=<code>` (the Field console's QR): sign in by pairing code. */
    class Pair(val code: String) : AppLink {
        override fun toString(): String = "Pair(<redacted>)"
    }
}

object SignInLinks {
    /** The verified App Link host (AndroidManifest.xml intent filters with android:autoVerify). */
    const val WEB_HOST = "app.scmtips.com"
    private val PAIR_CODE = Regex("^[A-Za-z0-9-]{4,64}$")

    /**
     * The link in [raw], or null when it is none of the three. [hosts]: the hosts accepted (MainActivity passes the
     * verified host); null accepts any http(s) host, for a link pasted or scanned from a stand-in core's own web app
     * (the token only ever goes to the SCMTIPS address this app is set to).
     */
    fun parse(raw: String?, hosts: Set<String>? = null): AppLink? {
        val t = raw?.trim()?.takeIf { it.startsWith("https://", true) || it.startsWith("http://", true) } ?: return null
        val uri = runCatching { URI(t) }.getOrNull() ?: return null
        val host = uri.host?.lowercase() ?: return null
        if (hosts != null && host !in hosts) return null
        val path = (uri.rawPath ?: "").trimEnd('/')
        val query = query(uri.rawQuery)
        return when {
            path == "/reset/confirm" -> query["token"]?.takeIf(AccountTokens::valid)?.let(AppLink::Reset)
            path.startsWith("/invite/") -> path.removePrefix("/invite/").takeIf(AccountTokens::valid)?.let(AppLink::Invite)
            path == "/pair" -> query["code"]?.trim()?.takeIf(PAIR_CODE::matches)?.let(AppLink::Pair)
            else -> null
        }
    }

    private fun query(raw: String?): Map<String, String> = raw.orEmpty().split('&').mapNotNull { kv ->
        val k = kv.substringBefore('=', "")
        if (k.isEmpty()) null else k to runCatching { URLDecoder.decode(kv.substringAfter('='), "UTF-8") }.getOrDefault("")
    }.toMap()

    /** What a scan of "Scan a code from your computer" means. */
    sealed interface Scanned {
        data class Link(val link: AppLink) : Scanned
        /** The field-api PC pairing QR (`{"v":…}`), still accepted: the old "I have a code from my PC". */
        data class PcPairing(val text: String) : Scanned
        class Code(val code: String) : Scanned {
            override fun toString(): String = "Code(<redacted>)"
        }
        data object NotACode : Scanned
    }

    /** A console QR (App Link) or a bare pairing code; a field-api pairing JSON goes to the old PC pairing. */
    fun scanned(raw: String): Scanned {
        val t = raw.trim()
        parse(t)?.let { return Scanned.Link(it) }
        if (t.startsWith("{") && runCatching { PairingPayload.parse(t) }.isSuccess) return Scanned.PcPairing(t)
        return if (PAIR_CODE.matches(t)) Scanned.Code(t) else Scanned.NotACode
    }

    /** "I have an invite": a pasted invite link, its 43-character code, or (helpfully) a reset or console link. */
    fun pasted(raw: String): AppLink? {
        val t = raw.trim()
        parse(t)?.let { return it }
        // An e-mail client may wrap the link in <…> or put text around it: take the first link in the text.
        Regex("https?://\\S+").find(t)?.value?.trimEnd('>', ')', '.', ',')?.let { parse(it) }?.let { return it }
        return t.takeIf(AccountTokens::valid)?.let(AppLink::Invite)
    }
}

/** The 6-box code entry (contract §7): digits only, paste, auto-submit once. */
object CodeEntry {
    const val LENGTH = 6
    private val SIX = Regex("(?<![0-9])[0-9]{6}(?![0-9])")

    /**
     * What the boxes hold after [input] (typed or pasted): a run of exactly six digits wins (a pasted "Your code is
     * 123456, valid 10 minutes"), else the first six digits in order (typed "123 456").
     */
    fun clean(input: String): String = SIX.find(input)?.value ?: input.filter { it in '0'..'9' }.take(LENGTH)

    fun complete(code: String): Boolean = code.length == LENGTH && code.all { it in '0'..'9' }

    /** The six boxes, left to right (null: empty). */
    fun boxes(code: String): List<Char?> = (0 until LENGTH).map { code.getOrNull(it) }

    /** The box that shows the cursor. */
    fun focus(code: String): Int = minOf(code.length, LENGTH - 1)

    /** Auto-submit once per code: a full code that was not the one just refused, and nothing running. */
    fun shouldSubmit(code: String, lastTried: String?, busy: Boolean): Boolean = !busy && complete(code) && code != lastTried
}

/** "Resend code" after 30 s (contract §7). */
object ResendTimer {
    const val WAIT_MS = 30_000L

    fun secondsLeft(sentAtMs: Long?, nowMs: Long): Int {
        val sent = sentAtMs ?: return 0
        val left = sent + WAIT_MS - nowMs
        return if (left <= 0) 0 else ((left + 999) / 1000).toInt()
    }

    fun canResend(sentAtMs: Long?, nowMs: Long): Boolean = secondsLeft(sentAtMs, nowMs) == 0

    fun label(sentAtMs: Long?, nowMs: Long): String {
        val s = secondsLeft(sentAtMs, nowMs)
        return if (s == 0) "Resend code" else "Resend code in 0:%02d".format(s)
    }
}

/** The SAMPLE demo button (contract §1, §3, §7). */
object DemoOffer {
    const val HOSTED_DEMO = "https://api.scmtips.com"

    /**
     * Shown when the SCMTIPS address is the hosted demo or a stand-in on the owner's own network (http to a private
     * address: the stand-in core of START FIELD TEST), and that address has not answered 403 demo_off ([demoOff]).
     */
    fun shown(coreUrl: String?, demoOff: Set<String>): Boolean {
        val core = coreUrl?.let(CoreUrls::normalise) ?: return false
        if (core in demoOff) return false
        if (core.equals(HOSTED_DEMO, ignoreCase = true)) return true
        return core.startsWith("http://") && PairingPayload.isPrivateHost(PairingPayload.hostOf(core))
    }
}

/** The five ways in, in the order the screen shows them ("Forgot password?" is the link under them). */
enum class SignInWay(val label: String, val sub: String) {
    EMAIL("Continue with e-mail", "Use your password, or get a code by e-mail"),
    SCAN("Scan a code from your computer", "SCMTIPS on your computer shows a sign-in code"),
    INVITE("I have an invite", "Paste the link or code from the invite e-mail"),
    DEMO("Try the SAMPLE demo", "One tap, SAMPLE data only, nothing is kept"),
    ;

    companion object {
        fun shown(demo: Boolean): List<SignInWay> = entries.filter { it != DEMO || demo }
    }
}

/** The neutral error kinds of the sign-in screen (contract §7). */
enum class SignInProblem {
    WRONG, LOCKED, NO_FIELD_ROLE, SSO, DEMO_OFF, OFFLINE, OTHER;

    /** "Try the SAMPLE demo" under the message (no Field role: the demo shows what the app does). */
    val offersDemo: Boolean get() = this == NO_FIELD_ROLE

    /** "Scan a code from your computer" under the message (single sign-on happens on the computer). */
    val offersScan: Boolean get() = this == SSO

    companion object {
        fun of(status: Int, code: String?): SignInProblem = when {
            status == 0 && code == CoreSignIn.OFFLINE -> OFFLINE
            code == FieldAccess.NO_FIELD_ROLE -> NO_FIELD_ROLE
            status == 401 -> WRONG
            status == 429 -> LOCKED
            status == 403 && code == "sso_required" -> SSO
            status == 403 && code == "demo_off" -> DEMO_OFF
            else -> OTHER
        }
    }
}
