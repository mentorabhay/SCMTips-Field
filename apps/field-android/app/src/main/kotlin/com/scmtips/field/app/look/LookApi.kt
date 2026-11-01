package com.scmtips.field.app.look

import com.scmtips.field.app.jobs.ApiRequest
import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.JobTransport
import com.scmtips.field.core.common.UUIDv7
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.security.MessageDigest

/** A raw-bytes PUT beside the JSON [JobTransport] (the captures upload). FieldSession implements it. */
fun interface BytesPort {
    suspend fun put(path: String, bytes: ByteArray, contentType: String): ApiResult
}

/**
 * One look photo, ready to upload: JPEG with faces already pixelated on the phone ([facesBlurred]),
 * at most [LookApi.MAX_PX] (1600) on its long side and [LookApi.MAX_BYTES]. [captureMs] is how long the camera took.
 */
class LookPhoto(
    val jpeg: ByteArray,
    val width: Int,
    val height: Int,
    val camera: CameraUsed,
    val takenAtMs: Long,
    val captureMs: Long,
    val facesBlurred: Int,
)

sealed interface UploadResult {
    data class Uploaded(val captureId: String) : UploadResult
    data object NeedsConsent : UploadResult
    data class Failed(val text: String) : UploadResult
}

sealed interface LookResult {
    data class Ok(val look: Look) : LookResult
    data class Failed(val text: String) : LookResult
}

sealed interface ClaimResult {
    data class Ok(val claim: Claim) : ClaimResult
    data class Failed(val text: String) : ClaimResult
}

sealed interface ClaimsList {
    data class Ok(val claims: List<Claim>) : ClaimsList

    /** 403: this person does not decide claims (the server decides; the phone only hides the card). */
    data object NotAllowed : ClaimsList
    data class Failed(val text: String) : ClaimsList
}

sealed interface StepResult {
    data class Ok(val step: ClaimStep) : StepResult
    data class Failed(val text: String, val status: Int?, val code: String? = null) : StepResult
}

/**
 * The M5 calls as data (docs/design/M5_CONTRACT.md §2–§3, captures API unchanged). Field names are pinned
 * by LookClientTest.
 */
object LookApi {
    /** The captures crop limit (field-api MAX_CROP_BYTES, 1 MB): the JPEG steps down in quality to fit it. */
    const val MAX_BYTES = 1_000_000
    /** A look photo's long side (M5-P01, owner-approved 1 Nov 2026: 640 left labels unreadable). Faces are pixelated
     *  on this full-size photo before it leaves the phone; the server cuts each label crop from it (at most 768 px).
     *  Scan crops keep core-capture's own 640 px rule (FR2.066, QuietModePolicy). */
    const val MAX_PX = 1600
    /** The first JPEG quality tried for a look photo; lower ones only when the photo is above [MAX_BYTES]. */
    const val JPEG_QUALITY = 85
    const val CODE_TYPE = "look"
    const val NO_CONSENT = "FIELD-CAP-403-NO-CONSENT"
    const val CONSENT_VERSION = "f1-2026-11"
    /** The look waits up to SAM 3.1 (15 s) + Muse label reads (30 s) on the server (vision/settings.py); 75 s leaves
     *  room for the upload and the reconciliation. Only the look call gets it. */
    const val LOOK_READ_TIMEOUT_S = 75

    fun uploadSession(key: String, deviceId: String, jpeg: ByteArray) =
        ApiRequest("POST", "/v1/captures/uploads", buildJsonObject {
            put("device_id", deviceId); put("sha256", sha256(jpeg)); put("bytes", jpeg.size); put("content_type", "image/jpeg")
        }, key)

    fun capture(key: String, deviceId: String, taskId: String?, siteId: String, photo: LookPhoto, uploadId: String, objectClass: String) =
        ApiRequest("POST", "/v1/captures", buildJsonObject {
            put("device_id", deviceId)
            taskId?.let { put("task_id", it) }
            put("site_id", siteId)
            put("shutter_timestamp", photo.takenAtMs)
            put("blur_applied", true)
            put("bystander_count", photo.facesBlurred)
            put("code_type", CODE_TYPE)
            put("code_value", "look-$key") // unique per photo: a second look is never a duplicate capture
            put("object_class", objectClass.take(32))
            put("crop_upload_id", uploadId)
        }, key)

    fun look(key: String, taskId: String, lineId: String?, captureId: String, case: LookCase) =
        ApiRequest("POST", "/v1/vision/looks", buildJsonObject {
            put("task_id", taskId)
            put("line_id", lineId)
            put("capture_id", captureId)
            put("object", case.noun)
            put("case", case.wire)
        }, key, readTimeoutSeconds = LOOK_READ_TIMEOUT_S)

    fun consent(key: String, siteId: String, deviceId: String) =
        ApiRequest("POST", "/v1/consents", buildJsonObject {
            put("site_id", siteId); put("device_id", deviceId); put("consent_version", CONSENT_VERSION)
            put("consent_type", "site_and_bystander_privacy"); put("granted", true)
        }, key)

    fun claim(key: String, lookId: String) = ApiRequest("POST", "/v1/claims", buildJsonObject { put("look_id", lookId) }, key)

    /** Oldest first, `{items, count}` (stream X). */
    fun drafts() = ApiRequest("GET", "/v1/claims?status=draft&limit=50")

    fun claimById(claimId: String) = ApiRequest("GET", "/v1/claims/${enc(claimId)}")

    /** If-Match is required (428 without, 412 when stale). */
    fun decision(key: String, claimId: String, approve: Boolean, reason: String?, etag: String) =
        ApiRequest("POST", "/v1/claims/${enc(claimId)}/decision", buildJsonObject {
            put("decision", if (approve) "approve" else "reject")
            reason?.takeIf { it.isNotBlank() }?.let { put("reason", it.take(200)) }
        }, key, mapOf("If-Match" to etag))

    /** With the ETag the decision answered; [words] are the supervisor's own confirm words. */
    fun confirm(key: String, claimId: String, etag: String, words: String?) =
        ApiRequest("POST", "/v1/claims/${enc(claimId)}/confirm", buildJsonObject {
            words?.takeIf { it.isNotBlank() }?.let { put("words", it.take(200)) }
        }, key, mapOf("If-Match" to etag))

    fun evidenceLink(key: String, docNumber: String, year: String?) =
        ApiRequest("POST", "/v1/evidence/documents/${enc(docNumber)}/link${year?.let { "?year=${enc(it)}" } ?: ""}", buildJsonObject { }, key)

    /** The signed evidence URL as an absolute address (field-api may answer a path such as /evidence/<token>). */
    fun absolute(base: String, url: String): String = when {
        url.startsWith("https://") || url.startsWith("http://") -> url
        else -> base.trimEnd('/') + "/" + url.trimStart('/')
    }

    fun sha256(b: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")
}

/**
 * Field-api for looks, claims and evidence. Pure: JSON through [JobTransport], the photo bytes through
 * [BytesPort], so LookClientTest drives it with a scripted fake. Every write carries a fresh UUIDv7
 * Idempotency-Key ([newKey]).
 */
class LookClient(
    private val transport: JobTransport,
    private val bytes: BytesPort,
    private val deviceId: () -> String?,
    private val newKey: () -> String = UUIDv7::generate,
) {
    /** Uploads the photo through the captures API (upload session → PUT bytes → capture). */
    suspend fun upload(photo: LookPhoto, taskId: String?, siteId: String, objectClass: String): UploadResult {
        val dev = deviceId() ?: return UploadResult.Failed("This phone is not registered yet.")
        if (photo.jpeg.size > LookApi.MAX_BYTES) return UploadResult.Failed("The photo is too large to send.")
        val session = when (val r = transport.send(LookApi.uploadSession(newKey(), dev, photo.jpeg))) {
            is ApiResult.Ok -> r.body.s("upload_id") ?: return UploadResult.Failed("The server did not open an upload.")
            else -> return failed(r)
        }
        val put = bytes.put("/v1/captures/uploads/$session", photo.jpeg, "image/jpeg")
        if (put !is ApiResult.Ok) return failed(put)
        return when (val r = transport.send(LookApi.capture(newKey(), dev, taskId, siteId, photo, session, objectClass))) {
            is ApiResult.Ok -> r.body.s("id")?.let { UploadResult.Uploaded(it) } ?: UploadResult.Failed("The server did not keep the photo.")
            is ApiResult.Problem -> if (r.code == LookApi.NO_CONSENT) UploadResult.NeedsConsent else UploadResult.Failed(r.plain)
            is ApiResult.Offline -> UploadResult.Failed(OFFLINE)
        }
    }

    suspend fun consent(siteId: String): Boolean {
        val dev = deviceId() ?: return false
        return transport.send(LookApi.consent(newKey(), siteId, dev)) is ApiResult.Ok
    }

    suspend fun look(taskId: String, lineId: String?, captureId: String, case: LookCase): LookResult =
        when (val r = transport.send(LookApi.look(newKey(), taskId, lineId, captureId, case))) {
            is ApiResult.Ok -> LookJson.look(r.body)?.let { LookResult.Ok(it) } ?: LookResult.Failed("The look came back empty. Count aloud instead.")
            is ApiResult.Problem -> LookResult.Failed(if (r.status == 404) NOT_YET else r.plain)
            is ApiResult.Offline -> LookResult.Failed(OFFLINE)
        }

    /** 201 a new claim, or 200 the look's existing one (one claim per look). */
    suspend fun claim(lookId: String): ClaimResult = when (val r = transport.send(LookApi.claim(newKey(), lookId))) {
        is ApiResult.Ok -> LookJson.claim(r.body)?.let { ClaimResult.Ok(it.copy(etag = r.etag ?: it.etag)) }
            ?: ClaimResult.Failed("The server did not make the claim.")
        is ApiResult.Problem -> ClaimResult.Failed(if (r.status == 404) "Claims are not available on this server yet." else r.plain)
        is ApiResult.Offline -> ClaimResult.Failed(OFFLINE)
    }

    suspend fun drafts(): ClaimsList = when (val r = transport.send(LookApi.drafts())) {
        is ApiResult.Ok -> ClaimsList.Ok(LookJson.claims(r.body))
        is ApiResult.Problem -> if (r.status == 403 || r.status == 404) ClaimsList.NotAllowed else ClaimsList.Failed(r.plain)
        is ApiResult.Offline -> ClaimsList.Failed(OFFLINE)
    }

    /** The claim's current ETag (the list may not carry one): `GET /v1/claims/{id}`. */
    suspend fun etag(claimId: String): String? = when (val r = transport.send(LookApi.claimById(claimId))) {
        is ApiResult.Ok -> r.etag ?: LookJson.claim(r.body)?.etag
        else -> null
    }

    suspend fun decide(claimId: String, approve: Boolean, reason: String?, etag: String): StepResult =
        step(transport.send(LookApi.decision(newKey(), claimId, approve, reason, etag)))

    suspend fun confirm(claimId: String, etag: String, words: String?): StepResult =
        step(transport.send(LookApi.confirm(newKey(), claimId, etag, words)))

    /** The signed evidence link for a posted document; null with the reason when there is none. */
    suspend fun evidenceLink(docNumber: String, year: String?): Pair<String?, String?> =
        when (val r = transport.send(LookApi.evidenceLink(newKey(), docNumber, year))) {
            is ApiResult.Ok -> (r.body.s("url") ?: r.body.s("evidence_url") ?: r.body.s("link"))
                ?.let { it to null } ?: (null to "The server sent no evidence link.")
            is ApiResult.Problem -> null to (if (r.status == 404) "The evidence page is not available on this server yet." else r.plain)
            is ApiResult.Offline -> null to OFFLINE
        }

    private fun step(r: ApiResult): StepResult = when (r) {
        is ApiResult.Ok -> StepResult.Ok(LookJson.step(r.body, r.etag))
        is ApiResult.Problem -> StepResult.Failed(r.plain, r.status, r.code)
        is ApiResult.Offline -> StepResult.Failed(OFFLINE, null)
    }

    private fun failed(r: ApiResult): UploadResult.Failed = when (r) {
        is ApiResult.Problem -> UploadResult.Failed(r.plain)
        is ApiResult.Offline -> UploadResult.Failed(OFFLINE)
        is ApiResult.Ok -> UploadResult.Failed("Unexpected answer.")
    }

    private fun kotlinx.serialization.json.JsonObject.s(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull

    companion object {
        const val OFFLINE = "Cannot reach the PC. Check the Wi-Fi."
        const val NOT_YET = "Looks are not available on this server yet. Count aloud instead."
    }
}
