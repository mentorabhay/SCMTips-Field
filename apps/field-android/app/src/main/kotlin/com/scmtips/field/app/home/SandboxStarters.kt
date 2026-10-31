package com.scmtips.field.app.home

import com.scmtips.field.app.jobs.ApiRequest
import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.JobTransport
import com.scmtips.field.core.common.UUIDv7
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/** What Today offers on a sandbox site so "nothing assigned" is never a dead end (owner test, 31 Oct). */
enum class SandboxStart(val label: String, val sub: String) {
    HOME_RECEIPT("New home receipt", "Receive what is in front of you"),
    COUNT_SHELF("Count a shelf", "Count one shelf or bin"),
}

/** A created task to open, or a reason to show. */
sealed interface SandboxOutcome {
    data class Created(val taskId: String, val refDocNo: String?) : SandboxOutcome
    data class Refused(val text: String) : SandboxOutcome
}

/**
 * field-api's sandbox routes (M3 contract §3; services/field-api/src/field_api/sandbox/api.py):
 * `POST /v1/sandbox/receipts {site_id}` and `POST /v1/sandbox/counts {site_id, bin}`, both 201
 * `{task_id, ref_doc_no}`; refused on a production site (403 FIELD-SBX-403-PRODUCTION).
 */
object SandboxStarters {
    fun offered(sandbox: Boolean): List<SandboxStart> = if (sandbox) SandboxStart.entries.toList() else emptyList()

    fun receipt(siteId: String, key: String = UUIDv7.generate()): ApiRequest =
        ApiRequest("POST", "/v1/sandbox/receipts", buildJsonObject { put("site_id", siteId) }, key)

    fun count(siteId: String, bin: String, key: String = UUIDv7.generate()): ApiRequest =
        ApiRequest("POST", "/v1/sandbox/counts", buildJsonObject { put("site_id", siteId); put("bin", bin.trim()) }, key)

    /** A shelf or bin label as typed or scanned: 1-64 characters, no spaces inside. */
    fun binOk(bin: String): Boolean = bin.trim().let { it.isNotEmpty() && it.length <= 64 && it.none(Char::isWhitespace) }

    suspend fun start(transport: JobTransport, siteId: String, what: SandboxStart, bin: String? = null): SandboxOutcome {
        val req = when (what) {
            SandboxStart.HOME_RECEIPT -> receipt(siteId)
            SandboxStart.COUNT_SHELF -> {
                if (bin == null || !binOk(bin)) return SandboxOutcome.Refused("Enter the shelf or bin label, like A-01.")
                count(siteId, bin)
            }
        }
        return when (val r = transport.send(req)) {
            is ApiResult.Ok -> (r.body["task_id"] as? JsonPrimitive)?.contentOrNull
                ?.let { SandboxOutcome.Created(it, (r.body["ref_doc_no"] as? JsonPrimitive)?.contentOrNull) }
                ?: SandboxOutcome.Refused("The server did not say which job it made. Refresh Today.")
            is ApiResult.Problem -> SandboxOutcome.Refused(
                if (r.code == PRODUCTION) "This site is not a sandbox: home receipts and shelf counts are for sandbox sites only." else r.plain,
            )
            is ApiResult.Offline -> SandboxOutcome.Refused("Cannot reach the PC. The job was not made.")
        }
    }

    const val PRODUCTION = "FIELD-SBX-403-PRODUCTION"
}
