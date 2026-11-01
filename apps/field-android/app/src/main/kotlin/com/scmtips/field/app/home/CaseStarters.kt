package com.scmtips.field.app.home

import com.scmtips.field.app.jobs.ApiRequest
import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.JobTransport
import com.scmtips.field.app.look.LookCase
import com.scmtips.field.core.common.UUIDv7
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/** A short "How to test" card per case (contract §1): what to lay out, how many, one layer, what to say. */
data class HowToTest(val title: String, val steps: List<String>)

/** The two M5 cases on a sandbox site's Today (contract §1), and what each one starts. */
enum class CaseStart(val case: LookCase, val label: String, val sub: String, val howTo: HowToTest, val introHint: String) {
    GROCERY(
        LookCase.GROCERY, "New grocery delivery", "Packs on a table · one look",
        HowToTest("How to test: grocery delivery", listOf(
            "Lay out 8 to 20 identical packs (biscuits, noodles, juice boxes) in ONE layer, labels up or facing you.",
            "Put one or two aside as damaged if you like (a torn or crushed pack) to see a flag.",
            "Stand so all packs are in view, about one metre away. Say “look”.",
            "Listen, then say what you accept, for example “receive 18, flag 2”. Then “post” and “yes”.",
            "Say “make a claim” for short, damaged or wrong pack-size items.",
        )),
        "Lay the packs out in one layer, then say look.",
    ),
    PHARMACY(
        LookCase.PHARMACY, "New pharmacy delivery", "Medicine boxes · batch and expiry",
        HowToTest("How to test: pharmacy receipt", listOf(
            "Lay out 5 to 15 boxes of ONE product in one layer, the side with batch and expiry facing up.",
            "Mix in an expired or soon-expiring box if you have one, to see it flagged.",
            "Say “look”. For small print, hold one box close and say “look again”.",
            "Say what you accept, for example “receive 10, flag 2”. Then “post” and “yes”.",
            "Say “make a claim” for expired, near-expiry or damaged boxes.",
        )),
        "Lay the boxes out in one layer, batch and expiry up, then say look.",
    ),
    ;

    companion object {
        fun offered(sandbox: Boolean): List<CaseStart> = if (sandbox) entries.toList() else emptyList()
        fun of(case: LookCase): CaseStart? = entries.firstOrNull { it.case == case }
    }
}

sealed interface CaseOutcome {
    data class Created(val taskId: String, val refDocNo: String?) : CaseOutcome

    /** The server has no case receipts yet (404/422 from a field-api before stream V's route): a clear message. */
    data class NotAvailable(val text: String) : CaseOutcome
    data class Refused(val text: String) : CaseOutcome
}

/**
 * Starts a case on the sandbox site: `POST /v1/sandbox/receipts {site_id, case}` (stream V adds `case`;
 * the M3 route takes `{site_id}` only and answers 201 `{task_id, ref_doc_no}`). An older server that
 * refuses the field (422) or the route (404) is "not available yet", never a crash.
 */
object CaseStarters {
    fun request(siteId: String, case: LookCase, key: String = UUIDv7.generate()): ApiRequest =
        ApiRequest("POST", "/v1/sandbox/receipts", buildJsonObject { put("site_id", siteId); put("case", case.wire) }, key)

    suspend fun start(transport: JobTransport, siteId: String, start: CaseStart): CaseOutcome =
        when (val r = transport.send(request(siteId, start.case))) {
            is ApiResult.Ok -> (r.body["task_id"] as? JsonPrimitive)?.contentOrNull
                ?.let { CaseOutcome.Created(it, (r.body["ref_doc_no"] as? JsonPrimitive)?.contentOrNull) }
                ?: CaseOutcome.Refused("The server did not say which job it made. Refresh Today.")
            is ApiResult.Problem -> when {
                r.code == SandboxStarters.PRODUCTION -> CaseOutcome.Refused("This site is not a sandbox: the test cases run on sandbox sites only.")
                r.status == 404 || r.status == 422 -> CaseOutcome.NotAvailable(
                    "${start.label} is not available on this server yet. Update the Field server, or use New home receipt.",
                )
                else -> CaseOutcome.Refused(r.plain)
            }
            is ApiResult.Offline -> CaseOutcome.Refused("Cannot reach the PC. The job was not made.")
        }
}
