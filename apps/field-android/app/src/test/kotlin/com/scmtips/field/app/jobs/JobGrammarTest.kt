package com.scmtips.field.app.jobs

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The M2 job grammar (Glasses.dc.html "What you can say, any time") and the 0.80 floor (FR2.032). */
class JobGrammarTest {
    @Test
    fun everyDesignPhraseMapsToItsCommand() {
        val cases = mapOf(
            "capture" to Command.Capture,
            "all here" to Command.AllHere,
            "All here." to Command.AllHere,
            "next" to Command.Next,
            "repeat" to Command.Repeat,
            "what is this" to Command.WhatIsThis,
            "What is this?" to Command.WhatIsThis,
            "post" to Command.Post,
            "yes" to Command.Yes,
            "Yes." to Command.Yes,
            "cancel" to Command.Cancel,
            "clipped" to Command.Clipped,
            "harness clipped" to Command.Clipped,
        )
        cases.forEach { (said, cmd) -> assertEquals(said, cmd, JobGrammar.parse(said, 0.9f)) }
    }

    @Test
    fun m1PhrasesStayAccepted() {
        assertEquals(Command.Yes, JobGrammar.parse("confirm", 0.9f))
        assertEquals(Command.Number(12), JobGrammar.parse("count twelve", 0.9f))
    }

    @Test
    fun numbersAsDigitsOrWordsUpTo9999() {
        assertEquals(Command.Number(22), JobGrammar.parse("Twenty-two.", 0.9f))
        assertEquals(Command.Number(22), JobGrammar.parse("22", 0.9f))
        assertEquals(Command.Number(0), JobGrammar.parse("zero", 0.9f))
        assertEquals(Command.Number(1205), JobGrammar.parse("one thousand two hundred and five", 0.9f))
        assertEquals(Command.Number(9999), JobGrammar.parse("9999", 0.9f))
        assertNull(JobGrammar.parse("10000", 0.9f))
        assertNull("TC2.030: not a supported form", JobGrammar.parse("twelve hundred", 0.9f))
    }

    @Test
    fun belowTheFloorOrOutsideTheGrammarIsNothing_fr2_032() {
        assertNull(JobGrammar.parse("yes", 0.79f))
        assertEquals(Command.Yes, JobGrammar.parse("yes", 0.80f))
        assertNull(JobGrammar.parse("ship it", 0.99f))
        assertNull(JobGrammar.parse("   ", 0.99f))
        assertNull(JobGrammar.parse("post it now", 0.99f))
    }
}
