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

/** How the person signs in (handover 01, F2): demo e-mail + password, or a pairing code made on the web. */
sealed interface SignInMethod {
    class Password(val email: String, val password: String) : SignInMethod {
        override fun toString(): String = "Password(email=$email, password=<redacted>)"
    }

    class PairingCode(val code: String) : SignInMethod {
        override fun toString(): String = "PairingCode(<redacted>)"
    }
}

/** `device_model` of the sign-in body. */
enum class DeviceModel(val wire: String) { RAYBAN_META_GEN2("RAYBAN_META_GEN2"), PHONE_ONLY("PHONE_ONLY") }

/** The wearable (device) session: its token goes only to the core's decision calls, with [deviceId]. */
class WearableSession(val sessionId: String, val token: String, val expiresAt: String, val deviceId: String) {
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
            throw SignInException(0, null, "Cannot reach SCMTIPS at ${url.substringBefore("/v1/")}. Check the address and the Wi-Fi.")
        }
        if (!reply.ok) throw refusal(reply)
        val body = CoreJson.obj(reply.body) ?: throw SignInException(reply.status, null, "SCMTIPS answered something this app cannot read.")
        return try {
            parse(body)
        } catch (e: IllegalArgumentException) {
            throw SignInException(reply.status, null, "SCMTIPS answered without ${e.message?.substringAfter("missing ") ?: "a field"}.")
        }
    }

    companion object {
        const val CLIENT = "scmtips-field"
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
                        val code = method.code.trim()
                        if (code.isEmpty() || code.length > 64 || code.any { it.isWhitespace() }) {
                            throw SignInException(0, "pairing_code", "Enter the pairing code shown in SCMTIPS on the web.")
                        }
                        put("pairing_code", code)
                    }
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
            val w = body.o("wearable") ?: throw IllegalArgumentException("missing 'wearable'")
            val u = body.o("user") ?: throw IllegalArgumentException("missing 'user'")
            val caps = body.o("capabilities")
            return AppToken(
                accessToken = access,
                expiresInSeconds = body.i("expires_in") ?: 3600,
                tenantId = claims.s("tenant_id"),
                sites = claims.strings("sites"),
                permissions = claims.strings("permissions"),
                wearable = WearableSession(w.req("session_id"), w.req("token"), w.s("expires_at").orEmpty(), w.req("device_id")),
                user = CoreUser(u.req("id"), u.s("display_name") ?: u.s("email") ?: "Signed in", u.s("email")),
                capabilities = Capabilities(caps?.b("approve_decisions") ?: false, caps?.b("field_operator") ?: false),
            )
        }

        /** 401 invalid_credentials, 403 pairing_required, 429, 503 core_tokens_unavailable (handover 01, 01a). */
        fun refusal(reply: HttpReply): SignInException {
            val p = CoreJson.problem(reply.body)
            val code = p?.code ?: p?.detail?.takeIf { it.matches(Regex("^[a-z_]+$")) }
            val text = when {
                reply.status == 401 -> "The e-mail or password is not right."
                reply.status == 403 && code == "pairing_required" ->
                    "Your organisation signs in with a pairing code. Make one in SCMTIPS on the web and enter it here."
                reply.status == 403 -> "SCMTIPS does not allow this sign-in (${code ?: "403"})."
                reply.status == 429 -> "Too many tries. Wait a minute, then try again."
                reply.status == 503 -> "SCMTIPS cannot sign anyone in right now (${code ?: "503"}). Try again later."
                else -> "SCMTIPS refused the sign-in (HTTP ${reply.status}${code?.let { " $it" } ?: ""})."
            }
            return SignInException(reply.status, code, text)
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
