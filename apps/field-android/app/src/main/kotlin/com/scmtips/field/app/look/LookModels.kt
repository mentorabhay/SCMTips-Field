package com.scmtips.field.app.look

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

/** The two real-world test cases of docs/design/M5_CONTRACT.md §1, and the generic look. */
enum class LookCase(val wire: String, val noun: String, val starter: String) {
    GROCERY("grocery", "pack", "New grocery delivery"),
    PHARMACY("pharmacy", "box", "New pharmacy delivery"),
    GENERIC("generic", "item", "New delivery"),
    ;

    companion object {
        fun of(wire: String?): LookCase = entries.firstOrNull { it.wire == wire } ?: GENERIC
    }
}

/** Which camera took the photo; the phone always says which one was used (contract §4). */
enum class CameraUsed(val label: String) { GLASSES("Glasses camera"), PHONE("Phone camera") }

data class LabelRead(val read: Boolean, val piecesPerUnit: Int?, val batch: String?, val expiry: String?)

/** One outlined item; [box] and [polygon] are in image pixels of the uploaded photo, [n] is 1-based. */
data class LookInstance(
    val n: Int,
    val box: List<Double>?,
    val polygon: List<Pair<Double, Double>>?,
    val score: Double?,
    val damaged: Boolean,
    val damageNote: String?,
    val label: LabelRead?,
)

data class LookCounts(val expected: Int?, val seen: Int?, val damaged: Int?, val good: Int?)

data class Proposal(val receive: Int?, val flag: Int?, val reasons: List<String>)

data class ModelCall(val model: String, val purpose: String?, val latencyMs: Long?, val outcome: String?)

/** `POST /v1/vision/looks` 200 body (contract §2). Unknown fields are ignored; missing ones are null. */
data class Look(
    val lookId: String,
    val source: String,
    val captureId: String?,
    val imageWidth: Int?,
    val imageHeight: Int?,
    val instances: List<LookInstance>,
    val counts: LookCounts,
    val packMismatches: Int,
    val piecesDifference: Int?,
    val expiryFlagged: Int,
    val batches: List<String>,
    val proposal: Proposal?,
    val say: String,
    val models: List<ModelCall>,
    val reasons: List<String>,
) {
    /** No model answered (no key, budget refused, timeout): the operator counts aloud (contract §2). */
    val rulesOnly: Boolean get() = source == "rules"
}

data class ClaimLine(val reason: String, val units: Int?, val pieces: Int?)

/** `POST /v1/claims` and the claim list items (contract §3). */
data class Claim(
    val claimId: String,
    val status: String,
    val lines: List<ClaimLine>,
    val text: String,
    val source: String?,
    val evidenceUrl: String?,
    val title: String?,
)

/** The answer to `/decision` (a read-back to confirm) or `/confirm` (the result). */
data class ClaimStep(val status: String, val say: String, val confirmBy: String?)

/** Hand-written readers (the JVM gate has no serialization plugin), tolerant of nulls and extra fields. */
object LookJson {
    fun look(o: JsonObject): Look? {
        val id = o.s("look_id") ?: return null
        val image = o.obj("image")
        val counts = o.obj("counts")
        val pack = o.obj("pack")
        val expiry = o.obj("expiry")
        val proposal = o.obj("proposal")
        return Look(
            lookId = id,
            source = o.s("source") ?: "rules",
            captureId = image?.s("capture_id"),
            imageWidth = image?.i("width")?.takeIf { it > 0 },
            imageHeight = image?.i("height")?.takeIf { it > 0 },
            instances = o.arr("instances").mapNotNull { (it as? JsonObject)?.let(::instance) }.sortedBy { it.n },
            counts = LookCounts(counts?.i("expected"), counts?.i("seen"), counts?.i("damaged"), counts?.i("good")),
            packMismatches = pack?.arr("mismatches")?.size ?: 0,
            piecesDifference = pack?.i("pieces_difference"),
            expiryFlagged = expiry?.arr("flagged")?.size ?: 0,
            batches = expiry?.arr("batches").orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull },
            proposal = proposal?.let {
                Proposal(it.i("receive"), it.i("flag"), it.arr("reasons").mapNotNull { r -> (r as? JsonPrimitive)?.contentOrNull })
            },
            say = o.s("say").orEmpty(),
            models = o.arr("models").mapNotNull { m ->
                (m as? JsonObject)?.let { ModelCall(it.s("model") ?: "?", it.s("purpose"), it.d("latency_ms")?.toLong(), it.s("outcome")) }
            },
            reasons = o.arr("reasons").mapNotNull { (it as? JsonPrimitive)?.contentOrNull },
        )
    }

    private fun instance(o: JsonObject): LookInstance? {
        val n = o.i("n") ?: return null
        val box = o.arr("box").mapNotNull { (it as? JsonPrimitive)?.doubleOrNull }.takeIf { it.size == 4 }
        val poly = (o["polygon"] as? JsonArray)?.mapNotNull { p ->
            val xy = (p as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.doubleOrNull }
            if (xy != null && xy.size >= 2) xy[0] to xy[1] else null
        }?.takeIf { it.size >= 3 }
        val label = o.obj("label")?.let {
            LabelRead(it.b("read") ?: false, it.i("pieces_per_unit"), it.s("batch"), it.s("expiry"))
        }
        return LookInstance(n, box, poly, o.d("score"), o.b("damaged") ?: false, o.s("damage_note"), label)
    }

    fun claim(o: JsonObject): Claim? {
        val id = o.s("claim_id") ?: o.s("id") ?: return null
        return Claim(
            claimId = id,
            status = o.s("status") ?: "draft",
            lines = o.arr("lines").mapNotNull { l ->
                (l as? JsonObject)?.let { ClaimLine(it.s("reason") ?: "other", it.i("units"), it.i("pieces")) }
            },
            text = o.s("text").orEmpty(),
            source = o.s("source"),
            evidenceUrl = o.s("evidence_url"),
            title = o.s("title") ?: o.s("ref_doc_no")?.let { "Delivery $it" },
        )
    }

    /** `GET /v1/claims?status=…`: `{"items": [...]}` or a bare list under `claims`. */
    fun claims(o: JsonObject): List<Claim> =
        (o.arr("items").ifEmpty { o.arr("claims") }).mapNotNull { (it as? JsonObject)?.let(::claim) }

    fun step(o: JsonObject): ClaimStep = ClaimStep(o.s("status") ?: "", o.s("say").orEmpty(), o.s("confirm_by"))

    internal fun JsonObject.s(k: String): String? = (this[k] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull
    internal fun JsonObject.i(k: String): Int? = (this[k] as? JsonPrimitive)?.let { it.intOrNull ?: it.doubleOrNull?.toInt() }
    private fun JsonObject.d(k: String): Double? = (this[k] as? JsonPrimitive)?.doubleOrNull
    private fun JsonObject.b(k: String): Boolean? = (this[k] as? JsonPrimitive)?.booleanOrNull
    private fun JsonObject.obj(k: String): JsonObject? = this[k] as? JsonObject
    private fun JsonObject.arr(k: String): List<JsonElement> = (this[k] as? JsonArray).orEmpty()
}
