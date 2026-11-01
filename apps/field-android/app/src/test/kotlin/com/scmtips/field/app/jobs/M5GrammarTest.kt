package com.scmtips.field.app.jobs

import com.scmtips.field.app.look.ClaimGrammar
import com.scmtips.field.app.look.LookCase
import com.scmtips.field.app.session.LocalIntents
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** M5 words (docs/design/M5_CONTRACT.md §4): look, receive N flag M, claims; numbers as digits or words. */
class M5GrammarTest {
    private fun p(t: String, c: Float = 0.9f) = JobGrammar.parse(t, c)

    @Test
    fun m5B02_receiveAndFlag_asWordsOrDigits() {
        assertEquals(Command.Receive(18, 2), p("receive eighteen flag two"))
        assertEquals(Command.Receive(18, 2), p("Receive 18, flag 2."))
        assertEquals(Command.Receive(18, 2), p("receive eighteen and flag two"))
        assertEquals(Command.Receive(18, 2), p("receive 18 good, flag 2 damaged"))
        assertEquals(Command.Receive(20, 0), p("receive twenty flag zero"))
        assertEquals(Command.Receive(18, null), p("receive 18"))
        assertEquals(Command.Receive(18, null), p("receive eighteen"))
        assertEquals(Command.Receive(null, 2), p("flag 2"))
        assertEquals(Command.Receive(null, 2), p("flag two"))
        assertEquals(Command.Receive(124, 3), p("receive one hundred and twenty four flag three"))
    }

    @Test
    fun m5B02_receiveOutsideTheGrammar_isNothing() {
        assertNull(p("receive"))
        assertNull(p("receive lots"))
        assertNull(p("receive 18 flag many"))
        assertNull(p("receive 10000"))
        assertNull("below the 0.80 floor", p("receive eighteen flag two", 0.79f))
        assertNull(p("flag"))
    }

    @Test
    fun m5B02_lookAndClaimWords() {
        listOf("look", "take a look", "Take a look.", "look again", "count again", "have a look").forEach {
            assertEquals(it, Command.Look, p(it))
        }
        listOf("make a claim", "Make a claim.", "claim").forEach { assertEquals(it, Command.Claim, p(it)) }
    }

    @Test
    fun m5B02_m2WordsAreUnchanged() {
        assertEquals(Command.Number(12), p("count twelve"))
        assertEquals(Command.Number(18), p("eighteen"))
        assertEquals(Command.Yes, p("confirm"))
        assertEquals(Command.Post, p("post"))
        assertEquals(Command.Next, p("next"))
        assertNull(p("post it now"))
    }

    @Test
    fun m5B03_claimReviewWords() {
        assertEquals(ClaimGrammar.Said.Approve, ClaimGrammar.parse("approve", 0.9f))
        assertEquals(ClaimGrammar.Said.Approve, ClaimGrammar.parse("Approve the claim.", 0.9f))
        assertEquals(ClaimGrammar.Said.Confirm, ClaimGrammar.parse("confirm", 0.9f))
        assertEquals(ClaimGrammar.Said.Confirm, ClaimGrammar.parse("yes", 0.9f))
        assertEquals(ClaimGrammar.Said.Cancel, ClaimGrammar.parse("cancel", 0.9f))
        assertEquals(ClaimGrammar.Said.Next, ClaimGrammar.parse("next claim", 0.9f))
        assertEquals(ClaimGrammar.Said.Repeat, ClaimGrammar.parse("repeat", 0.9f))
        assertEquals(ClaimGrammar.Said.Stop, ClaimGrammar.parse("stop", 0.9f))
        assertEquals(ClaimGrammar.Said.Reject(null), ClaimGrammar.parse("reject", 0.9f))
        assertEquals(ClaimGrammar.Said.Reject("photo is blurred"), ClaimGrammar.parse("Reject because photo is blurred", 0.9f))
        assertNull(ClaimGrammar.parse("approve", 0.5f))
        assertNull(ClaimGrammar.parse("ship it", 0.9f))
        assertEquals(ClaimGrammar.Said.Approve, ClaimGrammar.button(ClaimGrammar.APPROVE_ID))
        assertNull(ClaimGrammar.button("decision.approve.1"))
    }

    @Test
    fun m5B04_sessionPhrasesForCasesClaimsAndConsent() {
        assertEquals(LocalIntents.Intent.NewCase(LookCase.GROCERY), LocalIntents.parse("New grocery delivery"))
        assertEquals(LocalIntents.Intent.NewCase(LookCase.PHARMACY), LocalIntents.parse("new pharmacy delivery"))
        assertEquals(LocalIntents.Intent.NewCase(LookCase.PHARMACY), LocalIntents.parse("start a new pharmacy delivery"))
        assertEquals(LocalIntents.Intent.Claims, LocalIntents.parse("claims"))
        assertEquals(LocalIntents.Intent.Claims, LocalIntents.parse("Next claim."))
        assertEquals(LocalIntents.Intent.Agree, LocalIntents.parse("I agree"))
        // M3/M4 phrases keep their meaning.
        assertEquals(LocalIntents.Intent.Start(JobType.RECEIVE), LocalIntents.parse("start receive"))
        assertEquals(LocalIntents.Intent.Decisions, LocalIntents.parse("next decision"))
    }
}
