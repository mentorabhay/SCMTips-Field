package com.scmtips.field.feature.decisions.api

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

// Wire models of the SCMTIPS core's /v1 wearable contract, as the core's own wearable app reads them
// (ported from its api/Models.kt). Parsed by hand from JsonObject (the JVM gate has no serialization
// compiler plugin); unknown fields are ignored, so the core can add fields without breaking the app.

/** `GET /v1/wearable/next` item: the decision waiting longest for this approver. */
data class NextItem(
    val decisionId: String,
    val title: String,
    /** ≤ 240 characters, for a screen. */
    val card: String,
    /** The core's ~20 s template brief; the spoken brief is rewritten from it (field-api) or spoken as is. */
    val spoken: String,
    val options: List<ItemOption> = emptyList(),
    val band: Band? = null,
    val deadlineAt: String? = null,
    /** Decisions waiting for this approver (this one included; at least 1 when an item is returned). */
    val waiting: Int = 0,
)

data class ItemOption(val letter: String, val optionId: String, val title: String, val committed: String = "", val net: String = "")

data class Band(val label: String = "", val stepUp: Boolean = false, val approvers: Int = 1)

/** `POST /v1/voice/challenges`: a single-use nonce for the first voice turn. */
data class Challenge(
    val nonce: String,
    val decisionId: String,
    val expiresAt: String? = null,
    val ttlSeconds: Int? = null,
    val turn: Int = 0,
    val status: String? = null,
    val title: String? = null,
    val brief: String? = null,
    val options: List<ChallengeOption> = emptyList(),
    val stepUpFresh: Boolean = false,
    val stepUpWaived: Boolean = false,
    /** Utterances below this recogniser confidence are never sent (asked again instead). */
    val confidenceFloor: Double = 0.0,
)

/** The core owns the shapes of the money fields; the app only passes them through. */
data class ChallengeOption(
    val letter: String,
    val optionId: String,
    val title: String,
    val costTotal: JsonElement? = null,
    val committedSpend: JsonElement? = null,
    val band: JsonElement? = null,
    val details: JsonElement? = null,
)

/** `POST /v1/voice/commands`: what the core's grammar made of the words, and what to say. */
data class CommandResponse(
    val outcome: String,
    val say: String,
    val stepUpRequired: Boolean = false,
    val next: NextTurn? = null,
    val decision: DecisionRef? = null,
    val approvalId: String? = null,
    val pending: JsonElement? = null,
    val parsed: JsonElement? = null,
) {
    companion object {
        const val READBACK = "readback"
        const val CLARIFY = "clarify"
        const val DETAILS = "details"
        const val REPEAT = "repeat"
        const val CANCELLED = "cancelled"
        const val EXECUTED = "executed"
    }
}

data class NextTurn(val nonce: String, val expiresAt: String? = null, val turn: Int = 0)

data class DecisionRef(val id: String, val status: String? = null, val version: JsonElement? = null)

data class StepUpStatus(val fresh: Boolean = false, val method: String? = null, val verifiedAt: String? = null, val waived: Boolean = false)

enum class StepUpMethod(val wire: String) { TOTP("totp"), BACKUP_CODE("backup_code") }

enum class SubjectKind(val wire: String) { RECOVERY_PLAN("recovery_plan"), ACTION("action") }

/** Multipart body of `POST /v1/evidence/photos`. Photos only: the app never uploads audio or video there. */
class PhotoUpload(
    val image: ByteArray,
    val mimeType: String,
    val subjectKind: SubjectKind,
    val subjectId: String,
    val label: String,
    val segmentPrompt: String? = null,
)

data class PhotoEvidence(
    val id: String,
    val subjectKind: String,
    val subjectId: String,
    val label: String,
    val facesBlurred: Boolean = false,
    val mask: Boolean = false,
    val createdAt: String? = null,
)

/** One row of `GET /v1/wearable/sessions` (this user's device sessions). */
data class DeviceSessionInfo(val sessionId: String, val deviceId: String?, val deviceModel: String?, val expiresAt: String?, val current: Boolean)

/** RFC 7807 problem document (the core also puts its machine code in `code`). */
data class Problem(val type: String? = null, val title: String? = null, val status: Int? = null, val detail: String? = null, val code: String? = null)

/** JSON helpers shared by the core and field-api clients of this module. */
object CoreJson {
    val json = Json { ignoreUnknownKeys = true }

    fun obj(text: String): JsonObject? = runCatching { json.parseToJsonElement(text.ifBlank { "{}" }) as? JsonObject }.getOrNull()

    fun JsonObject.s(k: String): String? = (this[k] as? JsonPrimitive)?.takeUnless { it is JsonNull }?.contentOrNull
    fun JsonObject.req(k: String): String = s(k) ?: throw IllegalArgumentException("response is missing '$k'")
    fun JsonObject.b(k: String): Boolean? = (this[k] as? JsonPrimitive)?.booleanOrNull
    fun JsonObject.i(k: String): Int? = (this[k] as? JsonPrimitive)?.let { it.intOrNull ?: it.doubleOrNull?.toInt() }
    fun JsonObject.d(k: String): Double? = (this[k] as? JsonPrimitive)?.doubleOrNull
    fun JsonObject.o(k: String): JsonObject? = this[k] as? JsonObject
    fun JsonObject.a(k: String): List<JsonObject> = (this[k] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
    fun JsonObject.e(k: String): JsonElement? = this[k]?.takeUnless { it is JsonNull }

    fun problem(text: String): Problem? = obj(text)?.let { p ->
        // FastAPI-style {"detail": {"code": ...}} as well as flat problem+json.
        val detailObj = p.o("detail")
        Problem(p.s("type"), p.s("title"), p.i("status"), p.s("detail") ?: detailObj?.s("message"),
            p.s("code") ?: detailObj?.s("code") ?: p.s("error"))
    }

    fun nextItem(body: JsonObject): NextItem? {
        val item = body.o("item") ?: return null
        return NextItem(
            decisionId = item.req("decision_id"),
            title = item.s("title").orEmpty(),
            card = item.s("card").orEmpty(),
            spoken = item.s("spoken").orEmpty(),
            options = item.a("options").map { o ->
                ItemOption(o.req("letter"), o.s("option_id").orEmpty(), o.s("title").orEmpty(), o.s("committed").orEmpty(), o.s("net").orEmpty())
            },
            band = item.o("band")?.let { Band(it.s("label").orEmpty(), it.b("step_up") ?: false, it.i("approvers") ?: 1) },
            deadlineAt = item.s("deadline_at"),
            waiting = item.i("waiting") ?: 0,
        )
    }

    fun challenge(c: JsonObject) = Challenge(
        nonce = c.req("nonce"),
        decisionId = c.req("decision_id"),
        expiresAt = c.s("expires_at"),
        ttlSeconds = c.i("ttl_seconds"),
        turn = c.i("turn") ?: 0,
        status = c.s("status"),
        title = c.s("title"),
        brief = c.s("brief"),
        options = c.a("options").map { o ->
            ChallengeOption(o.req("letter"), o.s("option_id").orEmpty(), o.s("title").orEmpty(),
                o.e("cost_total"), o.e("committed_spend"), o.e("band"), o.e("details"))
        },
        stepUpFresh = c.b("step_up_fresh") ?: false,
        stepUpWaived = c.b("step_up_waived") ?: false,
        confidenceFloor = c.d("confidence_floor") ?: 0.0,
    )

    fun command(r: JsonObject) = CommandResponse(
        outcome = r.req("outcome"),
        say = r.s("say").orEmpty(),
        stepUpRequired = r.b("step_up_required") ?: false,
        next = r.o("next")?.let { n -> n.s("nonce")?.let { NextTurn(it, n.s("expires_at"), n.i("turn") ?: 0) } },
        decision = r.o("decision")?.let { d -> d.s("id")?.let { DecisionRef(it, d.s("status"), d.e("version")) } },
        approvalId = r.s("approval_id"),
        pending = r.e("pending"),
        parsed = r.e("parsed"),
    )

    fun stepUp(s: JsonObject) = StepUpStatus(s.b("fresh") ?: false, s.s("method"), s.s("verified_at"), s.b("waived") ?: false)

    fun photo(p: JsonObject) = PhotoEvidence(
        p.req("id"), p.s("subject_kind").orEmpty(), p.s("subject_id").orEmpty(), p.s("label").orEmpty(),
        p.b("faces_blurred") ?: false, p.b("mask") ?: false, p.s("created_at"),
    )

    /** `GET /v1/wearable/sessions`: `{"items": [...]}` or a bare list. */
    fun sessions(text: String): List<DeviceSessionInfo> {
        val el = runCatching { json.parseToJsonElement(text.ifBlank { "[]" }) }.getOrNull() ?: return emptyList()
        val rows = when (el) {
            is JsonArray -> el.mapNotNull { it as? JsonObject }
            is JsonObject -> el.a("items").ifEmpty { el.a("sessions") }
            else -> emptyList()
        }
        return rows.mapNotNull { r ->
            val id = r.s("session_id") ?: r.s("id") ?: return@mapNotNull null
            DeviceSessionInfo(id, r.s("device_id"), r.s("device_model"), r.s("expires_at"), r.b("current") ?: false)
        }
    }
}
