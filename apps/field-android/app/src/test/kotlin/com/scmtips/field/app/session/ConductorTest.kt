package com.scmtips.field.app.session

import com.scmtips.field.app.assistant.AssistantAction
import com.scmtips.field.app.assistant.AssistantEvent
import com.scmtips.field.app.assistant.AssistantOutcome
import com.scmtips.field.app.assistant.AssistantReply
import com.scmtips.field.app.assistant.AssistantTurn
import com.scmtips.field.app.jobs.Command
import com.scmtips.field.app.jobs.JobAction
import com.scmtips.field.app.jobs.JobGrammar
import com.scmtips.field.app.jobs.JobRunner
import com.scmtips.field.app.jobs.JobState
import com.scmtips.field.app.jobs.JobTask
import com.scmtips.field.app.jobs.RecordingSpeaker
import com.scmtips.field.app.jobs.Rig
import com.scmtips.field.app.jobs.StepKind
import com.scmtips.field.app.jobs.Tasks
import com.scmtips.field.app.jobs.num
import com.scmtips.field.app.jobs.obj
import com.scmtips.field.app.jobs.str
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Test double of the Field Assistant: answers from a script, records every turn (test code only). */
class ScriptedAssistant : AssistantPort {
    val turns = mutableListOf<AssistantTurn>()
    val replies = ArrayDeque<AssistantOutcome>()

    override suspend fun turn(t: AssistantTurn): AssistantOutcome {
        turns += t
        return replies.removeFirstOrNull() ?: AssistantOutcome.Failed("offline: no route to host")
    }

    fun answer(say: String, vararg actions: AssistantAction) {
        replies += AssistantOutcome.Ok(AssistantReply("sess-1", say, null, actions.toList(), "rules", 0.0))
    }
}

/** A [JobDesk] over a real [JobRunner] (from [Rig]) and a task list; records what the conductor asked for. */
class DeskRig(task: JobTask?, var tasks: List<JobTask> = listOf(Tasks.receive, Tasks.count)) {
    val rig: Rig? = task?.let { Rig(it) }
    var runner: JobRunner? = rig?.runner
    val opened = mutableListOf<String>()
    val refreshed = mutableListOf<Pair<String, String?>>()
    var captures = 0
    var photos = 0
    var photo: Photo? = Photo(listOf("8901234567890"), "/9j/AAAA")

    val desk = object : JobDesk {
        override val jobOpen: Boolean get() = runner != null
        override val jobState: JobState get() = runner?.state ?: JobState(null, null, null)
        override fun tasks(): List<JobTask> = tasks
        override suspend fun act(a: JobAction) { runner?.act(a) }
        override suspend fun openTask(taskId: String): Boolean {
            if (tasks.none { it.id == taskId }) return false
            opened += taskId
            return true
        }
        override suspend fun refreshTask(taskId: String, focusCode: String?) { refreshed += taskId to focusCode }
        override suspend fun capture() { captures += 1 }
        override suspend fun photo(): Photo? { photos += 1; return photo }
    }
}

class ConductorTest {
    private class Setup(task: JobTask? = Tasks.receive, tasks: List<JobTask> = listOf(Tasks.receive, Tasks.count), decisions: DecisionPort? = null) {
        val d = DeskRig(task, tasks)
        val ai = ScriptedAssistant()
        val voice = RecordingSpeaker()
        val session = WorkSession().also { it.start(MicSource.GLASSES, glassesStarted = true) }
        var stopped = 0
        val log = mutableListOf<String>()
        var now = 1_000_000L
        val c = Conductor({ "site-1" }, d.desk, ai, TurnSpeaker(voice), session, { stopped += 1 }, { log += it }, { now }, decisions)
        val runnerSaid: List<String> get() = d.rig!!.speaker.said
        val sent get() = d.rig!!.transport
    }

    // --- routing ---------------------------------------------------------------------------

    @Test
    fun insideAJobTheGrammarComesFirstAndTheAssistantIsNotAsked() = runBlocking {
        val s = Setup()
        assertEquals(Route.GRAMMAR, s.c.heard("next", 0.92f))
        assertEquals("Scan the label on a box", s.d.rig!!.v.title)
        assertTrue(s.ai.turns.isEmpty())
        assertEquals("next", s.session.view.heard)
    }

    @Test
    fun wordsTheGrammarDoesNotParseGoToTheAssistantWithTheJobState() = runBlocking {
        val s = Setup()
        s.ai.answer("Say next to start, then look at a box.")
        assertEquals(Route.ASSISTANT, s.c.heard("what do I do here", 0.9f))
        val t = s.ai.turns.single()
        assertEquals(AssistantEvent.UTTERANCE, t.event)
        assertEquals("what do I do here", t.text)
        assertEquals("site-1", t.siteId)
        assertEquals(JobState("t-rcv", null, "intro"), t.state)
        assertEquals(listOf("Say next to start, then look at a box."), s.voice.said)
        assertEquals("Say next to start, then look at a box.", s.session.view.said)
    }

    @Test
    fun outsideAJobEverythingGoesToTheAssistantEvenFixedWords() = runBlocking {
        val s = Setup(task = null)
        s.ai.answer("You have two jobs.")
        assertEquals(Route.ASSISTANT, s.c.heard("next", 0.95f))
        assertEquals(JobState(null, null, null), s.ai.turns.single().state)
    }

    @Test
    fun noiseIsIgnoredAndStopWorkIsAlwaysLocal() = runBlocking {
        val s = Setup()
        assertEquals(Route.IGNORED, s.c.heard("uh", Conductor.NOISE_FLOOR - 0.01f))
        assertEquals(Route.IGNORED, s.c.heard("   ", 0.99f))
        assertEquals(Route.LOCAL, s.c.heard("Stop work.", 0.9f))
        assertEquals(1, s.stopped)
        assertTrue(s.ai.turns.isEmpty())
    }

    @Test
    fun captureTakesAPhotoWithoutAskingTheAssistant() = runBlocking {
        val s = Setup()
        assertEquals(Route.LOCAL, s.c.heard("capture", 0.9f))
        assertEquals(1, s.d.captures)
        assertTrue(s.ai.turns.isEmpty())
    }

    // --- actions -----------------------------------------------------------------------------

    @Test
    fun anAssistantCommandRunsTheSameRunnerCommandAsTheGrammarWithTheOperatorsWords() = runBlocking {
        val s = Setup(task = Tasks.count)
        s.d.rig!!.primary() // at the bin
        s.d.rig.scan("SAMPLE-MAT-0001")
        assertEquals(StepKind.COUNT, s.d.rig.v.kind)
        s.ai.answer("Seven saved.", AssistantAction.Command("count", 7))
        assertEquals(Route.ASSISTANT, s.c.heard("I can see seven of them", 0.9f))
        val count = s.sent.last("/v1/count-records")
        assertEquals(7.0, count.num("value")!!, 0.0)
        assertEquals("voice", count.str("source"))
        assertEquals("the voice event keeps the operator's own words", "I can see seven of them", s.sent.last("/v1/voice-events").str("transcript"))
        assertEquals(StepKind.REVIEW, s.d.rig.v.kind)
    }

    @Test
    fun theAssistantCanStagePostButConfirmingStaysTheOperatorsOwnYes() = runBlocking {
        val s = Setup(task = Tasks.count)
        s.d.rig!!.primary(); s.d.rig.scan("SAMPLE-MAT-0001"); s.d.rig.say("seven")
        assertEquals(StepKind.REVIEW, s.d.rig.v.kind)

        // A reply that tries to confirm: the conductor refuses the confirm, only "post" (staging) runs.
        s.ai.answer("Send it? Say yes.", AssistantAction.Command("post", null), AssistantAction.Command("confirm", null), AssistantAction.Command("yes", null))
        assertEquals(Route.ASSISTANT, s.c.heard("okay I'm finished, send my count", 0.9f))
        assertEquals(StepKind.CONFIRM, s.d.rig.v.kind)
        assertTrue("staged, waiting for the operator", s.d.rig.v.listening)
        assertTrue("nothing posted by the assistant", s.sent.all("/post-requests").isEmpty())
        assertTrue(s.log.any { it.contains("refused command confirm") })
        assertTrue(s.log.any { it.contains("refused command yes") })

        // Even a Spoken(Yes) reaching the runner directly confirms nothing.
        s.d.rig.runner.act(JobAction.Spoken(Command.Yes, "yes", 0.99f))
        assertTrue(s.sent.all("/post-requests").isEmpty())

        // The operator's own "yes" is grammar, and posts with both voice ids.
        assertEquals(Route.GRAMMAR, s.c.heard("yes", 0.93f))
        val post = s.sent.last("/post-requests")
        assertEquals("voice", post.obj("confirm")!!.str("method"))
        assertEquals(1, s.ai.turns.size)
    }

    @Test
    fun aPostGuessedFromUnclearWordsIsNotStaged() = runBlocking {
        val s = Setup(task = Tasks.count)
        s.d.rig!!.primary(); s.d.rig.scan("SAMPLE-MAT-0001"); s.d.rig.say("seven")
        s.ai.answer("Posting.", AssistantAction.Command("post", null))
        s.c.heard("mumble send mumble", JobGrammar.FLOOR - 0.1f)
        assertEquals(StepKind.REVIEW, s.d.rig.v.kind)
        assertEquals("Say post again, clearly.", s.runnerSaid.last())
    }

    @Test
    fun commandsRunOnlyInAnswerToTheOperatorsWords() = runBlocking {
        val s = Setup(task = Tasks.count)
        s.d.rig!!.primary(); s.d.rig.scan("SAMPLE-MAT-0001")
        s.ai.answer("What is it?", AssistantAction.Command("count", 4), AssistantAction.Listen("free"))
        s.c.unknownCode("8901234567890")
        assertEquals(StepKind.COUNT, s.d.rig.v.kind)
        assertTrue(s.sent.all("/v1/count-records").isEmpty())
        assertTrue(s.log.any { it.contains("not an answer to the operator's words") })
        assertEquals("free", s.session.view.listenMode)
    }

    @Test
    fun openTaskAndRefreshTaskGoToTheDeskAndTheRunnersWordsQueueAfterTheAssistants() = runBlocking {
        val s = Setup(task = null)
        s.ai.answer("Starting the count of bin 03-05-02. Done means every product counted and sent.", AssistantAction.OpenTask("t-ct"),
            AssistantAction.OpenTask("gone"), AssistantAction.RefreshTask("t-ct", "8901234567890"))
        s.c.heard("start the count", 0.9f)
        assertEquals(listOf("t-ct"), s.d.opened)
        assertEquals(listOf("t-ct" to "8901234567890"), s.d.refreshed)
        assertEquals(listOf("Starting the count of bin 03-05-02. Done means every product counted and sent.", "That job is no longer open."), s.voice.said)
    }

    // --- listen mode and yes/no --------------------------------------------------------------

    @Test
    fun afterAQuestionTheNextWordsGoToTheAssistantEvenIfTheGrammarKnowsThem() = runBlocking {
        val s = Setup(task = Tasks.receive)
        s.d.rig!!.primary()
        s.ai.answer("What is it?", AssistantAction.Listen("free"))
        s.c.unknownCode("8901234567890")
        s.ai.answer("How many?", AssistantAction.Listen("free"))
        assertEquals(Route.ASSISTANT, s.c.heard("next", 0.95f)) // e.g. an item really called "next"
        s.ai.answer("Add 4 Tea to this receipt?")
        assertEquals(Route.ASSISTANT, s.c.heard("four", 0.95f))
        assertEquals(listOf(AssistantEvent.UNKNOWN_CODE, AssistantEvent.UTTERANCE, AssistantEvent.UTTERANCE), s.ai.turns.map { it.event })
        assertEquals("command", s.session.view.listenMode)
        assertEquals(Route.GRAMMAR, s.c.heard("repeat", 0.95f))
    }

    @Test
    fun yesOrNoWithNoPostWaitingAnswersTheAssistant() = runBlocking {
        val s = Setup(task = Tasks.receive)
        s.ai.answer("Added Tea.", AssistantAction.RefreshTask("t-rcv", "8901234567890"))
        assertEquals(Route.ASSISTANT, s.c.heard("yes", 0.95f))
        assertEquals("yes", s.ai.turns.single().text)
        assertTrue(s.sent.all("/post-requests").isEmpty())
    }

    // --- the assistant cannot be reached -----------------------------------------------------

    @Test
    fun inAJobTheFixedPhrasesKeepWorkingWithOneSpokenHint() = runBlocking {
        val s = Setup()
        assertEquals(Route.FALLBACK, s.c.heard("where does this go", 0.9f))
        assertEquals(JobGrammar.NOT_UNDERSTOOD, s.runnerSaid.last())
        assertTrue(s.voice.said.single().startsWith("The assistant is offline."))
        assertEquals(false, s.session.view.assistantOnline)
        s.c.heard("and this one", 0.9f)
        assertEquals("the hint is spoken once per outage", 1, s.voice.said.size)
        assertEquals(Route.GRAMMAR, s.c.heard("next", 0.9f))
        assertEquals("Scan the label on a box", s.d.rig!!.v.title)
    }

    @Test
    fun outsideAJobTheLocalIntentsStartWorkAndListIt() = runBlocking {
        val s = Setup(task = null)
        s.c.heard("start count", 0.9f)
        assertEquals(listOf("t-ct"), s.d.opened)
        s.c.heard("what's next", 0.9f)
        assertTrue(s.voice.said.last(), s.voice.said.last().startsWith("You have 2 jobs: Receive Delivery 1800 0000 22, Count bin 03-05-02."))
        s.c.heard("start pick", 0.9f)
        assertEquals("No order to pick right now.", s.voice.said.last())
        s.c.heard("tell me a joke", 0.9f)
        assertTrue(s.voice.said.last().startsWith("The assistant cannot be reached."))
    }

    @Test
    fun theGreetingIsTheSessionStartTurnWithALocalOneWhenOffline() = runBlocking {
        val s = Setup(task = null)
        s.ai.answer("Good morning. You have a delivery and a count.", AssistantAction.OpenTask("t-rcv"))
        s.c.start()
        assertEquals(AssistantEvent.SESSION_START, s.ai.turns.single().event)
        assertEquals(listOf("t-rcv"), s.d.opened)
        assertEquals(true, s.session.view.assistantOnline)

        val off = Setup(task = null)
        off.c.start()
        assertTrue(off.voice.said.single().contains("You have 2 jobs"))
    }

    // --- scans and photos --------------------------------------------------------------------

    @Test
    fun anUnknownCodeGoesToTheAssistantWithAGlassesPhoto() = runBlocking {
        val s = Setup()
        s.ai.answer("What is it?", AssistantAction.Listen("free"))
        s.c.unknownCode("8901234567890")
        val t = s.ai.turns.single()
        assertEquals(AssistantEvent.UNKNOWN_CODE, t.event)
        assertEquals("8901234567890", t.code)
        assertEquals("/9j/AAAA", t.photoJpegB64)
        assertEquals(1, s.d.photos)

        val off = Setup()
        off.d.photo = null
        off.c.unknownCode("X1")
        assertNull(off.ai.turns.single().photoJpegB64)
        assertTrue(off.voice.said.single().startsWith("X1 is not on this job"))
    }

    @Test
    fun theSameUnknownCodeIsAskedAboutOnceAMinute() = runBlocking {
        val s = Setup()
        s.c.unknownCode("8901234567890")
        s.now += 3_000
        s.c.unknownCode(" 8901234567890 ")
        s.c.unknownCode("4006381333931")
        assertEquals(listOf("8901234567890", "4006381333931"), s.ai.turns.map { it.code })
        assertEquals("no second photo for the same box", 2, s.d.photos)
        s.now += Conductor.ASK_AGAIN_MS
        s.c.unknownCode("8901234567890")
        assertEquals(3, s.ai.turns.size)
    }

    @Test
    fun aScanOutsideAJobIsAScanTurnOrALocalLookup() = runBlocking {
        val s = Setup(task = null)
        s.ai.answer("That is Grade 1, on the delivery.")
        s.c.scannedOutsideJob("SAMPLE-MAT-0001")
        assertEquals(AssistantEvent.SCAN, s.ai.turns.single().event)
        assertEquals("SAMPLE-MAT-0001", s.ai.turns.single().code)
        s.c.scannedOutsideJob("SAMPLE-MAT-0001")
        assertEquals("Product SAMPLE-MAT-0001. Industrial Component Grade 1. To start it, say start, or open Receive 1800000022 on the phone.", s.voice.said.last())
    }

    @Test
    fun whatIsThisTakesAFullPhotoForTheAssistantAndFallsBackToTheLine() = runBlocking {
        val s = Setup()
        s.ai.answer("That is a tea box. It is not on this delivery.")
        assertEquals(Route.ASSISTANT, s.c.heard("what is this", 0.9f))
        val t = s.ai.turns.single()
        assertEquals(AssistantEvent.PHOTO, t.event)
        assertEquals("8901234567890", t.code)
        assertEquals("/9j/AAAA", t.photoJpegB64)
        assertEquals(Route.FALLBACK, s.c.heard("what is this", 0.9f))
        assertEquals("Nothing scanned yet.", s.runnerSaid.last())
    }

    @Test
    fun pauseResumeStepDoneAndEndAreTurns() = runBlocking {
        val s = Setup()
        s.c.paused()
        s.ai.answer("Welcome back. Look at a box.")
        s.c.resumed()
        s.c.stepDone()
        s.c.end()
        assertEquals(listOf(AssistantEvent.PAUSE, AssistantEvent.RESUME, AssistantEvent.STEP_DONE, AssistantEvent.SESSION_END), s.ai.turns.map { it.event })
        assertEquals(listOf("Welcome back. Look at a box."), s.voice.said)
        val off = Setup()
        off.c.resumed()
        assertEquals(listOf("Listening again."), off.voice.said)
        assertNull("count needs a value", Conductor.command(AssistantAction.Command("count", null)))
    }

    // --- M4: the immediate greeting and the approver flow in the session -------------------------

    /** The assistant's session_start answer held back until [gate] opens (a slow PC); other turns fail fast. */
    private class SlowStart : AssistantPort {
        val gate = kotlinx.coroutines.CompletableDeferred<AssistantOutcome>()
        val turns = mutableListOf<AssistantTurn>()
        override suspend fun turn(t: AssistantTurn): AssistantOutcome {
            turns += t
            return if (t.event == AssistantEvent.SESSION_START) gate.await() else AssistantOutcome.Failed("offline: timeout")
        }
    }

    private class Approver(override var approver: Boolean = true) : DecisionPort {
        override var reviewing = false
        var started = 0
        val words = mutableListOf<String>()
        override fun startReview() { started += 1; reviewing = true }
        override fun heard(text: String, confidence: Float) { words += text }
    }

    @Test
    fun startWorkSpeaksALocalGreetingAtOnce_andTheServersReplyFollowsWhenItArrives() = runBlocking {
        val voice = RecordingSpeaker()
        val session = WorkSession().also { it.start(MicSource.GLASSES, glassesStarted = true) }
        val ai = SlowStart()
        val d = DeskRig(null)
        val c = Conductor({ "site-1" }, d.desk, ai, TurnSpeaker(voice), session, {}, {})
        val start = launch { c.start() }
        kotlinx.coroutines.withTimeout(5_000) { while (voice.said.isEmpty()) yield() }
        // Spoken before any server answer: the job count comes from the phone's own task list.
        assertEquals(listOf("Work session started. You have 2 jobs: Receive Delivery 1800 0000 22, Count bin 03-05-02. Say start and the job."), voice.said)
        assertEquals(AssistantEvent.SESSION_START, ai.turns.single().event)
        assertFalse(start.isCompleted)
        ai.gate.complete(AssistantOutcome.Ok(AssistantReply("sess-1", "Good morning. The delivery is first.", null, listOf(AssistantAction.OpenTask("t-rcv")), "rules", 0.0)))
        start.join()
        assertEquals("Good morning. The delivery is first.", voice.said.last())
        assertEquals(listOf("t-rcv"), d.opened)
    }

    @Test
    fun wordsSaidWhileTheServerIsSlowAreHandledAtOnce_andTheLateReplyIsNotSpokenOverThem() = runBlocking {
        val voice = RecordingSpeaker()
        val session = WorkSession().also { it.start(MicSource.GLASSES, glassesStarted = true) }
        val ai = SlowStart()
        val d = DeskRig(null)
        val log = mutableListOf<String>()
        val c = Conductor({ "site-1" }, d.desk, ai, TurnSpeaker(voice), session, {}, { log += it })
        val start = launch { c.start() }
        kotlinx.coroutines.withTimeout(5_000) { while (voice.said.isEmpty()) yield() }
        assertEquals(Route.FALLBACK, c.heard("start count", 0.9f)) // not kept waiting behind session_start
        assertEquals(listOf("t-ct"), d.opened)
        ai.gate.complete(AssistantOutcome.Ok(AssistantReply("sess-1", "Good morning.", null, listOf(AssistantAction.OpenTask("t-rcv")), "rules", 0.0)))
        start.join()
        assertFalse(voice.said.contains("Good morning."))
        assertEquals(listOf("t-ct"), d.opened)
        assertTrue(log.any { "not spoken" in it })
    }

    @Test
    fun anApproverHearsHowManyDecisionsWait_andSayingDecisionsStartsTheReview() = runBlocking {
        val port = Approver()
        val s = Setup(task = null, decisions = port)
        s.c.decisionsWaiting(1)
        assertEquals("1 decision is waiting for you. Say decisions to hear it.", s.voice.said.last())
        s.c.decisionsWaiting(0)
        assertEquals(1, s.voice.said.size)
        assertEquals(Route.DECISIONS, s.c.heard("next decision", 0.9f))
        assertEquals(1, port.started)
        assertTrue(s.ai.turns.isEmpty())
    }

    @Test
    fun whileAReviewRunsTheSessionsWordsGoToIt_butStopWorkStillStops() = runBlocking {
        val port = Approver().apply { reviewing = true }
        val s = Setup(decisions = port)
        assertEquals(Route.DECISIONS, s.c.heard("approve option two", 0.91f))
        assertEquals(Route.DECISIONS, s.c.heard("next", 0.92f)) // not the job's "next" while a decision is open
        assertEquals(listOf("approve option two", "next"), port.words)
        assertTrue(s.ai.turns.isEmpty())
        assertEquals("intro", s.d.rig!!.runner.state.step)
        assertEquals(Route.LOCAL, s.c.heard("stop work", 0.9f))
        assertEquals(1, s.stopped)
        // No announcement over a running review.
        s.c.decisionsWaiting(2)
        assertFalse(s.voice.said.any { "waiting for you" in it })
    }

    @Test
    fun withoutTheApproveCapabilityDecisionsAreNotTheAppsToOpen() = runBlocking {
        val port = Approver(approver = false)
        val s = Setup(task = null, decisions = port)
        s.ai.answer("You have no decisions to make here.")
        assertEquals(Route.ASSISTANT, s.c.heard("decisions", 0.9f))
        assertEquals(0, port.started)
        s.c.decisionsWaiting(3)
        assertFalse(s.voice.said.any { "waiting for you" in it })
    }
}
