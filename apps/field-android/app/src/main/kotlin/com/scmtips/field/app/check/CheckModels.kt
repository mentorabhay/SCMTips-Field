package com.scmtips.field.app.check

import com.scmtips.field.app.look.ModelCall
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

/** The colour a verdict is shown in (docs/design/M5_C3_CONTRACT.md §7). */
enum class VerdictTone { GREEN, AMBER, GREY, RED }

/** The five verdicts of contract §3, plus [UNKNOWN] for a verdict this app does not know (shown grey, never green). */
enum class Verdict(val wire: String, val tone: VerdictTone, val headline: String) {
    GENUINE_NEW("GENUINE_NEW", VerdictTone.GREEN, "Genuine and new"),
    GENUINE_PREVIOUSLY_ACTIVATED("GENUINE_PREVIOUSLY_ACTIVATED", VerdictTone.AMBER, "Genuine, but not new: activated before"),
    RETURNED_REFURBISHED("RETURNED_REFURBISHED", VerdictTone.AMBER, "Genuine, but not new: returned or refurbished"),
    CANNOT_VERIFY("CANNOT_VERIFY", VerdictTone.GREY, "Cannot verify"),
    LIKELY_COUNTERFEIT("LIKELY_COUNTERFEIT", VerdictTone.RED, "Likely counterfeit"),
    UNKNOWN("", VerdictTone.GREY, "Unknown answer"),
    ;

    companion object {
        fun of(wire: String?): Verdict = entries.firstOrNull { it.wire.isNotEmpty() && it.wire == wire } ?: UNKNOWN
    }
}

/** S1, the signed seal code (contract §2.1): oem / serial / sku / sealed_at are null unless the payload parsed. */
data class SealSignal(
    val status: String,
    val oem: String?,
    val oemName: String?,
    val kid: String?,
    val serial: String?,
    val sku: String?,
    val sealedAt: String?,
)

/** One unit history event (S2): manufactured, shipped_to_seller, delivered, activated, returned, refurbished. */
data class UnitEvent(val type: String, val at: String?, val area: String?)

/** S2, the OEM registry: `not_asked` when the code did not verify (R1-R7). */
data class RegistrySignal(
    val status: String,
    val sku: String?,
    val events: List<UnitEvent>,
    val activatedAt: String?,
    val returnedAt: String?,
    val refurbishedAt: String?,
)

/** S3, the first-check claim: first | same_checker | other_checker | not_recorded. */
data class FirstCheckSignal(val status: String, val firstCheckedAt: String?, val area: String?)

/** S4, the visual seal check: none | pending | done | failed; [box] in image pixels of the photo. */
data class VisualSignal(
    val status: String,
    val captureId: String?,
    val sealFound: Boolean?,
    val box: List<Double>?,
    val score: Double?,
    val signs: List<String>,
    val imageWidth: Int?,
    val imageHeight: Int?,
)

/** `POST /v1/authenticity/checks` and `GET /v1/authenticity/checks/{id}` (contract §4.1). */
data class AuthenticityCheck(
    val checkId: String,
    /** False while the visual seal check runs (two steps); a body without the field is final. */
    val final: Boolean,
    val verdict: Verdict,
    /** The verdict exactly as the server sent it (logged; an unknown one is shown as [Verdict.UNKNOWN]). */
    val verdictWire: String?,
    /** True: tamper signs seen; false: the seal looked intact; null: no photo, still running, failed. */
    val tamper: Boolean?,
    val reasons: List<String>,
    val code: SealSignal?,
    val registry: RegistrySignal?,
    val firstCheck: FirstCheckSignal?,
    val visual: VisualSignal?,
    val say: String,
    val sayNext: String?,
    val models: List<ModelCall>,
    val evidenceUrl: String?,
    val claimId: String?,
    val siteId: String?,
    val captureId: String?,
    val createdAt: String?,
)

/** Hand-written reader (the JVM gate has no serialization plugin), tolerant of nulls and extra fields. */
object CheckJson {
    fun check(o: JsonObject): AuthenticityCheck? {
        val id = o.s("check_id") ?: return null
        val signals = o.obj("signals")
        val wire = o.s("verdict")
        return AuthenticityCheck(
            checkId = id,
            final = o.b("final") ?: true,
            verdict = Verdict.of(wire),
            verdictWire = wire,
            tamper = o.b("tamper"),
            reasons = o.strings("reasons"),
            code = signals?.obj("code")?.let {
                SealSignal(it.s("status") ?: "unknown", it.s("oem"), it.s("oem_name"), it.s("kid"), it.s("serial"), it.s("sku"), it.s("sealed_at"))
            },
            registry = signals?.obj("registry")?.let { r ->
                RegistrySignal(
                    status = r.s("status") ?: "unknown",
                    sku = r.s("sku"),
                    events = r.arr("events").mapNotNull { e -> (e as? JsonObject)?.let { UnitEvent(it.s("type") ?: "event", it.s("at"), it.s("area")) } },
                    activatedAt = r.s("activated_at"),
                    returnedAt = r.s("returned_at"),
                    refurbishedAt = r.s("refurbished_at"),
                )
            },
            firstCheck = signals?.obj("first_check")?.let { FirstCheckSignal(it.s("status") ?: "not_recorded", it.s("first_checked_at"), it.s("area")) },
            visual = signals?.obj("visual")?.let { v ->
                val image = v.obj("image")
                VisualSignal(
                    status = v.s("status") ?: "none",
                    captureId = v.s("capture_id"),
                    sealFound = v.b("seal_found"),
                    box = v.arr("box").mapNotNull { (it as? JsonPrimitive)?.doubleOrNull }.takeIf { it.size == 4 },
                    score = v.d("score"),
                    signs = v.strings("signs"),
                    imageWidth = image?.i("width")?.takeIf { it > 0 },
                    imageHeight = image?.i("height")?.takeIf { it > 0 },
                )
            },
            say = o.s("say").orEmpty(),
            sayNext = o.s("say_next")?.ifBlank { null },
            models = o.arr("models").mapNotNull { m ->
                (m as? JsonObject)?.let { ModelCall(it.s("model") ?: "?", it.s("purpose"), it.d("latency_ms")?.toLong(), it.s("outcome")) }
            },
            evidenceUrl = o.s("evidence_url")?.ifBlank { null },
            claimId = o.s("claim_id"),
            siteId = o.s("site_id"),
            captureId = o.s("capture_id"),
            createdAt = o.s("created_at"),
        )
    }

    private fun JsonObject.s(k: String): String? = (this[k] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull
    private fun JsonObject.i(k: String): Int? = (this[k] as? JsonPrimitive)?.let { it.intOrNull ?: it.doubleOrNull?.toInt() }
    private fun JsonObject.d(k: String): Double? = (this[k] as? JsonPrimitive)?.doubleOrNull
    private fun JsonObject.b(k: String): Boolean? = (this[k] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.booleanOrNull
    private fun JsonObject.obj(k: String): JsonObject? = this[k] as? JsonObject
    private fun JsonObject.arr(k: String): List<JsonElement> = (this[k] as? JsonArray).orEmpty()
    private fun JsonObject.strings(k: String): List<String> = arr(k).mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p !is JsonNull }?.contentOrNull }
}
