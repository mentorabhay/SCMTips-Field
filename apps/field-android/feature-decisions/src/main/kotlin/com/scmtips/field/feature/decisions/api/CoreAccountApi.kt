package com.scmtips.field.feature.decisions.api

import com.scmtips.field.feature.decisions.api.CoreJson.a
import com.scmtips.field.feature.decisions.api.CoreJson.b
import com.scmtips.field.feature.decisions.api.CoreJson.s
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import java.io.IOException

/**
 * The core's public account routes the app calls without a token (M5-L contract §2, §5), all with
 * `X-Requested-With: lr`: the e-mailed sign-in code, the password reset (request and confirm) and the invite (read and
 * accept). Pure over [CoreHttp]; every answer becomes a sealed result the sign-in screens draw. Nothing here says
 * whether an e-mail has an account: the two "send me an e-mail" calls answer [MailReply.Accepted] for every answer
 * of the core (it answers 202 for every e-mail), and only an unreachable core or a core without the route differs.
 *
 * The bodies mirror the SCMTIPS web pages (apps/web/src/auth: actions.ts resetConfirmAction, invite-actions.ts), so
 * the app and the web send the same thing.
 */
class CoreAccountApi(baseUrl: String, private val http: CoreHttp) {
    private val v1 = CoreUrls.v1(baseUrl)
    private val base = baseUrl.trim().trimEnd('/')

    /** §2 `POST /v1/auth/app/code/request` `{email, device_id}`. */
    suspend fun requestCode(email: String, deviceId: String): MailReply =
        mail(CoreUrls.join(v1, "auth", "app", "code", "request"), buildJsonObject { put("email", email.trim()); put("device_id", deviceId) })

    /** §5 `POST /v1/auth/password/reset/request` `{email}` (the core e-mails the reset link through its outbox). */
    suspend fun requestReset(email: String): MailReply =
        mail(CoreUrls.join(v1, "auth", "password", "reset", "request"), buildJsonObject { put("email", email.trim()) })

    /** §5 `POST /v1/auth/password/reset/confirm` `{token, password}` (the web page's resetConfirmAction). */
    suspend fun confirmReset(token: String, password: String): ResetReply {
        if (!AccountTokens.valid(token)) return ResetReply.InvalidLink
        val reply = try {
            http.execute(post(CoreUrls.join(v1, "auth", "password", "reset", "confirm"), buildJsonObject { put("token", token); put("password", password) }))
        } catch (e: IOException) {
            return ResetReply.Failed(offline(), offline = true)
        }
        if (reply.ok) return ResetReply.Done
        val p = CoreJson.obj(reply.body)
        val code = p?.let(::problemCode)
        return when {
            code == "sso_required" -> ResetReply.Sso
            reply.status == 422 -> ResetReply.Policy(PasswordPolicy.messages(p).ifEmpty { listOf(PasswordPolicy.TOO_SHORT) })
            reply.status == 400 || reply.status == 404 || reply.status == 410 -> ResetReply.InvalidLink
            reply.status == 429 -> ResetReply.Failed(LOCKED)
            else -> ResetReply.Failed(UNAVAILABLE)
        }
    }

    /** §5 `GET /v1/invites/{token}` (public): the organisation, the invited e-mail, the roles and the invite's state. */
    suspend fun invite(token: String): InviteReply {
        if (!AccountTokens.valid(token)) return InviteReply.Invalid
        val reply = try {
            http.execute(HttpCall("GET", CoreUrls.join(v1, "invites", token), headers()))
        } catch (e: IOException) {
            return InviteReply.Failed(offline(), offline = true)
        }
        if (reply.status == 404 || reply.status == 400 || reply.status == 422) return InviteReply.Invalid
        if (!reply.ok) return InviteReply.Failed(UNAVAILABLE)
        val o = CoreJson.obj(reply.body) ?: return InviteReply.Failed(UNREADABLE)
        val names = o.strings("role_names").ifEmpty { o.strings("roles") }
        return InviteReply.Found(
            PublicInvite(
                organisation = o.s("organisation") ?: o.s("organization") ?: "your organisation",
                email = o.s("email").orEmpty(),
                roleNames = names,
                expiresAt = o.s("expires_at"),
                state = InviteState.of(o.s("state")),
                accountExists = o.b("account_exists") ?: false,
            ),
        )
    }

    /**
     * §5 `POST /v1/invites/{token}/accept`: a new account sends `{name, password, consent_terms, consent_dpdp,
     * terms_version, dpdp_version}`, an existing account only `{password}` (as invite-actions.ts).
     */
    suspend fun acceptInvite(token: String, a: InviteAcceptance): AcceptReply {
        if (!AccountTokens.valid(token)) return AcceptReply.Failed(INVITE_INVALID)
        AcceptRules.problem(a)?.let { return AcceptReply.Failed(it) }
        val reply = try {
            http.execute(post(CoreUrls.join(v1, "invites", token, "accept"), AcceptRules.body(a)))
        } catch (e: IOException) {
            return AcceptReply.Failed(offline(), offline = true)
        }
        if (reply.ok) {
            val o = CoreJson.obj(reply.body)
            return AcceptReply.Accepted(verificationRequired = o?.b("verification_required") ?: false)
        }
        val p = CoreJson.obj(reply.body)
        val reasons = PasswordPolicy.messages(p)
        return when {
            reasons.isNotEmpty() -> AcceptReply.Policy(reasons)
            reply.status == 404 || reply.status == 410 -> AcceptReply.Failed(INVITE_INVALID)
            reply.status == 409 -> AcceptReply.Failed("This invite was already used. Sign in with the account it created.")
            reply.status == 429 -> AcceptReply.Failed(LOCKED)
            else -> AcceptReply.Failed(p?.s("detail")?.takeIf { it.isNotBlank() && it.length < 200 } ?: "The invite could not be accepted. Try again.")
        }
    }

    private suspend fun mail(url: String, body: JsonObject): MailReply {
        val reply = try {
            http.execute(post(url, body))
        } catch (e: IOException) {
            return MailReply.Offline(offline())
        }
        return if (reply.status in NO_ROUTE) MailReply.NotAvailable else MailReply.Accepted
    }

    private fun post(url: String, body: JsonObject) = HttpCall("POST", url, headers(), HttpBody.Json(body.toString()))

    private fun headers() = mapOf(CoreClient.HEADER_REQUESTED_WITH to CoreClient.REQUESTED_WITH)

    private fun offline() = "Cannot reach SCMTIPS at $base. Check the address and the Wi-Fi."

    companion object {
        /** The core has no such route (an older core): the app says so instead of waiting for an e-mail that never comes. */
        val NO_ROUTE = setOf(404, 405, 501)
        const val LOCKED = "Too many tries. Wait a few minutes, then try again."
        const val UNAVAILABLE = "SCMTIPS cannot do this right now. Try again in a moment."
        const val UNREADABLE = "SCMTIPS answered something this app cannot read."
        const val INVITE_INVALID = "This invite is not valid. Check that you copied the whole link from the e-mail."

        internal fun problemCode(p: JsonObject): String? = p.s("code") ?: (p["detail"] as? JsonObject)?.s("code") ?: p.s("error")

        private fun JsonObject.strings(k: String): List<String> =
            (this[k] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.takeIf(String::isNotBlank) }
    }
}

/** The answer to a "send me an e-mail" call. */
sealed interface MailReply {
    /** Shown the same way for every e-mail: "If that e-mail has an account, … is on its way". */
    data object Accepted : MailReply

    /** This SCMTIPS server has no such route (404 / 405 / 501). */
    data object NotAvailable : MailReply

    data class Offline(val message: String) : MailReply
}

sealed interface ResetReply {
    data object Done : ResetReply
    data object Sso : ResetReply
    data object InvalidLink : ResetReply
    data class Policy(val messages: List<String>) : ResetReply
    data class Failed(val message: String, val offline: Boolean = false) : ResetReply
}

enum class InviteState { PENDING, ACCEPTED, REVOKED, EXPIRED;
    companion object {
        fun of(s: String?): InviteState = entries.firstOrNull { it.name.equals(s?.trim(), ignoreCase = true) } ?: PENDING
    }
}

/** `GET /v1/invites/{token}` (the web page's PublicInvite). */
data class PublicInvite(
    val organisation: String,
    val email: String,
    val roleNames: List<String>,
    val expiresAt: String?,
    val state: InviteState,
    val accountExists: Boolean,
)

sealed interface InviteReply {
    data class Found(val invite: PublicInvite) : InviteReply
    data object Invalid : InviteReply
    data class Failed(val message: String, val offline: Boolean = false) : InviteReply
}

/** What the invite screen sends. [existing]: the invited e-mail already has an account here (only the password). */
class InviteAcceptance(
    val existing: Boolean,
    val name: String,
    val password: String,
    val consentTerms: Boolean,
    val consentDpdp: Boolean,
) {
    override fun toString(): String = "InviteAcceptance(existing=$existing, name=$name, password=<redacted>, terms=$consentTerms, dpdp=$consentDpdp)"
}

sealed interface AcceptReply {
    data class Accepted(val verificationRequired: Boolean) : AcceptReply
    data class Policy(val messages: List<String>) : AcceptReply
    data class Failed(val message: String, val offline: Boolean = false) : AcceptReply
}

/** The consent versions the core expects (the web's signup-api.ts TERMS_VERSION and DPDP_VERSION). */
object Consents {
    const val TERMS_VERSION = "2026-01"
    const val DPDP_VERSION = "2026-01"
    const val TERMS_URL = "scmtips.com/legal/terms"
    const val PRIVACY_URL = "scmtips.com/legal/privacy"
    const val TERMS_TEXT = "I agree to the SCMTIPS Terms of Service (version $TERMS_VERSION, $TERMS_URL)."
    const val DPDP_TEXT = "I consent to SCMTIPS processing my personal data under the Digital Personal Data Protection Act, 2023, " +
        "as described in the Privacy Notice (version $DPDP_VERSION, $PRIVACY_URL)."
}

object AcceptRules {
    /** As invite-actions.ts: a new account needs a name, a password and both consents; an existing one a password. */
    fun problem(a: InviteAcceptance): String? = when {
        !a.existing && a.name.isBlank() -> "Enter your name."
        a.password.isEmpty() -> "Enter a password."
        !a.existing && (!a.consentTerms || !a.consentDpdp) -> "Accept the Terms of Service and the DPDP consent to continue."
        else -> null
    }

    fun body(a: InviteAcceptance): JsonObject = buildJsonObject {
        if (!a.existing) put("name", a.name.trim().take(200))
        put("password", a.password)
        if (!a.existing) {
            put("consent_terms", true)
            put("consent_dpdp", true)
            put("terms_version", Consents.TERMS_VERSION)
            put("dpdp_version", Consents.DPDP_VERSION)
        }
    }
}

/** The 43-character URL-safe tokens of the reset and invite links (the web pages' TOKEN_RE). */
object AccountTokens {
    private val TOKEN = Regex("^[A-Za-z0-9_-]{43}$")
    fun valid(token: String): Boolean = TOKEN.matches(token)
}

/** The core's password-policy codes in the web's words (apps/web/src/auth/api.ts POLICY_MSG). */
object PasswordPolicy {
    const val MIN_LENGTH = 12
    const val TOO_SHORT = "Use at least 12 characters."
    private val MESSAGES = mapOf(
        "too_short" to TOO_SHORT,
        "too_long" to "Use at most 1024 characters.",
        "too_common" to "This password is too common. Choose a less predictable one.",
        "contains_email" to "Do not include your e-mail address in the password.",
        "breached" to "This password has appeared in a data breach. Choose a different one.",
        "reused" to "You have used this password before. Choose a new one.",
    )

    fun message(code: String?): String = MESSAGES[code] ?: "Choose a different password."

    /** The password errors of a 422 problem (`errors[]` whose path names the password, or has no path). */
    fun messages(problem: JsonObject?): List<String> =
        problem?.a("errors").orEmpty()
            .filter { e -> e.s("path").let { it == null || it.contains("password") } }
            .mapNotNull { e -> e.s("code") }
            .map(::message)
            .distinct()

    /** The set-password screen's own checks before anything is sent (as the web's resetConfirmAction). */
    fun local(password: String, again: String): List<String> = buildList {
        if (password.codePointCount(0, password.length) < MIN_LENGTH) add(TOO_SHORT)
        if (password != again) add("The passwords do not match.")
    }
}
