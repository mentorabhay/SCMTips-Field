package com.scmtips.field.app.assistant

import com.scmtips.field.app.jobs.ApiRequest
import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.JobState
import com.scmtips.field.app.jobs.JobTransport
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.put

/** `event` of `POST /v1/assistant/turns` (docs/design/M3_CONTRACT.md §4). */
enum class AssistantEvent(val wire: String) {
    SESSION_START("session_start"), UTTERANCE("utterance"), SCAN("scan"), UNKNOWN_CODE("unknown_code"),
    PHOTO("photo"), STEP_DONE("step_done"), PAUSE("pause"), RESUME("resume"), SESSION_END("session_end"),
}

/** One turn as the phone sends it. [photoJpegB64] is at most 1 MB of JPEG, base64 (the caller sizes it). */
data class AssistantTurn(
    val siteId: String,
    val event: AssistantEvent,
    val text: String? = null,
    val code: String? = null,
    val photoJpegB64: String? = null,
    val state: JobState = JobState(null, null, null),
)

/** What the reply asks the phone to do; the phone runs it through its own job runner. */
sealed interface AssistantAction {
    data class OpenTask(val taskId: String) : AssistantAction

    /** `command`: next | repeat | post | cancel | all_here | count (with [value]). Anything else is dropped by the parser. */
    data class Command(val command: String, val value: Int?) : AssistantAction
    data class RefreshTask(val taskId: String, val focusCode: String?) : AssistantAction
    data class Listen(val mode: String) : AssistantAction
}

data class AssistantCard(val title: String, val body: String)

data class AssistantReply(
    val sessionId: String,
    val say: String,
    val card: AssistantCard?,
    val actions: List<AssistantAction>,
    /** "model" or "rules" (rules = the server answered without AI). */
    val ai: String?,
    val costUsd: Double?,
    /** Actions the parser refused (unknown types, a confirm command); logged on the phone. */
    val dropped: List<String> = emptyList(),
)

sealed interface AssistantOutcome {
    data class Ok(val reply: AssistantReply) : AssistantOutcome

    /** No usable answer: offline, an HTTP problem or a body without a session id. Work goes on without it. */
    data class Failed(val reason: String) : AssistantOutcome
}

/** Request body and reply parsing, pinned by AssistantWireTest against the contract's JSON. */
object AssistantWire {
    const val PATH = "/v1/assistant/turns"

    /** The commands the phone accepts from a reply. There is no confirm: the operator says it (contract §4). */
    val COMMANDS = setOf("next", "repeat", "post", "cancel", "all_here", "count")

    fun request(key: String, sessionId: String?, t: AssistantTurn): ApiRequest =
        ApiRequest("POST", PATH, buildJsonObject {
            put("session_id", sessionId.json())
            put("site_id", t.siteId)
            put("event", t.event.wire)
            put("text", t.text.json())
            put("code", t.code.json())
            put("photo_jpeg_b64", t.photoJpegB64.json())
            put("client_state", buildJsonObject {
                put("task_id", t.state.taskId.json())
                put("line_id", t.state.lineId.json())
                put("step", t.state.step.json())
            })
        }, key)

    /** Null when the body has no session id (not a reply this phone can trust). */
    fun parse(body: JsonObject): AssistantReply? {
        val sessionId = body.s("session_id") ?: return null
        val dropped = mutableListOf<String>()
        val actions = (body["actions"] as? JsonArray).orEmpty().mapNotNull { el ->
            val a = el as? JsonObject ?: return@mapNotNull null.also { dropped += el.toString() }
            action(a) ?: null.also { dropped += a.toString() }
        }
        val card = (body["card"] as? JsonObject)?.let { c ->
            val title = c.s("title").orEmpty()
            val text = c.s("body").orEmpty()
            if (title.isBlank() && text.isBlank()) null else AssistantCard(title, text)
        }
        return AssistantReply(
            sessionId = sessionId,
            say = body.s("say").orEmpty().trim(),
            card = card,
            actions = actions,
            ai = body.s("ai"),
            costUsd = (body["cost_usd"] as? JsonPrimitive)?.doubleOrNull,
            dropped = dropped,
        )
    }

    private fun action(a: JsonObject): AssistantAction? = when (a.s("type")) {
        "open_task" -> a.s("task_id")?.let { AssistantAction.OpenTask(it) }
        "command" -> a.s("command")?.trim()?.lowercase()?.takeIf { it in COMMANDS }?.let { cmd ->
            val value = (a["value"] as? JsonPrimitive)?.let { it.intOrNull ?: it.doubleOrNull?.toInt() }
            if (cmd == "count" && (value == null || value !in 0..9999)) null else AssistantAction.Command(cmd, value)
        }
        "refresh_task" -> a.s("task_id")?.let { AssistantAction.RefreshTask(it, a.s("focus_code")?.takeIf(String::isNotBlank)) }
        "listen" -> AssistantAction.Listen(a.s("mode")?.takeIf { it == "command" || it == "free" } ?: "command")
        else -> null
    }

    private fun JsonObject.s(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull

    private fun String?.json(): JsonElement = if (this == null) JsonNull else JsonPrimitive(this)
}

/**
 * Talks to `POST /v1/assistant/turns` over the phone's [JobTransport] (field-api with the field token).
 * Keeps the assistant session id: the first turn sends null and the server starts a session; [reset]
 * forgets it when the work session ends. Every turn carries a fresh Idempotency-Key (contract §4).
 */
class AssistantClient(private val transport: JobTransport, private val newKey: () -> String) {
    var sessionId: String? = null
        private set

    suspend fun turn(t: AssistantTurn): AssistantOutcome {
        val sid = if (t.event == AssistantEvent.SESSION_START) null else sessionId
        return when (val r = transport.send(AssistantWire.request(newKey(), sid, t))) {
            is ApiResult.Ok -> {
                val reply = AssistantWire.parse(r.body) ?: return AssistantOutcome.Failed("the assistant answered without a session id")
                sessionId = reply.sessionId
                if (t.event == AssistantEvent.SESSION_END) sessionId = null
                AssistantOutcome.Ok(reply)
            }
            is ApiResult.Problem -> AssistantOutcome.Failed("HTTP ${r.status}${r.code?.let { " $it" } ?: ""}")
            is ApiResult.Offline -> AssistantOutcome.Failed("offline: ${r.reason}")
        }
    }

    fun reset() {
        sessionId = null
    }
}
