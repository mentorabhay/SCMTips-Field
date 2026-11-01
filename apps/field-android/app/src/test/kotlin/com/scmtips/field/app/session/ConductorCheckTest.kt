package com.scmtips.field.app.session

import com.scmtips.field.app.check.CheckAction
import com.scmtips.field.app.jobs.RecordingSpeaker
import com.scmtips.field.app.jobs.Tasks
import com.scmtips.field.app.look.LookCase
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** M5-T05: the work session routes the box check's words; with its card open "make a claim" is the check's. */
class ConductorCheckTest {
    private class Checks : CheckPort {
        val acts = mutableListOf<CheckAction>()
        override var open = false
        override suspend fun act(a: CheckAction) { acts += a }
    }

    private class Looks : LookPort {
        val calls = mutableListOf<String>()
        override val reviewingClaims: Boolean = false
        override val consentPending: Boolean = false
        override fun heardForClaims(text: String, confidence: Float) { calls += "claims-heard:$text" }
        override suspend fun look() { calls += "look" }
        override suspend fun claim() { calls += "claim" }
        override fun startClaims() { calls += "start-claims" }
        override suspend fun startCase(case: LookCase) { calls += "case:${case.wire}" }
        override suspend fun agree() { calls += "agree" }
    }

    private class Setup(withChecks: Boolean = true, job: Boolean = false) {
        val d = DeskRig(if (job) Tasks.receive else null)
        val ai = ScriptedAssistant()
        val looks = Looks()
        val checks = Checks()
        val session = WorkSession().also { it.start(MicSource.GLASSES, glassesStarted = true) }
        val c = Conductor({ "site-1" }, d.desk, ai, TurnSpeaker(RecordingSpeaker()), session, {}, looks = looks,
            checks = if (withChecks) checks else null)
    }

    @Test
    fun m5T05_checkThisBox_startsACheck_withOrWithoutAJob_neverTheAssistant() = runBlocking {
        val s = Setup()
        assertEquals(Route.CHECK, s.c.heard("check this box", 0.9f))
        assertEquals(Route.CHECK, s.c.heard("Is this new?", 0.9f))
        val j = Setup(job = true)
        assertEquals("no task is needed, and an open job does not take the words", Route.CHECK, j.c.heard("check the seal", 0.9f))
        assertEquals(listOf(CheckAction.START, CheckAction.START), s.checks.acts)
        assertEquals(listOf(CheckAction.START), j.checks.acts)
        assertTrue(s.ai.turns.isEmpty()); assertTrue(j.ai.turns.isEmpty())
    }

    @Test
    fun m5T05_withTheCardOpen_claimEvidenceAgainAndDone_areTheChecks() = runBlocking {
        val s = Setup(job = true)
        s.checks.open = true
        for (t in listOf("make a claim", "show evidence", "check again", "try again", "done")) assertEquals(t, Route.CHECK, s.c.heard(t, 0.9f))
        assertEquals(listOf(CheckAction.CLAIM, CheckAction.EVIDENCE, CheckAction.AGAIN, CheckAction.RETRY, CheckAction.DONE), s.checks.acts)
        assertTrue("the last look's claim is not made", s.looks.calls.isEmpty())
        s.checks.open = false
        assertEquals("without the card make a claim is the look's again", Route.LOOK, s.c.heard("make a claim", 0.9f))
        assertEquals(listOf("claim"), s.looks.calls)
    }

    @Test
    fun m5T05_aMumbledCheckIsNothing_andWithoutThePortTheWordsGoOnAsBefore() = runBlocking {
        val s = Setup()
        s.c.heard("check this box", 0.6f)
        assertTrue(s.checks.acts.isEmpty())
        val n = Setup(withChecks = false)
        n.ai.answer("I can't check boxes.")
        assertEquals(Route.ASSISTANT, n.c.heard("check this box", 0.9f))
        assertEquals("check this box", n.ai.turns.single().text)
    }
}
