package com.scmtips.field.app.check

import com.scmtips.field.app.jobs.ApiRequest
import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.JobTransport
import com.scmtips.field.app.look.BytesPort
import com.scmtips.field.app.look.Claim
import com.scmtips.field.app.look.LookClient
import com.scmtips.field.app.look.LookJson
import com.scmtips.field.app.look.LookPhoto
import com.scmtips.field.app.look.UploadResult
import com.scmtips.field.core.common.UUIDv7
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import java.net.URLEncoder

/** The C3 calls as data (docs/design/M5_C3_CONTRACT.md §4). Field names are pinned by AuthenticityClientTest. */
object CheckApi {
    const val CHECKS = "/v1/authenticity/checks"

    /** The QR text the server takes (1..1024 characters; longer is 422 there, so the phone does not send it). */
    const val MAX_CODE = 1024

    /** The seal photo's captures API fields (contract §7): no task, its own code type. */
    const val SEAL_CODE_TYPE = "seal_photo"
    const val SEAL_CODE_VALUE = "authenticity"
    const val SEAL_OBJECT = "seal"

    /** Two steps (contract §4.1): GET every second, up to 45 s, while the visual seal check runs. */
    const val POLL_MS = 1_000L
    const val POLL_MAX = 45

    const val ERR_SITE = "FIELD-AUT-422-SITE"
    const val ERR_CAPTURE = "FIELD-AUT-404-CAPTURE"
    const val ERR_CHECK = "FIELD-AUT-404-CHECK"
    const val ERR_FORBIDDEN = "FIELD-AUTH-403-FORBIDDEN"
    const val ERR_VALIDATION = "FIELD-HTTP-422-VALIDATION"
    const val ERR_CLAIM_PENDING = "FIELD-CLM-409-CHECK-PENDING"
    const val ERR_NOTHING_TO_CLAIM = "FIELD-CLM-422-NOTHING-TO-CLAIM"

    /**
     * `POST /v1/authenticity/checks`. `capture_id` and `site_id` are sent as null when there are none (the server
     * then uses the capture's site or the person's only site); `area` is not sent: the owner has not decided to.
     */
    fun check(key: String, code: String, captureId: String?, siteId: String?) =
        ApiRequest("POST", CHECKS, buildJsonObject {
            put("code", code)
            put("capture_id", captureId)
            put("site_id", siteId)
        }, key)

    fun checkById(checkId: String) = ApiRequest("GET", "$CHECKS/${enc(checkId)}")

    /** The signed evidence page link: `{url, path, expires_at}`. */
    fun link(key: String, checkId: String) = ApiRequest("POST", "$CHECKS/${enc(checkId)}/link", buildJsonObject { }, key)

    /** A claim from a check (exactly one of look_id / check_id; contract §4.4). */
    fun claim(key: String, checkId: String) = ApiRequest("POST", "/v1/claims", buildJsonObject { put("check_id", checkId) }, key)

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")
}

/** Why a check was not answered (contract §4.5 and §7 "Errors"); each one has its own spoken sentence. */
enum class CheckError { OFFLINE, FORBIDDEN, SITE, CAPTURE_GONE, NOT_ON_SERVER, INVALID, EMPTY, OTHER }

sealed interface CheckResult {
    data class Ok(val check: AuthenticityCheck) : CheckResult
    data class Failed(val error: CheckError, val text: String) : CheckResult
}

sealed interface CheckClaimResult {
    data class Ok(val claim: Claim) : CheckClaimResult

    /** 422 FIELD-CLM-422-NOTHING-TO-CLAIM: genuine and new, the seal intact. */
    data object NothingToClaim : CheckClaimResult

    /** 409 FIELD-CLM-409-CHECK-PENDING: the visual seal check still runs. */
    data object Pending : CheckClaimResult
    data class Failed(val text: String) : CheckClaimResult
}

/**
 * Field-api for C3 box checks. Pure: JSON through [JobTransport], the seal photo through the captures API (the
 * look's [LookClient] upload, with the seal's code type), so AuthenticityClientTest drives it with a scripted
 * fake. Every write but a retried check carries a fresh UUIDv7 Idempotency-Key ([newKey]); the check itself
 * takes its key from the caller so a retry after a network failure sends the same one.
 */
class CheckClient(
    private val transport: JobTransport,
    bytes: BytesPort,
    deviceId: () -> String?,
    private val newKey: () -> String = UUIDv7::generate,
) {
    private val captures = LookClient(transport, bytes, deviceId, newKey)

    /** The seal photo: faces already pixelated, through the captures API with `seal_photo` / `authenticity`. */
    suspend fun uploadSeal(photo: LookPhoto, siteId: String): UploadResult =
        captures.upload(photo, null, siteId, CheckApi.SEAL_OBJECT, CheckApi.SEAL_CODE_TYPE, CheckApi.SEAL_CODE_VALUE)

    suspend fun consent(siteId: String): Boolean = captures.consent(siteId)

    fun key(): String = newKey()

    suspend fun check(key: String, code: String, captureId: String?, siteId: String?): CheckResult =
        answer(transport.send(CheckApi.check(key, code, captureId, siteId)))

    /** `GET /v1/authenticity/checks/{id}`: the check now (final, or the seal still being checked). */
    suspend fun checkNow(checkId: String): CheckResult = answer(transport.send(CheckApi.checkById(checkId)))

    suspend fun claim(checkId: String): CheckClaimResult = when (val r = transport.send(CheckApi.claim(newKey(), checkId))) {
        is ApiResult.Ok -> LookJson.claim(r.body)?.let { CheckClaimResult.Ok(it.copy(etag = r.etag ?: it.etag)) }
            ?: CheckClaimResult.Failed("The server did not make the claim.")
        is ApiResult.Problem -> when {
            r.code == CheckApi.ERR_NOTHING_TO_CLAIM -> CheckClaimResult.NothingToClaim
            r.code == CheckApi.ERR_CLAIM_PENDING -> CheckClaimResult.Pending
            r.status == 403 -> CheckClaimResult.Failed("You are not allowed to make claims here.")
            r.status == 404 || r.code == CheckApi.ERR_VALIDATION -> CheckClaimResult.Failed("Claims from a box check are not available on this server yet.")
            else -> CheckClaimResult.Failed(r.plain)
        }
        is ApiResult.Offline -> CheckClaimResult.Failed(OFFLINE)
    }

    /** The signed evidence page of a check; null with the reason when there is none. */
    suspend fun evidenceLink(checkId: String): Pair<String?, String?> =
        when (val r = transport.send(CheckApi.link(newKey(), checkId))) {
            is ApiResult.Ok -> ((r.body["url"] as? JsonPrimitive)?.contentOrNull ?: (r.body["path"] as? JsonPrimitive)?.contentOrNull)
                ?.let { it to null } ?: (null to "The server sent no evidence link.")
            is ApiResult.Problem -> null to (if (r.status == 404) "The evidence page is not available on this server yet." else r.plain)
            is ApiResult.Offline -> null to OFFLINE
        }

    private fun answer(r: ApiResult): CheckResult = when (r) {
        is ApiResult.Ok -> CheckJson.check(r.body)?.let { CheckResult.Ok(it) } ?: CheckResult.Failed(CheckError.EMPTY, "The check came back empty.")
        is ApiResult.Problem -> when {
            r.status == 403 -> CheckResult.Failed(CheckError.FORBIDDEN, FORBIDDEN)
            r.code == CheckApi.ERR_SITE -> CheckResult.Failed(CheckError.SITE, PICK_SITE)
            r.code == CheckApi.ERR_CAPTURE -> CheckResult.Failed(CheckError.CAPTURE_GONE, "The seal photo was not found on the server.")
            r.code == CheckApi.ERR_CHECK -> CheckResult.Failed(CheckError.OTHER, "That check is not there any more. Say check this box again.")
            r.status == 404 -> CheckResult.Failed(CheckError.NOT_ON_SERVER, NOT_ON_SERVER)
            r.status == 422 -> CheckResult.Failed(CheckError.INVALID, "The server could not read this code. Scan it again.")
            else -> CheckResult.Failed(CheckError.OTHER, r.plain)
        }
        is ApiResult.Offline -> CheckResult.Failed(CheckError.OFFLINE, OFFLINE)
    }

    companion object {
        /** Contract §7 "Errors", word for word. */
        const val OFFLINE = "I couldn't reach Field. Try again."
        const val FORBIDDEN = "You are not allowed to check boxes here."
        const val PICK_SITE = "Pick a site first: open Me, then Site. Then say check this box again."
        const val NOT_ON_SERVER = "Box checks are not available on this server yet."
    }
}
