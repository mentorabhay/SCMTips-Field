package com.scmtips.field.app.config

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Normalized application configuration data class (Task T2.005 / FR2.004 / FR2.054).
 */
data class AppConfig(
    val fieldApiBaseUrl: String = DEFAULT_BASE_URL,
    val tenantHint: String = "",
    val siteId: String = "",
    val allowedGlassesModels: List<String> = listOf("Ray-Ban Display", "Ray-Ban Meta"),
    val forceAudioOnly: Boolean = false,
    val phoneCameraModeAllowed: Boolean = true,
    val maxOutboxItems: Int = 500,
    val logLevel: String = "INFO"
) {
    companion object {
        const val DEFAULT_BASE_URL = "http://10.0.2.2:8000"
    }
}

/**
 * Effective Configuration Manager merging MDM, Server and Defaults with precedence:
 * MDM > Server > App Default (TC2.104).
 */
class EffectiveConfigManager(
    private val mdmSource: () -> Map<String, Any?> = { emptyMap() },
    private val serverSource: suspend () -> Map<String, Any?> = { emptyMap() }
) {
    private val _effectiveConfig = MutableStateFlow(AppConfig())
    val effectiveConfig: StateFlow<AppConfig> = _effectiveConfig.asStateFlow()

    fun computeEffectiveConfig(
        mdm: Map<String, Any?> = mdmSource(),
        server: Map<String, Any?> = emptyMap(),
        defaults: AppConfig = AppConfig()
    ): AppConfig {
        fun <T> resolve(key: String, mdmVal: Any?, serverVal: Any?, defaultVal: T, transform: (Any) -> T): T {
            if (mdmVal != null) {
                return try { transform(mdmVal) } catch (_: Exception) { defaultVal }
            }
            if (serverVal != null) {
                return try { transform(serverVal) } catch (_: Exception) { defaultVal }
            }
            return defaultVal
        }

        val baseUrl = resolve(
            "field_api_base_url",
            mdm["field_api_base_url"],
            server["field_api_base_url"],
            defaults.fieldApiBaseUrl
        ) { it.toString() }

        val tenantHint = resolve(
            "tenant_hint",
            mdm["tenant_hint"],
            server["tenant_hint"],
            defaults.tenantHint
        ) { it.toString() }

        val siteId = resolve(
            "site_id",
            mdm["site_id"],
            server["site_id"],
            defaults.siteId
        ) { it.toString() }

        val allowedModels = resolve(
            "allowed_glasses_models",
            mdm["allowed_glasses_models"],
            server["allowed_glasses_models"],
            defaults.allowedGlassesModels
        ) { raw ->
            when (raw) {
                is List<*> -> raw.mapNotNull { it?.toString() }
                is String -> raw.split(",").map { it.trim() }
                else -> defaults.allowedGlassesModels
            }
        }

        val forceAudioOnly = resolve(
            "force_audio_only",
            mdm["force_audio_only"],
            server["force_audio_only"],
            defaults.forceAudioOnly
        ) { raw ->
            when (raw) {
                is Boolean -> raw
                is String -> raw.toBooleanStrictOrNull() ?: defaults.forceAudioOnly
                else -> defaults.forceAudioOnly
            }
        }

        val phoneCameraModeAllowed = resolve(
            "phone_camera_mode_allowed",
            mdm["phone_camera_mode_allowed"],
            server["phone_camera_mode_allowed"],
            defaults.phoneCameraModeAllowed
        ) { raw ->
            when (raw) {
                is Boolean -> raw
                is String -> raw.toBooleanStrictOrNull() ?: defaults.phoneCameraModeAllowed
                else -> defaults.phoneCameraModeAllowed
            }
        }

        val maxOutboxItems = resolve(
            "max_outbox_items",
            mdm["max_outbox_items"],
            server["max_outbox_items"],
            defaults.maxOutboxItems
        ) { raw ->
            when (raw) {
                is Number -> raw.toInt()
                is String -> raw.toIntOrNull() ?: defaults.maxOutboxItems
                else -> defaults.maxOutboxItems
            }
        }

        val logLevel = resolve(
            "log_level",
            mdm["log_level"],
            server["log_level"],
            defaults.logLevel
        ) { it.toString() }

        val merged = AppConfig(
            fieldApiBaseUrl = baseUrl,
            tenantHint = tenantHint,
            siteId = siteId,
            allowedGlassesModels = allowedModels,
            forceAudioOnly = forceAudioOnly,
            phoneCameraModeAllowed = phoneCameraModeAllowed,
            maxOutboxItems = maxOutboxItems,
            logLevel = logLevel
        )

        _effectiveConfig.value = merged
        return merged
    }

    suspend fun refresh() {
        val mdm = mdmSource()
        val server = try { serverSource() } catch (_: Exception) { emptyMap() }
        computeEffectiveConfig(mdm, server)
    }
}
