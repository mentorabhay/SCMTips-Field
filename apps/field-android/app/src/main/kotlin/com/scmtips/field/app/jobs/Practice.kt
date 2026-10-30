package com.scmtips.field.app.jobs

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put

/**
 * The practice task in Me (design: "Practice task · Nothing goes to SAP"): a receive job against an
 * in-app sample delivery. [PracticeTransport] answers on the phone and never opens a connection, so
 * nothing reaches field-api or SAP. Every practice step carries the banner "Practice — nothing goes to SAP".
 */
object Practice {
    const val TASK_ID = "practice-receive"

    val task = JobTask(
        id = TASK_ID,
        type = JobType.RECEIVE,
        status = "open",
        title = "Practice delivery 1800 0000 01",
        subtitle = "From SAMPLE-VENDOR-01 · 2 items · 36 pieces",
        refDocNo = "1800000001",
        lines = listOf(
            JobLine("practice-10", 10, "SAMPLE-MAT-0001", "Industrial Component Grade 1", "EA", expectedQty = 12.0, countedQty = 0.0),
            JobLine("practice-20", 20, "SAMPLE-MAT-0002", "Industrial Component Grade 2", "EA", expectedQty = 24.0, countedQty = 0.0),
        ),
    )
}

/** Local answers for the practice task: the request shapes are the real ones, the answers are canned. */
class PracticeTransport : JobTransport {
    val sent = mutableListOf<ApiRequest>()
    private var n = 0

    override suspend fun send(request: ApiRequest): ApiResult {
        sent += request
        n += 1
        val body: JsonObject = when {
            request.path == "/v1/voice-events" -> buildJsonObject { put("id", "practice-voice-$n") }
            request.path == "/v1/count-records" -> buildJsonObject {
                put("counted_qty", (request.body?.get("value") as? JsonPrimitive)?.doubleOrNull ?: 0.0)
            }
            request.path.endsWith("/post-requests") -> buildJsonObject {
                put("posting_request_id", "practice-$n"); put("status", STATUS)
            }
            else -> buildJsonObject { put("ok", true) }
        }
        return ApiResult.Ok(200, body)
    }

    companion object {
        /** Post-request status that only the practice transport returns; the runner ends the job without SAP. */
        const val STATUS = "practice"
    }
}
