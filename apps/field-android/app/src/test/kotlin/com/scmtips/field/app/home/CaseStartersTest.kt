package com.scmtips.field.app.home

import com.scmtips.field.app.jobs.ApiResult
import com.scmtips.field.app.jobs.str
import com.scmtips.field.app.look.LookCase
import com.scmtips.field.app.look.ScriptedFieldApi
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Today's M5 case starters (contract §1) and their fallback on a field-api without stream V's route. */
class CaseStartersTest {
    @Test
    fun m5B04_bothCasesOnASandboxSiteOnly_eachWithAHowToTestCard() {
        assertEquals(listOf(CaseStart.GROCERY, CaseStart.PHARMACY), CaseStart.offered(true))
        assertTrue(CaseStart.offered(false).isEmpty())
        CaseStart.entries.forEach { c ->
            assertTrue(c.howTo.steps.size in 3..6)
            assertTrue("one layer is said", c.howTo.steps.any { "one layer" in it.lowercase() })
            assertTrue("what to say", c.howTo.steps.any { "“look”" in it })
            assertTrue(c.introHint.endsWith("say look."))
        }
        assertEquals(CaseStart.PHARMACY, CaseStart.of(LookCase.PHARMACY))
    }

    @Test
    fun m5B04_aCaseIsASandboxReceiptWithItsCase() = runBlocking {
        val api = ScriptedFieldApi().apply { ok("POST /v1/sandbox/receipts", """{"task_id":"t-9","ref_doc_no":"1800000031"}""") }
        assertEquals(CaseOutcome.Created("t-9", "1800000031"), CaseStarters.start(api, "site-1", CaseStart.GROCERY))
        val req = api.sent.single()
        assertEquals("site-1", req.str("site_id")); assertEquals("grocery", req.str("case"))
        assertTrue(req.idempotencyKey != null)
        CaseStarters.start(api, "site-1", CaseStart.PHARMACY)
        assertEquals("pharmacy", api.sent.last().str("case"))
    }

    @Test
    fun m5B04_anOlderServer_saysNotAvailableYet_neverCrashes() = runBlocking {
        val noRoute = ScriptedFieldApi() // unscripted: 404
        val r = CaseStarters.start(noRoute, "site-1", CaseStart.GROCERY)
        assertEquals(CaseOutcome.NotAvailable("New grocery delivery is not available on this server yet. Update the Field server, or use New home receipt."), r)
        val noField = ScriptedFieldApi().apply { on("POST /v1/sandbox/receipts", ApiResult.Problem(422, "FIELD-HTTP-422-VALIDATION", "Validation Error", "case")) }
        assertTrue(CaseStarters.start(noField, "site-1", CaseStart.PHARMACY) is CaseOutcome.NotAvailable)
        val prod = ScriptedFieldApi().apply { on("POST /v1/sandbox/receipts", ApiResult.Problem(403, SandboxStarters.PRODUCTION, "Production site", null)) }
        assertEquals(CaseOutcome.Refused("This site is not a sandbox: the test cases run on sandbox sites only."), CaseStarters.start(prod, "s", CaseStart.GROCERY))
        val off = ScriptedFieldApi().apply { on("POST /v1/sandbox/receipts", ApiResult.Offline("timeout")) }
        assertEquals(CaseOutcome.Refused("Cannot reach the PC. The job was not made."), CaseStarters.start(off, "s", CaseStart.GROCERY))
        val noId = ScriptedFieldApi().apply { ok("POST /v1/sandbox/receipts", """{"ok":true}""") }
        assertTrue(CaseStarters.start(noId, "s", CaseStart.GROCERY) is CaseOutcome.Refused)
    }
}
