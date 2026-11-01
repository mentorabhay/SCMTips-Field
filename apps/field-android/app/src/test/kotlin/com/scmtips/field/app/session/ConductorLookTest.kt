package com.scmtips.field.app.session

import com.scmtips.field.app.jobs.RecordingSpeaker
import com.scmtips.field.app.jobs.StepKind
import com.scmtips.field.app.jobs.Tasks
import com.scmtips.field.app.look.LookCase
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The work session routes the M5 words: look, claim, claims review, the two cases, photo consent. */
class ConductorLookTest {
    private class Looks : LookPort {
        val calls = mutableListOf<String>()
        var reviewing = false
        var consent = false
        override val reviewingClaims: Boolean get() = reviewing
        override val consentPending: Boolean get() = consent
        override fun heardForClaims(text: String, confidence: Float) { calls += "claims-heard:$text" }
        override suspend fun look() { calls += "look" }
        override suspend fun claim() { calls += "claim" }
        override fun startClaims() { calls += "start-claims" }
        override suspend fun startCase(case: LookCase) { calls += "case:${case.wire}" }
        override suspend fun agree() { calls += "agree" }
    }

    private class Setup(withLooks: Boolean = true) {
        val d = DeskRig(Tasks.receive)
        val ai = ScriptedAssistant()
        val looks = Looks()
        val session = WorkSession().also { it.start(MicSource.GLASSES, glassesStarted = true) }
        val c = Conductor({ "site-1" }, d.desk, ai, TurnSpeaker(RecordingSpeaker()), session, {}, looks = if (withLooks) looks else null)
    }

    @Test
    fun m5B04_lookAndClaimWordsGoToTheLookPort_notToTheAssistant() = runBlocking {
        val s = Setup()
        assertEquals(Route.LOOK, s.c.heard("take a look", 0.9f))
        assertEquals(Route.LOOK, s.c.heard("count again", 0.9f))
        assertEquals(Route.LOOK, s.c.heard("make a claim", 0.9f))
        assertEquals(listOf("look", "look", "claim"), s.looks.calls)
        assertTrue(s.ai.turns.isEmpty())
    }

    @Test
    fun m5B04_receiveAndFlagGoToTheOpenJob() = runBlocking {
        val s = Setup()
        assertEquals(Route.GRAMMAR, s.c.heard("receive 12", 0.9f))
        assertEquals("two lines and none selected: the runner asks for a scan", StepKind.INFO, s.d.rig!!.v.kind)
        assertEquals("Scan a box first, then say receive and the number.", s.d.rig!!.speaker.said.last())
    }

    @Test
    fun m5B04_casesClaimsAndConsentByVoice() = runBlocking {
        val s = Setup()
        assertEquals(Route.LOOK, s.c.heard("new pharmacy delivery", 0.9f))
        assertEquals(Route.CLAIMS, s.c.heard("claims", 0.9f))
        s.c.heard("I agree", 0.9f) // nothing waits for consent: not a consent
        assertTrue("agree" !in s.looks.calls)
        s.looks.consent = true
        assertEquals(Route.LOOK, s.c.heard("I agree", 0.9f))
        s.looks.reviewing = true
        assertEquals(Route.CLAIMS, s.c.heard("approve", 0.9f))
        assertEquals(listOf("case:pharmacy", "start-claims", "agree", "claims-heard:approve"), s.looks.calls)
    }

    @Test
    fun m5B04_aMumbledAgreeIsNotConsent() = runBlocking {
        val s = Setup()
        s.looks.consent = true
        s.c.heard("I agree", 0.6f)
        assertTrue(s.looks.calls.isEmpty())
    }

    @Test
    fun m5B04_withoutTheLookPortTheM4RoutingIsUnchanged() = runBlocking {
        val s = Setup(withLooks = false)
        s.ai.answer("I can only count by voice here.")
        assertEquals(Route.ASSISTANT, s.c.heard("take a look", 0.9f))
        assertEquals("take a look", s.ai.turns.single().text)
    }
}
