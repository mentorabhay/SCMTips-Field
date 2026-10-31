package com.scmtips.field.feature.decisions.api

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.IOException

/**
 * The SCMTIPS core as the approver flow sees it: the calls the wearable (device) token may make, all
 * under `{core}/v1` with `Authorization: Bearer <wearable token>`, `X-Device-Id` and `X-Requested-With: lr`
 * (handover 01, F1; the core checks the last on every state-changing route, its reply TO_FIELD section 3).
 * Every approval rule lives in the core: these calls only carry words and codes there.
 */
interface DecisionsApi {
    /** GET /v1/wearable/next: the decision waiting longest, or null when nothing waits. */
    suspend fun next(): NextItem?

    /** GET /v1/briefs/decision/{id}?format=…: the core's brief document (the template the spoken brief is made from). */
    suspend fun brief(decisionId: String, format: BriefFormat = BriefFormat.SPOKEN): CoreBrief

    /** POST /v1/voice/challenges. */
    suspend fun createChallenge(decisionId: String): Challenge

    /** POST /v1/voice/commands with an Idempotency-Key (a retry of the same turn reuses it). */
    suspend fun sendCommand(nonce: String, transcript: String, idempotencyKey: String): CommandResponse

    /** GET /v1/auth/step-up. */
    suspend fun stepUpStatus(): StepUpStatus

    /** POST /v1/auth/step-up. Throws [CoreException.InvalidStepUpCode] for a wrong code. */
    suspend fun stepUp(method: StepUpMethod, code: String): StepUpStatus

    /** POST /v1/evidence/photos (multipart). */
    suspend fun uploadPhoto(upload: PhotoUpload): PhotoEvidence

    /** GET /v1/wearable/sessions. */
    suspend fun sessions(): List<DeviceSessionInfo>

    /** DELETE /v1/wearable/sessions/{session_id} (sign out of this device; 204). */
    suspend fun revoke(sessionId: String)
}

sealed class CoreException(message: String, cause: Throwable? = null) : Exception(message, cause) {
    /** 401 anywhere except a wrong step-up code: the wearable token expired or was revoked. Sign in again. */
    class Unauthorized(val problem: Problem?) : CoreException(problem?.title ?: "Unauthorized")

    /** 401 `invalid_code` from POST /v1/auth/step-up. */
    class InvalidStepUpCode(val problem: Problem?) : CoreException(problem?.title ?: "Invalid code")

    /** Any other non-2xx answer. */
    class Http(val status: Int, val problem: Problem?) : CoreException(problem?.title ?: problem?.detail ?: "HTTP $status")

    /** No answer (offline, TLS, timeout) or an answer the app cannot read. */
    class Network(cause: Throwable) : CoreException(cause.message ?: "Network error", cause)

    /** Rejected by the app before anything was sent. */
    class Invalid(message: String) : CoreException(message)
}

/** Where the client reads the device identity and the wearable token (EncryptedSharedPreferences in the app). */
interface CoreCredentials {
    /** The device id the wearable token is bound to (the one sent at sign-in). */
    val deviceId: String

    /** The current wearable token, or null when signed out or expired. */
    val token: String?
}

class CoreClient(
    baseUrl: String,
    private val credentials: CoreCredentials,
    private val http: CoreHttp,
) : DecisionsApi {
    private val v1 = CoreUrls.v1(baseUrl)

    override suspend fun next(): NextItem? = json(authed("GET", "wearable", "next"), CoreJson::nextItem)

    override suspend fun brief(decisionId: String, format: BriefFormat): CoreBrief {
        val call = authed("GET", "briefs", "decision", decisionId)
        return json(call.copy(url = call.url + "?format=" + format.wire)) { CoreJson.brief(it, "decision", decisionId, format) }
    }

    override suspend fun createChallenge(decisionId: String): Challenge =
        json(authed("POST", "voice", "challenges", body = buildJsonObject { put("decision_id", decisionId) }), CoreJson::challenge)

    override suspend fun sendCommand(nonce: String, transcript: String, idempotencyKey: String): CommandResponse {
        val call = authed("POST", "voice", "commands", body = buildJsonObject { put("nonce", nonce); put("transcript", transcript) })
        return json(call.copy(headers = call.headers + (HEADER_IDEMPOTENCY_KEY to idempotencyKey)), CoreJson::command)
    }

    override suspend fun stepUpStatus(): StepUpStatus = json(authed("GET", "auth", "step-up"), CoreJson::stepUp)

    override suspend fun stepUp(method: StepUpMethod, code: String): StepUpStatus {
        val call = authed("POST", "auth", "step-up", body = buildJsonObject { put("method", method.wire); put("code", code.trim()) })
        return try {
            json(call, CoreJson::stepUp)
        } catch (e: CoreException.Unauthorized) {
            if (e.problem?.code == "invalid_code") throw CoreException.InvalidStepUpCode(e.problem) else throw e
        }
    }

    override suspend fun uploadPhoto(upload: PhotoUpload): PhotoEvidence {
        if (upload.mimeType != "image/jpeg" && upload.mimeType != "image/png") throw CoreException.Invalid("Photo must be JPEG or PNG")
        if (upload.image.size > MAX_PHOTO_BYTES) throw CoreException.Invalid("Photo is larger than 8 MB")
        if (upload.label.isBlank() || upload.label.length > 120) throw CoreException.Invalid("Label must be 1-120 characters")
        if ((upload.segmentPrompt?.length ?: 0) > 80) throw CoreException.Invalid("Segment prompt must be at most 80 characters")
        val fileName = if (upload.mimeType == "image/png") "evidence.png" else "evidence.jpg"
        val parts = buildList {
            add(FormPart.file("image", fileName, upload.mimeType, upload.image))
            add(FormPart.text("subject_kind", upload.subjectKind.wire))
            add(FormPart.text("subject_id", upload.subjectId))
            add(FormPart.text("label", upload.label))
            add(FormPart.text("consent", "true"))
            upload.segmentPrompt?.takeIf { it.isNotBlank() }?.let { add(FormPart.text("segment_prompt", it)) }
        }
        return json(authed("POST", "evidence", "photos").copy(body = HttpBody.Multipart(parts)), CoreJson::photo)
    }

    override suspend fun sessions(): List<DeviceSessionInfo> = CoreJson.sessions(text(authed("GET", "wearable", "sessions")))

    override suspend fun revoke(sessionId: String) {
        text(authed("DELETE", "wearable", "sessions", sessionId))
    }

    private fun authed(method: String, vararg segments: String, body: JsonObject? = null): HttpCall {
        val token = credentials.token ?: throw CoreException.Unauthorized(null)
        return HttpCall(
            method, CoreUrls.join(v1, *segments),
            mapOf(
                "Authorization" to "Bearer $token",
                HEADER_DEVICE_ID to credentials.deviceId,
                HEADER_REQUESTED_WITH to REQUESTED_WITH,
            ),
            body?.let { HttpBody.Json(it.toString()) },
        )
    }

    /** A JSON object answer read by [read]; an unreadable body or a missing field is a [CoreException.Network]. */
    private suspend fun <T> json(call: HttpCall, read: (JsonObject) -> T): T {
        val obj = CoreJson.obj(text(call)) ?: throw CoreException.Network(IllegalStateException("unreadable answer from ${call.method} ${call.url}"))
        return try {
            read(obj)
        } catch (e: IllegalArgumentException) {
            throw CoreException.Network(e)
        }
    }

    private suspend fun text(call: HttpCall): String {
        val reply = try {
            http.execute(call)
        } catch (e: IOException) {
            throw CoreException.Network(e)
        }
        if (!reply.ok) {
            val problem = CoreJson.problem(reply.body)
            if (reply.status == 401) throw CoreException.Unauthorized(problem)
            throw CoreException.Http(reply.status, problem)
        }
        return reply.body
    }

    companion object {
        const val HEADER_DEVICE_ID = "X-Device-Id"
        const val HEADER_REQUESTED_WITH = "X-Requested-With"
        const val REQUESTED_WITH = "lr"
        const val HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"
        const val MAX_PHOTO_BYTES = 8 * 1024 * 1024
    }
}

/** URL building that keeps a path prefix (`https://host/scmtips/` → `https://host/scmtips/v1/...`). */
object CoreUrls {
    fun v1(baseUrl: String): String = baseUrl.trim().trimEnd('/') + "/v1"

    fun join(base: String, vararg segments: String): String =
        base + segments.joinToString("") { "/" + encode(it) }

    private fun encode(segment: String): String =
        java.net.URLEncoder.encode(segment, "UTF-8").replace("+", "%20")

    /** The form of an `http(s)://host[:port][/prefix]` server address the app accepts (null when it is not one). */
    fun normalise(url: String): String? {
        val u = url.trim().trimEnd('/')
        if (!(u.startsWith("http://") || u.startsWith("https://"))) return null
        val host = u.substringAfter("://").substringBefore('/').substringBefore(':')
        return if (host.isBlank() || host.any { it.isWhitespace() }) null else u
    }
}
