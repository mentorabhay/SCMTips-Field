package com.scmtips.field.app.config

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * EffectiveConfigManager merge rule (FR2.004): MDM > server > app default for the 8 managed keys.
 * TC2.104 itself needs Robolectric with a RestrictionsManager stub; this covers the merge logic it drives.
 */
class EffectiveConfigTest {
    private val defaults = AppConfig()
    private val mdmValues = mapOf<String, Any?>(
        "field_api_base_url" to "https://mdm.example", "tenant_hint" to "mdm-tenant", "site_id" to "S-MDM",
        "allowed_glasses_models" to listOf("Ray-Ban Meta"), "force_audio_only" to true,
        "phone_camera_mode_allowed" to false, "max_outbox_items" to 1000, "log_level" to "WARN",
    )
    private val serverValues = mapOf<String, Any?>(
        "field_api_base_url" to "https://srv.example", "tenant_hint" to "srv-tenant", "site_id" to "S-SRV",
        "allowed_glasses_models" to "Ray-Ban Display, Ray-Ban Meta", "force_audio_only" to "false",
        "phone_camera_mode_allowed" to "true", "max_outbox_items" to "1500", "log_level" to "DEBUG",
    )
    private fun pick(c: AppConfig, key: String): Any = when (key) {
        "field_api_base_url" -> c.fieldApiBaseUrl
        "tenant_hint" -> c.tenantHint
        "site_id" -> c.siteId
        "allowed_glasses_models" -> c.allowedGlassesModels
        "force_audio_only" -> c.forceAudioOnly
        "phone_camera_mode_allowed" -> c.phoneCameraModeAllowed
        "max_outbox_items" -> c.maxOutboxItems
        "log_level" -> c.logLevel
        else -> error(key)
    }
    private val mdmExpected = AppConfig("https://mdm.example", "mdm-tenant", "S-MDM", listOf("Ray-Ban Meta"), true, false, 1000, "WARN")
    private val srvExpected = AppConfig("https://srv.example", "srv-tenant", "S-SRV", listOf("Ray-Ban Display", "Ray-Ban Meta"), false, true, 1500, "DEBUG")

    @Test
    fun fr2_004_everyKeyFollowsMdmOverServerOverDefaultInAllFourCombinations() {
        val m = EffectiveConfigManager()
        assertEquals(8, mdmValues.size)
        for (key in mdmValues.keys) {
            for (hasMdm in listOf(true, false)) for (hasSrv in listOf(true, false)) {
                val mdm = if (hasMdm) mapOf(key to mdmValues[key]) else emptyMap()
                val srv = if (hasSrv) mapOf(key to serverValues[key]) else emptyMap()
                val got = pick(m.computeEffectiveConfig(mdm, srv), key)
                val want = pick(if (hasMdm) mdmExpected else if (hasSrv) srvExpected else defaults, key)
                assertEquals("$key mdm=$hasMdm server=$hasSrv", want, got)
            }
        }
    }

    @Test
    fun anUnparseableMdmValueFallsThroughToServerThenDefault() {
        val m = EffectiveConfigManager()
        assertEquals(1500, m.computeEffectiveConfig(mapOf("max_outbox_items" to "lots"), mapOf("max_outbox_items" to 1500)).maxOutboxItems)
        assertEquals(2000, m.computeEffectiveConfig(mapOf("max_outbox_items" to -5), emptyMap()).maxOutboxItems)
        assertEquals(true, m.computeEffectiveConfig(mapOf("force_audio_only" to "maybe"), mapOf("force_audio_only" to "true")).forceAudioOnly)
    }

    @Test
    fun defaultsMatchTheSpecOutboxCap() {
        assertEquals(2000, AppConfig().maxOutboxItems)
    }

    @Test
    fun refreshPublishesTheMergedConfigAndSurvivesAServerFailure() = runBlocking {
        val m = EffectiveConfigManager(mdmSource = { mapOf("site_id" to "S-1") }, serverSource = { error("offline") })
        m.refresh()
        assertEquals("S-1", m.effectiveConfig.value.siteId)
    }
}
