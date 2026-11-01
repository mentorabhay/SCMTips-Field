package com.scmtips.field.app.jobs

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.Locale

enum class InputSource(val wire: String) { MANUAL("manual"), SCAN("scan"), VOICE("voice") }

enum class ConfirmKind(val wire: String) { BIN("bin"), PRODUCT("product"), HU("hu"), SERIAL("serial") }

/** One climb-safe event (contract §6). */
data class ClimbEvent(val deviceSeq: Long, val type: String, val occurredAt: String, val payload: JsonObject? = null)

/**
 * Every call the phone makes, as data (method, path, body). The bodies follow
 * docs/design/M2_JOBS_CONTRACT.md; field names are pinned by JobRequestsTest.
 */
object JobRequests {
    fun tasks(siteId: String): ApiRequest =
        ApiRequest("GET", "/v1/tasks?site_id=${enc(siteId)}&status=open,in_progress")

    fun voiceEvent(key: String, deviceId: String, taskId: String, intent: String, transcript: String, confidence: Float) =
        ApiRequest("POST", "/v1/voice-events", buildJsonObject {
            put("device_id", deviceId); put("task_id", taskId); put("transcript", transcript)
            put("confidence", confidence.toDouble()); put("intent", intent); put("is_accepted", true)
        }, key)

    /**
     * A line's count. M5 (contract §2 posting): after a look, [flagQty] of the [value] units go to quality
     * inspection (101 to 101Q) and the rest to unrestricted stock; [lookId] / [captureId] link the look.
     * Without them the body is exactly the M2/M4 one.
     */
    fun countRecord(
        key: String, lineId: String, value: Double, unit: String, source: InputSource, voiceEventId: String?,
        flagQty: Int? = null, lookId: String? = null, captureId: String? = null,
    ) =
        ApiRequest("POST", "/v1/count-records", buildJsonObject {
            put("task_line_id", lineId); put("value", value); put("unit", unit); put("source", source.wire)
            voiceEventId?.let { put("voice_event_id", it) }
            flagQty?.let { put("flag_qty", it) }
            lookId?.let { put("look_id", it) }
            captureId?.let { put("capture_id", it) }
        }, key)

    fun confirmation(key: String, taskId: String, lineId: String, kind: ConfirmKind, code: String, source: InputSource, role: String? = null) =
        ApiRequest("POST", "/v1/tasks/${enc(taskId)}/lines/${enc(lineId)}/confirmations", buildJsonObject {
            put("kind", kind.wire); put("code", code); put("source", source.wire)
            role?.let { put("role", it) }
        }, key)

    fun flag(key: String, taskId: String, lineId: String, flag: String, reason: String? = null) =
        ApiRequest("POST", "/v1/tasks/${enc(taskId)}/lines/${enc(lineId)}/flags", buildJsonObject {
            put("flag", flag)
            reason?.let { put("reason", it) }
        }, key)

    /** Touch confirmation: the operator saw the review screen and pressed "Yes" (contract §4). */
    fun postTouch(key: String, taskId: String, lines: List<Pair<String, Double>>, lookId: String? = null) =
        ApiRequest("POST", "/v1/tasks/${enc(taskId)}/post-requests", buildJsonObject {
            put("operation", "post")
            put("lines", buildJsonArray { lines.forEach { add(JsonPrimitive(it.first)) } })
            put("staged_hash", stagedHash(lines))
            put("confirm", buildJsonObject { put("method", "touch") })
            lookId?.let { put("look_id", it) }
        }, key)

    /**
     * Voice confirmation ("post" … "yes"). The top-level voice ids are sent as well: the contract keeps
     * them accepted, and today's field-api requires them.
     */
    fun postVoice(key: String, taskId: String, lines: List<Pair<String, Double>>, postVoiceId: String, confirmVoiceId: String, lookId: String? = null) =
        ApiRequest("POST", "/v1/tasks/${enc(taskId)}/post-requests", buildJsonObject {
            put("operation", "post")
            put("lines", buildJsonArray { lines.forEach { add(JsonPrimitive(it.first)) } })
            put("staged_hash", stagedHash(lines))
            put("confirm", buildJsonObject {
                put("method", "voice"); put("post_voice_event_id", postVoiceId); put("confirm_voice_event_id", confirmVoiceId)
            })
            put("post_voice_event_id", postVoiceId); put("confirm_voice_event_id", confirmVoiceId)
            lookId?.let { put("look_id", it) }
        }, key)

    fun checkIn(key: String, siteId: String, permitRef: String, permitValidUntil: String, lat: Double, lon: Double, accuracyM: Double, capturedAt: String) =
        ApiRequest("POST", "/v1/sites/${enc(siteId)}/visits", buildJsonObject {
            put("permit_ref", permitRef); put("permit_valid_until", permitValidUntil)
            put("lat", lat); put("lon", lon); put("accuracy_m", accuracyM); put("captured_at", capturedAt)
        }, key)

    fun checkOut(key: String, visitId: String, unsyncedCount: Int) =
        ApiRequest("PATCH", "/v1/visits/${enc(visitId)}", buildJsonObject { put("unsynced_count", unsyncedCount) }, key)

    fun climbEvents(key: String, visitId: String, events: List<ClimbEvent>) =
        ApiRequest("POST", "/v1/climb-sessions/${enc(visitId)}/events", buildJsonObject {
            put("events", buildJsonArray {
                events.forEach { e ->
                    add(buildJsonObject {
                        put("device_seq", e.deviceSeq); put("type", e.type); put("occurred_at", e.occurredAt)
                        e.payload?.let { put("payload", it) }
                    })
                }
            })
        }, key)

    fun safetyCheckIn(key: String, visitId: String) =
        ApiRequest("POST", "/v1/safety/visits/${enc(visitId)}/check-in", buildJsonObject { }, key)

    /** Same as field_api.routes.voice.staged_hash: sha256 of sorted "line_id:qty(3dp)" joined by "|". */
    fun stagedHash(lines: List<Pair<String, Double>>): String {
        val s = lines.map { "${it.first}:${String.format(Locale.ROOT, "%.3f", it.second)}" }.sorted().joinToString("|")
        return MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }
    }

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")
}
