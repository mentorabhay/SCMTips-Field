package com.scmtips.field.app.session

import com.scmtips.field.app.jobs.Command
import com.scmtips.field.app.jobs.JobGrammar
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Owner's live test, 4 Nov 2026: every phone result had confidence 0.00, so no spoken command ever worked. */
class SpokenTextTest {
    @Test
    fun aMissingOrZeroScoreCountsAsTheFloor_aRealLowScoreDoesNot() {
        assertEquals(0.80f, SpokenText.confidence(null))
        assertEquals(0.80f, SpokenText.confidence(floatArrayOf()))
        assertEquals(0.80f, SpokenText.confidence(floatArrayOf(0.0f, 0.0f)))
        assertEquals(0.80f, SpokenText.confidence(floatArrayOf(-1f)))
        assertEquals(0.93f, SpokenText.confidence(floatArrayOf(0.93f, 0.2f)))
        assertEquals(0.3f, SpokenText.confidence(floatArrayOf(0.3f)))
    }

    @Test
    fun theOwnersLoggedResultsNowParse() {
        for (heard in listOf("Look", "Look again", "Take a look", "Look look", "Look look look again")) {
            val cmd = JobGrammar.parse(SpokenText.tidy(heard), SpokenText.confidence(floatArrayOf(0.0f)))
            assertEquals(heard, Command.Look, cmd)
        }
        assertNull(JobGrammar.parse("look", SpokenText.confidence(floatArrayOf(0.3f))))
    }

    @Test
    fun repeatsAreKeptOnce_otherWordsUntouched() {
        assertEquals("Look again", SpokenText.tidy("Look look look again"))
        assertEquals("receive 5", SpokenText.tidy(" receive  5 "))
        assertEquals("receive 5 flag 5", SpokenText.tidy("receive 5 flag 5"))
        assertEquals("yes,", SpokenText.tidy("yes, yes")) // the first is kept as said; the grammars drop punctuation
        assertEquals("", SpokenText.tidy("  "))
    }
}
