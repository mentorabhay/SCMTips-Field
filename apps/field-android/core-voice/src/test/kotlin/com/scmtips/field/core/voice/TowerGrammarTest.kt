package com.scmtips.field.core.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** TowerGrammar (T4.048): tower phrases obey the 0.80 floor used by FR4.041 and FR4.043. */
class TowerGrammarTest {
    private val g = TowerGrammar()

    @Test
    fun fr4_041_harnessClippedNeedsConfidenceAtLeast080() {
        assertFalse(g.parseTowerPhrase("harness clipped", 0.79f).isAccepted)
        val ok = g.parseTowerPhrase("Harness Clipped", 0.80f)
        assertTrue(ok.isAccepted)
        assertEquals("CMD_HARNESS_CLIPPED", ok.command)
        assertTrue(g.parseTowerPhrase("harness clipped", 0.81f).isAccepted)
    }

    @Test
    fun fr4_043_checkInIsAcceptedAtTheFloor() {
        assertEquals("CMD_CHECK_IN", g.parseTowerPhrase("check in", 0.80f).command)
        assertFalse(g.parseTowerPhrase("check in", 0.5f).isAccepted)
    }

    @Test
    fun unknownTowerPhrasesAreRejectedAtAnyConfidence() {
        val r = g.parseTowerPhrase("harness on", 0.99f)
        assertFalse(r.isAccepted)
        assertEquals("UNKNOWN", r.command)
        assertEquals("CMD_MARK_MISSING", g.parseTowerPhrase("mark missing", 0.9f).command)
        assertEquals("CMD_NAV_ROUTE", g.parseTowerPhrase("route", 0.9f).command)
    }
}
