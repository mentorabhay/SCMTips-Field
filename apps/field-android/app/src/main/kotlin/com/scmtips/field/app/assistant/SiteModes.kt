package com.scmtips.field.app.assistant

import com.scmtips.field.app.jobs.ApiRequest
import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.JobTransport
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.net.URLEncoder

/** What `GET /v1/codes/{code}` says about a code (M3 contract §2). */
data class CodeInfo(val code: String, val kind: String, val material: String?, val description: String?, val bin: String?, val siteMode: String?)

/**
 * A site's mode, "production" or "sandbox" (M3 contract §2), from `GET /v1/sites` items or from the
 * `site_mode` of `GET /v1/codes/{code}`. Unknown (no answer, an older field-api) counts as production:
 * an unknown code is then refused as before, never added.
 */
class SiteModes(private val transport: JobTransport) {
    private val known = mutableMapOf<String, String>()

    fun modeOf(siteId: String): String? = known[siteId]

    fun isSandbox(siteId: String): Boolean = known[siteId] == SANDBOX

    /** Reads the site list once; quietly keeps nothing when the operator may not list sites. */
    suspend fun prime(siteId: String) {
        if (siteId in known) return
        val r = transport.send(sites()) as? ApiResult.Ok ?: return
        fromSites(r.body, siteId)?.let { known[siteId] = it }
    }

    /** Looks [code] up for [siteId]; remembers the site mode the answer carries. Null when it failed. */
    suspend fun lookup(siteId: String, code: String): CodeInfo? {
        val r = transport.send(codeLookup(code, siteId)) as? ApiResult.Ok ?: return null
        val info = parseCode(r.body) ?: return null
        info.siteMode?.let { known[siteId] = it }
        return info
    }

    /** True when [code] may become a new line: a sandbox site (asked once, then remembered). */
    suspend fun allowsNewItems(siteId: String, code: String): Boolean {
        if (siteId !in known) lookup(siteId, code)
        return isSandbox(siteId)
    }

    companion object {
        const val SANDBOX = "sandbox"
        const val PRODUCTION = "production"

        fun sites(): ApiRequest = ApiRequest("GET", "/v1/sites?limit=200")

        fun codeLookup(code: String, siteId: String): ApiRequest =
            ApiRequest("GET", "/v1/codes/${enc(code.trim())}?site_id=${enc(siteId)}")

        fun fromSites(body: JsonObject, siteId: String): String? =
            (body["items"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
                .firstOrNull { it.s("id") == siteId }?.s("mode")?.takeIf { it == SANDBOX || it == PRODUCTION }

        fun parseCode(body: JsonObject): CodeInfo? {
            val code = body.s("code") ?: return null
            val m = body["material"] as? JsonObject
            return CodeInfo(
                code = code,
                kind = body.s("kind") ?: "unknown",
                material = m?.s("material"),
                description = m?.s("description"),
                bin = body.s("bin"),
                siteMode = body.s("site_mode")?.takeIf { it == SANDBOX || it == PRODUCTION },
            )
        }

        private fun JsonObject.s(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull
        private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")
    }
}
