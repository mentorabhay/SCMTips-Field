package com.scmtips.field.app.net

import com.scmtips.field.app.slice.FieldBackend
import com.scmtips.field.app.slice.ReceiveTask
import com.scmtips.field.app.slice.TaskLine
import com.scmtips.field.core.common.UUIDv7
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class HttpError(val status: Int, val code: String?, message: String) : Exception(message)

/**
 * Talks to field-api exactly as tools/dev_stack/stack.py `Phone` does (that smoke run is the proof of
 * this call sequence): exchange the core token, register the phone, re-exchange bound to the device,
 * then tasks, voice events, count records, post requests and live events.
 *
 * Field tokens live 10 minutes; [token] re-exchanges a minute before expiry. The core token is never
 * logged. Every POST carries a fresh UUIDv7 Idempotency-Key (FR2.039).
 */
class FieldSession(
    private val apiBaseUrl: String,
    private val coreToken: String,
    var deviceId: String?,
    private val client: OkHttpClient = defaultClient(),
    private val clock: () -> Long = System::currentTimeMillis,
) : FieldBackend {
    private val json = Json { ignoreUnknownKeys = true }
    private val mutex = Mutex()
    private var accessToken: String? = null
    private var expiresAtMs: Long = 0

    private suspend fun token(): String = mutex.withLock {
        val t = accessToken
        if (t != null && clock() < expiresAtMs - 60_000) return t
        val body = buildJsonObject {
            put("device_token", coreToken)
            deviceId?.let { put("device_id", it) }
        }
        val res = call("POST", "/v1/auth/exchange", body, auth = null, idempotent = false).jsonObject
        accessToken = res.str("access_token")
        expiresAtMs = clock() + (res["expires_in"] as JsonPrimitive).intOrNull!! * 1000L
        accessToken!!
    }

    /** First run: register this phone, then bind the session to it. Returns the device id. */
    suspend fun registerPhone(serial: String, model: String, osVersion: String, appVersion: String): String {
        deviceId?.let { return it }
        val res = call("POST", "/v1/devices", buildJsonObject {
            put("kind", "phone"); put("serial_no", serial); put("model", model)
            put("os_version", osVersion); put("app_version", appVersion)
        }).jsonObject
        val id = res.str("id")
        mutex.withLock { accessToken = null; deviceId = id }
        token()
        return id
    }

    suspend fun receiveTasks(siteId: String): List<ReceiveTask> {
        val res = call("GET", "/v1/tasks?site_id=$siteId&type=receive", null).jsonObject
        return res["items"]!!.jsonArray.map { it.jsonObject }
            .filter { it.str("status") !in setOf("completed", "cancelled") }
            .map { t ->
                ReceiveTask(
                    id = t.str("id"),
                    erpRef = t.opt("erp_ref") ?: "",
                    title = t.opt("title") ?: "",
                    lines = (t["lines"] as? JsonArray ?: JsonArray(emptyList())).map { it.jsonObject }.map { l ->
                        TaskLine(
                            id = l.str("id"),
                            lineNo = (l["line_no"] as JsonPrimitive).intOrNull ?: 0,
                            material = l.opt("material"),
                            uom = l.opt("uom") ?: "EA",
                            expectedQty = (l["expected_qty"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
                            countedQty = (l["counted_qty"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
                            status = if (((l["counted_qty"] as? JsonPrimitive)?.doubleOrNull ?: 0.0) > 0 &&
                                l.opt("status") == "pending") "counted" else (l.opt("status") ?: "pending"),
                        )
                    },
                )
            }
    }

    override suspend fun voiceEvent(taskId: String, intent: String, transcript: String, confidence: Float): String =
        call("POST", "/v1/voice-events", buildJsonObject {
            put("device_id", deviceId ?: error("phone not registered"))
            put("task_id", taskId); put("transcript", transcript); put("confidence", confidence.toDouble())
            put("intent", intent); put("is_accepted", true)
        }).jsonObject.str("id")

    override suspend fun count(lineId: String, qty: Double, uom: String, voiceEventId: String): Double {
        val res = call("POST", "/v1/count-records", buildJsonObject {
            put("task_line_id", lineId); put("value", qty); put("unit", uom); put("voice_event_id", voiceEventId)
        }).jsonObject
        return (res["counted_qty"] as? JsonPrimitive)?.doubleOrNull ?: qty
    }

    override suspend fun postRequest(taskId: String, lines: List<Pair<String, Double>>, postVoiceId: String, confirmVoiceId: String): String =
        call("POST", "/v1/tasks/$taskId/post-requests", buildJsonObject {
            put("lines", buildJsonArray { lines.forEach { add(JsonPrimitive(it.first)) } })
            put("staged_hash", stagedHash(lines))
            put("post_voice_event_id", postVoiceId); put("confirm_voice_event_id", confirmVoiceId)
        }).jsonObject.str("posting_request_id")

    /** Pending live events for this device (SSE with once=true; called every couple of seconds). */
    suspend fun pollEvents(lastEventId: String?): List<JsonObject> {
        val id = deviceId ?: return emptyList()
        val q = "once=true" + (lastEventId?.let { "&last_event_id=$it" } ?: "")
        val text = raw("GET", "/v1/devices/$id/events?$q", null, token())
        return text.lineSequence().filter { it.startsWith("data: ") }
            .mapNotNull { runCatching { json.parseToJsonElement(it.removePrefix("data: ")).jsonObject }.getOrNull() }
            .toList()
    }

    private suspend fun call(method: String, path: String, body: JsonElement?, auth: String? = "", idempotent: Boolean = true): JsonElement {
        val bearer = if (auth == null) null else token()
        val text = raw(method, path, body, bearer, idempotent && method == "POST")
        return json.parseToJsonElement(text.ifBlank { "{}" })
    }

    private suspend fun raw(method: String, path: String, body: JsonElement?, bearer: String?, idemKey: Boolean = false): String =
        withContext(Dispatchers.IO) {
            val rb = Request.Builder().url(apiBaseUrl.trimEnd('/') + path)
            bearer?.let { rb.header("Authorization", "Bearer $it") }
            if (idemKey) rb.header("Idempotency-Key", UUIDv7.generate())
            rb.method(method, body?.toString()?.toRequestBody(JSON_TYPE))
            client.newCall(rb.build()).execute().use { res ->
                val text = res.body?.string().orEmpty()
                if (!res.isSuccessful) {
                    val code = runCatching { json.parseToJsonElement(text).jsonObject.opt("code") }.getOrNull()
                    throw HttpError(res.code, code, "HTTP ${res.code}${code?.let { " $it" } ?: ""}")
                }
                text
            }
        }

    companion object {
        private val JSON_TYPE = "application/json".toMediaType()

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .build()

        /** Same as field_api.routes.voice.staged_hash: sha256 of sorted "line_id:qty(3dp)" joined by "|". */
        fun stagedHash(lines: List<Pair<String, Double>>): String {
            val s = lines.map { "${it.first}:${"%.3f".format(java.util.Locale.ROOT, it.second)}" }.sorted().joinToString("|")
            return MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }
        }

        private fun JsonObject.opt(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull
        private fun JsonObject.str(k: String): String = opt(k) ?: throw HttpError(0, null, "response is missing '$k'")
    }
}
