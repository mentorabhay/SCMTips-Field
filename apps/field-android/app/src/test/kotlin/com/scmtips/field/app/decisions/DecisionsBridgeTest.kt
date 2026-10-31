package com.scmtips.field.app.decisions

import com.scmtips.field.app.jobs.RecordingSpeaker
import com.scmtips.field.feature.decisions.flow.CardButton
import com.scmtips.field.feature.decisions.flow.DecisionCard
import com.scmtips.field.feature.decisions.flow.FlowState
import com.scmtips.field.feature.decisions.flow.Outcome
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The app side of the approver flow: speech that waits for the TTS, the phone card, the words shown. */
class DecisionsBridgeTest {
    @Test
    fun speakingWaitsUntilTheTtsHasSaidIt_soTheFlowListensOnlyAfterwards() = runBlocking {
        val out = RecordingSpeaker()
        val tts = TtsSignals()
        val voice = SpeechWaiter(out, tts, estimateMs = { 5_000 }, settleMs = 10)
        val spoken = async { voice.playSpeech("Supplier A is six days late.", flushQueue = false); "done" }
        withTimeout(5_000) { while (out.said.isEmpty()) yield() }
        assertEquals(listOf("Supplier A is six days late."), out.said)
        assertFalse(spoken.isCompleted)
        tts.onSpeaking(true)
        yield()
        assertFalse(spoken.isCompleted)
        tts.onSpeaking(false)
        assertEquals("done", withTimeout(5_000) { spoken.await() })
    }

    @Test
    fun aTtsThatNeverReportsIsWaitedForOnlyAShortWhile() = runBlocking {
        val voice = SpeechWaiter(RecordingSpeaker(), TtsSignals(), estimateMs = { 30 }, settleMs = 10)
        withTimeout(5_000) { voice.playSpeech("anything", flushQueue = false) }
        voice.playSpeech("   ", flushQueue = false) // blank: nothing said, nothing waited for
    }

    @Test
    fun thePhoneCardIsShownUnlessAudioOnly_andOnlyItsOwnButtonsCount() = runBlocking {
        var audioOnly = false
        val d = PhoneCardDisplay { !audioOnly }
        val pressed = mutableListOf<String>()
        val card = DecisionCard("Late inbound", "Supplier A is late.", listOf(CardButton("approve:A", "Approve A", true), CardButton("reject", "Reject")))
        assertTrue(d.show(card) { pressed += it })
        assertEquals(card, d.card.value)
        assertTrue(d.press("approve:A"))
        assertFalse(d.press("confirm"))
        d.clear()
        assertNull(d.card.value)
        assertFalse(d.press("reject"))
        assertEquals(listOf("approve:A"), pressed)
        audioOnly = true
        assertFalse(d.show(card) { pressed += it })
        assertNull(d.card.value)
    }

    @Test
    fun theWorkSessionAnnouncesWaitingDecisions_andTheScreenNamesEachState() {
        assertEquals("1 decision is waiting for you. Say decisions to hear it.", DecisionText.waiting(1))
        assertEquals("3 decisions are waiting for you. Say decisions to hear the first.", DecisionText.waiting(3))
        assertNull(DecisionText.waiting(0))
        assertEquals("1 decision waiting", DecisionText.chip(1))
        assertEquals("Nothing waiting for your approval", DecisionText.chip(0))
        assertEquals("Committed", DecisionText.state(FlowState.Finished(Outcome.EXECUTED, "Approved.")))
        assertEquals("Speaking the brief (SCMTIPS template)", DecisionText.state(FlowState.Presenting("t", false, "template")))
        assertTrue(DecisionText.state(FlowState.Listening).startsWith("Listening"))
    }
}
