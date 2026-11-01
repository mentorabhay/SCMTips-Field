package com.scmtips.field.app.jobs

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** M5 receive with a look: the proposal pre-fills, the operator's spoken numbers post (good + flagged). */
class JobRunnerLookTest {
    private val oneLine = JobTask(
        "t-gr", JobType.RECEIVE, "open", "Grocery delivery", "From SAMPLE-VENDOR-01", "1800000031", siteId = "site-1",
        lines = listOf(JobLine("g1", 10, "SAMPLE-GROC-0001", "Biscuit pack", "EA", expectedQty = 20.0, countedQty = 0.0)),
    )
    private val fill = LookFill("lk-1", "cap-1", "g1", 18, 2, "Say receive 18, flag 2. Or say count again.")

    @Test
    fun m5B02_receiveEighteenFlagTwo_savesTwentyWithTwoFlagged_thenPostAndYesCarryTheLook() = runBlocking {
        val r = Rig(oneLine)
        assertTrue(r.v.canLook)
        r.runner.applyLook(fill)
        assertEquals(StepKind.COUNT, r.v.kind)
        assertEquals("pre-filled with the good units", 18, r.v.qty)
        assertEquals(2, r.v.flagged)
        assertTrue(r.v.qtyNote!!.contains("matches the 20 expected"))
        assertTrue("the look stages nothing", r.transport.sent.isEmpty())
        r.say("repeat")
        assertEquals(fill.hint, r.speaker.said.last())

        r.say("receive eighteen flag two")
        val count = r.transport.last("/v1/count-records")
        assertEquals("g1", count.str("task_line_id"))
        assertEquals(20.0, count.num("value")); assertEquals(2.0, count.num("flag_qty"))
        assertEquals("lk-1", count.str("look_id")); assertEquals("cap-1", count.str("capture_id"))
        assertEquals("voice", count.str("source")); assertTrue(count.str("voice_event_id") != null)
        assertEquals(StepKind.REVIEW, r.v.kind)
        assertEquals(listOf(Detail("Biscuit pack", "20 of 20 · 2 flagged")), r.v.detail)
        assertTrue(r.speaker.said.last().startsWith("18 good, 2 flagged, saved. 1 item, 20 pieces, 2 flagged."))

        r.say("post")
        assertEquals("Post 1 item, 20 pieces, 2 flagged? Say yes or cancel.", r.speaker.said.last())
        r.now += 4_000
        r.say("confirm")
        val post = r.transport.last("/post-requests")
        assertEquals("voice", post.obj("confirm")!!.str("method"))
        assertEquals("lk-1", post.str("look_id"))
        assertEquals(JobRequests.stagedHash(listOf("g1" to 20.0)), post.str("staged_hash"))
        assertNull(r.runner.postedDocument)
        r.runner.onLiveEvent("erp.posted", mapOf("task_id" to "t-gr", "doc_number" to "4900000101", "doc_year" to "2026"))
        assertEquals("4900000101", r.runner.postedDocument)
        assertEquals("2026", r.runner.postedYear)
        assertTrue(r.runner.usedLook)
        assertFalse(r.v.canLook)
    }

    @Test
    fun m5B02_flagAloneKeepsTheGoodUnits_andReceiveAloneFlagsNone() = runBlocking {
        val r = Rig(oneLine)
        r.runner.applyLook(fill)
        r.say("flag three")
        assertEquals(21.0, r.transport.last("/v1/count-records").num("value"))
        assertEquals(3.0, r.transport.last("/v1/count-records").num("flag_qty"))
        assertEquals("18 good, 3 flagged, saved. 1 more than expected.", r.speaker.said.last().substringBefore(" 1 item"))
        r.say("receive twenty")
        val c = r.transport.last("/v1/count-records")
        assertEquals(20.0, c.num("value")); assertEquals(0.0, c.num("flag_qty"))
        assertTrue(r.speaker.said.last().startsWith("20 good, none flagged, saved."))
        r.say("flag 1")
        assertEquals(21.0, r.transport.last("/v1/count-records").num("value"))
    }

    @Test
    fun m5B02_touchSaveAndAllHereAfterALook_keepTheFlaggedUnits() = runBlocking {
        val r = Rig(oneLine)
        r.runner.applyLook(fill)
        r.act(JobAction.AllHere)
        var c = r.transport.last("/v1/count-records")
        assertEquals("all 20 here, 2 of them flagged", 20.0, c.num("value")); assertEquals(2.0, c.num("flag_qty"))
        val r2 = Rig(oneLine)
        r2.runner.applyLook(fill)
        r2.act(JobAction.SetQty(17), JobAction.Primary)
        c = r2.transport.last("/v1/count-records")
        assertEquals(19.0, c.num("value")); assertEquals(2.0, c.num("flag_qty")); assertEquals("lk-1", c.str("look_id"))
        assertEquals("manual", c.str("source"))
    }

    @Test
    fun m5B02_withoutALookTheReceiveBodiesStayM4Shaped() = runBlocking {
        val r = Rig(oneLine)
        r.say("receive 20")
        val c = r.transport.last("/v1/count-records")
        assertEquals(20.0, c.num("value"))
        assertNull(c.str("flag_qty")); assertNull(c.str("look_id")); assertNull(c.str("capture_id"))
        r.say("post"); r.say("yes")
        assertNull(r.transport.last("/post-requests").str("look_id"))
        assertFalse(r.runner.usedLook)
        // Two lines and none selected: say which box first.
        val two = Rig(Tasks.receive)
        two.say("receive 12")
        assertEquals("Scan a box first, then say receive and the number.", two.speaker.said.last())
        assertTrue(two.transport.all("/v1/count-records").isEmpty())
        // Not a delivery: refused, nothing sent.
        val count = Rig(Tasks.count)
        count.say("receive 3")
        assertEquals("Say receive on a delivery.", count.speaker.said.last())
    }

    @Test
    fun m5B02_aCaseIntroSaysLook_andTheLookLineIsTheOnlyLine() = runBlocking {
        val sp = RecordingSpeaker()
        val r = JobRunner(oneLine, RecordingTransport(), sp, "dev-1", lookHint = "Lay the packs out in one layer, then say look.")
        r.start()
        assertEquals("Delivery 1800 0000 31. 1 item. Lay the packs out in one layer, then say look.", sp.said.last())
        assertEquals("g1", r.lookLineId)
        assertNull("two open lines, none selected", Rig(Tasks.receive).runner.lookLineId)
        val two = Rig(Tasks.receive)
        two.primary()
        two.scan("SAMPLE-MAT-0002")
        assertEquals("l20", two.runner.lookLineId)
    }
}
