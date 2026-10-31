package com.scmtips.field.app.jobs

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M3 contract §2/§5 on the phone: task lines carry `barcodes`; product scans match the material OR a
 * barcode; an unknown code on a receive/count goes to the sandbox handler (refused when it says no);
 * refresh_task merges new lines without losing progress; assistant commands keep the confirm rule.
 */
class BarcodeSandboxTest {
    private fun withBarcodes(t: JobTask, vararg codes: Pair<String, List<String>>): JobTask =
        t.copy(lines = t.lines.map { l -> codes.firstOrNull { it.first == l.id }?.let { l.copy(barcodes = it.second) } ?: l })

    private class Handler(private val answer: Boolean) : UnknownCodeHandler {
        val seen = mutableListOf<Pair<String, String>>()
        override suspend fun take(task: JobTask, code: String): Boolean { seen += task.id to code; return answer }
    }

    private fun rig(task: JobTask, handler: UnknownCodeHandler?): Pair<JobRunner, RecordingTransport> {
        val tr = RecordingTransport()
        val r = JobRunner(task, tr, RecordingSpeaker(), "dev-1", newKey = { "k" }, unknownCodes = handler)
        r.start()
        return r to tr
    }

    @Test
    fun taskParserReadsLineBarcodes() {
        val body = Json.parseToJsonElement("""
            {"items": [{"id": "t", "type": "receive", "status": "open", "title": "Home receipt", "lines": [
              {"id": "l1", "line_no": 10, "material": "HOME-0001", "barcodes": ["8901234567890", " 4006381333931 ", "", null]},
              {"id": "l2", "line_no": 20, "material": "SAMPLE-MAT-0001"}]}]}
        """).jsonObject
        val lines = TaskParser.parseList(body).single().lines
        assertEquals(listOf("8901234567890", "4006381333931"), lines[0].barcodes)
        assertEquals("absent barcodes: empty, as for an older field-api", emptyList<String>(), lines[1].barcodes)
        assertTrue(lines[0].isProduct("8901234567890"))
        assertTrue(lines[0].isProduct("home-0001"))
        assertFalse(lines[1].isProduct("8901234567890"))
    }

    @Test
    fun receiveAndCountMatchABarcodeLikeTheMaterialNumber() = runBlocking {
        val (r, _) = rig(withBarcodes(Tasks.receive, "l20" to listOf("8901234567890")), null)
        r.act(JobAction.Primary)
        r.act(JobAction.Scanned("8901234567890"))
        assertEquals(StepKind.COUNT, r.view.value.kind)
        assertEquals("SAMPLE-MAT-0002", r.view.value.where)
        assertEquals("l20", r.state.lineId)

        val (c, _) = rig(withBarcodes(Tasks.count, "c1" to listOf("4006381333931")), null)
        c.act(JobAction.Primary)
        c.act(JobAction.Scanned("4006381333931"))
        assertEquals(StepKind.COUNT, c.view.value.kind)
    }

    @Test
    fun putawayAndPickMatchABarcodeAndThePickConfirmationSendsTheScannedCode() = runBlocking {
        val (p, _) = rig(withBarcodes(Tasks.putaway, "p2" to listOf("5000000000002")), null)
        p.act(JobAction.Scanned("5000000000002"))
        assertEquals("02-03-04", p.view.value.where)

        val (k, tr) = rig(withBarcodes(Tasks.pick, "k1" to listOf("7000000000001")), null)
        k.act(JobAction.Primary) // at the first stop
        k.act(JobAction.Scanned("02-01-01"))
        k.act(JobAction.Scanned("7000000000001"))
        assertEquals(StepKind.COUNT, k.view.value.kind)
        val product = tr.all("/confirmations").last()
        assertEquals("product", product.str("kind"))
        assertEquals("the server matches material OR barcode (contract §2)", "7000000000001", product.str("code"))
    }

    @Test
    fun anUnknownCodeOnASandboxSiteGoesToTheHandlerInsteadOfBeingRefused() = runBlocking {
        val h = Handler(answer = true)
        val (r, _) = rig(Tasks.receive, h)
        r.act(JobAction.Primary)
        r.act(JobAction.Scanned("8901234567890"))
        assertEquals(listOf("t-rcv" to "8901234567890"), h.seen)
        assertEquals("8901234567890 is new here. Tell the assistant what it is.", r.view.value.message)
        assertEquals(Tone.NEUTRAL, r.view.value.messageTone)
    }

    @Test
    fun anUnknownCodeOnAProductionSiteIsRefusedAsBefore() = runBlocking {
        val h = Handler(answer = false)
        val (r, _) = rig(Tasks.receive, h)
        r.act(JobAction.Primary)
        r.act(JobAction.Scanned("8901234567890"))
        assertEquals(1, h.seen.size)
        assertEquals("8901234567890 is not on this delivery.", r.view.value.message)
        assertEquals(Tone.BAD, r.view.value.messageTone)

        val (c, _) = rig(Tasks.count, Handler(answer = true))
        c.act(JobAction.Primary)
        c.act(JobAction.Scanned("03-05-02"))
        assertEquals("the count's own bin is not an unknown item", "That is the bin. Now scan a product in it.", c.view.value.message)
    }

    @Test
    fun refreshedLinesAreMergedProgressIsKeptAndTheFocusCodeSelectsTheNewLine() = runBlocking {
        val (r, tr) = rig(Tasks.count, Handler(answer = true))
        r.act(JobAction.Primary)
        r.act(JobAction.Scanned("SAMPLE-MAT-0001"))
        r.act(JobAction.SetQty(3))
        r.act(JobAction.Primary)
        assertEquals(StepKind.REVIEW, r.view.value.kind)

        val added = JobLine("c2", 20, "HOME-0001", "Tea", "EA", bin = "03-05-02", barcodes = listOf("8901234567890"))
        r.updateTask(Tasks.count.copy(lines = Tasks.count.lines + added), focusCode = "8901234567890")
        assertEquals(StepKind.COUNT, r.view.value.kind)
        assertEquals("HOME-0001", r.view.value.where)
        r.act(JobAction.SetQty(4))
        r.act(JobAction.Primary)
        assertEquals(StepKind.REVIEW, r.view.value.kind)
        assertEquals(listOf(Detail("Grade 1", "3"), Detail("Tea", "4")), r.view.value.detail)
        assertEquals(2, tr.all("/v1/count-records").size)

        r.updateTask(Tasks.receive, focusCode = null) // another task: ignored
        assertEquals("t-ct", r.task.id)
    }

    @Test
    fun spokenCommandsFromTheAssistantRunLikeTheGrammarButNeverConfirm() = runBlocking {
        val (r, tr) = rig(Tasks.count, null)
        r.act(JobAction.Primary)
        r.act(JobAction.Scanned("SAMPLE-MAT-0001"))
        r.act(JobAction.Spoken(Command.Number(5), "five of them", 0.9f))
        assertEquals(StepKind.REVIEW, r.view.value.kind)
        r.act(JobAction.Spoken(Command.Post, "send it", 0.9f))
        assertEquals(StepKind.CONFIRM, r.view.value.kind)
        r.act(JobAction.Spoken(Command.Yes, "yes", 1.0f))
        assertEquals(StepKind.CONFIRM, r.view.value.kind)
        assertTrue(tr.all("/post-requests").isEmpty())
        assertEquals("confirm", r.stepName)
        r.act(JobAction.Heard("yes", 0.95f))
        assertEquals(1, tr.all("/post-requests").size)
    }

    @Test
    fun theJobStateNamesTheStep() = runBlocking {
        val (r, _) = rig(Tasks.receive, null)
        assertEquals(JobState("t-rcv", null, "intro"), r.state)
        r.act(JobAction.Primary)
        assertEquals("line.scan", r.stepName)
        r.act(JobAction.Scanned("SAMPLE-MAT-0001"))
        assertEquals(JobState("t-rcv", "l10", "line.count"), r.state)
        assertFalse(r.isDone)
    }
}
