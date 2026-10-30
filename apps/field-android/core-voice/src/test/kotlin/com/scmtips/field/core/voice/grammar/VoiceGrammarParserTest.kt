package com.scmtips.field.core.voice.grammar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** VoiceGrammarParser against FR2.031 (closed grammar, MSG2.10) and FR2.032 (0.80 floor). */
class VoiceGrammarParserTest {
    private val parser = VoiceGrammarParser()

    @Test
    fun tc2_128_allFifteenCommandsParseToTheirIntent() {
        val expected = mapOf(
            "capture" to VoiceIntent.CAPTURE,
            "count twelve" to VoiceIntent.COUNT,
            "reading forty two" to VoiceIntent.READING,
            "undo" to VoiceIntent.UNDO,
            "wrong one" to VoiceIntent.WRONG_ONE,
            "mark damaged" to VoiceIntent.MARK_DAMAGED,
            "condition good" to VoiceIntent.CONDITION_GOOD,
            "left" to VoiceIntent.CHOOSE_LEFT,
            "right" to VoiceIntent.CHOOSE_RIGHT,
            "post" to VoiceIntent.POST,
            "confirm" to VoiceIntent.CONFIRM,
            "cancel" to VoiceIntent.CANCEL,
            "next" to VoiceIntent.NEXT,
            "repeat" to VoiceIntent.REPEAT,
            "what is this" to VoiceIntent.WHAT_IS_THIS,
        )
        assertEquals(15, expected.size)
        for ((phrase, intent) in expected) {
            val p = parser.parse("  ${phrase.uppercase()} ", 0.95f)
            assertTrue(phrase, p.isAccepted)
            assertEquals(phrase, intent, p.intent)
        }
        assertEquals(12.0, parser.parse("count twelve", 0.9f).quantityOrValue!!, 0.0)
        assertEquals(42.0, parser.parse("reading forty two", 0.9f).quantityOrValue!!, 0.0)
    }

    @Test
    fun tc2_128_outOfGrammarGivesMsg2_10AndIsNotAccepted() {
        val phrases = listOf(
            "hello", "post it", "confirmed", "yes", "no", "stop", "go back", "count", "count banana",
            "reading", "capture this", "left side", "undo that", "damaged", "what", "next one please",
            "count twelve hundred", "cancel cancel", "wrong", "condition bad",
        )
        assertEquals(20, phrases.size)
        for (ph in phrases) {
            val p = parser.parse(ph, 0.95f)
            assertFalse(ph, p.isAccepted)
            assertEquals(ph, VoiceIntent.UNKNOWN, p.intent)
            assertEquals(ph, "Did not catch that. Nothing changed. Hold the button and say it again.", p.feedbackMessage)
        }
    }

    /** FR2.032: below 0.80 is rejected; the floor is inclusive at 0.80 (TC2.027). */
    @Test
    fun tc2_027_floorIsInclusiveAt080() {
        assertTrue(parser.parse("left", 0.80f).isAccepted)
        assertEquals(VoiceIntent.CHOOSE_LEFT, parser.parse("left", 0.80f).intent)
        val low = parser.parse("left", 0.799f)
        assertFalse(low.isAccepted)
        assertEquals(VoiceIntent.UNKNOWN, low.intent)
        assertEquals(VoiceGrammarParser.MSG2_10, low.feedbackMessage)
    }
}
