package com.scmtips.field.app.jobs

import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The one job runner (M2_JOBS_CONTRACT.md; design Main.dc.html jobs()): every job type's steps, scan
 * resolution, wrong-bin handling, staged hash, request bodies and live events.
 */
class JobRunnerTest {

    // --- receive -----------------------------------------------------------------------------

    @Test
    fun receive_touchFlowFollowsTheDesignSevenStepsAndPostsWithTouchConfirmation() = runBlocking {
        val r = Rig(Tasks.receive)
        val steps = mutableListOf<Pair<Int, StepKind>>()
        fun note() { steps += r.v.stepNo to r.v.kind; assertEquals(7, r.v.stepCount) }
        note()
        assertEquals("Check in this delivery", r.v.title)
        assertEquals(listOf(Detail("From", "SAMPLE-VENDOR-01"), Detail("Expected", "2 items · 36 pieces"), Detail("Delivery", "1800 0000 22")), r.v.detail)
        assertEquals("Delivery 1800 0000 22. 2 items. Scan a box with the phone.", r.speaker.said.last())
        r.primary(); note()
        assertEquals("Scan the label on a box", r.v.title)
        r.scan("sample-mat-0001\n"); note()
        assertEquals(StepKind.COUNT, r.v.kind)
        assertEquals(12, r.v.expected); assertEquals(12, r.v.qty)
        assertEquals("Matches what is expected", r.v.qtyNote)
        assertEquals("Save and scan the next box", r.v.primary)
        assertEquals(EarconCue.CAPTURED, r.speaker.earcons.last())
        r.act(JobAction.AllHere); note()
        assertEquals("Scan the next box", r.v.title)
        assertEquals("12 saved. Scan the next box with the phone.", r.speaker.said.last())
        r.scan("SAMPLE-MAT-0002"); note()
        assertEquals("Save and check", r.v.primary)
        r.act(JobAction.SetQty(22))
        assertEquals("2 fewer than expected", r.v.qtyNote); assertEquals(Tone.WARN, r.v.qtyTone)
        r.primary(); note()
        assertEquals(StepKind.REVIEW, r.v.kind)
        assertEquals(listOf(Detail("Industrial Component Grade 1", "12 of 12"), Detail("Industrial Component Grade 2", "22 of 24")), r.v.detail)
        assertTrue(r.speaker.said.last().startsWith("Industrial Component Grade 2: 22, 2 fewer than expected."))
        r.primary()
        assertEquals(StepKind.CONFIRM, r.v.kind)
        assertEquals("Post to SAP now?", r.v.title); assertEquals("Yes, post it", r.v.primary)
        assertEquals("2 items, 34 pieces, with 1 difference.", r.v.body)
        r.primary()
        assertEquals(StepKind.WAITING, r.v.kind)

        val counts = r.transport.all("/v1/count-records")
        assertEquals(listOf("l10" to 12.0, "l20" to 22.0), counts.map { it.str("task_line_id") to it.num("value") })
        assertEquals(listOf("manual", "manual"), counts.map { it.str("source") })
        assertEquals(listOf("EA", "EA"), counts.map { it.str("unit") })
        val post = r.transport.last("/post-requests")
        assertEquals("POST /v1/tasks/t-rcv/post-requests", "${post.method} ${post.path}")
        assertEquals("post", post.str("operation"))
        assertEquals(listOf("l10", "l20"), post.arr("lines"))
        assertEquals("8085a1d7185bdc812b506f84e2c354a3307a49bf4081d73bdab775ad6ebeca63", post.str("staged_hash"))
        assertEquals("touch", post.obj("confirm")!!.str("method"))
        assertNull("touch posts carry no voice ids", post.str("post_voice_event_id"))
        assertTrue("every write has an idempotency key", r.transport.sent.all { it.idempotencyKey != null })

        assertFalse(r.runner.onLiveEvent("erp.posted", mapOf("task_id" to "t-rcv", "doc_number" to "4900000101")))
        note()
        assertEquals(StepKind.DONE, r.v.kind)
        assertEquals("Goods received", r.v.title)
        assertEquals(listOf(Detail("SAP document", "4900 0001 01")), r.v.detail)
        assertEquals("Posted. Document 4900 0001 01.", r.speaker.said.last())
        assertEquals(listOf(1, 2, 3, 4, 5, 6, 7), steps.map { it.first })
        r.primary()
        assertTrue(r.v.finished)
    }

    @Test
    fun receive_voiceFlowPostsOnlyAfterPostThenYesWithBothVoiceIds_fr2_033() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary()
        r.scan("SAMPLE-MAT-0001"); r.say("all here")
        r.scan("SAMPLE-MAT-0002"); r.say("Twenty-two.")
        assertEquals(StepKind.REVIEW, r.v.kind)
        r.say("post")
        assertEquals(StepKind.CONFIRM, r.v.kind)
        assertTrue(r.v.listening)
        assertEquals("Post 2 items, 34 pieces, with 1 difference? Say yes or cancel.", r.speaker.said.last())
        assertEquals(EarconCue.CONFIRM_PROMPT, r.speaker.earcons.last())
        assertTrue(r.transport.all("/post-requests").isEmpty())
        r.now += 4_000
        r.say("yes")
        assertEquals(StepKind.WAITING, r.v.kind)

        val voice = r.transport.all("/v1/voice-events")
        assertEquals(listOf("count", "count", "post", "confirm"), voice.map { it.str("intent") })
        assertEquals(listOf("dev-1"), voice.map { it.str("device_id") }.distinct())
        assertEquals(listOf("t-rcv"), voice.map { it.str("task_id") }.distinct())
        val counts = r.transport.all("/v1/count-records")
        assertEquals(listOf("voice", "voice"), counts.map { it.str("source") })
        assertEquals(listOf("ve-1", "ve-3"), counts.map { it.str("voice_event_id") })
        assertEquals(listOf(12.0, 22.0), counts.map { it.num("value") })
        val post = r.transport.last("/post-requests")
        val confirm = post.obj("confirm")!!
        assertEquals("voice", confirm.str("method"))
        assertEquals("ve-5", confirm.str("post_voice_event_id")); assertEquals("ve-6", confirm.str("confirm_voice_event_id"))
        assertEquals("ve-5", post.str("post_voice_event_id")); assertEquals("ve-6", post.str("confirm_voice_event_id"))
        assertEquals(JobRequests.stagedHash(listOf("l10" to 12.0, "l20" to 22.0)), post.str("staged_hash"))
    }

    @Test
    fun receive_yesAfterTenSecondsIsRefusedAndNothingIsPosted_msg2_22() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.say("all here"); r.say("next"); r.say("5"); r.say("post")
        assertTrue(r.v.listening)
        r.now += 10_001
        r.runner.tick()
        assertEquals(StepKind.REVIEW, r.v.kind)
        assertTrue(r.speaker.said.last().startsWith("Post cancelled: no answer within 10 seconds."))
        r.say("yes")
        assertEquals("Nothing to confirm. Say post first.", r.speaker.said.last())
        assertTrue(r.transport.all("/post-requests").isEmpty())
    }

    @Test
    fun receive_belowFloorAndOutOfGrammarChangeNothing_fr2_032() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.say("all here"); r.say("next"); r.say("all here"); r.say("post")
        assertTrue(r.v.listening)
        val before = r.transport.sent.size
        r.say("yes", 0.79f)
        r.say("ship it", 0.99f)
        assertEquals(before, r.transport.sent.size)
        assertTrue("stage survives noise", r.v.listening)
        assertEquals(JobGrammar.NOT_UNDERSTOOD, r.speaker.said.last())
    }

    @Test
    fun receive_cancelOrAnotherCommandDropsTheVoiceStage() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.say("all here"); r.say("next")
        r.say("4"); r.say("post"); r.say("cancel")
        assertEquals(StepKind.REVIEW, r.v.kind)
        assertTrue(r.speaker.said.last().startsWith("Cancelled. Nothing posted."))
        r.say("post"); r.say("4")
        assertFalse("a number is not a yes", r.v.listening)
        r.say("yes")
        assertTrue(r.transport.all("/post-requests").isEmpty())
    }

    @Test
    fun receive_aNumberNeedsACountStepAndPostNeedsTheReview() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary()
        r.say("count 3")
        assertEquals("Say a number on a count step.", r.speaker.said.last())
        r.say("post")
        assertTrue(r.speaker.said.last().startsWith("Not yet."))
        r.say("yes")
        assertEquals("Nothing to confirm. Say post first.", r.speaker.said.last())
        assertTrue(r.transport.sent.isEmpty())
    }

    @Test
    fun receive_unknownLabelIsRefusedOnThePhoneWithoutACall() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary()
        r.scan("SOMETHING-ELSE")
        assertEquals(StepKind.SCAN, r.v.kind)
        assertEquals("SOMETHING-ELSE is not on this delivery.", r.v.message)
        assertEquals(Tone.BAD, r.v.messageTone)
        assertEquals("Not on this delivery.", r.speaker.said.last())
        assertEquals(EarconCue.ERROR, r.speaker.earcons.last())
        assertTrue(r.transport.sent.isEmpty())
    }

    @Test
    fun receive_nextSelectsTheNextUncountedLineAndRepeatAndWhatIsThisSpeak() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary()
        r.say("next")
        assertEquals(StepKind.COUNT, r.v.kind)
        assertEquals("SAMPLE-MAT-0001", r.v.where)
        val prompt = r.speaker.said.last()
        assertEquals("Industrial Component Grade 1. 12 expected. Say the count, or all here.", prompt)
        r.say("what is this")
        assertEquals("Line 10. SAMPLE-MAT-0001. Industrial Component Grade 1.", r.speaker.said.last())
        r.say("repeat")
        assertEquals(prompt, r.speaker.said.last())
    }

    @Test
    fun receive_backFromCountReturnsToScanAndBackAtTheStartLeaves() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary(); r.scan("SAMPLE-MAT-0001")
        r.act(JobAction.Back)
        assertEquals(StepKind.SCAN, r.v.kind)
        assertTrue(r.transport.sent.isEmpty())
        r.act(JobAction.Back)
        assertTrue(r.v.finished)
    }

    @Test
    fun receive_aRefusedCountKeepsTheStepAndSaysWhyInPlainEnglish() = runBlocking {
        val r = Rig(Tasks.receive)
        r.transport.rules += { req ->
            if (req.path == "/v1/count-records") ApiResult.Problem(410, "FIELD-CAP-410-TASK-CLOSED", "Task closed", null) else null
        }
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.act(JobAction.AllHere)
        assertEquals(StepKind.COUNT, r.v.kind)
        assertEquals("This job is already closed. Go back to Today.", r.v.message)
        assertEquals("Not saved. Check phone.", r.speaker.said.last())
    }

    @Test
    fun receive_voiceNeedsARegisteredPhone() = runBlocking {
        val r = Rig(Tasks.receive, deviceId = null)
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.say("12")
        assertEquals("This phone is not registered yet. Use the buttons.", r.v.message)
        assertTrue(r.transport.sent.isEmpty())
    }

    @Test
    fun resume_receiveLinesCountedOnTheServerStayDone_pickLinesAreRedone() = runBlocking {
        val started = Tasks.receive.copy(status = "in_progress", lines = Tasks.receive.lines.map {
            if (it.id == "l10") it.copy(status = "counted", countedQty = 11.0) else it
        })
        val r = Rig(started)
        r.primary()
        assertEquals("Scan the next box", r.v.title)
        assertEquals(4, r.v.stepNo)
        r.scan("SAMPLE-MAT-0002"); r.act(JobAction.AllHere)
        r.primary(); r.primary()
        assertEquals(JobRequests.stagedHash(listOf("l10" to 11.0, "l20" to 24.0)), r.transport.last("/post-requests").str("staged_hash"))

        val pick = Rig(Tasks.pick.copy(lines = Tasks.pick.lines.map { it.copy(status = "counted", countedQty = 3.0) }))
        assertEquals("Go to the first stop", pick.v.title)
    }

    @Test
    fun bestOfPrefersACodeThisJobKnows() {
        val r = Rig(Tasks.receive)
        assertEquals("sample-mat-0002", r.runner.bestOf(listOf("4006381333931", "sample-mat-0002")))
        assertEquals("A", r.runner.bestOf(listOf("A", "B")))
        assertNull(r.runner.bestOf(emptyList()))
    }

    // --- posting edge cases ------------------------------------------------------------------

    @Test
    fun postOffline_retrySendsExactlyTheSameRequestAndKey() = runBlocking {
        val r = Rig(Tasks.receive)
        var first = true
        r.transport.rules += { req -> if (req.path.endsWith("/post-requests") && first) { first = false; ApiResult.Offline("timeout") } else null }
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.act(JobAction.AllHere); r.say("next"); r.act(JobAction.AllHere)
        r.primary(); r.primary()
        assertEquals(StepKind.CONFIRM, r.v.kind)
        assertTrue(r.v.message!!.contains("cannot reach the PC"))
        assertEquals(EarconCue.OFFLINE_QUEUED, r.speaker.earcons.last())
        r.primary()
        val posts = r.transport.all("/post-requests")
        assertEquals(2, posts.size)
        assertEquals(posts[0], posts[1])
        assertEquals(StepKind.WAITING, r.v.kind)
    }

    @Test
    fun postRefused_returnsToReviewWithThePlainReason() = runBlocking {
        val r = Rig(Tasks.receive)
        r.transport.rules += { req ->
            if (req.path.endsWith("/post-requests")) ApiResult.Problem(422, "FIELD-POST-422-NO-CONFIRM", "Staged lines changed", "staged_hash does not match") else null
        }
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.act(JobAction.AllHere); r.say("next"); r.act(JobAction.AllHere)
        r.primary(); r.primary()
        assertEquals(StepKind.REVIEW, r.v.kind)
        assertEquals("Something changed before it was sent, so nothing was posted. Check and try again.", r.v.message)
    }

    @Test
    fun erpFailed_showsThePlainErrorFromTheEvent() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.act(JobAction.AllHere); r.say("next"); r.act(JobAction.AllHere)
        r.primary(); r.primary()
        r.runner.onLiveEvent("erp.failed", mapOf("task_id" to "t-rcv", "message" to "Material SAMPLE-MAT-0001 is blocked for posting."))
        assertEquals(StepKind.FAILED, r.v.kind)
        assertEquals("SAP did not accept this", r.v.title)
        assertTrue(r.v.body!!.startsWith("Material SAMPLE-MAT-0001 is blocked for posting."))
        assertEquals("Posting failed. Check phone.", r.speaker.said.last())
    }

    @Test
    fun liveEvents_otherTasksAreIgnored_taskAssignedAsksForARefresh_andAnEarlyEventIsKept() = runBlocking {
        val r = Rig(Tasks.receive)
        assertTrue(r.runner.onLiveEvent("task.assigned", mapOf("task_id" to "t-new", "type" to "putaway", "title" to "Put away")))
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.act(JobAction.AllHere); r.say("next"); r.act(JobAction.AllHere)
        r.primary()
        // erp.posted arrives while the 202 is still on its way back
        r.transport.beforeReply = { req ->
            if (req.path.endsWith("/post-requests")) r.runner.onLiveEvent("erp.posted", mapOf("task_id" to "t-rcv", "doc_number" to "4900000102"))
        }
        r.primary()
        assertEquals(StepKind.DONE, r.v.kind)
        assertEquals(listOf(Detail("SAP document", "4900 0001 02")), r.v.detail)
        assertFalse(r.runner.onLiveEvent("erp.posted", mapOf("task_id" to "someone-else", "doc_number" to "1")))
        assertEquals("4900 0001 02", r.v.detail.single().v)
    }

    @Test
    fun liveEvents_todaysErpDocumentIdAlsoMatches() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.act(JobAction.AllHere); r.say("next"); r.act(JobAction.AllHere)
        r.primary(); r.primary()
        r.runner.onLiveEvent("erp.posted", mapOf("erp_document_id" to "erp-doc-1", "doc_number" to "4900000103"))
        assertEquals(StepKind.DONE, r.v.kind)
    }

    // --- put-away ----------------------------------------------------------------------------

    @Test
    fun putaway_scanPalletGoToBinWrongBinRefusedLocallyThenBinConfirmation() = runBlocking {
        val r = Rig(Tasks.putaway)
        assertEquals(10, r.v.stepCount)
        assertEquals("Scan the pallet label", r.v.title)
        r.scan("SAMPLE-MAT-0002")
        assertEquals("Take it to this bin", r.v.title)
        assertEquals("02-03-04", r.v.where); assertEquals("Put away to", r.v.whereLabel)
        assertEquals("24 EA · Grade 2", r.v.hint)
        r.primary()
        assertEquals("Scan the bin label to confirm", r.v.title)
        r.scan("03-05-01")
        assertEquals("That is bin 03-05-01. Go to 02-03-04.", r.v.message)
        assertEquals("Wrong bin. Go to 02-03-04.", r.speaker.said.last())
        assertTrue("wrong bin needs no server call", r.transport.sent.isEmpty())
        r.scan("02-03-04")
        val c = r.transport.last("/confirmations")
        assertEquals("POST /v1/tasks/t-pa/lines/p2/confirmations", "${c.method} ${c.path}")
        assertEquals(listOf("bin", "02-03-04", "scan"), listOf(c.str("kind"), c.str("code"), c.str("source")))
        assertNull(c.str("role"))
        assertEquals("Stored in 02-03-04", r.v.title)
        assertEquals("1 more pallet to put away.", r.v.body); assertEquals("Next pallet", r.v.primary)
        r.primary()
        r.scan("SAMPLE-MAT-0001")
        r.scan("03-05-02") // scanning the bin straight from "go" also confirms
        assertEquals("That was the last pallet.", r.v.body); assertEquals("Check and finish", r.v.primary)
        r.primary()
        assertEquals("All pallets stored", r.v.title)
        r.transport.postStatus = "completed"
        r.primary()
        assertEquals("Send this now?", r.v.title)
        r.primary()
        assertEquals(StepKind.DONE, r.v.kind)
        assertEquals("Put-away finished", r.v.title); assertEquals("2 pallets stored.", r.v.body)
        assertEquals(setOf("p1", "p2"), r.transport.last("/post-requests").arr("lines").toSet())
    }

    @Test
    fun putaway_serverWrongCode409TitleIsShownAsIs() = runBlocking {
        val r = Rig(Tasks.putaway)
        r.transport.rules += { req ->
            if (req.path.endsWith("/confirmations")) ApiResult.Problem(409, "FIELD-TASK-409-WRONG-CODE", "That is bin 03-05-01. Go to 03-05-02.", null) else null
        }
        r.scan("SAMPLE-MAT-0001"); r.primary(); r.scan("03-05-02")
        assertEquals("That is bin 03-05-01. Go to 03-05-02.", r.v.message)
        assertEquals("Scan the bin label to confirm", r.v.title)
        assertEquals(EarconCue.ERROR, r.speaker.earcons.last())
    }

    // --- pick ----------------------------------------------------------------------------------

    @Test
    fun pick_stopsInOrderBinThenProductThenQuantityAndAShortPickIsFlagged() = runBlocking {
        val r = Rig(Tasks.pick)
        assertEquals(8, r.v.stepCount)
        assertEquals("Go to the first stop", r.v.title)
        assertEquals("02-01-01", r.v.where); assertEquals("Stop 1 of 2 · bin", r.v.whereLabel)
        r.scan("02-01-01")
        assertEquals(StepKind.SCAN, r.v.kind)
        assertEquals("bin", r.transport.last("/confirmations").str("kind"))
        r.scan("SAMPLE-MAT-0009")
        assertEquals("That is SAMPLE-MAT-0009. Pick SAMPLE-MAT-0003 here.", r.v.message)
        r.scan("02-03-04")
        assertEquals("That is bin 02-03-04. Go to 02-01-01.", r.v.message)
        r.scan("SAMPLE-MAT-0003")
        assertEquals("product", r.transport.last("/confirmations").str("kind"))
        assertEquals("Pick 20", r.v.title); assertEquals(20, r.v.qty); assertEquals("Picked, next stop", r.v.primary)
        r.act(JobAction.SetQty(18)); r.primary()
        val flag = r.transport.last("/flags")
        assertEquals("POST /v1/tasks/t-pk/lines/k1/flags", "${flag.method} ${flag.path}")
        assertEquals("short", flag.str("flag")); assertEquals("picked 18 of 20", flag.str("reason"))
        assertEquals("Go to the next stop", r.v.title); assertEquals("Stop 2 of 2 · bin", r.v.whereLabel)
        r.primary() // "I am at the bin"
        r.scan("SAMPLE-MAT-0004"); r.act(JobAction.AllHere)
        assertEquals(listOf(Detail("Grade 3", "18 of 20"), Detail("Grade 4", "5 of 5")), r.v.detail)
        assertEquals("Post goods issue", r.v.primary)
        r.primary(); r.primary()
        assertEquals(JobRequests.stagedHash(listOf("k1" to 18.0, "k2" to 5.0)), r.transport.last("/post-requests").str("staged_hash"))
        r.runner.onLiveEvent("erp.posted", mapOf("task_id" to "t-pk", "doc_number" to "4900000200"))
        assertEquals("Picked and posted", r.v.title)
    }

    @Test
    fun pick_hashUsesThePickedQuantityTheServerReturns() = runBlocking {
        val r = Rig(Tasks.pick)
        r.transport.rules += { req ->
            if (req.path == "/v1/count-records") ApiResult.Ok(200, buildJsonObject { put("picked_qty", 20.0); put("counted_qty", 0.0) }) else null
        }
        r.primary(); r.scan("SAMPLE-MAT-0003"); r.act(JobAction.AllHere)
        r.primary(); r.scan("SAMPLE-MAT-0004"); r.act(JobAction.AllHere)
        r.primary(); r.primary()
        assertEquals(JobRequests.stagedHash(listOf("k1" to 20.0, "k2" to 20.0)), r.transport.last("/post-requests").str("staged_hash"))
    }

    // --- count ---------------------------------------------------------------------------------

    @Test
    fun count_isBlind_wrongBinRefused_differenceGoesForApproval_fr3_029() = runBlocking {
        val r = Rig(Tasks.count)
        assertEquals(5, r.v.stepCount)
        assertEquals("Go to the bin", r.v.title); assertEquals("03-05-02", r.v.where); assertEquals("Count bin", r.v.whereLabel)
        r.scan("03-05-01")
        assertEquals("That is bin 03-05-01. Go to 03-05-02.", r.v.message)
        r.scan("03-05-02")
        assertEquals("Scan a product in the bin", r.v.title)
        r.scan("03-05-02")
        assertEquals("That is the bin. Now scan a product in it.", r.v.message)
        r.scan("SAMPLE-MAT-0001")
        assertEquals("How many do you see?", r.v.title)
        assertNull("blind count: no expected quantity", r.v.expected)
        assertEquals(0, r.v.qty)
        assertEquals("Tap + and − to set your count", r.v.qtyNote)
        assertEquals("Grade 1. Say how many you see.", r.speaker.said.last())
        r.act(JobAction.SetQty(48)); r.primary()
        assertEquals(listOf(Detail("Grade 1", "48")), r.v.detail)
        r.transport.postStatus = "awaiting_approval"
        r.primary(); r.primary()
        assertEquals(StepKind.DONE, r.v.kind)
        assertEquals("Count saved", r.v.title)
        assertTrue(r.v.body!!.contains("inventory controller reviews it"))
        assertTrue(r.transport.all("/confirmations").isEmpty())
    }

    @Test
    fun count_queuedThenAwaitingApprovalEventFinishes() = runBlocking {
        val r = Rig(Tasks.count)
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.say("forty eight"); r.primary(); r.primary()
        assertEquals(StepKind.WAITING, r.v.kind)
        r.runner.onLiveEvent("count.awaiting_approval", mapOf("task_id" to "t-ct"))
        assertEquals("Count saved", r.v.title)
    }

    @Test
    fun recount_showsTheReasonAndCanBeLeftForLater() = runBlocking {
        val r = Rig(Tasks.recount)
        assertEquals("Recount", r.v.jobKind)
        assertEquals("Requested by an exception case: count differed from the books", r.v.banner)
        assertEquals("Please count this bin again", r.v.title)
        assertEquals("The last count did not match the books.", r.v.hint)
        assertEquals("Cannot do it now", r.v.secondary)
        r.runner.act(JobAction.Secondary)
        assertTrue(r.v.finished)
        assertEquals("Recount left for later. It stays on your list.", r.v.exitNote)
        assertTrue(r.transport.sent.isEmpty())
    }

    // --- tower: audit with check-in, climb-safe and check-out ----------------------------------

    @Test
    fun audit_checkInChecklistClimbSerialsMissingFindingsClimbDownCheckOut() = runBlocking {
        val r = Rig(Tasks.audit)
        assertEquals(10, r.v.stepCount)
        assertEquals(StepKind.CHECKIN, r.v.kind)
        assertEquals("SAMPLE-TWR-0001", r.v.where)
        assertFalse(r.v.primaryEnabled)
        r.act(JobAction.Permit("PTW-2041"))
        assertFalse("no location yet", r.v.primaryEnabled)
        r.act(JobAction.Location(28.61, 77.20, 80.0, r.now))
        assertFalse("80 m is too rough", r.v.primaryEnabled)
        assertEquals("Too rough (±80 m). Move into the open.", r.v.detail.first().v)
        r.act(JobAction.Location(28.61, 77.20, 12.0, r.now))
        assertTrue(r.v.primaryEnabled)
        r.primary()
        val visit = r.transport.last("/visits")
        assertEquals("POST /v1/sites/twr-1/visits", "${visit.method} ${visit.path}")
        assertEquals("PTW-2041", visit.str("permit_ref"))
        assertTrue(visit.str("permit_valid_until")!!.endsWith("T23:59:59+05:30"))
        assertEquals(listOf(28.61, 77.20, 12.0), listOf(visit.num("lat"), visit.num("lon"), visit.num("accuracy_m")))
        assertTrue(visit.str("captured_at")!!.endsWith("+05:30"))
        assertEquals("visit-1", r.runner.visitId)

        assertEquals("Before you climb", r.v.title)
        r.primary()
        assertEquals("all three checks are needed", StepKind.CHECK, r.v.kind)
        r.act(JobAction.ToggleCheck(0), JobAction.ToggleCheck(1))
        assertFalse(r.v.primaryEnabled)
        r.act(JobAction.ToggleCheck(2))
        assertTrue(r.v.primaryEnabled)
        r.primary()
        val activated = r.transport.last("/climb-sessions")
        assertEquals("POST /v1/climb-sessions/visit-1/events", "${activated.method} ${activated.path}")
        assertEquals(listOf("climb_safe_activated" to 1), events(activated))
        assertEquals(StepKind.CLIMB, r.v.kind)
        assertTrue(r.v.dark); assertFalse(r.v.canGoBack)
        r.act(JobAction.Back)
        assertEquals("the phone stays locked while climbing", StepKind.CLIMB, r.v.kind)
        r.say("harness clipped")
        assertEquals("phrase alone confirms nothing (TC4.136)", StepKind.CLIMB, r.v.kind)
        assertEquals(1, r.transport.all("/climb-sessions").size)
        r.now += 4_000
        r.primary() // the tap half, within 10 s
        val clipped = r.transport.last("/climb-sessions")
        assertEquals(listOf("harness_confirmed" to 2, "checkpoint_reached" to 3), events(clipped))
        assertEquals(1, ((clipped.body!!["events"] as JsonArray)[1] as JsonObject)["payload"]!!.let { (it as JsonObject)["level"]!!.jsonPrimitive.int })

        assertEquals("Capture the label", r.v.title)
        assertEquals("Sector A · slot 1", r.v.where); assertEquals("It is not there", r.v.secondary)
        r.scan("SN-1001")
        val c1 = r.transport.last("/confirmations")
        assertEquals("POST /v1/tasks/t-au/lines/a1/confirmations", "${c1.method} ${c1.path}")
        assertEquals("serial", c1.str("kind"))
        r.transport.rules += { req ->
            if (req.path.endsWith("/a2/confirmations")) ApiResult.Ok(200, buildJsonObject { put("ok", true); put("match", false) }) else null
        }
        r.scan("SN-1002") // the server's match=false wins over the local comparison
        r.runner.act(JobAction.Secondary) // slot 3: "It is not there"
        val missing = r.transport.last("/flags")
        assertEquals("POST /v1/tasks/t-au/lines/a3/flags", "${missing.method} ${missing.path}")
        assertEquals("missing", missing.str("flag"))

        assertEquals(StepKind.REVIEW, r.v.kind)
        assertEquals("2 things do not match", r.v.title)
        assertEquals(
            listOf(Detail("Captured", "2 of 3 units"), Detail("Not found", "Power supply unit"), Detail("Different serial", "Sector A · slot 2")),
            r.v.detail,
        )
        r.transport.postStatus = "completed"
        r.primary(); assertEquals("Send this now?", r.v.title)
        r.primary()
        assertEquals(listOf("a1", "a2", "a3"), r.transport.last("/post-requests").arr("lines"))
        assertEquals(StepKind.CLIMB, r.v.kind); assertEquals("Climb down safely", r.v.title)
        r.primary()
        assertEquals(listOf("climb_safe_released" to 4), events(r.transport.last("/climb-sessions")))
        assertEquals("Check out of the site", r.v.title)
        r.primary()
        val out = r.transport.last("/v1/visits/")
        assertEquals("PATCH /v1/visits/visit-1", "${out.method} ${out.path}")
        assertEquals(0.0, out.num("unsynced_count")!!, 0.0)
        assertEquals("Checked out", r.v.title)
        assertEquals(10, r.v.stepNo)
        assertNull(r.runner.visitId)
    }

    @Test
    fun harness_tapOnlyOrPhraseOnlyOrHalvesMoreThan10sApartConfirmNothing_fr4_041_tc4_136() = runBlocking {
        val r = Rig(Tasks.audit, visitId = "v-1")
        r.act(JobAction.ToggleCheck(0), JobAction.ToggleCheck(1), JobAction.ToggleCheck(2))
        r.primary()
        r.primary() // tap only
        assertEquals(StepKind.CLIMB, r.v.kind)
        assertEquals("Now say “harness clipped”.", r.v.message)
        r.now += 10_001
        r.say("harness clipped") // too late for that tap
        assertEquals(StepKind.CLIMB, r.v.kind)
        r.say("clipped") // not the harness phrase
        assertEquals("Say harness clipped.", r.speaker.said.last())
        r.say("harness clipped", 0.79f) // below the floor: nothing
        assertEquals(StepKind.CLIMB, r.v.kind)
        assertEquals(1, r.transport.all("/climb-sessions").size)
        r.now += 2_000
        r.primary() // tap within 10 s of the accepted phrase
        assertEquals(StepKind.SCAN, r.v.kind)
        assertEquals(listOf("harness_confirmed" to 2, "checkpoint_reached" to 3), events(r.transport.last("/climb-sessions")))
    }

    @Test
    fun audit_withAnActiveVisitStartsAtTheChecklist() {
        val r = Rig(Tasks.audit, visitId = "visit-7")
        assertEquals(StepKind.CHECK, r.v.kind)
        assertEquals(9, r.v.stepCount)
    }

    @Test
    fun climbEvents_offlineNeverBlockTheClimberAndAreResentWithTheNextBatch() = runBlocking {
        val r = Rig(Tasks.audit, visitId = "v-1")
        var offline = true
        r.transport.rules += { req -> if (req.path.contains("/climb-sessions/") && offline) { offline = false; ApiResult.Offline("no signal") } else null }
        r.act(JobAction.ToggleCheck(0), JobAction.ToggleCheck(1), JobAction.ToggleCheck(2))
        r.primary()
        assertEquals(StepKind.CLIMB, r.v.kind)
        assertEquals(Tone.WARN, r.v.messageTone)
        assertEquals(1, r.runner.unsentSafetyRecords)
        r.primary(); r.say("harness clipped")
        assertEquals(listOf("climb_safe_activated" to 1, "harness_confirmed" to 2, "checkpoint_reached" to 3), events(r.transport.last("/climb-sessions")))
        assertEquals(0, r.runner.unsentSafetyRecords)
    }

    // --- tower: swap ---------------------------------------------------------------------------

    @Test
    fun swap_oldSerialMustMatch_newMustDiffer_postsAndChecksOut() = runBlocking {
        val r = Rig(Tasks.swap, visitId = "visit-9")
        assertEquals(4, r.v.stepCount)
        assertEquals("Scan the old unit", r.v.title); assertEquals("Sector B · slot 2", r.v.where)
        r.scan("SN-OTHER")
        assertEquals("That is serial SN-OTHER. This job removes SN-OLD-7.", r.v.message)
        assertTrue(r.transport.sent.isEmpty())
        r.scan("sn-old-7")
        val old = r.transport.last("/confirmations")
        assertEquals(listOf("serial", "sn-old-7", "old"), listOf(old.str("kind"), old.str("code"), old.str("role")))
        assertEquals("Scan the new unit", r.v.title)
        r.scan("SN-OLD-7")
        assertEquals("That is the old unit. Scan the new one.", r.v.message)
        r.scan("SN-NEW-8")
        assertEquals("new", r.transport.last("/confirmations").str("role"))
        assertEquals("Confirm the swap", r.v.title)
        assertEquals(listOf(Detail("Remove", "sn-old-7"), Detail("Install", "SN-NEW-8"), Detail("Position", "Sector B · slot 2")), r.v.detail)
        r.primary(); r.primary()
        assertEquals(StepKind.WAITING, r.v.kind)
        r.runner.onLiveEvent("erp.posted", mapOf("task_id" to "t-sw", "doc_number" to "TWR0000301"))
        assertEquals("Swap recorded", r.v.title)
        assertEquals("Check out of the site", r.v.secondary)
        r.runner.act(JobAction.Secondary)
        assertEquals("PATCH /v1/visits/visit-9", r.transport.paths().last())
        assertTrue(r.v.finished)
        assertEquals("Checked out. You can leave the site.", r.v.exitNote)
    }

    @Test
    fun swap_withoutAVisitChecksInFirst() {
        val r = Rig(Tasks.swap)
        assertEquals(StepKind.CHECKIN, r.v.kind)
        assertEquals(5, r.v.stepCount)
    }

    // --- practice ------------------------------------------------------------------------------

    @Test
    fun practice_runsTheReceiveJobLocallyWithTheBannerOnEveryStep() = runBlocking {
        val practice = PracticeTransport()
        val r = Rig(Practice.task, practice = true, transport = practice)
        val banners = mutableListOf<String?>()
        banners += r.v.banner
        r.primary(); banners += r.v.banner
        r.scan("SAMPLE-MAT-0001"); banners += r.v.banner
        r.act(JobAction.AllHere); banners += r.v.banner
        r.scan("SAMPLE-MAT-0002"); r.act(JobAction.AllHere); banners += r.v.banner
        r.primary(); banners += r.v.banner
        r.primary(); banners += r.v.banner
        assertEquals(StepKind.DONE, r.v.kind)
        assertEquals("Practice finished", r.v.title)
        assertEquals("Practice", r.v.jobKind)
        assertEquals(listOf(JobRunner.PRACTICE_BANNER), banners.distinct())
        assertTrue(practice.sent.any { it.path.endsWith("/post-requests") })
        assertEquals("Practice finished. Nothing was sent to SAP.", r.speaker.said.last())
    }

    @Test
    fun scanStepsAreTheOnesThatTakeACode() = runBlocking {
        val r = Rig(Tasks.receive)
        assertFalse(r.runner.isScanStep)
        r.primary(); assertTrue(r.runner.isScanStep)
        r.scan("SAMPLE-MAT-0001"); assertFalse(r.runner.isScanStep)
    }

    private fun events(req: ApiRequest): List<Pair<String, Int>> =
        (req.body!!["events"] as JsonArray).map { e ->
            val o = e as JsonObject
            (o["type"] as JsonPrimitive).content to (o["device_seq"] as JsonPrimitive).int
        }
}
