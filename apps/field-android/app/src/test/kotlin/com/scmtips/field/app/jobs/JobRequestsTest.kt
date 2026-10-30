package com.scmtips.field.app.jobs

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Request shapes (M2_JOBS_CONTRACT.md §2–§6), the task-list parser and plain-English errors. */
class JobRequestsTest {
    @Test
    fun stagedHashIsTheServersHash() {
        // field_api.routes.voice.staged_hash([("l20", 11), ("l10", 24)]), computed by the server code
        assertEquals("1d64577d6c2a7e6056d5996cc057a115ee407ad7a95971acc4400614ed6a94ed",
            JobRequests.stagedHash(listOf("l20" to 11.0, "l10" to 24.0)))
    }

    @Test
    fun taskListAsksForOpenAndInProgressWorkOfTheSite() {
        val r = JobRequests.tasks("site 1")
        assertEquals("GET", r.method)
        assertEquals("/v1/tasks?site_id=site+1&status=open,in_progress", r.path)
        assertNull(r.idempotencyKey)
    }

    @Test
    fun confirmationAndFlagBodies() {
        val c = JobRequests.confirmation("k", "t1", "l1", ConfirmKind.SERIAL, "SN-1", InputSource.SCAN, role = "new")
        assertEquals("/v1/tasks/t1/lines/l1/confirmations", c.path)
        assertEquals("""{"kind":"serial","code":"SN-1","source":"scan","role":"new"}""", c.body.toString())
        assertEquals("k", c.idempotencyKey)
        val f = JobRequests.flag("k2", "t1", "l1", "missing")
        assertEquals("""{"flag":"missing"}""", f.body.toString())
    }

    @Test
    fun countRecordOmitsAMissingVoiceEvent() {
        assertEquals("""{"task_line_id":"l1","value":3.0,"unit":"EA","source":"manual"}""",
            JobRequests.countRecord("k", "l1", 3.0, "EA", InputSource.MANUAL, null).body.toString())
    }

    @Test
    fun climbEventsAndCheckOutBodies() {
        val e = JobRequests.climbEvents("k", "v1", listOf(ClimbEvent(7, "climb_safe_released", "2026-10-31T10:00:00+05:30")))
        assertEquals("/v1/climb-sessions/v1/events", e.path)
        assertEquals("""{"events":[{"device_seq":7,"type":"climb_safe_released","occurred_at":"2026-10-31T10:00:00+05:30"}]}""", e.body.toString())
        val o = JobRequests.checkOut("k", "v1", 2)
        assertEquals("PATCH", o.method)
        assertEquals("""{"unsynced_count":2}""", o.body.toString())
        assertEquals("/v1/safety/visits/v1/check-in", JobRequests.safetyCheckIn("k", "v1").path)
    }

    @Test
    fun parsesTheContractTaskList() {
        val body = Json.parseToJsonElement(CONTRACT_SAMPLE) as JsonObject
        val tasks = TaskParser.parseList(body)
        assertEquals(listOf(JobType.RECEIVE, JobType.COUNT, JobType.AUDIT), tasks.map { it.type })
        val rcv = tasks[0]
        assertEquals("1800000022", rcv.refDocNo)
        assertEquals("From SAMPLE-VENDOR-01 · 2 items · 36 pieces", rcv.subtitle)
        assertEquals(listOf(10, 20), rcv.lines.map { it.lineNo })
        assertEquals(12.0, rcv.lines[0].expectedQty!!, 0.0)
        assertEquals("03-05-02", rcv.lines[0].bin)
        val count = tasks[1]
        assertTrue(count.isRecount)
        assertNull("blind count", count.lines.single().expectedQty)
        val audit = tasks[2]
        assertEquals("Sector A · slot 2", audit.lines.single().position)
        assertEquals("SN-1002", audit.lines.single().expectedSerial)
    }

    @Test
    fun parsesTodaysFieldApiNamesAndSkipsUnknownTypes() {
        val body = Json.parseToJsonElement(
            """{"items":[{"id":"a","type":"receive","status":"pending","title":"","erp_ref":"1800000099","lines":[]},
               {"id":"b","type":"pack","status":"open","lines":[]}]}""",
        ) as JsonObject
        val t = TaskParser.parseList(body).single()
        assertEquals("1800000099", t.refDocNo)
        assertEquals("Delivery 1800000099", t.title)
        assertTrue(t.status in TaskParser.OPEN_STATUSES)
    }

    @Test
    fun problemsAreShownInPlainEnglish() {
        fun p(status: Int, code: String?, title: String?, detail: String? = null) = ApiResult.Problem(status, code, title, detail).plain
        assertEquals("That is bin 03-05-01. Go to 03-05-02.", p(409, "FIELD-TASK-409-WRONG-CODE", "That is bin 03-05-01. Go to 03-05-02."))
        assertEquals("Your sign-in expired. Connect this phone again from the PC.", p(401, "FIELD-AUTH-401-EXPIRED", "HTTP Error"))
        assertEquals("The work permit is not valid today. Check the permit number.",
            p(422, "FIELD-HTTP-422-ERROR", "HTTP Error", "FIELD-VIS-422-PERMIT: MSG4.03: Site access permit expired"))
        assertTrue(p(422, "FIELD-HTTP-422-ERROR", "HTTP Error", "FIELD-VIS-422-GEOFENCE: GPS accuracy 80.0 m").startsWith("You do not seem to be at the site"))
        assertEquals("Device binding mismatch", p(409, "FIELD-AUTH-401-BINDING", "Device binding mismatch"))
        assertEquals("Site not found", p(404, "FIELD-HTTP-404-NOT-FOUND", "Not Found", "Site not found"))
        assertEquals("The server had a problem. Try again in a minute.", p(500, "FIELD-SYS-500-INTERNAL", "Internal Server Error"))
    }

    private companion object {
        const val CONTRACT_SAMPLE = """{"items": [
          {"id": "t1", "type": "receive", "status": "open", "title": "Delivery 1800000022",
           "subtitle": "From SAMPLE-VENDOR-01 · 2 items · 36 pieces", "ref_doc_no": "1800000022", "reason": null, "due": null,
           "site_id": "s1", "version": 3, "lines": [
             {"id": "l20", "line_no": 20, "material": "SAMPLE-MAT-0002", "description": "Grade 2", "uom": "EA", "bin": null,
              "expected_qty": 24, "counted_qty": 0, "position": null, "expected_serial": null, "status": "open", "version": 1},
             {"id": "l10", "line_no": 10, "material": "SAMPLE-MAT-0001", "description": "Grade 1", "uom": "EA", "bin": "03-05-02",
              "expected_qty": 12, "counted_qty": 0, "position": null, "expected_serial": null, "status": "open", "version": 1}]},
          {"id": "t2", "type": "count", "status": "open", "title": "Recount bin 03-05-02",
           "reason": "Requested by an exception case: count differed from the books", "lines": [
             {"id": "c1", "line_no": 10, "material": "SAMPLE-MAT-0001", "uom": "EA", "bin": "03-05-02", "status": "open", "version": 1}]},
          {"id": "t3", "type": "audit", "status": "in_progress", "title": "SAMPLE-TWR-0001 · Sector A", "lines": [
             {"id": "a2", "line_no": 20, "material": "RRU-4402", "description": "Radio unit", "uom": "EA",
              "position": "Sector A · slot 2", "expected_serial": "SN-1002", "status": "open", "version": 1}]}
        ], "next_cursor": null}"""
    }
}
