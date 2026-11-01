package com.scmtips.field.app.ui.kit

import com.scmtips.field.app.check.AuthenticityCheck
import com.scmtips.field.app.check.CheckState
import com.scmtips.field.app.check.FirstCheckSignal
import com.scmtips.field.app.check.RegistrySignal
import com.scmtips.field.app.check.SealSignal
import com.scmtips.field.app.check.UnitEvent
import com.scmtips.field.app.check.Verdict
import com.scmtips.field.app.check.VisualSignal
import com.scmtips.field.app.decisions.DecisionText
import com.scmtips.field.app.jobs.JobAction
import com.scmtips.field.app.jobs.JobGrammar
import com.scmtips.field.app.jobs.LookFill
import com.scmtips.field.app.jobs.Rig
import com.scmtips.field.app.jobs.StepKind
import com.scmtips.field.app.jobs.StepView
import com.scmtips.field.app.jobs.Tasks
import com.scmtips.field.app.look.Look
import com.scmtips.field.app.look.LookCounts
import com.scmtips.field.app.look.Proposal
import com.scmtips.field.feature.decisions.api.ItemOption
import com.scmtips.field.feature.decisions.api.NextItem
import com.scmtips.field.feature.decisions.flow.CardFormatter
import com.scmtips.field.feature.decisions.flow.FlowState
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * M5-U04: the pure rules of the redesigned task screens, driven by the real [com.scmtips.field.app.jobs.JobRunner]
 * (so the step numbering follows what the runner really shows) and by the real decision and check models.
 */
class TaskModelTest {

    private data class Seen(val kind: StepKind, val segment: Int, val name: String, val hint: Hint?)

    private fun seen(v: StepView): Seen = TaskSteps.of(v).let { Seen(v.kind, it.segment, it.segmentName, it.hint) }

    @Test
    fun m5U04_receiveSteps_lookCheckConfirm_withTheirHints() = runBlocking {
        val r = Rig(Tasks.receive)
        val out = mutableListOf<Seen>()
        fun note() { out += seen(r.v); assertEquals(3, TaskSteps.of(r.v).segments) }
        note() // intro
        r.primary(); note() // scan a box
        r.scan("SAMPLE-MAT-0001"); note() // count
        r.act(JobAction.AllHere); note() // scan next
        r.scan("SAMPLE-MAT-0002"); note()
        r.primary(); note() // review
        r.primary(); note() // confirm (touch)
        r.primary(); note() // waiting
        r.runner.onLiveEvent("erp.posted", mapOf("task_id" to "t-rcv", "doc_number" to "4900000101")); note()
        assertEquals(
            listOf(
                Seen(StepKind.INFO, 1, "Look", Hint.LOOK),
                Seen(StepKind.SCAN, 1, "Look", Hint.LOOK),
                Seen(StepKind.COUNT, 2, "Check", Hint.SAY_NUMBERS),
                Seen(StepKind.SCAN, 1, "Look", Hint.LOOK),
                Seen(StepKind.COUNT, 2, "Check", Hint.SAY_NUMBERS),
                Seen(StepKind.REVIEW, 2, "Check", null),
                Seen(StepKind.CONFIRM, 3, "Confirm", Hint.CONFIRM),
                Seen(StepKind.WAITING, 3, "Confirm", null),
                Seen(StepKind.DONE, 3, "Confirm", null),
            ),
            out,
        )
        assertEquals("Step 3 of 3 · Confirm", TaskSteps.of(r.v).subtitle)
        assertEquals(Backdrop.GROUND, TaskSteps.backdropFor(r.v))
    }

    @Test
    fun m5U04_practiceHasNoLookHint_andWarehouseScansGetTheBinThenProductHint() = runBlocking {
        val practice = Rig(Tasks.receive, practice = true)
        practice.primary()
        assertEquals(StepKind.SCAN, practice.v.kind)
        assertEquals("Practice", practice.v.jobKind)
        assertNull(TaskSteps.hintFor(practice.v))
        assertEquals("Scan", TaskSteps.of(practice.v).segmentName)

        val pa = Rig(Tasks.putaway)
        val out = mutableListOf<Seen>()
        out += seen(pa.v) // scan pallet
        pa.scan("SAMPLE-MAT-0002"); out += seen(pa.v) // take it to this bin
        pa.primary(); out += seen(pa.v) // scan the bin
        pa.scan("02-03-04"); out += seen(pa.v) // stored
        pa.primary(); out += seen(pa.v) // scan pallet again
        pa.scan("SAMPLE-MAT-0001"); pa.scan("03-05-02"); pa.primary(); out += seen(pa.v) // review
        assertEquals(
            listOf(
                Seen(StepKind.SCAN, 1, "Scan", Hint.SCAN_BIN_PRODUCT),
                Seen(StepKind.INFO, 2, "Store", null),
                Seen(StepKind.SCAN, 2, "Store", Hint.SCAN_BIN_PRODUCT),
                Seen(StepKind.INFO, 2, "Store", null),
                Seen(StepKind.SCAN, 1, "Scan", Hint.SCAN_BIN_PRODUCT),
                Seen(StepKind.REVIEW, 3, "Finish", null),
            ),
            out,
        )

        val pk = Rig(Tasks.pick)
        assertEquals(Seen(StepKind.INFO, 1, "Go", null), seen(pk.v))
        pk.primary(); assertEquals(Seen(StepKind.SCAN, 2, "Pick", Hint.SCAN_BIN_PRODUCT), seen(pk.v))
        pk.scan("SAMPLE-MAT-0003"); assertEquals(Seen(StepKind.COUNT, 2, "Pick", null), seen(pk.v))

        val ct = Rig(Tasks.count)
        assertEquals(Seen(StepKind.INFO, 1, "Go", null), seen(ct.v))
        ct.scan("03-05-02"); assertEquals(Seen(StepKind.SCAN, 2, "Count", Hint.SCAN_BIN_PRODUCT), seen(ct.v))
        ct.scan("SAMPLE-MAT-0001"); assertEquals(Seen(StepKind.COUNT, 2, "Count", null), seen(ct.v))
        ct.act(JobAction.SetQty(48)); ct.primary(); assertEquals(Seen(StepKind.REVIEW, 3, "Send", null), seen(ct.v))
    }

    @Test
    fun m5U04_siteVisit_safetySlotsFinish_clipInOnlyOnTheClimbUp() = runBlocking {
        for (visit in listOf<String?>(null, "v-1")) {
            val r = Rig(Tasks.audit, visitId = visit)
            if (visit == null) {
                assertEquals(Seen(StepKind.CHECKIN, 1, "Safety", null), seen(r.v))
                r.act(JobAction.Permit("PTW-2041"), JobAction.Location(28.61, 77.20, 12.0, r.now))
                r.primary()
            }
            assertEquals(Seen(StepKind.CHECK, 1, "Safety", null), seen(r.v))
            r.act(JobAction.ToggleCheck(0), JobAction.ToggleCheck(1), JobAction.ToggleCheck(2))
            r.primary()
            assertEquals(Seen(StepKind.CLIMB, 1, "Safety", Hint.CLIP_IN), seen(r.v))
            assertEquals("Say “harness clipped”", TaskSteps.voiceFor(r.v, null))
            assertEquals(Backdrop.NIGHT, TaskSteps.backdropFor(r.v))
            r.say("harness clipped"); r.now += 2_000; r.primary()
            assertEquals(Seen(StepKind.SCAN, 2, "Slots", null), seen(r.v))
            r.scan("SN-1001"); r.scan("SN-1002"); r.scan("SN-1003")
            assertEquals(Seen(StepKind.REVIEW, 3, "Finish", null), seen(r.v))
            r.transport.postStatus = "completed"
            r.primary(); r.primary()
            assertEquals("Climb down safely", r.v.title)
            assertEquals(Seen(StepKind.CLIMB, 3, "Finish", null), seen(r.v))
            assertEquals("Say “clipped” at each platform", TaskSteps.voiceFor(r.v, null))
        }
    }

    @Test
    fun m5U04_theConfirmStepPlaysTheRing_andItsVoiceChipOnlyWhileListening() = runBlocking {
        val r = Rig(Tasks.receive)
        r.primary(); r.scan("SAMPLE-MAT-0001"); r.say("all here"); r.scan("SAMPLE-MAT-0002"); r.say("all here")
        assertEquals(StepKind.REVIEW, r.v.kind)
        assertEquals("Say “post”", TaskSteps.voiceFor(r.v, null))
        r.say("post")
        assertTrue(r.v.listening)
        assertEquals(Hint.CONFIRM, TaskSteps.hintFor(r.v))
        assertEquals("Say “yes” or “cancel”", TaskSteps.voiceFor(r.v, null))
        r.say("cancel"); r.primary()
        assertEquals(StepKind.CONFIRM, r.v.kind)
        assertFalse(r.v.listening)
        assertNull("a touch confirm has no deadline, so no voice chip", TaskSteps.voiceFor(r.v, null))
    }

    @Test
    fun m5U04_everyVoiceChipPhraseIsOneTheJobGrammarUnderstands() = runBlocking {
        val r = Rig(Tasks.receive)
        val look = look(say = "8 packs.", proposal = Proposal(7, 1, emptyList()))
        val chips = mutableListOf<String?>()
        chips += TaskSteps.voiceFor(r.v, null)
        r.primary(); r.scan("SAMPLE-MAT-0001")
        chips += TaskSteps.voiceFor(r.v, look)
        chips += TaskSteps.voiceFor(r.v, null)
        r.runner.applyLook(LookFill("look-1", null, "l10", 7, 1, "Say receive 7, flag 1."))
        chips += TaskSteps.voiceFor(r.v, look)
        val phrases = chips.filterNotNull().flatMap { c -> Regex("“([^”]+)”").findAll(c).map { it.groupValues[1] }.toList() } +
            listOf("yes", "cancel", "post", "harness clipped", "clipped")
        assertTrue(phrases.contains("look")); assertTrue(phrases.contains("receive 7, flag 1")); assertTrue(phrases.contains("all here"))
        phrases.forEach { assertNotNull("“$it” must parse", JobGrammar.parse(it, 0.95f)) }
        assertEquals("Say “receive 7, flag 1”", TaskSteps.voiceFor(r.v, look))
        assertEquals("Say “receive 7”", TaskSteps.voiceFor(r.v, look(say = "", proposal = Proposal(7, 0, emptyList()))))
    }

    @Test
    fun m5U04_aHintPlaysByItselfOnlyTheFirstTimeItsTaskTypeAndStepOpen() {
        val store = MemoryHintStore()
        val m = HintMemory(store)
        val key = TaskSteps.hintKey("Receive", 1, Hint.LOOK)
        assertEquals("Receive|1|LOOK", key)
        assertTrue(m.autoShow(key))
        assertFalse(m.autoShow(key))
        assertTrue("another task type is a new step", m.autoShow(TaskSteps.hintKey("Pick", 2, Hint.SCAN_BIN_PRODUCT)))
        assertTrue("another step of the same type too", m.autoShow(TaskSteps.hintKey("Receive", 2, Hint.SAY_NUMBERS)))
        assertFalse(m.autoShow(null))
        assertEquals(3, store.load().size)
        assertFalse("remembered across app starts (the store)", HintMemory(store).autoShow(key))
        assertTrue(HintMemory(store).seen(key))
    }

    @Test
    fun m5U04_ringProgressFollowsTheTenSecondConfirmWindow() {
        val t0 = 1_000_000L
        assertEquals(10_000L, ConfirmRingMath.WINDOW_MS)
        assertEquals(1f, ConfirmRingMath.progress(t0, t0), 0f)
        assertEquals(10, ConfirmRingMath.secondsLeft(t0, t0))
        assertEquals(0.75f, ConfirmRingMath.progress(t0, t0 + 2_500), 1e-6f)
        assertEquals(8, ConfirmRingMath.secondsLeft(t0, t0 + 2_500))
        assertEquals(1, ConfirmRingMath.secondsLeft(t0, t0 + 9_999))
        assertEquals(0, ConfirmRingMath.secondsLeft(t0, t0 + 10_000))
        assertEquals(0f, ConfirmRingMath.progress(t0, t0 + 25_000), 0f)
        assertEquals("a clock that goes back never overfills", 1f, ConfirmRingMath.progress(t0, t0 - 500), 0f)
        assertFalse(ConfirmRingMath.urgent(4)); assertTrue(ConfirmRingMath.urgent(3)); assertTrue(ConfirmRingMath.urgent(0))
        assertEquals(0f, ConfirmRingMath.progress(t0, t0, windowMs = 0), 0f)
    }

    @Test
    fun m5U04_verdictColoursAndTheFourSignals() {
        assertEquals(VerdictLook("Genuine and new", 0xFF157A3C, 0xFFE6F4EA, VerdictIcon.TICK), VerdictStyle.of(Verdict.GENUINE_NEW))
        listOf(Verdict.GENUINE_PREVIOUSLY_ACTIVATED, Verdict.RETURNED_REFURBISHED).forEach {
            assertEquals(0xFFA15C07, VerdictStyle.of(it).ink); assertEquals(VerdictIcon.WARN, VerdictStyle.of(it).icon)
        }
        assertEquals(VerdictIcon.CROSS, VerdictStyle.of(Verdict.LIKELY_COUNTERFEIT).icon)
        assertEquals(0xFFB3261E, VerdictStyle.of(Verdict.LIKELY_COUNTERFEIT).ink)
        assertEquals(0xFF4B5160, VerdictStyle.of(Verdict.CANNOT_VERIFY).ink)
        assertEquals("an unknown verdict is grey, never green", 0xFF4B5160, VerdictStyle.of(Verdict.UNKNOWN).ink)

        val returned = check(
            Verdict.RETURNED_REFURBISHED, tamper = false, codeStatus = "valid", firstStatus = "first",
            events = listOf("manufactured", "activated", "returned"), visualStatus = "done",
        )
        val rows = VerdictStyle.signals(returned, visualPending = false)
        assertEquals(listOf("Signed code", "History", "First check", "Seal"), rows.map { it.name })
        assertEquals(listOf(SignalTone.GOOD, SignalTone.AMBER, SignalTone.GOOD, SignalTone.GOOD), rows.map { it.tone })
        assertEquals("Signed by the maker: Kestrel Optics (SAMPLE) · Serial SN-1 · SKU-1", rows[0].value)
        assertEquals("Made, Activated, Returned", rows[1].value)
        assertEquals("Seal looks intact", rows[3].value)

        val fake = check(Verdict.LIKELY_COUNTERFEIT, tamper = null, codeStatus = "bad_signature", firstStatus = null,
            events = emptyList(), registryStatus = "not_asked", visualStatus = null)
        assertEquals(listOf(SignalTone.BAD, SignalTone.GREY, SignalTone.GREY, SignalTone.GREY),
            VerdictStyle.signals(fake, false).map { it.tone })
        assertEquals("History: not asked (the code did not verify)", VerdictStyle.signals(fake, false)[1].value)

        val copied = check(Verdict.CANNOT_VERIFY, tamper = true, codeStatus = "valid", firstStatus = "other_checker",
            events = listOf("manufactured"), visualStatus = "done")
        assertEquals(listOf(SignalTone.GOOD, SignalTone.GOOD, SignalTone.AMBER, SignalTone.AMBER),
            VerdictStyle.signals(copied, false).map { it.tone })
        val pending = VerdictStyle.signals(copied, visualPending = true)[3]
        assertEquals(SignalRow("Seal", "Checking the seal…", SignalTone.GREY), pending)
    }

    @Test
    fun m5U04_theBoxCheckHint_isTheSealCode_untilAVerdictIsUp() {
        assertEquals(Hint.SEAL_CODE, TaskSteps.checkHint(CheckState.CAPTURING, hasVerdict = false))
        assertEquals(Hint.SEAL_CODE, TaskSteps.checkHint(CheckState.NO_CODE, hasVerdict = false))
        assertNull(TaskSteps.checkHint(CheckState.CHECKING, hasVerdict = false))
        assertNull(TaskSteps.checkHint(CheckState.SHOWN, hasVerdict = true))
        assertNull(TaskSteps.checkHint(CheckState.NO_CODE, hasVerdict = true))
    }

    @Test
    fun m5U04_decisionDetail_optionsApproveRejectAndTheBriefWaveform() {
        val item = NextItem("d-1", "Magnet export curbs", "Choose the response.", "Brief.",
            options = listOf(ItemOption("1", "o1", "Option 1"), ItemOption("2", "o2", "Option 2"), ItemOption("3", "o3", "Option 3")))
        val card = CardFormatter.decisionCard(item)
        assertEquals(listOf("1", "2", "3"), DecisionLayout.options(card).map { it.letter })
        assertEquals("approve:2", DecisionLayout.options(card)[1].buttonId)
        assertEquals("the card's primary is the default pick", "1", DecisionLayout.picked(card, null)?.letter)
        assertEquals("3", DecisionLayout.picked(card, "3")?.letter)
        assertEquals("a tap on an option no longer on the card falls back", "1", DecisionLayout.picked(card, "9")?.letter)
        assertFalse(DecisionLayout.confirmStage(card))
        assertTrue(DecisionLayout.others(card).isEmpty())

        val confirm = CardFormatter.confirmCard("Magnet export curbs", "Approve option 1. Say confirm.")
        assertTrue(DecisionLayout.confirmStage(confirm))
        assertTrue(DecisionLayout.options(confirm).isEmpty())
        assertNull(DecisionLayout.picked(confirm, null))

        assertTrue(DecisionLayout.briefPlaying(DecisionText.state(FlowState.Presenting("t", true, "model"))))
        assertTrue(DecisionLayout.briefPlaying(DecisionText.state(FlowState.Presenting("t", true, "template"))))
        assertFalse(DecisionLayout.briefPlaying(DecisionText.state(FlowState.Listening)))
        assertFalse(DecisionLayout.briefPlaying(""))
    }

    @Test
    fun m5U04_lookAnswers_firstThenReadingThenSecond() {
        assertEquals(LookAnswers(null, null, false), LookAnswerRules.of(null, false, null))
        val first = look(say = "8 packs. Reading the labels.", final = false)
        assertEquals(LookAnswers("8 packs. Reading the labels.", null, true), LookAnswerRules.of(first, true, null))
        val final = look(say = "8 packs. Reading the labels.", sayNext = "Pack 7 is damaged. Receive 7, flag 1?")
        assertEquals(LookAnswers("8 packs. Reading the labels.", "Pack 7 is damaged. Receive 7, flag 1?", false),
            LookAnswerRules.of(final, false, "8 packs. Reading the labels."))
        val replaced = look(say = "Pack 7 is damaged. Receive 7, flag 1?")
        assertEquals(LookAnswers("8 packs. Reading the labels.", "Pack 7 is damaged. Receive 7, flag 1?", false),
            LookAnswerRules.of(replaced, false, "8 packs. Reading the labels."))
        assertEquals("a one-step look has one answer", LookAnswers("8 packs.", null, false), LookAnswerRules.of(look(say = "8 packs."), false, null))
    }

    // --- helpers -----------------------------------------------------------------------------

    private fun look(say: String, proposal: Proposal? = null, final: Boolean = true, sayNext: String? = null) =
        Look("look-1", "model", null, null, null, emptyList(), LookCounts(8, 8, 1, 7), 0, null, 0, emptyList(), proposal, say,
            emptyList(), emptyList(), final = final, sayNext = sayNext)

    private fun check(
        verdict: Verdict, tamper: Boolean?, codeStatus: String?, firstStatus: String?, events: List<String>,
        registryStatus: String = "found", visualStatus: String?,
    ) = AuthenticityCheck(
        checkId = "c-1", final = true, verdict = verdict, verdictWire = verdict.wire, tamper = tamper, reasons = emptyList(),
        code = codeStatus?.let { SealSignal(it, "kestrel", "Kestrel Optics (SAMPLE)", "k1", "SN-1", "SKU-1", null) },
        registry = RegistrySignal(registryStatus, "SKU-1", events.map { UnitEvent(it, null, null) }, null, null, null),
        firstCheck = firstStatus?.let { FirstCheckSignal(it, null, null) },
        visual = visualStatus?.let { VisualSignal(it, null, true, null, null, emptyList(), null, null) },
        say = "", sayNext = null, models = emptyList(), evidenceUrl = null, claimId = null, siteId = null, captureId = null,
        createdAt = null,
    )
}
