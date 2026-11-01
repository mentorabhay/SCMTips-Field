package com.scmtips.field.app.jobs

import com.scmtips.field.core.wearables.EarconCue
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

/** Task types of the M2 jobs contract (docs/design/M2_JOBS_CONTRACT.md §2). */
enum class JobType(val wire: String) {
    RECEIVE("receive"), PUTAWAY("putaway"), PICK("pick"), COUNT("count"), AUDIT("audit"), SWAP("swap");

    val isTower: Boolean get() = this == AUDIT || this == SWAP

    companion object {
        fun of(wire: String?): JobType? = entries.firstOrNull { it.wire == wire }
    }
}

data class JobLine(
    val id: String,
    val lineNo: Int,
    val material: String? = null,
    val description: String? = null,
    val uom: String = "EA",
    val bin: String? = null,
    /** Never sent for count tasks (blind count, FR3.029). */
    val expectedQty: Double? = null,
    val countedQty: Double? = null,
    val position: String? = null,
    val expectedSerial: String? = null,
    val status: String = "open",
    val version: Int = 1,
    /** Every barcode of the line's material (M3 contract §2); a product scan matches the material OR any of these. */
    val barcodes: List<String> = emptyList(),
) {
    /** True when [code] is this line's material number or one of its barcodes (trimmed, case-insensitive). */
    fun isProduct(code: String): Boolean = JobRunner.same(code, material) || barcodes.any { JobRunner.same(code, it) }

    /** What the operator calls this line: the description, else the material, else the position. */
    val label: String get() = description?.takeIf { it.isNotBlank() } ?: material ?: position ?: "Line $lineNo"
}

data class JobTask(
    val id: String,
    val type: JobType,
    val status: String,
    val title: String,
    val subtitle: String? = null,
    val refDocNo: String? = null,
    val reason: String? = null,
    val due: String? = null,
    val siteId: String? = null,
    val version: Int = 1,
    val lines: List<JobLine> = emptyList(),
) {
    val isRecount: Boolean get() = type == JobType.COUNT && !reason.isNullOrBlank()
}

/** Parses `GET /v1/tasks` (contract §2). Tolerates today's field-api names (`erp_ref`, status `pending`). */
object TaskParser {
    /** The statuses the phone lists as work to do ("pending" is today's field-api name for "open"). */
    val OPEN_STATUSES = setOf("open", "in_progress", "pending")

    fun parseList(body: JsonObject): List<JobTask> =
        (body["items"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonObject)?.let(::parseTask) }

    fun parseTask(t: JsonObject): JobTask? {
        val type = JobType.of(t.s("type")) ?: return null
        val id = t.s("id") ?: return null
        val lines = (t["lines"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonObject)?.let(::parseLine) }
        return JobTask(
            id = id,
            type = type,
            status = t.s("status") ?: "open",
            title = t.s("title")?.takeIf { it.isNotBlank() } ?: defaultTitle(type, t.s("ref_doc_no") ?: t.s("erp_ref")),
            subtitle = t.s("subtitle"),
            refDocNo = t.s("ref_doc_no") ?: t.s("erp_ref"),
            reason = t.s("reason"),
            due = t.s("due"),
            siteId = t.s("site_id"),
            version = t.i("version") ?: 1,
            lines = lines.sortedBy { it.lineNo },
        )
    }

    private fun parseLine(l: JsonObject): JobLine? {
        val id = l.s("id") ?: return null
        return JobLine(
        id = id,
        lineNo = l.i("line_no") ?: 0,
        material = l.s("material"),
        description = l.s("description"),
        uom = l.s("uom") ?: "EA",
        bin = l.s("bin"),
        expectedQty = l.d("expected_qty"),
        countedQty = l.d("counted_qty"),
        position = l.s("position"),
        expectedSerial = l.s("expected_serial"),
        status = l.s("status") ?: "open",
        version = l.i("version") ?: 1,
        barcodes = (l["barcodes"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.trim()?.takeIf(String::isNotEmpty) },
        )
    }

    private fun defaultTitle(type: JobType, ref: String?): String = when (type) {
        JobType.RECEIVE -> "Delivery ${ref ?: ""}".trim()
        JobType.PUTAWAY -> "Put away"
        JobType.PICK -> "Order ${ref ?: ""}".trim()
        JobType.COUNT -> "Count"
        JobType.AUDIT -> "Sector audit"
        JobType.SWAP -> "Swap a unit"
    }

    internal fun JsonObject.s(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull
    private fun JsonObject.i(k: String): Int? = (this[k] as? JsonPrimitive)?.intOrNull
    private fun JsonObject.d(k: String): Double? = (this[k] as? JsonPrimitive)?.doubleOrNull
}

/** One HTTP call, described without any HTTP library so the job logic is testable on the JVM. */
data class ApiRequest(
    val method: String,
    val path: String,
    val body: JsonObject? = null,
    /** UUIDv7; the same key on a retry returns the first result (contract §1). Null for GET. */
    val idempotencyKey: String? = null,
    /** M5: extra request headers (If-Match on claim decisions); empty for every earlier call. */
    val headers: Map<String, String> = emptyMap(),
)

sealed interface ApiResult {
    data class Ok(val status: Int, val body: JsonObject, val etag: String? = null) : ApiResult

    /** problem+json from field-api: `code` (FIELD-…), `title`, `detail`. */
    data class Problem(val status: Int, val code: String?, val title: String?, val detail: String?) : ApiResult {
        /** What the phone shows the operator: plain English, never a bare code. */
        val plain: String get() = ProblemText.plain(this)
    }

    /** No answer: Wi-Fi, the PC, a timeout. */
    data class Offline(val reason: String) : ApiResult
}

/** Runs [ApiRequest]s: field-api over HTTP on the phone, a local stand-in for the practice task. */
interface JobTransport {
    suspend fun send(request: ApiRequest): ApiResult
}

/** Audio out (Ray-Ban Meta Gen 2 has no display: every prompt is spoken, plus earcons). */
interface Speaker {
    fun say(text: String)
    fun earcon(cue: EarconCue)

    /** Speaks [text] after whatever is being said now (default: like [say]). */
    fun queue(text: String) = say(text)
}

object ProblemText {
    private val GENERIC_TITLES = setOf("HTTP Error", "Validation Error", "Not Found", "Internal Server Error")
    private val CODE_PREFIX = Regex("^(FIELD-[A-Z0-9-]+:\\s*)?(MSG\\d+\\.\\d+:\\s*)?")

    fun plain(p: ApiResult.Problem): String {
        val code = p.code.orEmpty()
        return when {
            code == "FIELD-TASK-409-WRONG-CODE" && !p.title.isNullOrBlank() -> p.title
            code == "FIELD-CAP-410-TASK-CLOSED" -> "This job is already closed. Go back to Today."
            code == "FIELD-POST-409-ALREADY-REQUESTED" -> "This was already sent to SAP. Nothing more to do."
            code == "FIELD-POST-422-NO-CONFIRM" -> "Something changed before it was sent, so nothing was posted. Check and try again."
            code.startsWith("FIELD-VIS-422-PERMIT") || (p.detail ?: "").startsWith("FIELD-VIS-422-PERMIT") ->
                "The work permit is not valid today. Check the permit number."
            code.startsWith("FIELD-VIS-422-GEOFENCE") || (p.detail ?: "").startsWith("FIELD-VIS-422-GEOFENCE") ->
                "You do not seem to be at the site, or the location is too rough. Move into the open and try again."
            p.status == 401 -> "Your sign-in expired. Connect this phone again from the PC."
            p.status == 403 -> "This phone is not allowed to do that. Ask your supervisor."
            p.status >= 500 -> "The server had a problem. Try again in a minute."
            !p.title.isNullOrBlank() && p.title !in GENERIC_TITLES -> p.title
            !p.detail.isNullOrBlank() -> p.detail.replace(CODE_PREFIX, "").trim().ifEmpty { "The server refused this ($code)." }
            else -> "The server refused this${if (code.isNotEmpty()) " ($code)" else ""}."
        }
    }
}
