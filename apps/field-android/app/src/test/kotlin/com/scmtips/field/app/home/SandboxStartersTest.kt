package com.scmtips.field.app.home

import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.RecordingTransport
import com.scmtips.field.app.jobs.str
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** M3 fix (owner test, 31 Oct): Today on a sandbox site is never a dead end. */
class SandboxStartersTest {
    private fun created(id: String) = ApiResult.Ok(201, buildJsonObject { put("task_id", id); put("ref_doc_no", "1900000001") })

    @Test
    fun onlyASandboxSiteOffersAHomeReceiptAndAShelfCount() {
        assertEquals(listOf("New home receipt", "Count a shelf"), SandboxStarters.offered(sandbox = true).map { it.label })
        assertTrue(SandboxStarters.offered(sandbox = false).isEmpty())
    }

    @Test
    fun aHomeReceiptPostsTheSiteToTheSandboxReceiptsRoute() = runBlocking {
        val t = RecordingTransport().apply { rules += { r -> if (r.path == "/v1/sandbox/receipts") created("t-home") else null } }
        assertEquals(SandboxOutcome.Created("t-home", "1900000001"), SandboxStarters.start(t, "site-9", SandboxStart.HOME_RECEIPT))
        val r = t.sent.single()
        assertEquals("POST", r.method)
        assertEquals("site-9", r.str("site_id"))
        assertTrue(r.idempotencyKey!!.isNotBlank())
    }

    @Test
    fun aShelfCountPostsSiteAndBin_andNeedsABin() = runBlocking {
        val t = RecordingTransport().apply { rules += { r -> if (r.path == "/v1/sandbox/counts") created("t-shelf") else null } }
        assertTrue(SandboxStarters.start(t, "site-9", SandboxStart.COUNT_SHELF, " ") is SandboxOutcome.Refused)
        assertTrue(SandboxStarters.start(t, "site-9", SandboxStart.COUNT_SHELF, "A 01") is SandboxOutcome.Refused)
        assertTrue(t.sent.isEmpty())
        assertEquals(SandboxOutcome.Created("t-shelf", "1900000001"), SandboxStarters.start(t, "site-9", SandboxStart.COUNT_SHELF, " A-01 "))
        val r = t.sent.single()
        assertEquals("/v1/sandbox/counts", r.path)
        assertEquals("site-9", r.str("site_id"))
        assertEquals("A-01", r.str("bin"))
    }

    @Test
    fun aProductionSiteOrNoAnswerIsSaidPlainly() = runBlocking {
        val prod = RecordingTransport().apply { rules += { ApiResult.Problem(403, SandboxStarters.PRODUCTION, "Forbidden", null) } }
        val r = SandboxStarters.start(prod, "site-1", SandboxStart.HOME_RECEIPT) as SandboxOutcome.Refused
        assertTrue(r.text, r.text.contains("not a sandbox"))
        val off = RecordingTransport().apply { rules += { ApiResult.Offline("timeout") } }
        assertTrue((SandboxStarters.start(off, "site-1", SandboxStart.HOME_RECEIPT) as SandboxOutcome.Refused).text.contains("Cannot reach"))
        val odd = RecordingTransport().apply { rules += { ApiResult.Ok(201, buildJsonObject { }) } }
        assertTrue(SandboxStarters.start(odd, "site-1", SandboxStart.HOME_RECEIPT) is SandboxOutcome.Refused)
    }
}
