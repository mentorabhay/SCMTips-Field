package com.scmtips.field.app.jobs

import com.scmtips.field.core.wearables.EarconCue
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put
import java.time.ZoneId

/** Test transport: records every request and answers like field-api unless a [rule] says otherwise. */
class RecordingTransport : JobTransport {
    val sent = mutableListOf<ApiRequest>()
    val rules = mutableListOf<(ApiRequest) -> ApiResult?>()
    var postStatus = "queued"
    var beforeReply: ((ApiRequest) -> Unit)? = null
    private var n = 0

    override suspend fun send(request: ApiRequest): ApiResult {
        sent += request
        n += 1
        beforeReply?.invoke(request)
        rules.firstNotNullOfOrNull { it(request) }?.let { return it }
        val p = request.path
        return ApiResult.Ok(200, when {
            p == "/v1/voice-events" -> buildJsonObject { put("id", "ve-$n") }
            p == "/v1/count-records" -> buildJsonObject { put("counted_qty", request.num("value") ?: 0.0) }
            p.endsWith("/post-requests") -> buildJsonObject { put("posting_request_id", "erp-doc-1"); put("status", postStatus) }
            p.matches(Regex("/v1/sites/.+/visits")) -> buildJsonObject { put("id", "visit-1"); put("status", "checked_in") }
            else -> buildJsonObject { put("ok", true) }
        })
    }

    fun paths(): List<String> = sent.map { "${it.method} ${it.path}" }
    fun last(pathPart: String): ApiRequest = sent.last { pathPart in it.path }
    fun all(pathPart: String): List<ApiRequest> = sent.filter { pathPart in it.path }
}

class RecordingSpeaker : Speaker {
    val said = mutableListOf<String>()
    val earcons = mutableListOf<EarconCue>()
    override fun say(text: String) { said += text }
    override fun earcon(cue: EarconCue) { earcons += cue }
}

fun ApiRequest.str(k: String): String? = (body?.get(k) as? JsonPrimitive)?.contentOrNull
fun ApiRequest.num(k: String): Double? = (body?.get(k) as? JsonPrimitive)?.doubleOrNull
fun ApiRequest.obj(k: String): JsonObject? = body?.get(k) as? JsonObject
fun ApiRequest.arr(k: String): List<String> = (body?.get(k) as? JsonArray).orEmpty().map { (it as JsonPrimitive).content }
fun JsonObject.str(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull

object Tasks {
    val receive = JobTask(
        "t-rcv", JobType.RECEIVE, "open", "Delivery 1800000022", "From SAMPLE-VENDOR-01 · 2 items · 36 pieces", "1800000022",
        siteId = "site-1",
        lines = listOf(
            JobLine("l10", 10, "SAMPLE-MAT-0001", "Industrial Component Grade 1", "EA", expectedQty = 12.0, countedQty = 0.0),
            JobLine("l20", 20, "SAMPLE-MAT-0002", "Industrial Component Grade 2", "EA", expectedQty = 24.0, countedQty = 0.0),
        ),
    )
    val putaway = JobTask(
        "t-pa", JobType.PUTAWAY, "open", "3 pallets to store", siteId = "site-1",
        lines = listOf(
            JobLine("p1", 10, "SAMPLE-MAT-0001", "Grade 1", "EA", bin = "03-05-02", expectedQty = 12.0, countedQty = 0.0),
            JobLine("p2", 20, "SAMPLE-MAT-0002", "Grade 2", "EA", bin = "02-03-04", expectedQty = 24.0, countedQty = 0.0),
        ),
    )
    val pick = JobTask(
        "t-pk", JobType.PICK, "open", "Order 7700000012", refDocNo = "7700000012", siteId = "site-1",
        lines = listOf(
            JobLine("k1", 10, "SAMPLE-MAT-0003", "Grade 3", "EA", bin = "02-01-01", expectedQty = 20.0, countedQty = 0.0),
            JobLine("k2", 20, "SAMPLE-MAT-0004", "Grade 4", "EA", bin = "02-03-04", expectedQty = 5.0, countedQty = 0.0),
        ),
    )
    val count = JobTask(
        "t-ct", JobType.COUNT, "open", "Count bin 03-05-02", siteId = "site-1",
        lines = listOf(JobLine("c1", 10, "SAMPLE-MAT-0001", "Grade 1", "EA", bin = "03-05-02")),
    )
    val recount = count.copy(id = "t-rc", reason = "Requested by an exception case: count differed from the books")
    val audit = JobTask(
        "t-au", JobType.AUDIT, "open", "SAMPLE-TWR-0001 · audit sectors", siteId = "twr-1",
        lines = listOf(
            JobLine("a1", 10, "RRU-4402", "Radio unit", position = "Sector A · slot 1", expectedSerial = "SN-1001"),
            JobLine("a2", 20, "RRU-4402", "Radio unit", position = "Sector A · slot 2", expectedSerial = "SN-1002"),
            JobLine("a3", 30, "PSU-48", "Power supply unit", position = "Sector A · slot 3", expectedSerial = "SN-1003"),
        ),
    )
    val swap = JobTask(
        "t-sw", JobType.SWAP, "open", "Replace radio unit · sector B", siteId = "twr-1",
        lines = listOf(JobLine("s1", 10, "RRU-4402", "Radio unit", position = "Sector B · slot 2", expectedSerial = "SN-OLD-7")),
    )
}

class Rig(task: JobTask, visitId: String? = null, practice: Boolean = false, deviceId: String? = "dev-1",
          transport: JobTransport? = null) {
    var now = 1_793_000_000_000L // 2026-10-26T…Z
    private var keys = 0
    private var seq = 0L
    val transport: RecordingTransport = (transport as? RecordingTransport) ?: RecordingTransport()
    val speaker = RecordingSpeaker()
    val runner = JobRunner(
        task, transport ?: this.transport, speaker, deviceId, visitId = visitId, siteLabel = "SAMPLE-TWR-0001",
        practice = practice, clock = { now }, zone = ZoneId.of("Asia/Kolkata"), newKey = { "key-${++keys}" }, nextSeq = { ++seq },
    )
    val v: StepView get() = runner.view.value

    init { runner.start() }

    suspend fun act(vararg a: JobAction) = a.forEach { runner.act(it) }
    suspend fun scan(code: String) = runner.act(JobAction.Scanned(code))
    suspend fun primary() = runner.act(JobAction.Primary)
    suspend fun say(t: String, c: Float = 0.92f) = runner.act(JobAction.Heard(t, c))
}
