package com.scmtips.field.app.session

import com.scmtips.field.app.jobs.RecordingSpeaker
import com.scmtips.field.app.jobs.Speaker
import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The work session's pause/resume rules, the microphone choice, recogniser restarts and queued speech. */
class WorkSessionTest {

    @Test
    fun listensOnlyInAnActiveUnpausedSessionAndNotWhileThePhoneSpeaks() {
        val changes = mutableListOf<SessionView>()
        val w = WorkSession { changes += it }
        assertFalse(w.view.listening)
        assertEquals(SessionChange.Started, w.start(MicSource.BLUETOOTH, glassesStarted = true))
        assertNull("a second start changes nothing", w.start(MicSource.PHONE, glassesStarted = true))
        assertTrue(w.view.listening)
        assertEquals("Listening · glasses over Bluetooth", w.view.stateText)
        w.speaking(true)
        assertFalse("no self-hearing", w.view.listening)
        w.speaking(false)
        assertTrue(w.view.listening)
        w.mic(MicSource.NONE)
        assertFalse(w.view.listening)
        assertEquals(SessionChange.Stopped, w.stop())
        assertFalse(w.view.active)
        assertTrue(changes.isNotEmpty())
    }

    @Test
    fun glassesPauseAndResumeTheSession() {
        val w = WorkSession()
        w.start(MicSource.GLASSES, glassesStarted = true)
        assertEquals(SessionChange.Paused(PauseReason.GLASSES_PAUSED), w.onGlasses("PAUSED"))
        assertFalse(w.view.listening)
        assertEquals("Paused · glasses paused (tap or taken off)", w.view.stateText)
        assertEquals(SessionChange.Resumed, w.onGlasses("STARTED"))
        assertTrue(w.view.listening)
        assertEquals(SessionChange.Paused(PauseReason.GLASSES_GONE), w.onGlasses("STOPPED"))
        assertNull("already paused", w.onGlasses("IDLE"))
        assertEquals(SessionChange.Resumed, w.onGlasses("STARTED"))
    }

    @Test
    fun aPhoneOnlySessionIsNotPausedByGlassesItNeverHad() {
        val w = WorkSession()
        w.start(MicSource.PHONE, glassesStarted = false)
        assertNull(w.onGlasses("none"))
        assertNull(w.onGlasses("STOPPED"))
        assertTrue(w.view.listening)
        w.onGlasses("STARTED") // glasses joined later: from now on their loss pauses
        assertEquals(SessionChange.Paused(PauseReason.GLASSES_GONE), w.onGlasses("STOPPED"))
    }

    @Test
    fun theOperatorsPauseIsLiftedOnlyByTheOperator() {
        val w = WorkSession()
        w.start(MicSource.GLASSES, glassesStarted = true)
        assertEquals(SessionChange.Paused(PauseReason.OPERATOR), w.pauseByOperator())
        assertNull("the glasses do not undo the operator's pause", w.onGlasses("STARTED"))
        assertEquals(PauseReason.OPERATOR, w.view.paused)
        assertEquals(SessionChange.Resumed, w.resumeByOperator())
        assertNull(w.resumeByOperator())
    }

    @Test
    fun glassesConnectingOutsideASessionOfferIt() {
        val w = WorkSession()
        assertNull(w.onGlasses("STARTED"))
        assertTrue(w.view.offer)
        w.start(MicSource.GLASSES, glassesStarted = true)
        assertFalse(w.view.offer)
        w.stop()
        w.onGlasses("STOPPED")
        assertFalse(w.view.offer)
    }

    @Test
    fun wordsAndListenModeAreKeptOnlyDuringASession() {
        val w = WorkSession()
        w.heard("hello"); w.listenMode("free")
        assertNull(w.view.heard); assertEquals("command", w.view.listenMode)
        w.start(MicSource.PHONE, glassesStarted = false)
        w.heard("start receive"); w.said("Starting.", "Delivery" to "2 items"); w.listenMode("free"); w.assistant(false)
        assertEquals("start receive", w.view.heard)
        assertEquals("Delivery" to "2 items", w.view.card)
        assertEquals("free", w.view.listenMode)
        assertEquals(false, w.view.assistantOnline)
        w.stop()
        assertNull(w.view.heard); assertNull(w.view.said); assertEquals("command", w.view.listenMode)
    }

    @Test
    fun glassesSpeechIsUsedOnlyWhenOnAndAcceptedByTheToolkit() {
        assertTrue(MicPlan.useGlassesSpeech(true, "ready"))
        assertTrue(MicPlan.useGlassesSpeech(true, "STARTED"))
        assertFalse("operator turned it off", MicPlan.useGlassesSpeech(false, "STARTED"))
        assertFalse(MicPlan.useGlassesSpeech(true, "refused: not approved"))
        assertFalse(MicPlan.useGlassesSpeech(true, "unavailable: no capability"))
        assertFalse(MicPlan.useGlassesSpeech(true, "error: stream"))
        assertFalse("not connected", MicPlan.useGlassesSpeech(true, "off"))
    }

    @Test
    fun recogniserRestartsAtOnceAfterSilenceAndBacksOffOnErrors() {
        val b = RestartBackoff(quickMs = 250, firstMs = 1_000, maxMs = 15_000)
        assertEquals(250L, b.afterResult())
        assertEquals(250L, b.afterError(RestartBackoff.ERROR_NO_MATCH))
        assertEquals(250L, b.afterError(RestartBackoff.ERROR_SPEECH_TIMEOUT))
        assertEquals(listOf(1_000L, 2_000L, 4_000L, 8_000L, 15_000L, 15_000L), (1..6).map { b.afterError(2) })
        assertEquals(1_000L, b.afterError(RestartBackoff.ERROR_RECOGNIZER_BUSY))
        b.afterResult()
        assertEquals("a result resets the backoff", 1_000L, b.afterError(3))
        assertNull("no microphone permission: stop", b.afterError(RestartBackoff.ERROR_INSUFFICIENT_PERMISSIONS))
    }

    @Test
    fun whileHoldingTheRunnersWordsQueueBehindTheAssistantsInsteadOfCuttingThemOff() = runBlocking {
        val out = object : Speaker {
            val log = mutableListOf<String>()
            override fun say(text: String) { log += "say:$text" }
            override fun queue(text: String) { log += "queue:$text" }
            override fun earcon(cue: EarconCue) { log += "earcon:$cue" }
        }
        val s = TurnSpeaker(out)
        s.say("Starting the delivery.")
        s.holding { s.say("Delivery 1800. Look at a box."); s.earcon(EarconCue.READY) }
        s.say("")
        s.say("Next.")
        assertEquals(listOf("say:Starting the delivery.", "queue:Delivery 1800. Look at a box.", "earcon:READY", "say:Next."), out.log)
        val rec = RecordingSpeaker()
        TurnSpeaker(rec).queue("x")
        assertEquals("the default queue speaks", listOf("x"), rec.said)
    }
}
