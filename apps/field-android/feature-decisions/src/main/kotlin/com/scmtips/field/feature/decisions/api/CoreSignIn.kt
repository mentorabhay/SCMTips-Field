package com.scmtips.field.feature.decisions.api

import com.scmtips.field.feature.decisions.api.CoreJson.b
import com.scmtips.field.feature.decisions.api.CoreJson.i
import com.scmtips.field.feature.decisions.api.CoreJson.o
import com.scmtips.field.feature.decisions.api.CoreJson.req
import com.scmtips.field.feature.decisions.api.CoreJson.s
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import java.io.IOException

/**
 * How the person signs in (handover 01, F2; M5-L contract §1): e-mail + password, a pairing code made on the web or
 * shown as a QR by the Field console, a 6-digit code e-mailed by `POST /v1/auth/app/code/request` (§2), or the one-tap
 * SAMPLE demo guest (§3, demo mode only).
 */
sealed interface SignInMethod {
    class Password(val email: String, val password: String) : SignInMethod {
        override fun toString(): String = "Password(email=$email, password=<redacted>)"
    }

    class PairingCode(val code: String) : SignInMethod {
        override fun toString(): String = "PairingCode(<redacted>)"
    }

    /** §1 e-mail code: `email` + `email_code` (6 digits, single use, 10 minutes). */
    class EmailCode(val email: String, val code: String) : SignInMethod {
        override fun toString(): String = "EmailCode(email=$email, code=<redacted>)"
    }

    /** §1 demo: `demo: true` signs in the SAMPLE organisation's guest member (403 demo_off when demo mode is off). */
    data object Demo : SignInMethod
}

/**
 * Pairing codes (the web's and the Field console's QR): the console shows them in groups of four ("ABCD EFGH"), and
 * the spaces are not part of the code; the core takes 8 to 20 characters (core 384c471, AppTokenIn.pairing_code).
 */
object PairingCodes {
    val LENGTHS = 8..20
    fun clean(raw: String): String = raw.filterNot { it == ' ' || it == '\u00A0' }.trim()
}

/** `device_model` of the sign-in body. */
enum class DeviceModel(val wire: String) { RAYBAN_META_GEN2("RAYBAN_META_GEN2"), PHONE_ONLY("PHONE_ONLY") }

/**
 * The wearable (device) session: its token goes only to the core's decision calls, with [deviceId]. The core answers
 * `wearable: null` for an account without a pairing permission (core 384c471, AppTokenOut): then [present] is false,
 * every field is empty but [deviceId], and the account has no decision calls.
 */
class WearableSession(val sessionId: String, val token: String, val expiresAt: String, val deviceId: String) {
    val present: Boolean get() = token.isNotEmpty()

    override fun toString(): String = "WearableSession($sessionId, device=$deviceId, expiresAt=$expiresAt, token=<redacted>)"
}

data class CoreUser(val id: String, val displayName: String, val email: String?)

/** What the core lets this person do in the app. The app shows homes by it but never decides permission. */
data class Capabilities(val approveDecisions: Boolean = false, val fieldOperator: Boolean = false)

/** `200` of `POST /v1/auth/app/token`. */
class AppToken(
    /** The core JWT (EdDSA): exchanged at field-api `/v1/auth/exchange`, never sent anywhere else. */
    val accessToken: String,
    val expiresInSeconds: Int,
    val tenantId: String?,
    /** The `sites` claim (may be empty for an approver who does no field work). */
    val sites: List<String>,
    val permissions: List<String>,
    val wearable: WearableSession,
    val user: CoreUser,
    val capabilities: Capabilities,
) {
    override fun toString(): String = "AppToken(user=${user.id}, tenant=$tenantId, capabilities=$capabilities, accessToken=<redacted>, wearable=$wearable)"
}

/** A refusal, in words the person can act on. [code] is the core's machine code. */
class SignInException(val status: Int, val code: String?, message: String) : Exception(message)

/**
 * `POST {core}/v1/auth/app/token` with `X-Requested-With: lr` (handover 01, F2). The body carries
 * either e-mail + password or a pairing code, the device id the wearable token will be bound to, the
 * device model, `display_capable: false` (Ray-Ban Meta Gen 2 has no display) and `client`.
 */
class CoreSignIn(baseUrl: String, private val http: CoreHttp) {
    private val url = CoreUrls.join(CoreUrls.v1(baseUrl), "auth", "app", "token")

    suspend fun signIn(method: SignInMethod, deviceId: String, model: DeviceModel): AppToken {
        val call = request(url, method, deviceId, model)
        val reply = try {
            http.execute(call)
        } catch (e: IOException) {
            throw SignInException(0, OFFLINE, "Cannot reach SCMTIPS at ${url.substringBefore("/v1/")}. Check the address and the Wi-Fi.")
        }
        if (!reply.ok) throw refusal(reply, method)
        val body = CoreJson.obj(reply.body) ?: throw SignInException(reply.status, null, "SCMTIPS answered something this app cannot read.")
        return try {
            parse(body)
        } catch (e: IllegalArgumentException) {
            throw SignInException(reply.status, null, "SCMTIPS answered without ${e.message?.substringAfter("missing ") ?: "a field"}.")
        }
    }

    companion object {
        const val CLIENT = "scmtips-field"

        /** [SignInException.code] when there was no answer at all (offline, TLS, timeout). */
        const val OFFLINE = "offline"
        private val EMAIL_CODE = Regex("^[0-9]{6}$")
        private val DEVICE_ID = Regex("^[A-Za-z0-9._:-]{8,64}$")

        /** Builds the call; throws [SignInException] (status 0) for input the core would refuse anyway. */
        fun request(url: String, method: SignInMethod, deviceId: String, model: DeviceModel): HttpCall {
            if (!DEVICE_ID.matches(deviceId)) throw SignInException(0, "device_id", "This phone's device id is not valid. Reinstall the app.")
            val body = buildJsonObject {
                when (method) {
                    is SignInMethod.Password -> {
                        val email = method.email.trim()
                        if (!email.contains('@') || email.length > 254) throw SignInException(0, "email", "Enter your work e-mail address.")
                        if (method.password.isEmpty()) throw SignInException(0, "password", "Enter your password.")
                        put("email", email)
                        put("password", method.password)
                    }
                    is SignInMethod.PairingCode -> {
                        // The console shows the code in groups of four ("ABCD EFGH"): spaces are not part of it. The core
                        // takes 8 to 20 characters (core 384c471, AppTokenIn.pairing_code).
                        val code = PairingCodes.clean(method.code)
                        if (code.length !in PairingCodes.LENGTHS || code.any { it.isWhitespace() }) {
                            throw SignInException(0, "pairing_code", "Enter the pairing code shown in SCMTIPS on the web.")
                        }
                        put("pairing_code", code)
                    }
                    is SignInMethod.EmailCode -> {
                        val email = method.email.trim()
                        if (!email.contains('@') || email.length > 254) throw SignInException(0, "email", "Enter your work e-mail address.")
                        val code = method.code.filter { !it.isWhitespace() }
                        if (!EMAIL_CODE.matches(code)) throw SignInException(0, "email_code", "Enter the 6 digits from the e-mail.")
                        put("email", email)
                        put("email_code", code)
                    }
                    SignInMethod.Demo -> put("demo", true)
                }
                put("device_id", deviceId)
                put("device_model", model.wire)
                put("display_capable", false)
                put("client", CLIENT)
            }
            return HttpCall(
                "POST", url,
                mapOf(CoreClient.HEADER_REQUESTED_WITH to CoreClient.REQUESTED_WITH),
                HttpBody.Json(body.toString()),
            )
        }

        fun parse(body: JsonObject): AppToken {
            val access = body.req("access_token")
            val claims = body.o("claims") ?: jwtClaims(access) ?: JsonObject(emptyMap())
            // `wearable` is required in the answer but may be null (no pairing permission): no decision calls then.
            if (!body.containsKey("wearable")) throw IllegalArgumentException("missing 'wearable'")
            val w = body.o("wearable")
            val u = body.o("user") ?: throw IllegalArgumentException("missing 'user'")
            val caps = body.o("capabilities")
            return AppToken(
                accessToken = access,
                expiresInSeconds = body.i("expires_in") ?: 3600,
                tenantId = claims.s("tenant_id"),
                sites = claims.strings("sites"),
                permissions = claims.strings("permissions"),
                wearable = w?.let { WearableSession(it.req("session_id"), it.req("token"), it.s("expires_at").orEmpty(), it.req("device_id")) }
                    ?: WearableSession("", "", "", claims.s("device_id").orEmpty()),
                user = CoreUser(u.req("id"), u.s("display_name") ?: u.s("email") ?: "Signed in", u.s("email")),
                // Without a wearable token there is nothing to approve with, whatever the capability says.
                capabilities = Capabilities((caps?.b("approve_decisions") ?: false) && w != null, caps?.b("field_operator") ?: false),
            )
        }

        /**
         * 401 invalid_credentials / invalid_code, 403 pairing_required / sso_required / demo_off, 429 too_many_attempts /
         * locked, 503 core_tokens_unavailable (handover 01, 01a; M5-L contract §1). Every sentence is neutral: none
         * says whether an e-mail has an account.
         */
        fun refusal(reply: HttpReply, method: SignInMethod? = null): SignInException {
            val p = CoreJson.problem(reply.body)
            val code = p?.code ?: p?.detail?.takeIf { it.matches(Regex("^[a-z_]+$")) }
            val text = when {
                reply.status == 401 && method is SignInMethod.PairingCode ->
                    "That pairing code is not valid or has expired. Make a new one in SCMTIPS on the web."
                reply.status == 401 && method is SignInMethod.EmailCode ->
                    "That code is not right or has expired. Check the e-mail, or ask for a new code."
                reply.status == 401 -> "The e-mail or password is not right."
                reply.status == 403 && code == "pairing_required" ->
                    "Your organisation signs in with a pairing code. Make one in SCMTIPS on the web and enter it here."
                reply.status == 403 && code == "sso_required" ->
                    "Your organisation signs in with single sign-on. Sign in to SCMTIPS on your computer, then scan its sign-in code here."
                reply.status == 403 && code == "demo_off" -> "The SAMPLE demo is not available on this SCMTIPS server."
                reply.status == 403 -> "SCMTIPS does not allow this sign-in (${code ?: "403"})."
                reply.status == 429 && code == "locked" -> "Too many wrong tries for that code. Ask for a new code."
                reply.status == 429 && method is SignInMethod.Demo ->
                    "The SAMPLE demo has had many sign-ins from this network. Try again in an hour, or use a judge account."
                reply.status == 429 -> "Too many tries. Wait a minute, then try again."
                reply.status == 503 -> "SCMTIPS cannot sign anyone in right now (${code ?: "503"}). Try again later."
                else -> "SCMTIPS refused the sign-in (HTTP ${reply.status}${code?.let { " $it" } ?: ""})."
            }
            return SignInException(reply.status, code, text)
        }

        /**
         * The core wearable app's own pairing (`POST {core}/v1/wearable/sessions`, no auth, one-time 8-character
         * code; ported from its OkHttpScmtipsApi.pair). It gives a wearable session only (decisions, no field-api
         * token); the app uses it when a core does not serve `/v1/auth/app/token`.
         */
        suspend fun pairWearable(baseUrl: String, http: CoreHttp, code: String, deviceId: String, model: DeviceModel): Pair<WearableSession, String> {
            val c = PairingCodes.clean(code)
            if (c.length != 8) throw SignInException(0, "pairing_code", "The pairing code has 8 characters.")
            if (!DEVICE_ID.matches(deviceId)) throw SignInException(0, "device_id", "This phone's device id is not valid. Reinstall the app.")
            val url = CoreUrls.join(CoreUrls.v1(baseUrl), "wearable", "sessions")
            val body = buildJsonObject {
                put("pairing_code", c); put("device_id", deviceId); put("device_model", model.wire); put("display_capable", false)
            }
            val reply = try {
                http.execute(HttpCall("POST", url, mapOf(CoreClient.HEADER_REQUESTED_WITH to CoreClient.REQUESTED_WITH), HttpBody.Json(body.toString())))
            } catch (e: IOException) {
                throw SignInException(0, OFFLINE, "Cannot reach SCMTIPS at ${baseUrl.trim().trimEnd('/')}. Check the address and the Wi-Fi.")
            }
            if (!reply.ok) throw refusal(reply, SignInMethod.PairingCode(c))
            val o = CoreJson.obj(reply.body) ?: throw SignInException(reply.status, null, "SCMTIPS answered something this app cannot read.")
            return try {
                WearableSession(o.req("session_id"), o.req("token"), o.s("expires_at").orEmpty(), o.req("device_id")) to
                    (o.s("user_display_name") ?: "Signed in")
            } catch (e: IllegalArgumentException) {
                throw SignInException(reply.status, null, "SCMTIPS answered without ${e.message?.substringAfter("missing ") ?: "a field"}.")
            }
        }

        /** The payload of a JWT (no signature check: field-api verifies the token; the app only reads its claims). */
        fun jwtClaims(token: String): JsonObject? {
            val payload = token.split('.').getOrNull(1) ?: return null
            return runCatching {
                CoreJson.obj(String(java.util.Base64.getUrlDecoder().decode(payload.padEnd((payload.length + 3) / 4 * 4, '='))))
            }.getOrNull()
        }

        private fun JsonObject.strings(k: String): List<String> =
            (this[k] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
    }
}
