package com.scmtips.field.feature.decisions.flow

import com.scmtips.field.feature.decisions.api.StepUpMethod
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UtteranceInboxTest {
    @Test
    fun wordsHeardWhileListeningAreTaken_andWordsHeardBeforeAreDropped() = runBlocking {
        val inbox = UtteranceInbox { 5_000 }
        assertTrue(inbox.offer("said during the brief", 0.9f))
        val heard = async { inbox.listen() }
        withTimeout(5_000) { while (!inbox.waiting.value) yield() }
        inbox.offer("  approve option two ", 0.88f)
        val c = heard.await()!!
        assertEquals("approve option two", c.transcript)
        assertEquals(0.88f, c.confidence)
        assertFalse(inbox.waiting.value)
    }

    @Test
    fun nothingHeardInTime_isNull_andBlankWordsAreRefused() = runBlocking {
        val inbox = UtteranceInbox { 50 }
        assertFalse(inbox.offer("   ", 0.9f))
        assertNull(inbox.listen())
    }

    @Test
    fun stepUpBroker_handsTheRequestToTheScreen_andTheAnswerBack() = runBlocking {
        var requested = 0
        val broker = StepUpBroker { requested++ }
        val answer = async { broker.requestCode("That code was not accepted. Try again.") }
        withTimeout(5_000) { while (broker.pending.value == null) yield() }
        val p = broker.pending.value!!
        assertEquals("That code was not accepted. Try again.", p.retryMessage)
        broker.answer(p, StepUpEntry(StepUpMethod.TOTP, "123456"))
        broker.answer(p, null) // a second answer is ignored
        assertEquals(StepUpEntry(StepUpMethod.TOTP, "123456"), answer.await())
        assertNull(broker.pending.value)
        assertEquals(1, requested)
        assertFalse(StepUpEntry(StepUpMethod.TOTP, "123456").toString().contains("123456"))
    }
}
