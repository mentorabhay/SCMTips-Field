package com.scmtips.field.app.signin

import com.scmtips.field.app.net.HttpError
import com.scmtips.field.app.net.PhoneBinding
import com.scmtips.field.feature.decisions.api.AppToken
import com.scmtips.field.feature.decisions.api.Capabilities
import com.scmtips.field.feature.decisions.api.CoreUser
import com.scmtips.field.feature.decisions.api.DeviceModel
import com.scmtips.field.feature.decisions.api.WearableSession
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** F2 token storage policy and the sign-in screen's rules (M4 contract §4 B). */
class CoreAccountTest {
    private class MapStore : PhoneBinding.Store {
        val m = mutableMapOf<String, String>()
        override fun get(key: String) = m[key]
        override fun put(key: String, value: String) { m[key] = value }
        override fun remove(key: String) { m.remove(key) }
    }

    private val now = 1_800_000_000_000L
    private fun token(caps: Capabilities = Capabilities(approveDecisions = true, fieldOperator = true)) = AppToken(
        accessToken = "eyJ.core-access.sig", expiresInSeconds = 3600, tenantId = "t-1", sites = listOf("site-1"),
        permissions = emptyList(),
        wearable = WearableSession("ws-1", "scmw_wearable_secret", "2030-01-01T00:00:00Z", "dev-install-0001"),
        user = CoreUser("u-1", "Approver Sample", "approver@sample.test"), capabilities = caps,
    )

    private fun account(caps: Capabilities = Capabilities(approveDecisions = true, fieldOperator = true)) =
        CoreAccount.from(token(caps), "http://192.168.1.20:8011", "http://192.168.1.20:8020", now)

    @Test
    fun anAccountIsSavedAndLoadedWhole_andItsTextNeverShowsATokenOrTheStoreKeysValuesInLogs() {
        val store = MapStore()
        val accounts = AccountStore(store)
        val a = account()
        accounts.save(a)
        val b = accounts.load()!!
        assertEquals(a.accessToken, b.accessToken)
        assertEquals(a.wearable.token, b.wearable.token)
        assertEquals("dev-install-0001", b.wearable.deviceId)
        assertEquals(now + 3_600_000, b.accessExpiresAtMs)
        assertEquals(Capabilities(approveDecisions = true, fieldOperator = true), b.capabilities)
        assertEquals(listOf("site-1"), b.sites)
        assertEquals("t-1", b.tenantId)
        val text = a.toString() + b.toString() + a.wearable.toString()
        assertFalse(text, "scmw_wearable_secret" in text || "core-access" in text)
    }

    @Test
    fun signOutRemovesEverySecret_butKeepsTheServerAddressesAndTheEmail() {
        val store = MapStore()
        val accounts = AccountStore(store)
        accounts.save(account())
        accounts.clear()
        assertNull(accounts.load())
        assertFalse(store.m.values.any { "scmw_wearable_secret" in it || "core-access" in it })
        assertEquals("http://192.168.1.20:8011", accounts.lastCoreUrl)
        assertEquals("http://192.168.1.20:8020", accounts.lastFieldUrl)
        assertEquals("approver@sample.test", accounts.lastEmail)
        assertTrue(AccountStore.SECRET_KEYS.none { it in store.m })
    }

    @Test
    fun aPartlySavedAccountIsNoAccount() {
        val store = MapStore()
        AccountStore(store).save(account())
        store.remove("core_wearable_token")
        assertNull(AccountStore(store).load())
    }

    @Test
    fun theCoreCallsHaveNoTokenOnceTheWearableSessionHasExpired() {
        var a: CoreAccount? = account()
        var clock = now
        val creds = AccountCredentials({ a }, { clock })
        assertEquals("scmw_wearable_secret", creds.token)
        assertEquals("dev-install-0001", creds.deviceId)
        clock = java.time.OffsetDateTime.parse("2030-01-01T00:00:00Z").toInstant().toEpochMilli()
        assertNull(creds.token)
        a = null
        assertNull(creds.token)
        assertEquals("", creds.deviceId)
        // The core access token (for field-api) has its own clock.
        assertFalse(account().accessExpired(now + 3_599_000))
        assertTrue(account().accessExpired(now + 3_600_000))
    }

    @Test
    fun homesFollowTheCoresCapabilities_andAQrPairingIsFieldWork() {
        assertEquals(HomeSections(decisions = true, fieldWork = false), HomeSections.of(account(Capabilities(approveDecisions = true)), paired = false))
        assertEquals(HomeSections(decisions = false, fieldWork = true), HomeSections.of(account(Capabilities(fieldOperator = true)), paired = false))
        assertEquals(HomeSections(decisions = true, fieldWork = true), HomeSections.of(account(), paired = false))
        assertEquals(HomeSections(decisions = false, fieldWork = true), HomeSections.of(null, paired = true))
    }

    @Test
    fun theSignInScreensAddressesDefaultFromWhatIsKnown() {
        assertEquals(SignInDefaults.DEV_FIELD_URL, SignInDefaults.fieldUrl(null, null))
        assertEquals("http://192.168.1.20:8020", SignInDefaults.fieldUrl(null, "http://192.168.1.20:8020"))
        assertEquals("http://10.0.0.5:8020", SignInDefaults.fieldUrl("http://10.0.0.5:8020", "http://192.168.1.20:8020"))
        // The stand-in core runs next to field-api on the owner's PC.
        assertEquals("http://192.168.1.20:8011", SignInDefaults.coreUrl(null, "http://192.168.1.20:8020"))
        assertEquals(SignInDefaults.DEV_CORE_URL, SignInDefaults.coreUrl(null, "https://tunnel.example.test"))
        assertEquals("https://core.example.test", SignInDefaults.coreUrl("https://core.example.test", "http://192.168.1.20:8020"))
    }

    @Test
    fun aHostedBuildOffersTheHostedServers_m5h02() {
        val hosted = ServerDefaults("https://api.scmtips.com", "https://field.scmtips.com")
        assertEquals("https://field.scmtips.com", SignInDefaults.fieldUrl(null, null, hosted))
        assertEquals("https://api.scmtips.com", SignInDefaults.coreUrl(null, "https://field.scmtips.com", hosted))
        assertEquals("https://api.scmtips.com", SignInDefaults.coreUrl(null, null, hosted))
        // what was typed last and a QR pairing still win; a plain-http field-api keeps its stand-in core beside it
        assertEquals("http://192.168.1.20:8020", SignInDefaults.fieldUrl(null, "http://192.168.1.20:8020", hosted))
        assertEquals("https://core.example.test", SignInDefaults.coreUrl("https://core.example.test", null, hosted))
        assertEquals("http://192.168.1.20:8011", SignInDefaults.coreUrl(null, "http://192.168.1.20:8020", hosted))
        // the debug build's pair is the dev stack, as before
        assertEquals(ServerDefaults(SignInDefaults.DEV_CORE_URL, SignInDefaults.DEV_FIELD_URL), ServerDefaults.DEV)
        assertEquals(SignInDefaults.DEV_FIELD_URL, SignInDefaults.fieldUrl(null, null, ServerDefaults.DEV))
        assertEquals(SignInDefaults.DEV_CORE_URL, SignInDefaults.coreUrl(null, "https://tunnel.example.test", ServerDefaults.DEV))
    }

    @Test
    fun fieldApiIsOn8020BesideTheCoreOn8000_m4b08() {
        // The core's reply (TO_FIELD, 31 Oct): the SCMTIPS core API keeps 8000, field-api is pinned at 8020.
        assertEquals("http://127.0.0.1:8020", SignInDefaults.DEV_FIELD_URL)
        assertEquals("http://10.0.2.2:8020", com.scmtips.field.app.config.AppConfig.DEFAULT_BASE_URL)
        assertTrue(SignInDefaults.check("", "SCMTips Field server").second!!.contains(":8020"))
    }

    @Test
    fun noFieldRoleShowsFieldApisSentenceOnTheSignInScreen_m4b08() {
        val sentence = "Your SCMTIPS account has no role that SCMTips Field can use (your roles: planner2). Ask your SCMTIPS administrator for the approver or procurement role, then sign in again."
        val e = HttpError(403, FieldAccess.NO_FIELD_ROLE, "No SCMTips Field role", sentence, "HTTP 403")
        assertEquals(sentence, FieldAccess.noFieldRole(e))
        assertTrue(FieldAccess.noFieldRole(HttpError(403, FieldAccess.NO_FIELD_ROLE, null, null, "HTTP 403"))!!.contains("approver or procurement"))
        assertNull(FieldAccess.noFieldRole(HttpError(403, "FIELD-AUTH-403-DEVICE-REVOKED", null, "revoked", "HTTP 403")))
        assertNull(FieldAccess.noFieldRole(HttpError(401, FieldAccess.NO_FIELD_ROLE, null, sentence, "HTTP 401")))
    }

    @Test
    fun plainHttpIsOnlyForTheOwnersNetwork_asWithTheQrCode() {
        assertEquals("http://192.168.1.20:8011", SignInDefaults.check("http://192.168.1.20:8011/", "SCMTIPS").first)
        assertEquals("https://core.example.test", SignInDefaults.check(" https://core.example.test ", "SCMTIPS").first)
        assertNotNull(SignInDefaults.check("http://core.example.test", "SCMTIPS").second)
        assertNotNull(SignInDefaults.check("core.local:8011", "SCMTIPS").second)
        assertEquals(DeviceModel.RAYBAN_META_GEN2, SignInDefaults.deviceModel(glassesRegistered = true))
        assertEquals(DeviceModel.PHONE_ONLY, SignInDefaults.deviceModel(glassesRegistered = false))
    }

    @Test
    fun theSiteIsTheFirstOfTheTokensSitesThatFieldApiLists() {
        val sites = Json.parseToJsonElement("""{"items":[{"id":"s-a","name":"Warehouse A","mode":"production"},{"id":"s-b","name":"Home","mode":"sandbox"}]}""").jsonObject
        assertEquals(SiteRef("s-b", "Home", "sandbox"), SiteChoice.pick(listOf("s-x", "s-b"), sites))
        assertEquals(SiteRef("s-a", "Warehouse A", "production"), SiteChoice.pick(emptyList(), sites))
        assertNull(SiteChoice.pick(listOf("s-a"), Json.parseToJsonElement("""{"items":[]}""").jsonObject))
        val p = account().pairing("s-b", "Home")
        assertEquals("http://192.168.1.20:8020", p.apiBaseUrl)
        assertEquals("t-1", p.tenantId)
        assertEquals("s-b", p.siteId)
    }

    @Test
    fun theInstallIdIsMadeOnceAndIsAValidCoreDeviceId() {
        val store = MapStore()
        var n = 0
        val b = PhoneBinding(store) { "3f1c2a9e-5b7d-4c11-9e2f-0a1b2c3d4e5${n++}" }
        val id = b.installId()
        assertEquals(id, b.installId())
        assertTrue(Regex("^[A-Za-z0-9._:-]{8,64}$").matches(id))
    }

    @Test
    fun theCoresPermissionsAlsoGrantTheHomes_asTheStandInsDemoUsersHaveThem() {
        // approver@demo: core role [approver], permissions [voice.approve, decision.read, evidence.upload]
        val approver = CoreAccount.from(token(Capabilities()).let {
            AppToken(it.accessToken, 3600, "t-1", listOf("*"), listOf("voice.approve", "decision.read", "evidence.upload"), it.wearable, it.user, Capabilities())
        }, "http://127.0.0.1:8011", "http://127.0.0.1:8020", now)
        assertTrue(approver.approver)
        assertFalse(approver.fieldOperator)
        // operator@demo: permissions [field.operate, evidence.upload], echoed by field-api as core_permissions
        val operator = account(Capabilities()).withPermissions(listOf("field.operate", "evidence.upload"))
        assertTrue(operator.fieldOperator)
        assertFalse(operator.approver)
        assertEquals(HomeSections(decisions = false, fieldWork = true), HomeSections.of(operator, paired = false))
        val store = MapStore()
        AccountStore(store).save(operator)
        assertEquals(listOf("field.operate", "evidence.upload"), AccountStore(store).load()!!.permissions)
        val same = operator.withPermissions(listOf("field.operate"))
        assertTrue(same === operator)
    }

    @Test
    fun theCoreAppsPairingIsDecisionsOnly_withoutAFieldApiLink() {
        val a = CoreAccount.paired(WearableSession("ws-2", "scmw_p", "2030-01-01T00:00:00Z", "dev-install-0001"), "Approver Sample",
            "http://127.0.0.1:8011", "http://127.0.0.1:8020")
        assertFalse(a.hasFieldAccess)
        assertTrue(a.approver)
        assertFalse(a.accessExpired(Long.MAX_VALUE))
        assertEquals(HomeSections(decisions = true, fieldWork = false), HomeSections.of(a, paired = false))
        val store = MapStore()
        AccountStore(store).save(a)
        assertEquals("scmw_p", AccountStore(store).load()!!.wearable.token)
    }
}
