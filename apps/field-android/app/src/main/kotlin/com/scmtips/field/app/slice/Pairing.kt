package com.scmtips.field.app.slice

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

/**
 * What the phone learns from the QR code that `stack pair` prints on the owner's PC
 * (tools/dev_stack/stack.py `pairing_payload` is the producer; the two must stay identical).
 *
 * `token` is a core login token (fake-core in the field test). The app exchanges it for a short-lived
 * field token (POST /v1/auth/exchange) and never sends it anywhere else.
 */
data class Pairing(
    val apiBaseUrl: String,
    val coreToken: String,
    val tenantId: String,
    val siteId: String,
    val siteName: String,
)

object PairingPayload {
    const val VERSION = 1

    /** Parses and validates a scanned QR payload; throws [IllegalArgumentException] with a user-facing reason. */
    fun parse(text: String): Pairing {
        val obj = try {
            Json.parseToJsonElement(text.trim()) as? JsonObject
        } catch (e: Exception) {
            null
        } ?: throw IllegalArgumentException("This QR code is not a SCMTips pairing code.")
        val version = (obj["v"] as? JsonPrimitive)?.intOrNull
        require(version == VERSION) { "Pairing code version $version is not supported; update the app." }
        fun field(name: String): String {
            val v = (obj[name] as? JsonPrimitive)?.contentOrNull?.trim()
            require(!v.isNullOrEmpty()) { "Pairing code is missing '$name'." }
            return v
        }
        val api = field("api").trimEnd('/')
        require(api.startsWith("http://") || api.startsWith("https://")) { "Pairing code has no valid server address." }
        if (api.startsWith("http://")) {
            require(isPrivateHost(hostOf(api))) {
                "Plain http is only allowed to a PC on your own network; use the https tunnel address instead."
            }
        }
        return Pairing(api, field("token"), field("tenant"), field("site"), field("site_name"))
    }

    internal fun hostOf(url: String): String =
        url.substringAfter("://").substringBefore('/').substringBefore(':').lowercase()

    /** RFC 1918 / loopback / link-local addresses: the only hosts debug builds may reach over http. */
    internal fun isPrivateHost(host: String): Boolean {
        if (host == "localhost") return true
        val parts = host.split('.').map { it.toIntOrNull() ?: return false }
        if (parts.size != 4 || parts.any { it !in 0..255 }) return false
        val (a, b) = parts[0] to parts[1]
        return a == 10 || a == 127 || (a == 172 && b in 16..31) || (a == 192 && b == 168) || (a == 169 && b == 254)
    }
}
