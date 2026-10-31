package com.scmtips.field.app.session

import com.scmtips.field.app.assistant.AssistantAction
import com.scmtips.field.app.assistant.AssistantEvent
import com.scmtips.field.app.assistant.AssistantOutcome
import com.scmtips.field.app.assistant.AssistantReply
import com.scmtips.field.app.assistant.AssistantTurn
import com.scmtips.field.app.home.TodayModel
import com.scmtips.field.app.jobs.Command
import com.scmtips.field.app.jobs.JobAction
import com.scmtips.field.app.jobs.JobGrammar
import com.scmtips.field.app.jobs.JobRunner
import com.scmtips.field.app.jobs.JobState
import com.scmtips.field.app.jobs.JobTask
import com.scmtips.field.app.jobs.JobType
import com.scmtips.field.app.jobs.ScanLookup
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** The open job and the task list, as the conductor needs them (FieldController implements it). */
interface JobDesk {
    val jobOpen: Boolean
    val jobState: JobState
    fun tasks(): List<JobTask>

    /** Runs an action on the open job's runner (no-op without a job). */
    suspend fun act(a: JobAction)

    /** Opens the job; false when it is not in the operator's open list (after one refresh). */
    suspend fun openTask(taskId: String): Boolean

    /** Fetches the task again and merges it into the open job; [focusCode] is then handled as a scan. */
    suspend fun refreshTask(taskId: String, focusCode: String?)

    /** "capture": a photo with the chosen scanner, its barcode handled as a scan (as before M3). */
    suspend fun capture()

    /** A full glasses photo for the assistant: decoded codes and the JPEG (≤ 1 MB, base64); null without one. */
    suspend fun photo(): Photo?
}

data class Photo(val codes: List<String>, val jpegB64: String?)

fun interface AssistantPort {
    suspend fun turn(t: AssistantTurn): AssistantOutcome
}

/** How one utterance was handled (logged, and pinned by ConductorTest). */
enum class Route { GRAMMAR, ASSISTANT, LOCAL, FALLBACK, IGNORED }

/**
 * Phrases the phone always understands itself, and the small set it answers when the assistant cannot
 * be reached ("work never stops because of the AI", contract §4).
 */
object LocalIntents {
    sealed interface Intent {
        data object StopWork : Intent
        data object ListWork : Intent
        data class Start(val type: JobType) : Intent
    }

    private val STOP = setOf("stop work", "end work", "finish work", "stop listening", "end session", "stop the session")
    private val LIST = setOf("whats next", "what is next", "my work", "list work", "list my work", "what do i have", "what work do i have")
    private val TYPES = listOf(
        JobType.RECEIVE to listOf("receive", "receiving", "the delivery", "delivery", "a delivery"),
        JobType.PUTAWAY to listOf("put away", "putaway", "the put away"),
        JobType.PICK to listOf("pick", "picking", "the pick", "an order", "the order"),
        JobType.COUNT to listOf("count", "counting", "the count", "a count"),
        JobType.AUDIT to listOf("audit", "the audit", "site visit", "the site visit"),
        JobType.SWAP to listOf("swap", "the swap"),
    )

    fun parse(text: String): Intent? {
        val t = JobGrammar.normalise(text)
        if (t in STOP) return Intent.StopWork
        if (t in LIST) return Intent.ListWork
        val rest = listOf("start ", "open ", "begin ", "lets do ", "do ").firstOrNull { t.startsWith(it) }?.let { t.removePrefix(it).trim() } ?: return null
        return TYPES.firstOrNull { (_, words) -> rest in words }?.let { Intent.Start(it.first) }
    }

    /** "You have 3 jobs: receive delivery 1800 0000 22, count bin 03-05-02, and 1 more." */
    fun workList(tasks: List<JobTask>): String {
        if (tasks.isEmpty()) return "No work is assigned to you right now."
        val names = tasks.take(3).map { TodayModel.card(it).title.replace(" · ", " ") }
        val more = tasks.size - names.size
        return "You have ${tasks.size} ${JobRunner.plural(tasks.size, "job")}: ${names.joinToString(", ")}" +
            (if (more > 0) ", and $more more." else ".")
    }
}

/**
 * Routes what the operator says and scans during a work session (M3 contract §5):
 * - while a job is open, the fixed JobGrammar first; what it does not parse goes to the assistant;
 * - outside a job everything goes to the assistant, except "capture", "what is this" and "stop work";
 * - the reply's `say` is spoken and its `actions` run through the same job runner commands the grammar
 *   uses. Commands are run only in reply to the operator's own words, and never a confirm: posting still
 *   needs the operator's "yes" within 10 s, heard by the grammar;
 * - when the assistant cannot be reached the fixed phrases keep working and a short local hint is spoken.
 *
 * Pure Kotlin; FieldController implements [JobDesk] and [AssistantPort]. One turn at a time ([mutex]).
 */
class Conductor(
    private val siteId: () -> String?,
    private val desk: JobDesk,
    private val assistant: AssistantPort,
    private val speaker: TurnSpeaker,
    private val session: WorkSession,
    private val onStopWork: () -> Unit,
    private val log: (String) -> Unit = {},
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val mutex = Mutex()
    private var hinted = false
    private val askedAbout = mutableMapOf<String, Long>()

    suspend fun start() = mutex.withLock {
        val reply = send(AssistantEvent.SESSION_START)
        if (reply != null) perform(reply, words = null)
        else speaker.say("Work session started. The assistant is offline, so use the fixed words. ${LocalIntents.workList(desk.tasks())} Say start and the job.")
    }

    suspend fun end() = mutex.withLock { send(AssistantEvent.SESSION_END) }

    suspend fun paused() = mutex.withLock { send(AssistantEvent.PAUSE) }

    suspend fun resumed() = mutex.withLock {
        val reply = send(AssistantEvent.RESUME)
        if (reply != null) perform(reply, words = null) else speaker.say("Listening again.")
    }

    /** The open job reached its done step: the assistant can say what is next. */
    suspend fun stepDone() = mutex.withLock {
        send(AssistantEvent.STEP_DONE)?.let { perform(it, words = null) }
    }

    suspend fun heard(text: String, confidence: Float): Route = mutex.withLock {
        val words = text.trim()
        if (words.isEmpty() || confidence < NOISE_FLOOR) return@withLock Route.IGNORED
        session.heard(words)
        if (LocalIntents.parse(words) == LocalIntents.Intent.StopWork) {
            speaker.say("Stopping work. The microphone is off.")
            onStopWork()
            return@withLock Route.LOCAL
        }
        val cmd = JobGrammar.parse(words, confidence)
        val free = session.view.listenMode == "free"
        val staged = desk.jobState.step == "confirm"
        // "free": the assistant asked a question (an item's name, a quantity): the answer goes to it as
        // words, except yes/cancel while a post waits for the operator's confirmation.
        if (free) session.listenMode("command")
        // yes / no with no post waiting answer the assistant's question (e.g. "add it to this receipt?").
        val yesNo = cmd == Command.Yes || cmd == Command.Cancel
        val toRunner = desk.jobOpen && cmd != null && if (yesNo) staged else !free
        when {
            cmd == Command.Capture -> { desk.capture(); return@withLock Route.LOCAL }
            cmd == Command.WhatIsThis && !free -> return@withLock whatIsThis(words, confidence)
            toRunner -> {
                desk.act(JobAction.Heard(words, confidence))
                return@withLock Route.GRAMMAR
            }
        }
        val reply = send(AssistantEvent.UTTERANCE, text = words)
        if (reply != null) {
            perform(reply, words = words to confidence)
            return@withLock Route.ASSISTANT
        }
        fallback(words, confidence)
        Route.FALLBACK
    }

    /** A scan outside a job (inside a job the runner takes scans directly). */
    suspend fun scannedOutsideJob(code: String) = mutex.withLock {
        val reply = send(AssistantEvent.SCAN, code = code)
        if (reply != null) perform(reply, words = null)
        else {
            val r = ScanLookup.lookup(code, desk.tasks())
            val start = r.actions.firstOrNull()?.first?.let { " To start it, say start, or open $it on the phone." } ?: ""
            speaker.say("${r.kind} $code. ${sentence(r.about)}$start")
        }
    }

    /** A code that is on no line of the open receive or count job, on a sandbox site (contract §5). */
    suspend fun unknownCode(code: String) = mutex.withLock {
        // The same box stays in view (frames repeat every 3 s), or a refresh did not bring the item:
        // ask about one code once a minute, so the question is not repeated and nothing loops.
        val now = clock()
        val key = code.trim().uppercase()
        askedAbout.entries.removeAll { now - it.value >= ASK_AGAIN_MS }
        if (key in askedAbout) return@withLock log("assistant: $code asked about already")
        askedAbout[key] = now
        val photo = desk.photo()
        val reply = send(AssistantEvent.UNKNOWN_CODE, code = code, photoB64 = photo?.jpegB64)
        if (reply != null) perform(reply, words = null)
        else speaker.say("$code is not on this job, and the assistant cannot be reached to add it. Use the phone or try again later.")
    }

    // --- internals -------------------------------------------------------------------------

    private suspend fun whatIsThis(words: String, confidence: Float): Route {
        val photo = desk.photo()
        val code = photo?.codes?.firstOrNull()
        if (photo != null && (code != null || photo.jpegB64 != null)) {
            val reply = send(AssistantEvent.PHOTO, text = words, code = code, photoB64 = photo.jpegB64)
            if (reply != null) {
                perform(reply, words = null)
                return Route.ASSISTANT
            }
        }
        when {
            desk.jobOpen -> desk.act(JobAction.Heard(words, confidence)) // the runner answers from the line
            code != null -> ScanLookup.lookup(code, desk.tasks()).let { speaker.say("${it.kind} $code. ${sentence(it.about)}") }
            else -> speaker.say("No barcode seen. Look straight at the label and ask again.")
        }
        return Route.FALLBACK
    }

    private suspend fun fallback(words: String, confidence: Float) {
        val hint = if (hinted) null else "The assistant is offline. Use the fixed words: next, repeat, a number, post, then yes."
        hinted = true
        if (desk.jobOpen) {
            desk.act(JobAction.Heard(words, confidence)) // the grammar's own answer (MSG2.10 when it does not parse)
            hint?.let(speaker::queue)
            return
        }
        when (val i = LocalIntents.parse(words)) {
            is LocalIntents.Intent.Start -> {
                val id = TodayModel.starters(desk.tasks()).firstOrNull { it.type == i.type }?.taskId
                if (id == null || !desk.openTask(id)) speaker.say(TodayModel.noneOpen(i.type))
            }
            LocalIntents.Intent.ListWork -> speaker.say(LocalIntents.workList(desk.tasks()))
            else -> speaker.say("The assistant cannot be reached. Say start and a job, like start receive, or use the phone.")
        }
    }

    private suspend fun send(event: AssistantEvent, text: String? = null, code: String? = null, photoB64: String? = null): AssistantReply? {
        val site = siteId() ?: return null
        val turn = AssistantTurn(site, event, text = text, code = code, photoJpegB64 = photoB64, state = desk.jobState)
        return when (val o = assistant.turn(turn)) {
            is AssistantOutcome.Ok -> {
                hinted = false
                session.assistant(true)
                o.reply.dropped.forEach { log("assistant: dropped action $it") }
                log("assistant ${event.wire} (${o.reply.ai ?: "?"}): ${o.reply.say}")
                o.reply
            }
            is AssistantOutcome.Failed -> {
                session.assistant(false)
                log("assistant ${event.wire} failed: ${o.reason}")
                null
            }
        }
    }

    /**
     * Speaks `say`, then runs the actions; what the runner says meanwhile is queued after it. [words] are
     * the operator's own words and confidence when the turn was an utterance; without them no command runs.
     */
    private suspend fun perform(reply: AssistantReply, words: Pair<String, Float>?) {
        session.said(reply.say, reply.card?.let { it.title to it.body })
        speaker.say(reply.say)
        speaker.holding {
            for (a in reply.actions) {
                when (a) {
                    is AssistantAction.OpenTask -> if (!desk.openTask(a.taskId)) speaker.say("That job is no longer open.")
                    is AssistantAction.RefreshTask -> desk.refreshTask(a.taskId, a.focusCode)
                    is AssistantAction.Listen -> session.listenMode(a.mode)
                    is AssistantAction.Command -> {
                        val cmd = command(a)
                        when {
                            cmd == null -> log("assistant: refused command ${a.command}")
                            words == null -> log("assistant: command ${a.command} ignored (not an answer to the operator's words)")
                            !desk.jobOpen -> log("assistant: command ${a.command} ignored (no job open)")
                            else -> desk.act(JobAction.Spoken(cmd, words.first, words.second))
                        }
                    }
                }
            }
        }
    }

    companion object {
        /** Below this the recogniser is guessing at noise: nothing is sent anywhere. */
        const val NOISE_FLOOR = 0.40f

        /** One unknown_code turn per code per minute. */
        const val ASK_AGAIN_MS = 60_000L

        private fun sentence(s: String): String = s.trim().let { if (it.endsWith(".")) it else "$it." }

        /** The reply commands the phone runs, as the grammar's commands. There is no confirm. */
        fun command(a: AssistantAction.Command): Command? = when (a.command) {
            "next" -> Command.Next
            "repeat" -> Command.Repeat
            "post" -> Command.Post
            "cancel" -> Command.Cancel
            "all_here" -> Command.AllHere
            "count" -> a.value?.takeIf { it in 0..9999 }?.let { Command.Number(it) }
            else -> null
        }
    }
}
