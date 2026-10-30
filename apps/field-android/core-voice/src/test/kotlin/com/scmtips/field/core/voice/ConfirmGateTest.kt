package com.scmtips.field.core.voice

import com.scmtips.field.core.voice.grammar.VoiceGrammarParser
import com.scmtips.field.core.voice.grammar.VoiceIntent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/** ConfirmGate against FR2.033 (confirm within 10 s), FR2.032 (inert below floor) and FR2.037 (BR2.18). */
class ConfirmGateTest {
    private val parser = VoiceGrammarParser()
    private val sent = mutableListOf<StagedPostingRequest>()
    private val gate = ConfirmGate(onPostingDispatched = { sent += it })

    private fun say(phrase: String, conf: Float, t: Long) = gate.handleUtterance(parser.parse(phrase, conf), "T-1", t)

    @Test
    fun tc2_031_postThenConfirmAt4sSendsExactlyOne() {
        say("count twelve", 0.95f, 0)
        val staged = say("post", 0.95f, 0)
        assertTrue(staged is ConfirmGateState.Staged)
        assertEquals("Post count 12? Say confirm or cancel.", (staged as ConfirmGateState.Staged).prompt)
        assertTrue(say("confirm", 0.95f, 4_000) is ConfirmGateState.Sent)
        assertEquals(1, sent.size)
        assertEquals(12.0, sent[0].quantity, 0.0)
        assertFalse(sent[0].isReversal)
        say("confirm", 0.95f, 4_500)
        assertEquals("a second confirm sends nothing", 1, sent.size)
    }

    @Test
    fun tc2_032_postNextConfirmSendsNothing() {
        say("count twelve", 0.95f, 0)
        say("post", 0.95f, 0)
        say("next", 0.95f, 1_000)
        say("confirm", 0.95f, 2_000)
        assertTrue(sent.isEmpty())
    }

    @Test
    fun tc2_026_confirmBelowFloorLeavesStageWaiting() {
        say("count twelve", 0.95f, 0)
        val staged = say("post", 0.95f, 0)
        assertEquals(staged, say("confirm", 0.799f, 1_000))
        assertTrue(sent.isEmpty())
        assertTrue("a later accepted confirm still sends", say("confirm", 0.85f, 2_000) is ConfirmGateState.Sent)
    }

    @Test
    fun tc2_025_countBelowFloorKeepsStagedCount() {
        say("count ten", 0.95f, 0)
        say("count twelve", 0.79f, 1_000)
        assertEquals(10.0, gate.getStagedCount()!!, 0.0)
    }

    @Test
    fun tc2_130_timeoutClearsStageWithMsg2_22AndSendsNothing() {
        say("count twelve", 0.95f, 0)
        say("post", 0.95f, 0)
        val afterWindow = gate.tick(10_001)
        assertTrue(afterWindow is ConfirmGateState.Cancelled)
        assertEquals(ConfirmGate.MSG2_22, (afterWindow as ConfirmGateState.Cancelled).message)
        say("confirm", 0.95f, 10_002)
        assertTrue(sent.isEmpty())
    }

    @Test
    fun confirmAt10sIsInsideTheWindowAnd10_1sIsOutside() {
        say("count one", 0.95f, 0); say("post", 0.95f, 0)
        assertTrue(say("confirm", 0.95f, 10_000) is ConfirmGateState.Sent)
        say("count one", 0.95f, 20_000); say("post", 0.95f, 20_000)
        assertFalse(say("confirm", 0.95f, 30_100) is ConfirmGateState.Sent)
        assertEquals(1, sent.size)
    }

    @Test
    fun postWithNothingCountedStagesNothing() {
        assertTrue(say("post", 0.95f, 0) is ConfirmGateState.Cancelled)
        say("confirm", 0.95f, 1_000)
        assertTrue(sent.isEmpty())
    }

    @Test
    fun tc2_133_undoBeforePostRemovesLineAndUndoAfterPostStagesOneReversal() {
        say("count twelve", 0.95f, 0)
        say("undo", 0.95f, 500)
        assertNull(gate.getStagedCount())
        assertTrue(say("post", 0.95f, 600) is ConfirmGateState.Cancelled)

        say("count twelve", 0.95f, 1_000); say("post", 0.95f, 1_000); say("confirm", 0.95f, 2_000)
        val reversal = say("undo", 0.95f, 3_000)
        assertTrue(reversal is ConfirmGateState.Staged)
        assertTrue((reversal as ConfirmGateState.Staged).request.isReversal)
        say("confirm", 0.95f, 4_000)
        assertEquals(2, sent.size)
        assertTrue(sent[1].isReversal)
        assertEquals(sent[0].quantity, sent[1].quantity, 0.0)
        say("undo", 0.95f, 5_000)
        say("confirm", 0.95f, 6_000)
        assertEquals("a reversal is never reversed again by undo", 2, sent.size)
    }

    @Test
    fun tc2_134_wrongOneSupersedesAndConditionToggles() {
        gate.onCaptureCommitted("C-1")
        say("mark damaged", 0.95f, 0)
        assertTrue(gate.isDamaged())
        say("condition good", 0.95f, 100)
        assertFalse(gate.isDamaged())
        say("count three", 0.95f, 200)
        say("wrong one", 0.95f, 300)
        assertFalse(gate.isLastCaptureActive())
        assertNull(gate.getStagedCount())
        gate.onCaptureCommitted("C-2")
        assertTrue(gate.isLastCaptureActive())
        say("mark damaged", 0.95f, 400); say("count two", 0.95f, 500); say("post", 0.95f, 500); say("confirm", 0.95f, 600)
        assertTrue(sent.single().isDamaged)
        assertEquals("C-2", sent.single().captureId)
    }

    /**
     * Seeded random sequences checked against an independent model of FR2.033: a post request is sent
     * only when an accepted post is followed by an accepted confirm within 10 s with no other accepted
     * intent in between, and below-floor utterances change nothing.
     */
    @Test
    fun randomSequencesMatchTheConfirmModel() {
        val phrases = listOf("count twelve", "post", "confirm", "cancel", "next", "left", "undo", "repeat", "hello")
        val rnd = Random(2026_11_09)
        repeat(1_000) {
            val got = mutableListOf<StagedPostingRequest>()
            val g = ConfirmGate(onPostingDispatched = { got += it })
            var t = 0L
            var expected = 0
            var countKnown = false
            var stagedAt: Long? = null
            var stagedIsReversal = false
            var committed = false // a non-reversal post was sent and not yet reversed
            repeat(rnd.nextInt(1, 21)) {
                t += rnd.nextLong(0, 15_001)
                val phrase = phrases[rnd.nextInt(phrases.size)]
                val conf = if (rnd.nextBoolean()) 0.78f + rnd.nextFloat() * 0.04f else rnd.nextFloat()
                val u = parser.parse(phrase, conf)
                g.handleUtterance(u, "T", t)
                if (!u.isAccepted) return@repeat
                if (stagedAt != null && t - stagedAt!! > 10_000) stagedAt = null
                val wasStaged = stagedAt != null
                when (u.intent) {
                    VoiceIntent.COUNT -> { stagedAt = null; countKnown = true }
                    VoiceIntent.POST -> { stagedAt = if (countKnown) t else null; stagedIsReversal = false }
                    VoiceIntent.CONFIRM -> if (wasStaged) {
                        expected++
                        stagedAt = null
                        countKnown = false
                        committed = !stagedIsReversal
                    }
                    VoiceIntent.UNDO -> {
                        stagedAt = null
                        if (countKnown) countKnown = false
                        else if (committed && !wasStaged) { stagedAt = t; stagedIsReversal = true }
                    }
                    else -> stagedAt = null
                }
            }
            assertEquals(expected, got.size)
        }
    }
}
