package com.scmtips.field.app.net

import com.scmtips.field.app.jobs.ApiRequest
import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.JobRequests
import com.scmtips.field.app.jobs.JobTask
import com.scmtips.field.app.jobs.JobTransport
import com.scmtips.field.app.jobs.TaskParser
import com.scmtips.field.core.common.UUIDv7
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Talks to field-api as tools/dev_stack/stack.py `Phone` does: exchange the core token, register the
 * phone, re-exchange bound to the device; then the job calls the [com.scmtips.field.app.jobs.JobRunner]
 * describes as [ApiRequest]s, and live events.
 *
 * Field tokens live 10 minutes; [token] re-exchanges a minute before expiry. The core token is never
 * logged. Every write carries an Idempotency-Key: the request's own (so a retry reuses it), else a fresh
 * UUIDv7 (FR2.039).
 */
class FieldSession(
    private val apiBaseUrl: String,
    private val coreToken: String,
    var deviceId: String?,
    private val client: OkHttpClient = defaultClient(),
    private val clock: () -> Long = System::currentTimeMillis,
) : JobTransport {
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
        val res = call("POST", "/v1/auth/exchange", body, bearer = null).jsonObject
        val access = res.str("access_token")
        accessToken = access
        expiresAtMs = clock() + ((res["expires_in"] as? JsonPrimitive)?.intOrNull ?: 600) * 1000L
        access
    }

    /** Exchange the core token again, bound to [id] (or unbound when null). Throws [HttpError] if refused. */
    suspend fun bind(id: String?) {
        mutex.withLock { accessToken = null; deviceId = id }
        token()
    }

    /** POST /v1/devices for this phone. [idempotencyKey] is saved by the caller, so a repeat replays the 201. */
    suspend fun registerPhone(serial: String, model: String, osVersion: String, appVersion: String, idempotencyKey: String): String {
        val text = raw("POST", "/v1/devices", buildJsonObject {
            put("kind", "phone"); put("serial_no", serial); put("model", model)
            put("os_version", osVersion); put("app_version", appVersion)
        }, token(), idempotencyKey)
        return json.parseToJsonElement(text.ifBlank { "{}" }).jsonObject.str("id")
    }

    /** `GET /v1/tasks` for the site: open and in-progress work (contract §2). */
    suspend fun tasks(siteId: String): List<JobTask> {
        val res = call("GET", JobRequests.tasks(siteId).path, null, bearer = token()).jsonObject
        return TaskParser.parseList(res).filter { it.status in TaskParser.OPEN_STATUSES }
    }

    override suspend fun send(request: ApiRequest): ApiResult = try {
        val text = raw(request.method, request.path, request.body, token(), request.idempotencyKey)
        ApiResult.Ok(200, (json.parseToJsonElement(text.ifBlank { "{}" }) as? JsonObject) ?: JsonObject(emptyMap()))
    } catch (e: HttpError) {
        ApiResult.Problem(e.status, e.code, e.title, e.detail)
    } catch (e: IOException) {
        ApiResult.Offline(e.message ?: e.javaClass.simpleName)
    }

    /** Pending live events for this device (SSE with once=true; called every couple of seconds). */
    suspend fun pollEvents(lastEventId: String?): List<JsonObject> {
        val id = deviceId ?: return emptyList()
        val q = "once=true" + (lastEventId?.let { "&last_event_id=$it" } ?: "")
        val text = raw("GET", "/v1/devices/$id/events?$q", null, token(), null)
        return text.lineSequence().filter { it.startsWith("data: ") }
            .mapNotNull { runCatching { json.parseToJsonElement(it.removePrefix("data: ")).jsonObject }.getOrNull() }
            .toList()
    }

    private suspend fun call(method: String, path: String, body: JsonElement?, bearer: String?): JsonElement {
        val text = raw(method, path, body, bearer, if (method == "GET") null else UUIDv7.generate())
        return json.parseToJsonElement(text.ifBlank { "{}" })
    }

    private suspend fun raw(method: String, path: String, body: JsonElement?, bearer: String?, idemKey: String?): String =
        withContext(Dispatchers.IO) {
            val rb = Request.Builder().url(apiBaseUrl.trimEnd('/') + path)
            bearer?.let { rb.header("Authorization", "Bearer $it") }
            val key = idemKey ?: if (method != "GET") UUIDv7.generate() else null
            key?.let { rb.header("Idempotency-Key", it) }
            val rbody = body?.toString()?.toRequestBody(JSON_TYPE) ?: if (method == "GET") null else "{}".toRequestBody(JSON_TYPE)
            rb.method(method, rbody)
            client.newCall(rb.build()).execute().use { res ->
                val text = res.body?.string().orEmpty()
                if (!res.isSuccessful) {
                    val problem = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull()
                    val code = problem?.opt("code")
                    val detail = problem?.get("detail")?.let { d -> (d as? JsonPrimitive)?.contentOrNull ?: (d as? JsonObject)?.opt("message") }
                    throw HttpError(res.code, code, problem?.opt("title"), detail, "HTTP ${res.code}${code?.let { " $it" } ?: ""}")
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

        private fun JsonObject.opt(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull
        private fun JsonObject.str(k: String): String = opt(k) ?: throw HttpError(0, null, null, null, "response is missing '$k'")
    }
}
