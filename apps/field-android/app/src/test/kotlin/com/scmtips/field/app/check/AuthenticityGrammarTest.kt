package com.scmtips.field.app.check

import com.scmtips.field.app.jobs.Command
import com.scmtips.field.app.jobs.JobGrammar
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** M5-T05: the phone's words for a box check, the QR choice and the card's words (contract §7). */
class AuthenticityGrammarTest {
    @Test
    fun m5T05_startPhrasesWorkAnyTime_withTheContractsVariants() {
        for (t in listOf("check this box", "Check this box.", "is this new?", "Is this unit really new", "check the seal",
            "check a box", "check the box", "check this unit", "is this box new", "check a delivered box")) {
            assertEquals(t, CheckAction.START, CheckGrammar.action(t, 0.9f, cardOpen = false))
            assertEquals(t, CheckAction.START, CheckGrammar.action(t, 0.9f, cardOpen = true))
        }
        assertEquals("check again without a card is a new check", CheckAction.START, CheckGrammar.action("check again", 0.9f, false))
        assertEquals(CheckAction.AGAIN, CheckGrammar.action("check again", 0.9f, true))
    }

    @Test
    fun m5T05_afterTheAnswer_claimEvidenceDoneRetryAndPhoneScan_onlyWhileTheCardIsOpen() {
        val open = mapOf(
            "make a claim" to CheckAction.CLAIM, "raise a claim" to CheckAction.CLAIM,
            "show evidence" to CheckAction.EVIDENCE, "show the evidence page" to CheckAction.EVIDENCE, "evidence" to CheckAction.EVIDENCE,
            "done" to CheckAction.DONE, "close" to CheckAction.DONE,
            "try again" to CheckAction.RETRY,
            "scan with the phone" to CheckAction.PHONE_SCAN, "scan the code" to CheckAction.PHONE_SCAN,
        )
        for ((t, a) in open) {
            assertEquals(t, a, CheckGrammar.action(t, 0.9f, cardOpen = true))
            assertNull("$t without the card belongs to someone else", CheckGrammar.action(t, 0.9f, cardOpen = false))
        }
        assertEquals("make a claim stays the look's without the card", Command.Claim, JobGrammar.parse("make a claim", 0.9f))
    }

    @Test
    fun m5T05_mumbledOrOtherWords_areNeverActedOn() {
        assertNull("below the 0.80 floor", CheckGrammar.action("check this box", 0.7f, cardOpen = true))
        assertNull(CheckGrammar.action("", 0.9f, cardOpen = true))
        for (t in listOf("check", "box", "is this", "look", "post", "yes", "next", "receive 12", "approve", "check the delivery")) {
            assertNull(t, CheckGrammar.action(t, 0.9f, cardOpen = true))
        }
    }

    @Test
    fun m5T05_theSealCodeIsPicked_andAnythingElseIsStillSent() {
        assertEquals("SEAL1.a.b.c", SealCode.pick(listOf("8901234567890", " SEAL1.a.b.c ")))
        assertEquals("a QR that is not a seal code is still sent (the server says so)", "https://example.test/x", SealCode.pick(listOf(" ", "https://example.test/x")))
        assertNull("nothing read: no code (hold closer, or scan with the phone)", SealCode.pick(emptyList()))
        assertNull(SealCode.pick(listOf("", "  ")))
        assertTrue(SealCode.sendable("SEAL1." + "x".repeat(1018)))
        assertFalse(SealCode.sendable("SEAL1." + "x".repeat(1019)))
        assertFalse(SealCode.sendable(""))
    }

    @Test
    fun m5T05_theSignalsInPlainWords() {
        val c = AuthenticityClientTest.parsed(AuthenticityClientTest.RETURNED)
        assertEquals("Signed by the maker: Kestrel Optics (SAMPLE)", CheckText.signature(c.code))
        assertEquals("Serial KSO-24-000102 · KSO-BINO-842", CheckText.unit(c.code))
        assertEquals("First check: this one", CheckText.firstCheck(c.firstCheck))
        assertEquals("Seal: tape over the original", CheckText.visual(c.visual, c.tamper))
        assertEquals(listOf("30 Sep 2026 · Made", "2 Oct 2026 · Shipped to the seller · Pune", "5 Oct 2026 · Delivered",
            "12 Oct 2026 · Activated", "20 Oct 2026 · Returned"), CheckText.timeline(c.registry))
        assertTrue(CheckText.notNewEvent("returned")); assertFalse(CheckText.notNewEvent("delivered"))
        assertNull(CheckText.registry(c.registry))

        assertEquals("Not signed by the maker's key", CheckText.signature(c.code!!.copy(status = "bad_signature")))
        assertEquals("Not a seal code", CheckText.signature(c.code!!.copy(status = "not_a_seal_code")))
        assertEquals("No maker is connected for this check", CheckText.signature(c.code!!.copy(status = "oem_not_configured")))
        assertEquals("First checked on 28 Oct 2026 by someone else", CheckText.firstCheck(FirstCheckSignal("other_checker", "2026-10-28T09:00:00Z", null)))
        assertEquals("You checked it first, on 28 Oct 2026", CheckText.firstCheck(FirstCheckSignal("same_checker", "2026-10-28T09:00:00Z", null)))
        assertEquals("First check: not recorded", CheckText.firstCheck(FirstCheckSignal("not_recorded", null, null)))
        assertEquals("History: not asked (the code did not verify)", CheckText.registry(c.registry!!.copy(status = "not_asked", events = emptyList())))
        val intact = c.visual!!.copy(signs = emptyList())
        assertEquals("Seal looks intact", CheckText.visual(intact, false))
        assertEquals("Checking the seal…", CheckText.visual(intact.copy(status = "pending"), null))
        assertEquals("The seal could not be checked", CheckText.visual(intact.copy(status = "failed"), null))
        assertEquals("Seal photo: none sent", CheckText.visual(null, null))
        assertEquals("not-a-date", CheckText.date("not-a-date"))
    }

    @Test
    fun m5T05_whatCanBeClaimed_followsTheContract() {
        fun c(verdict: String, tamper: String = "null", final: Boolean = true) = AuthenticityClientTest.parsed(
            AuthenticityClientTest.minimal(verdict, "x", tamper = tamper).replace("\"final\":true", "\"final\":$final"))
        assertFalse(CheckText.claimable(c("GENUINE_NEW")))
        assertFalse(CheckText.claimable(c("GENUINE_NEW", tamper = "false")))
        assertTrue("tampered seal, any verdict", CheckText.claimable(c("GENUINE_NEW", tamper = "true")))
        for (v in listOf("GENUINE_PREVIOUSLY_ACTIVATED", "RETURNED_REFURBISHED", "CANNOT_VERIFY", "LIKELY_COUNTERFEIT")) {
            assertTrue(v, CheckText.claimable(c(v)))
        }
        assertFalse("the visual check still runs", CheckText.claimable(c("LIKELY_COUNTERFEIT", final = false)))
        assertTrue(CheckText.cardVisible(linkedToSite = true, allowed = true))
        assertFalse(CheckText.cardVisible(linkedToSite = false, allowed = true))
    }
}
