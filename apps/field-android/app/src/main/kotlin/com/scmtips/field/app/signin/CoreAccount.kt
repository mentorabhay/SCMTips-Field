package com.scmtips.field.app.signin

import com.scmtips.field.app.net.HttpError
import com.scmtips.field.app.net.PhoneBinding
import com.scmtips.field.app.slice.Pairing
import com.scmtips.field.app.slice.PairingPayload
import com.scmtips.field.feature.decisions.api.AppToken
import com.scmtips.field.feature.decisions.api.Capabilities
import com.scmtips.field.feature.decisions.api.CoreCredentials
import com.scmtips.field.feature.decisions.api.CoreUrls
import com.scmtips.field.feature.decisions.api.DeviceModel
import com.scmtips.field.feature.decisions.api.WearableSession
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.time.OffsetDateTime

/**
 * Signed in against the SCMTIPS core (F2). Holds the core access token (exchanged at field-api) and the
 * wearable session (for the core's decision calls). Its [toString] never shows a token (A-02).
 */
class CoreAccount(
    val coreBaseUrl: String,
    val fieldBaseUrl: String,
    val accessToken: String,
    val accessExpiresAtMs: Long,
    val tenantId: String?,
    val sites: List<String>,
    val userId: String,
    val displayName: String,
    val email: String?,
    val wearable: WearableSession,
    val capabilities: Capabilities,
    /** The core's permission keys (the sign-in claims, then field-api's `core_permissions` echo). */
    val permissions: List<String> = emptyList(),
) {
    /** May approve decisions: the core's capability, or its `voice.approve` permission (stand-in and real core). */
    val approver: Boolean get() = capabilities.approveDecisions || APPROVE in permissions

    /** Does field work: the core's capability, or its `field.operate` permission. */
    val fieldOperator: Boolean get() = capabilities.fieldOperator || OPERATE in permissions

    /** Signed in with the core app's own pairing: a wearable session only, no field-api token. */
    val hasFieldAccess: Boolean get() = accessToken.isNotEmpty()

    fun withPermissions(more: List<String>): CoreAccount = if (more.all { it in permissions }) this else CoreAccount(
        coreBaseUrl, fieldBaseUrl, accessToken, accessExpiresAtMs, tenantId, sites, userId, displayName, email, wearable,
        capabilities, (permissions + more).distinct(),
    )

    fun accessExpired(nowMs: Long): Boolean = hasFieldAccess && nowMs >= accessExpiresAtMs

    /** True when the wearable token's `expires_at` is past. An unreadable date is not expired: the core's 401 decides. */
    fun wearableExpired(nowMs: Long): Boolean =
        runCatching { OffsetDateTime.parse(wearable.expiresAt).toInstant().toEpochMilli() }.getOrNull()?.let { nowMs >= it } ?: false

    /** The field-api link for this account at [siteId] (same flow as a scanned pairing code from here on). */
    fun pairing(siteId: String, siteName: String): Pairing = Pairing(fieldBaseUrl, accessToken, tenantId.orEmpty(), siteId, siteName)

    override fun toString(): String =
        "CoreAccount(user=$userId, core=$coreBaseUrl, field=$fieldBaseUrl, capabilities=$capabilities, wearable=$wearable, accessToken=<redacted>)"

    companion object {
        const val APPROVE = "voice.approve"
        const val OPERATE = "field.operate"

        /** From the core wearable app's pairing (POST /v1/wearable/sessions): decisions only, no field-api link. */
        fun paired(w: WearableSession, displayName: String, coreBaseUrl: String, fieldBaseUrl: String) = CoreAccount(
            coreBaseUrl = coreBaseUrl, fieldBaseUrl = fieldBaseUrl, accessToken = "", accessExpiresAtMs = 0, tenantId = null,
            sites = emptyList(), userId = w.sessionId, displayName = displayName, email = null, wearable = w,
            capabilities = Capabilities(approveDecisions = true, fieldOperator = false),
        )

        fun from(t: AppToken, coreBaseUrl: String, fieldBaseUrl: String, nowMs: Long) = CoreAccount(
            coreBaseUrl = coreBaseUrl, fieldBaseUrl = fieldBaseUrl, accessToken = t.accessToken,
            accessExpiresAtMs = nowMs + t.expiresInSeconds * 1000L, tenantId = t.tenantId, sites = t.sites,
            userId = t.user.id, displayName = t.user.displayName, email = t.user.email, wearable = t.wearable,
            capabilities = t.capabilities, permissions = t.permissions,
        )
    }
}

/**
 * Where the account lives: the app's EncryptedSharedPreferences ([PhoneBinding.Store] over them in
 * FieldController). Signing out removes every secret; the server addresses and the last e-mail stay so
 * signing in again is quick (they are not secrets).
 */
class AccountStore(private val store: PhoneBinding.Store) {
    fun save(a: CoreAccount) {
        store.put(K_CORE_URL, a.coreBaseUrl)
        store.put(K_FIELD_URL, a.fieldBaseUrl)
        store.put(K_ACCESS, a.accessToken)
        store.put(K_PERMS, a.permissions.joinToString(","))
        store.put(K_ACCESS_EXP, a.accessExpiresAtMs.toString())
        a.tenantId?.let { store.put(K_TENANT, it) } ?: store.remove(K_TENANT)
        store.put(K_SITES, a.sites.joinToString("\n"))
        store.put(K_USER, a.userId)
        store.put(K_NAME, a.displayName)
        a.email?.let { store.put(K_EMAIL, it) }
        store.put(K_W_SESSION, a.wearable.sessionId)
        store.put(K_W_TOKEN, a.wearable.token)
        store.put(K_W_EXP, a.wearable.expiresAt)
        store.put(K_W_DEVICE, a.wearable.deviceId)
        store.put(K_CAPS, listOfNotNull("approve_decisions".takeIf { a.capabilities.approveDecisions },
            "field_operator".takeIf { a.capabilities.fieldOperator }).joinToString(","))
    }

    /** The saved account, or null when signed out (or a part is missing). */
    fun load(): CoreAccount? {
        val caps = store.get(K_CAPS)?.split(',').orEmpty()
        return CoreAccount(
            coreBaseUrl = store.get(K_CORE_URL) ?: return null,
            fieldBaseUrl = store.get(K_FIELD_URL) ?: return null,
            accessToken = store.get(K_ACCESS) ?: return null,
            accessExpiresAtMs = store.get(K_ACCESS_EXP)?.toLongOrNull() ?: 0L,
            tenantId = store.get(K_TENANT),
            sites = store.get(K_SITES)?.split('\n')?.filter { it.isNotBlank() }.orEmpty(),
            userId = store.get(K_USER) ?: return null,
            displayName = store.get(K_NAME) ?: "Signed in",
            email = store.get(K_EMAIL),
            wearable = WearableSession(
                store.get(K_W_SESSION) ?: return null, store.get(K_W_TOKEN) ?: return null,
                store.get(K_W_EXP).orEmpty(), store.get(K_W_DEVICE) ?: return null,
            ),
            capabilities = Capabilities(approveDecisions = "approve_decisions" in caps, fieldOperator = "field_operator" in caps),
            permissions = store.get(K_PERMS)?.split(',')?.filter { it.isNotBlank() }.orEmpty(),
        )
    }

    fun clear() = SECRET_KEYS.forEach(store::remove)

    val lastCoreUrl: String? get() = store.get(K_CORE_URL)
    val lastFieldUrl: String? get() = store.get(K_FIELD_URL)
    val lastEmail: String? get() = store.get(K_EMAIL)

    /** The addresses typed on the sign-in screen, kept even when the sign-in fails. */
    fun rememberServers(coreUrl: String, fieldUrl: String) {
        store.put(K_CORE_URL, coreUrl)
        store.put(K_FIELD_URL, fieldUrl)
    }

    companion object {
        private const val K_CORE_URL = "core_base_url"
        private const val K_FIELD_URL = "core_field_url"
        private const val K_EMAIL = "core_email"
        private const val K_ACCESS = "core_access_token"
        private const val K_ACCESS_EXP = "core_access_expires_ms"
        private const val K_TENANT = "core_tenant"
        private const val K_SITES = "core_sites"
        private const val K_USER = "core_user"
        private const val K_NAME = "core_name"
        private const val K_W_SESSION = "core_wearable_session"
        private const val K_W_TOKEN = "core_wearable_token"
        private const val K_W_EXP = "core_wearable_expires"
        private const val K_W_DEVICE = "core_wearable_device"
        private const val K_CAPS = "core_capabilities"
        private const val K_PERMS = "core_permissions"

        /** Removed on sign-out. The addresses and the e-mail stay. */
        val SECRET_KEYS = listOf(K_ACCESS, K_ACCESS_EXP, K_TENANT, K_SITES, K_USER, K_NAME, K_W_SESSION, K_W_TOKEN, K_W_EXP, K_W_DEVICE, K_CAPS, K_PERMS)
    }
}

/** The core calls' credentials, read fresh from the store each time (an expired wearable token is no token). */
class AccountCredentials(private val account: () -> CoreAccount?, private val now: () -> Long = System::currentTimeMillis) : CoreCredentials {
    override val deviceId: String get() = account()?.wearable?.deviceId.orEmpty()
    override val token: String? get() = account()?.takeUnless { it.wearableExpired(now()) }?.wearable?.token
}

/** Which homes Today shows (handover 01 F1 step 1). Only the core's capabilities decide; a QR pairing is field work. */
data class HomeSections(val decisions: Boolean, val fieldWork: Boolean) {
    companion object {
        fun of(account: CoreAccount?, paired: Boolean): HomeSections = when (account) {
            null -> HomeSections(decisions = false, fieldWork = paired)
            else -> HomeSections(decisions = account.approver, fieldWork = account.fieldOperator && account.hasFieldAccess)
        }
    }
}

/**
 * The addresses a fresh install offers on the sign-in screen, per build type (M5-H02): BuildConfig.DEFAULT_CORE_URL and
 * DEFAULT_FIELD_URL from app/build.gradle.kts, i.e. the dev stack for debug and the hosted deployment
 * (api.scmtips.com, field.scmtips.com) for the `hosted` build type. [DEV] is the debug build's pair.
 */
data class ServerDefaults(val coreUrl: String, val fieldUrl: String) {
    companion object {
        val DEV = ServerDefaults(SignInDefaults.DEV_CORE_URL, SignInDefaults.DEV_FIELD_URL)
    }
}

/** The sign-in screen's addresses: what was typed last, else derived from the last QR pairing, else the build's default. */
object SignInDefaults {
    /**
     * Dev defaults (the stand-in core on 8011, field-api on 8020; on a phone through `adb reverse`); editable on the
     * screen. field-api is on 8020 because the SCMTIPS core API keeps 8000 on the owner's PC (the core's reply, 31 Oct).
     */
    const val DEV_FIELD_URL = "http://127.0.0.1:8020"
    const val DEV_CORE_URL = "http://127.0.0.1:8011"
    const val STAND_IN_CORE_PORT = 8011

    fun fieldUrl(lastField: String?, pairedApi: String?, defaults: ServerDefaults = ServerDefaults.DEV): String =
        lastField ?: pairedApi ?: defaults.fieldUrl

    /** The core stand-in runs on the same PC as a plain-http field-api: same host, port 8011; else the build's core. */
    fun coreUrl(lastCore: String?, fieldUrl: String?, defaults: ServerDefaults = ServerDefaults.DEV): String {
        lastCore?.let { return it }
        val f = fieldUrl?.let(CoreUrls::normalise) ?: return defaults.coreUrl
        val scheme = f.substringBefore("://")
        val host = f.substringAfter("://").substringBefore('/').substringBefore(':')
        return if (scheme == "http") "http://$host:$STAND_IN_CORE_PORT" else defaults.coreUrl
    }

    /** A server address the app may use, or a reason: plain http only to the owner's own network (as the QR pairing). */
    fun check(url: String, what: String): Pair<String?, String?> {
        val u = CoreUrls.normalise(url) ?: return null to "Enter the $what address, like http://192.168.1.20:8020."
        if (u.startsWith("http://") && !PairingPayload.isPrivateHost(PairingPayload.hostOf(u))) {
            return null to "Plain http is only allowed to a PC on your own network; use the https address for the $what."
        }
        return u to null
    }

    fun deviceModel(glassesRegistered: Boolean): DeviceModel = if (glassesRegistered) DeviceModel.RAYBAN_META_GEN2 else DeviceModel.PHONE_ONLY
}

/**
 * field-api's refusal of a core sign-in whose roles map to no Field role (403 FIELD-AUTH-403-NO-FIELD-ROLE, the core's
 * reply TO_FIELD section 2): its `detail` is a sentence written for the person, shown as it is on the sign-in screen.
 */
object FieldAccess {
    const val NO_FIELD_ROLE = "FIELD-AUTH-403-NO-FIELD-ROLE"

    /** The sign-in screen's message for this refusal, or null when [e] is another error. */
    fun noFieldRole(e: HttpError): String? = if (e.status == 403 && e.code == NO_FIELD_ROLE) {
        e.detail?.takeIf { it.isNotBlank() }
            ?: "Your SCMTIPS account has no role that SCMTips Field can use. Ask your SCMTIPS administrator for the approver or procurement role."
    } else null
}

data class SiteRef(val id: String, val name: String, val mode: String?)

/** Which site the signed-in person works at: the first of the token's `sites` field-api lists, else the first listed. */
object SiteChoice {
    fun pick(claimSites: List<String>, sitesBody: JsonObject): SiteRef? {
        val items = (sitesBody["items"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }.mapNotNull { o ->
            val id = o.s("id") ?: return@mapNotNull null
            SiteRef(id, o.s("name") ?: o.s("code") ?: id, o.s("mode"))
        }
        return claimSites.firstNotNullOfOrNull { c -> items.firstOrNull { it.id == c } } ?: items.firstOrNull()
    }

    private fun JsonObject.s(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull
}
