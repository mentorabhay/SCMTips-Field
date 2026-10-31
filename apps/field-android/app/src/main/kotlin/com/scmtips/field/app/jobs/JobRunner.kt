package com.scmtips.field.app.jobs

import com.scmtips.field.core.common.UUIDv7
import com.scmtips.field.core.safety.HarnessCheck
import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put
import java.time.Instant
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.atomic.AtomicLong

enum class ScannerKind(val label: String, val howTo: String) {
    CAMERA("Phone camera", "Point the phone at the barcode"),
    HANDHELD("Handheld scanner", "Pull the trigger on your scanner"),
    GLASSES("Glasses", "Look at the label and press the glasses button"),
}

enum class StepKind { INFO, SCAN, COUNT, CHECK, CHECKIN, CLIMB, REVIEW, CONFIRM, WAITING, DONE, FAILED }

enum class Tone { NEUTRAL, GOOD, WARN, BAD }

data class CheckItem(val label: String, val ticked: Boolean)

data class Detail(val k: String, val v: String)

/** Everything the job screen draws; the Compose screen renders any step from this alone. */
data class StepView(
    val kind: StepKind,
    val jobKind: String,
    val jobTitle: String,
    val stepNo: Int,
    val stepCount: Int,
    val title: String,
    val banner: String? = null,
    val where: String? = null,
    val whereLabel: String? = null,
    val hint: String? = null,
    val body: String? = null,
    val detail: List<Detail> = emptyList(),
    /** Expected quantity on a count step; null for a blind count. */
    val expected: Int? = null,
    val qty: Int = 0,
    val qtyNote: String? = null,
    val qtyTone: Tone = Tone.NEUTRAL,
    val checks: List<CheckItem> = emptyList(),
    /** Non-null on the check-in step: the permit number typed so far. */
    val permit: String? = null,
    val primary: String? = null,
    val primaryEnabled: Boolean = true,
    val secondary: String? = null,
    /** Climb-safe: dark, high-contrast, locked (no back). */
    val dark: Boolean = false,
    val canGoBack: Boolean = true,
    val message: String? = null,
    val messageTone: Tone = Tone.NEUTRAL,
    /** The spoken prompt for this step (also shown in audio-only mode as "listen"). */
    val prompt: String = "",
    val scanHowTo: String? = null,
    val busy: Boolean = false,
    /** A spoken "post" is waiting for "yes" (10 s). */
    val listening: Boolean = false,
    val practice: Boolean = false,
    /** The job is over; the app returns to Today and shows [exitNote] if set. */
    val finished: Boolean = false,
    val exitNote: String? = null,
)

sealed interface JobAction {
    data object Primary : JobAction
    data object Secondary : JobAction
    data object Back : JobAction
    data object AllHere : JobAction
    data class Scanned(val code: String, val source: InputSource = InputSource.SCAN) : JobAction
    data class SetQty(val qty: Int) : JobAction
    data class ToggleCheck(val index: Int) : JobAction
    data class Permit(val text: String) : JobAction
    data class Location(val lat: Double, val lon: Double, val accuracyM: Double, val atMs: Long) : JobAction
    data class Heard(val transcript: String, val confidence: Float) : JobAction

    /**
     * A command the Field Assistant chose for an utterance the grammar did not parse (M3 contract §4/§5):
     * the same commands the grammar gives, run as if spoken. [transcript]/[confidence] are the operator's
     * words. Command.Yes is never executed from here: confirming a post stays the operator's own word.
     */
    data class Spoken(val command: Command, val transcript: String, val confidence: Float) : JobAction
}

/**
 * A scanned code that matches no line of a receive or count job. Returns true when the code was taken
 * (sandbox site: the assistant asks what it is), false to refuse it as before (production site).
 */
fun interface UnknownCodeHandler {
    suspend fun take(task: JobTask, code: String): Boolean
}

/** What the phone tells the assistant about the open job (contract §4 `client_state`). */
data class JobState(val taskId: String?, val lineId: String?, val step: String?)

/**
 * ONE job runner for every task type (design: Main.dc.html job runner; contract M2_JOBS_CONTRACT.md).
 *
 * A task (type + lines) becomes steps: optional lead-in (intro / go to bin / tower check-in, checklist,
 * climb) → for each line its moves (go → scan → confirm or count) → review → confirm (touch "Yes" or
 * spoken "post" … "yes") → waiting for SAP → done. Scanned codes are resolved against the lines on the
 * phone first (a wrong bin is refused without a server call); the server re-checks every confirmation.
 * Live events (erp.posted / erp.failed / task.completed / count.awaiting_approval) finish the job.
 *
 * Pure Kotlin: no Android imports. All I/O goes through [JobTransport] as [ApiRequest] values, all
 * audio through [Speaker], so every behaviour is unit-tested on the JVM (JobRunnerTest).
 */
class JobRunner(
    task: JobTask,
    private val transport: JobTransport,
    private val speaker: Speaker,
    private val deviceId: String?,
    visitId: String? = null,
    private val siteId: String? = task.siteId,
    private val siteLabel: String = "the site",
    val practice: Boolean = false,
    scanner: ScannerKind = ScannerKind.CAMERA,
    private val clock: () -> Long = System::currentTimeMillis,
    private val zone: ZoneId = ZoneId.systemDefault(),
    private val newKey: () -> String = UUIDv7::generate,
    private val nextSeq: () -> Long = AtomicLong(0)::incrementAndGet,
    private val confirmWindowMs: Long = 10_000L,
    private val unknownCodes: UnknownCodeHandler? = null,
) {
    /** The task this job runs; [updateTask] replaces its lines (sandbox items added by the assistant). */
    var task: JobTask = task
        private set

    private enum class Phase { INTRO, CHECKIN, CHECKLIST, CLIMB, GO_BIN, LINE, REVIEW, CONFIRM, WAITING, CLIMB_DOWN, CHECKOUT, DONE, FAILED }
    private enum class Sub { SCAN, GO, SCAN_BIN, COUNT, STORED, SCAN_NEW }
    private enum class DoneKind { POSTED, COMPLETED, APPROVAL, PRACTICE, CHECKED_OUT }
    private data class Fix(val lat: Double, val lon: Double, val accuracyM: Double, val atMs: Long)
    private data class Capture(val code: String, val match: Boolean)
    private data class VoiceStage(val postVoiceId: String, val atMs: Long)

    private val type = task.type
    private var lines: List<JobLine> = task.lines.sortedBy { it.lineNo }
    private val ordered = type == JobType.PICK || type == JobType.AUDIT || type == JobType.SWAP
    private val subs: List<Sub> = when (type) {
        JobType.RECEIVE, JobType.COUNT -> listOf(Sub.SCAN, Sub.COUNT)
        JobType.PUTAWAY -> listOf(Sub.SCAN, Sub.GO, Sub.SCAN_BIN, Sub.STORED)
        JobType.PICK -> listOf(Sub.GO, Sub.SCAN, Sub.COUNT)
        JobType.AUDIT -> listOf(Sub.SCAN)
        JobType.SWAP -> listOf(Sub.SCAN, Sub.SCAN_NEW)
    }
    private val prefix: List<Phase> = when (type) {
        JobType.RECEIVE -> listOf(Phase.INTRO)
        JobType.COUNT -> listOf(Phase.GO_BIN)
        JobType.PUTAWAY, JobType.PICK -> emptyList()
        JobType.AUDIT -> listOfNotNull(Phase.CHECKIN.takeIf { visitId == null }, Phase.CHECKLIST, Phase.CLIMB)
        JobType.SWAP -> listOfNotNull(Phase.CHECKIN.takeIf { visitId == null })
    }
    private val suffix: List<Phase> =
        if (type == JobType.AUDIT) listOf(Phase.REVIEW, Phase.CLIMB_DOWN, Phase.CHECKOUT, Phase.DONE) else listOf(Phase.REVIEW, Phase.DONE)

    private val mutex = Mutex()
    private var phase = Phase.INTRO
    private var sub = Sub.SCAN
    private var activeId: String? = null
    private val completed = LinkedHashSet<String>()
    private val qtyByLine = mutableMapOf<String, Double>()
    private val captured = mutableMapOf<String, Capture>()
    private val missing = mutableSetOf<String>()
    private var oldSerial: String? = null
    private var newSerial: String? = null
    private var qty = 0
    private val ticked = sortedSetOf<Int>()
    private var permit = ""
    private var fix: Fix? = null
    private var message: String? = null
    private var messageTone = Tone.NEUTRAL
    private var busy = false
    private var voiceStage: VoiceStage? = null
    private var retryPost: ApiRequest? = null
    private var checkInKey: String? = null
    private var stashedEvent: Pair<String, Map<String, String?>>? = null
    private var doneKind = DoneKind.COMPLETED
    private var docNumber: String? = null
    private var failure: String? = null
    private var finished = false
    private var exitNote: String? = null
    private val pendingClimb = mutableListOf<ClimbEvent>()
    private val harness = HarnessCheck()
    private var level = 0
    private var lastPrompt = ""
    private var lastScan: String? = null

    /** The site visit this job runs under (set by check-in, cleared by check-out). */
    var visitId: String? = visitId
        private set

    /** The posting request id returned by field-api (receive/pick/count/swap). */
    var postingRequestId: String? = null
        private set

    var scanner: ScannerKind = scanner
        set(value) {
            field = value
            publish()
        }

    /** Climb events not yet accepted by the server (sent with the next batch; reported at check-out). */
    val unsentSafetyRecords: Int get() = pendingClimb.size

    private val _view = MutableStateFlow(render())
    val view: StateFlow<StepView> = _view.asStateFlow()

    val isScanStep: Boolean
        get() = phase == Phase.GO_BIN || (phase == Phase.LINE && sub in setOf(Sub.SCAN, Sub.GO, Sub.SCAN_BIN, Sub.SCAN_NEW))

    init {
        // Resuming a started job: receive / put-away lines already done on the server stay done. Blind
        // counts, picks (the server hashes picked_qty, which the list does not carry) and tower lines are redone.
        if (type == JobType.RECEIVE || type == JobType.PUTAWAY) {
            lines.filter { it.status in RESUMED_STATUSES && it.countedQty != null }
                .forEach { completed += it.id; qtyByLine[it.id] = it.countedQty ?: 0.0 }
        }
        phase = prefix.firstOrNull() ?: Phase.LINE
        if (phase == Phase.LINE) startLines()
        _view.value = render()
    }

    /** Speaks the first step's prompt. */
    fun start() = enter()

    suspend fun act(a: JobAction) = mutex.withLock {
        if (finished) return@withLock
        when (a) {
            is JobAction.Heard -> heard(a.transcript, a.confidence)
            is JobAction.Spoken -> spoken(a.command, a.transcript, a.confidence)
            is JobAction.SetQty -> { qty = a.qty.coerceIn(0, 9999); publish() }
            is JobAction.ToggleCheck -> {
                if (phase == Phase.CHECKLIST && a.index in CHECKLIST.indices) {
                    if (!ticked.remove(a.index)) ticked += a.index
                    publish()
                }
            }
            is JobAction.Permit -> { permit = a.text.take(40); publish() }
            is JobAction.Location -> { fix = Fix(a.lat, a.lon, a.accuracyM, a.atMs); publish() }
            JobAction.Primary -> primary(InputSource.MANUAL)
            JobAction.Secondary -> secondary()
            JobAction.Back -> back()
            JobAction.AllHere -> allHere(InputSource.MANUAL, null)
            is JobAction.Scanned -> scanned(a.code.trim(), a.source)
        }
    }

    /** Call about once a second: a spoken "post" without "yes" within 10 s is cancelled (MSG2.22). */
    fun tick() {
        val s = voiceStage ?: return
        if (busy || clock() - s.atMs <= confirmWindowMs) return
        voiceStage = null
        phase = Phase.REVIEW
        enter(lead = "Post cancelled: no answer within 10 seconds.")
    }

    /**
     * A live event for this device. Returns true when the Today list should be refreshed (task.assigned).
     * Events for other tasks are ignored.
     */
    fun onLiveEvent(kind: String, payload: Map<String, String?>): Boolean {
        if (kind == "task.assigned") return true
        val forUs = payload["task_id"] == task.id || (postingRequestId != null && payload["erp_document_id"] == postingRequestId)
        if (!forUs) return false
        if (busy && (phase == Phase.REVIEW || phase == Phase.CONFIRM)) {
            stashedEvent = kind to payload // the 202 has not been handled yet
            return false
        }
        applyEvent(kind, payload)
        return false
    }

    /** Of several codes in one photo, the one this step can use (else the first). */
    fun bestOf(codes: List<String>): String? {
        val known = buildSet {
            lines.forEach { l -> (listOfNotNull(l.material, l.bin, l.expectedSerial) + l.barcodes).forEach { add(norm(it)) } }
        }
        return codes.firstOrNull { norm(it) in known } ?: codes.firstOrNull()
    }

    /** The open job as the assistant sees it: task, active line and step name ("line.scan", "review", ...). */
    val state: JobState
        get() = JobState(task.id, activeId, stepName)

    /** Short step name for the assistant and logs. */
    val stepName: String
        get() = if (phase == Phase.LINE) "line.${sub.name.lowercase()}" else phase.name.lowercase()

    /** True once the job reached its done step (the work session tells the assistant `step_done`). */
    val isDone: Boolean get() = phase == Phase.DONE

    /**
     * The task as field-api lists it now (refresh_task, e.g. after the assistant added a sandbox item).
     * Lines already done stay done and the current step is kept; new lines become open work. With
     * [focusCode] the code is then handled as a scan, so the new line is selected at once.
     */
    suspend fun updateTask(fresh: JobTask, focusCode: String?) {
        mutex.withLock {
            if (finished || fresh.id != task.id) return@withLock
            task = fresh
            lines = fresh.lines.sortedBy { it.lineNo }
            if (phase == Phase.REVIEW && openLines().isNotEmpty()) { phase = Phase.LINE; startLines() }
            publish()
        }
        if (focusCode != null) act(JobAction.Scanned(focusCode))
    }

    // --- actions -----------------------------------------------------------------------------

    private suspend fun primary(source: InputSource) {
        if (busy) return
        when (phase) {
            Phase.INTRO, Phase.GO_BIN -> { phase = Phase.LINE; startLines(); enter() }
            Phase.CHECKIN -> checkIn()
            Phase.CHECKLIST -> if (ticked.size == CHECKLIST.size) {
                climb(listOf("climb_safe_activated" to null))
                nextPrefix()
            }
            Phase.CLIMB -> harnessTap()
            Phase.LINE -> when (sub) {
                Sub.GO -> { sub = if (type == JobType.PUTAWAY) Sub.SCAN_BIN else Sub.SCAN; enter() }
                Sub.COUNT -> saveCount(qty, source, null)
                Sub.STORED -> advanceLine(null)
                else -> Unit
            }
            Phase.REVIEW -> if (postable().isNotEmpty()) { phase = Phase.CONFIRM; enter() }
            Phase.CONFIRM -> post(null)
            Phase.CLIMB_DOWN -> {
                climb(listOf("climb_safe_released" to null))
                phase = if (visitId != null) Phase.CHECKOUT else Phase.DONE
                enter()
            }
            Phase.CHECKOUT -> if (checkOut()) done(DoneKind.CHECKED_OUT)
            Phase.DONE, Phase.FAILED -> finish(null)
            Phase.WAITING -> Unit
        }
    }

    private suspend fun secondary() {
        if (busy) return
        when (phase) {
            Phase.GO_BIN -> if (task.isRecount) finish("Recount left for later. It stays on your list.")
            Phase.LINE -> if (type == JobType.AUDIT && sub == Sub.SCAN) markMissing()
            Phase.CONFIRM -> cancelStage(spoken = true)
            Phase.WAITING -> finish("Still sending to SAP. The result will show on Today.")
            Phase.DONE -> if (type == JobType.SWAP && visitId != null && checkOut()) finish("Checked out. You can leave the site.")
            else -> Unit
        }
    }

    private fun back() {
        if (busy || phase == Phase.CLIMB || phase == Phase.CLIMB_DOWN) return
        when {
            phase == Phase.CONFIRM -> cancelStage(spoken = false)
            phase == Phase.LINE && subs.indexOf(sub) > 0 && sub != Sub.STORED -> {
                sub = subs[subs.indexOf(sub) - 1]
                if (!ordered && sub == Sub.SCAN) activeId = null
                message = null
                enter()
            }
            else -> finish(if (phase == Phase.WAITING) "Still sending to SAP. The result will show on Today." else null)
        }
    }

    private suspend fun heard(transcript: String, confidence: Float) {
        val cmd = JobGrammar.parse(transcript, confidence)
        if (cmd == null) {
            say(JobGrammar.NOT_UNDERSTOOD) // nothing changes (FR2.032)
            return
        }
        execute(cmd, transcript, confidence)
    }

    private suspend fun spoken(cmd: Command, transcript: String, confidence: Float) {
        when {
            // Defence in depth (contract §4): the server strips confirm actions; the runner refuses them too.
            cmd == Command.Yes -> say(if (voiceStage != null) "Say yes yourself to post." else "Nothing to confirm. Say post first.")
            // Posting keeps the voice floor (FR2.032): a guess from unclear words never stages a post.
            cmd == Command.Post && confidence < JobGrammar.FLOOR -> say("Say post again, clearly.")
            else -> execute(cmd, transcript, confidence)
        }
    }

    private suspend fun execute(cmd: Command, transcript: String, confidence: Float) {
        if (voiceStage != null && cmd !in STAGE_SAFE) cancelStage(spoken = true)
        when (cmd) {
            Command.Capture -> Unit // the app takes the photo (glasses or phone camera)
            Command.Repeat -> say(lastPrompt)
            Command.WhatIsThis -> say(whatIsThis())
            Command.Cancel -> if (phase == Phase.CONFIRM) cancelStage(spoken = true) else say("Nothing to cancel.")
            Command.Post -> if (phase == Phase.REVIEW || phase == Phase.CONFIRM) stageVoice(transcript, confidence)
                else say("Not yet. $lastPrompt")
            Command.Yes -> if (voiceStage != null) confirmVoice(transcript, confidence) else say("Nothing to confirm. Say post first.")
            Command.AllHere -> if (phase == Phase.LINE && sub == Sub.COUNT && expectedOf(activeLine) != null) {
                allHere(InputSource.VOICE, transcript to confidence)
            } else say("Say that on a count step.")
            is Command.Number -> if (phase == Phase.LINE && sub == Sub.COUNT) {
                val vid = voiceEvent("count", transcript, confidence) ?: return
                saveCount(cmd.value, InputSource.VOICE, vid)
            } else say("Say a number on a count step.")
            Command.Next -> next()
            Command.Clipped -> when (phase) {
                Phase.CLIMB -> harnessPhrase(transcript, confidence)
                Phase.CLIMB_DOWN -> { level += 1; climb(listOf("checkpoint_reached" to levelPayload())); say("Clipped. Keep going down.") }
                else -> say("Clipped is only used while climbing.")
            }
        }
    }

    private suspend fun next() {
        when {
            phase in setOf(Phase.INTRO, Phase.GO_BIN, Phase.DONE) -> primary(InputSource.VOICE)
            phase == Phase.LINE && (sub == Sub.GO || sub == Sub.STORED) -> primary(InputSource.VOICE)
            phase == Phase.LINE && sub == Sub.SCAN && (type == JobType.RECEIVE || type == JobType.COUNT) -> {
                // M1 rule: "next" selects the next uncounted line without a scan.
                val line = openLines().firstOrNull() ?: return say("All lines are done. Say post.")
                select(line)
            }
            else -> say(lastPrompt)
        }
    }

    private suspend fun allHere(source: InputSource, voice: Pair<String, Float>?) {
        if (phase != Phase.LINE || sub != Sub.COUNT) return
        val exp = expectedOf(activeLine) ?: return
        val vid = voice?.let { voiceEvent("count", it.first, it.second) ?: return }
        saveCount(exp, source, vid)
    }

    private suspend fun scanned(code: String, source: InputSource) {
        if (busy || code.isEmpty()) return
        lastScan = code
        message = null
        when (phase) {
            Phase.GO_BIN -> {
                val bin = countBin()
                if (bin == null || same(code, bin)) { phase = Phase.LINE; startLines(); enter(lead = "Bin confirmed.") }
                else wrongBin(code, bin)
            }
            Phase.LINE -> scannedOnLine(code, source)
            else -> { message = "Nothing to scan on this step."; messageTone = Tone.NEUTRAL; publish() }
        }
    }

    private suspend fun scannedOnLine(code: String, source: InputSource) {
        when (sub) {
            Sub.SCAN -> when (type) {
                JobType.RECEIVE, JobType.COUNT -> {
                    val line = openLines().firstOrNull { it.isProduct(code) } ?: lines.firstOrNull { it.isProduct(code) }
                    when {
                        line != null -> select(line)
                        type == JobType.COUNT && same(code, countBin()) -> notice("That is the bin. Now scan a product in it.", Tone.NEUTRAL)
                        unknownCodes?.take(task, code) == true -> notice("$code is new here. Tell the assistant what it is.", Tone.NEUTRAL)
                        type == JobType.COUNT -> refuse("$code is not on this count. If it is in the bin, tell your supervisor.", "Not on this count.")
                        else -> refuse("$code is not on this delivery.", "Not on this delivery.")
                    }
                }
                JobType.PUTAWAY -> {
                    val line = openLines().firstOrNull { it.isProduct(code) }
                    if (line == null) refuse("$code is not on this put-away list.", "Not on this list.")
                    else { activeId = line.id; sub = Sub.GO; speaker.earcon(EarconCue.CAPTURED); enter() }
                }
                JobType.PICK -> {
                    val line = activeLine ?: return
                    when {
                        same(code, line.bin) -> if (confirm(line, ConfirmKind.BIN, code, source)) notice("Bin confirmed. Now scan the product.", Tone.GOOD)
                        line.isProduct(code) -> if (confirm(line, ConfirmKind.PRODUCT, code, source)) {
                            sub = Sub.COUNT; qty = expectedOf(line) ?: 0; speaker.earcon(EarconCue.CAPTURED); enter()
                        }
                        looksLikeBin(code) && line.bin != null -> wrongBin(code, line.bin)
                        else -> refuse("That is $code. Pick ${line.material ?: line.label} here.", "Wrong product.")
                    }
                }
                JobType.AUDIT -> {
                    val line = activeLine ?: return
                    val res = confirmResult(line, ConfirmKind.SERIAL, code, source, null) ?: return
                    val local = line.expectedSerial == null || same(code, line.expectedSerial)
                    val match = (res["match"] as? JsonPrimitive)?.booleanOrNull ?: local
                    captured[line.id] = Capture(code, match)
                    completed += line.id
                    speaker.earcon(if (match) EarconCue.CAPTURED else EarconCue.DUPLICATE)
                    advanceLine(if (match) "Matches." else "Different serial. Recorded.")
                }
                JobType.SWAP -> {
                    val line = activeLine ?: return
                    val expected = line.expectedSerial
                    if (expected != null && !same(code, expected)) {
                        refuse("That is serial $code. This job removes $expected.", "Wrong unit.")
                    } else if (confirm(line, ConfirmKind.SERIAL, code, source, role = "old")) {
                        oldSerial = code; sub = Sub.SCAN_NEW; speaker.earcon(EarconCue.CAPTURED); enter()
                    }
                }
            }
            Sub.GO, Sub.SCAN_BIN -> {
                val line = activeLine ?: return
                val bin = line.bin
                if (bin != null && !same(code, bin)) return wrongBin(code, bin)
                if (!confirm(line, ConfirmKind.BIN, code, source)) return
                if (type == JobType.PUTAWAY) {
                    completed += line.id; sub = Sub.STORED; speaker.earcon(EarconCue.CAPTURED); enter()
                } else {
                    sub = Sub.SCAN; enter(lead = "Bin confirmed.")
                }
            }
            Sub.SCAN_NEW -> {
                val line = activeLine ?: return
                if (same(code, oldSerial)) return refuse("That is the old unit. Scan the new one.", "That is the old unit.")
                if (confirm(line, ConfirmKind.SERIAL, code, source, role = "new")) {
                    newSerial = code; completed += line.id; speaker.earcon(EarconCue.CAPTURED); advanceLine(null)
                }
            }
            Sub.COUNT -> notice("Save this count first, or go back to scan again.", Tone.WARN)
            Sub.STORED -> notice("Tap ${if (openLines().isEmpty()) "Check and finish" else "Next pallet"} first.", Tone.NEUTRAL)
        }
    }

    private fun select(line: JobLine) {
        activeId = line.id
        sub = Sub.COUNT
        qty = expectedOf(line) ?: qtyByLine[line.id]?.toInt() ?: 0
        speaker.earcon(EarconCue.CAPTURED)
        enter()
    }

    private suspend fun saveCount(value: Int, source: InputSource, voiceEventId: String?) {
        val line = activeLine ?: return
        val res = call(JobRequests.countRecord(newKey(), line.id, value.toDouble(), line.uom, source, voiceEventId)) ?: run {
            say("Not saved. Check phone.")
            return
        }
        val stored = res.num("picked_qty") ?: res.num("counted_qty") ?: value.toDouble()
        qtyByLine[line.id] = stored
        completed += line.id
        val exp = expectedOf(line)
        val n = qtyText(stored)
        var lead = when {
            exp == null || stored.toInt() == exp -> "$n saved."
            stored < exp -> "${shortLabel(line)}: $n, ${qtyText(exp - stored)} fewer than expected."
            else -> "${shortLabel(line)}: $n, ${qtyText(stored - exp)} more than expected."
        }
        if (type == JobType.PICK && exp != null && stored < exp) {
            val flagged = call(JobRequests.flag(newKey(), task.id, line.id, "short", "picked ${qtyText(stored)} of $exp")) != null
            if (flagged) lead += " Short pick flagged." else return say("Count saved, but the short pick was not flagged. Check phone.")
        }
        advanceLine(lead)
    }

    private suspend fun markMissing() {
        val line = activeLine ?: return
        call(JobRequests.flag(newKey(), task.id, line.id, "missing")) ?: return say("Not saved. Check phone.")
        missing += line.id
        completed += line.id
        advanceLine("Marked missing.")
    }

    private fun advanceLine(lead: String?) {
        val open = openLines()
        if (open.isEmpty()) {
            phase = Phase.REVIEW
            activeId = null
        } else {
            sub = subs.first()
            activeId = if (ordered) open.first().id else null
        }
        enter(lead = lead)
    }

    private fun startLines() {
        if (openLines().isEmpty()) { phase = Phase.REVIEW; return }
        sub = subs.first()
        activeId = if (ordered) openLines().first().id else null
    }

    private fun nextPrefix(lead: String? = null) {
        val i = prefix.indexOf(phase)
        val nextPhase = prefix.getOrNull(i + 1)
        if (nextPhase != null) phase = nextPhase else { phase = Phase.LINE; startLines() }
        enter(lead = lead)
    }

    // --- tower: visit and climb-safe ---------------------------------------------------------

    private suspend fun checkIn() {
        val f = fix
        val site = siteId
        if (permit.trim().length < 4 || f == null || f.accuracyM > MAX_ACCURACY_M || site == null) return
        val key = checkInKey ?: newKey().also { checkInKey = it }
        when (val r = send(JobRequests.checkIn(key, site, permit.trim(), endOfToday(), f.lat, f.lon, f.accuracyM, iso(f.atMs)))) {
            is ApiResult.Ok -> {
                checkInKey = null
                visitId = r.body.str("id")
                speaker.earcon(EarconCue.READY)
                nextPrefix(lead = "Checked in.")
            }
            is ApiResult.Problem -> { checkInKey = null; problem(r.plain) }
            is ApiResult.Offline -> problem(OFFLINE) // same key on the next try: no second visit
        }
    }

    /**
     * Harness confirmation is two halves (FR4.041, core-safety HarnessCheck): the phrase "harness clipped"
     * (confidence >= 0.80) and a tap on the button, within 10 s of each other, in either order. One half
     * alone confirms nothing (TC4.136).
     */
    private suspend fun harnessTap() {
        harness.onTap(clock())
        if (harness.isConfirmed) clippedIn() else { notice("Now say “harness clipped”.", Tone.NEUTRAL); speaker.say("Now say harness clipped.") }
    }

    private suspend fun harnessPhrase(transcript: String, confidence: Float) {
        if (!harness.onVoicePhrase(JobGrammar.normalise(transcript), confidence.toDouble(), clock())) return say("Say harness clipped.")
        if (harness.isConfirmed) clippedIn() else { notice("Heard you. Now tap “I am clipped in”.", Tone.NEUTRAL); speaker.say("Now tap the button.") }
    }

    private suspend fun clippedIn() {
        harness.clearConfirmation()
        level += 1
        climb(listOf("harness_confirmed" to null, "checkpoint_reached" to levelPayload()))
        nextPrefix(lead = "Clipped in.")
    }

    /** Climb-safe events never block the climber: unsent ones are kept and go with the next batch. */
    private suspend fun climb(events: List<Pair<String, JsonObject?>>) {
        events.forEach { (t, p) -> pendingClimb += ClimbEvent(nextSeq(), t, iso(clock()), p) }
        val v = visitId ?: return
        when (send(JobRequests.climbEvents(newKey(), v, pendingClimb.toList()))) {
            is ApiResult.Ok -> pendingClimb.clear()
            else -> { message = "Safety record not sent yet. It is kept and sent with the next one."; messageTone = Tone.WARN }
        }
    }

    private suspend fun checkOut(): Boolean {
        val v = visitId ?: return true
        val ok = call(JobRequests.checkOut(newKey(), v, pendingClimb.size)) != null
        if (ok) visitId = null
        return ok
    }

    private fun levelPayload(): JsonObject = buildJsonObject { put("level", level) }

    // --- posting -----------------------------------------------------------------------------

    private suspend fun stageVoice(transcript: String, confidence: Float) {
        if (postable().isEmpty()) return say("Nothing to post yet.")
        val id = voiceEvent("post", transcript, confidence) ?: return
        voiceStage = VoiceStage(id, clock())
        phase = Phase.CONFIRM
        speaker.earcon(EarconCue.CONFIRM_PROMPT)
        enter()
    }

    private suspend fun confirmVoice(transcript: String, confidence: Float) {
        val s = voiceStage ?: return
        if (clock() - s.atMs > confirmWindowMs) return tick()
        val id = voiceEvent("confirm", transcript, confidence) ?: return
        post(s.postVoiceId to id)
    }

    private fun cancelStage(spoken: Boolean) {
        voiceStage = null
        retryPost = null
        phase = Phase.REVIEW
        if (spoken) enter(lead = "Cancelled. Nothing posted.") else enter()
    }

    private suspend fun post(voice: Pair<String, String>?) {
        val lines = postable()
        if (lines.isEmpty()) return
        val req = retryPost ?: if (voice == null) JobRequests.postTouch(newKey(), task.id, lines)
        else JobRequests.postVoice(newKey(), task.id, lines, voice.first, voice.second)
        voiceStage = null
        busy = true
        publish()
        val r = transport.send(req)
        busy = false
        when (r) {
            is ApiResult.Ok -> {
                retryPost = null
                postingRequestId = r.body.str("posting_request_id") ?: r.body.str("id")
                when (r.body.str("status")) {
                    "completed" -> afterCompleted()
                    "awaiting_approval" -> done(DoneKind.APPROVAL)
                    PracticeTransport.STATUS -> done(DoneKind.PRACTICE)
                    else -> {
                        phase = Phase.WAITING
                        enter()
                        stashedEvent?.let { (k, p) -> stashedEvent = null; applyEvent(k, p) }
                    }
                }
            }
            is ApiResult.Problem -> {
                retryPost = null
                phase = Phase.REVIEW
                speaker.earcon(EarconCue.ERROR)
                message = r.plain; messageTone = Tone.BAD
                enter(lead = "Not posted. Check phone.")
            }
            is ApiResult.Offline -> {
                retryPost = req // the same Idempotency-Key: a retry can never post twice
                phase = Phase.CONFIRM
                speaker.earcon(EarconCue.OFFLINE_QUEUED)
                message = "Not sent: cannot reach the PC. Check the Wi-Fi, then press Yes again."; messageTone = Tone.BAD
                enter(lead = "Not sent. No connection.")
            }
        }
    }

    private fun applyEvent(kind: String, p: Map<String, String?>) {
        if (phase != Phase.WAITING) return
        when (kind) {
            "erp.posted" -> { docNumber = p["doc_number"]; done(DoneKind.POSTED) }
            "erp.failed" -> {
                failure = p["message"]?.takeIf { it.isNotBlank() }
                phase = Phase.FAILED
                speaker.earcon(EarconCue.ERROR)
                enter()
            }
            "task.completed" -> afterCompleted()
            "count.awaiting_approval" -> done(DoneKind.APPROVAL)
        }
    }

    private fun afterCompleted() {
        if (type == JobType.AUDIT) { phase = Phase.CLIMB_DOWN; speaker.earcon(EarconCue.READY); enter(lead = "Findings sent.") }
        else done(DoneKind.COMPLETED)
    }

    private fun done(kind: DoneKind) {
        doneKind = kind
        phase = Phase.DONE
        speaker.earcon(EarconCue.READY)
        enter()
    }

    private fun finish(note: String?) {
        finished = true
        exitNote = note
        publish()
    }

    /** The lines and quantities the post request covers; quantities as the server holds them. */
    private fun postable(): List<Pair<String, Double>> {
        val chosen = when (type) {
            JobType.AUDIT, JobType.SWAP -> if (openLines().isEmpty()) lines else emptyList()
            else -> lines.filter { it.id in completed }
        }
        return chosen.map { it.id to (qtyByLine[it.id] ?: it.countedQty ?: 0.0) }
    }

    // --- I/O helpers -------------------------------------------------------------------------

    private suspend fun voiceEvent(intent: String, transcript: String, confidence: Float): String? {
        val dev = deviceId ?: run { problem("This phone is not registered yet. Use the buttons."); return null }
        return call(JobRequests.voiceEvent(newKey(), dev, task.id, intent, transcript, confidence))?.str("id")
    }

    private suspend fun confirm(line: JobLine, kind: ConfirmKind, code: String, source: InputSource, role: String? = null): Boolean =
        confirmResult(line, kind, code, source, role) != null

    private suspend fun confirmResult(line: JobLine, kind: ConfirmKind, code: String, source: InputSource, role: String?): JsonObject? {
        val r = send(JobRequests.confirmation(newKey(), task.id, line.id, kind, code, source, role))
        return when (r) {
            is ApiResult.Ok -> r.body
            is ApiResult.Problem -> { speaker.earcon(EarconCue.ERROR); problem(r.plain); say(r.plain); null }
            is ApiResult.Offline -> { problem(OFFLINE); null }
        }
    }

    /** Sends; on failure shows the plain-English reason and returns null. */
    private suspend fun call(req: ApiRequest): JsonObject? = when (val r = send(req)) {
        is ApiResult.Ok -> r.body
        is ApiResult.Problem -> { speaker.earcon(EarconCue.ERROR); problem(r.plain); null }
        is ApiResult.Offline -> { speaker.earcon(EarconCue.ERROR); problem(OFFLINE); null }
    }

    private suspend fun send(req: ApiRequest): ApiResult {
        busy = true
        publish()
        return try {
            transport.send(req)
        } finally {
            busy = false
        }
    }

    private fun problem(text: String) {
        message = text
        messageTone = Tone.BAD
        publish()
    }

    private fun notice(text: String, tone: Tone) {
        message = text
        messageTone = tone
        publish()
    }

    private fun refuse(text: String, spoken: String) {
        speaker.earcon(EarconCue.ERROR)
        message = text
        messageTone = Tone.BAD
        say(spoken)
    }

    private fun wrongBin(code: String, bin: String) =
        refuse("That is bin $code. Go to $bin.", "Wrong bin. Go to $bin.")

    private fun say(text: String) {
        speaker.say(text)
        publish()
    }

    private fun enter(lead: String? = null) {
        val p = listOfNotNull(lead, promptFor()).joinToString(" ")
        lastPrompt = p
        speaker.say(p)
        publish()
    }

    private fun publish() {
        _view.value = render()
    }

    // --- what each step says and shows -------------------------------------------------------

    private val activeLine: JobLine? get() = lines.firstOrNull { it.id == activeId }

    private fun openLines(): List<JobLine> = lines.filter { it.id !in completed }

    private fun expectedOf(l: JobLine?): Int? =
        if (l == null || type == JobType.COUNT) null else l.expectedQty?.toInt()

    private fun countBin(): String? = lines.firstNotNullOfOrNull { it.bin }

    private fun promptFor(): String = when (phase) {
        Phase.INTRO -> "Delivery ${spokenDoc(task.refDocNo ?: "")}. ${lines.size} ${plural(lines.size, "item")}. ${scanVerb("a box")}"
        Phase.GO_BIN -> if (task.isRecount) "Recount requested. Go to bin ${countBin() ?: ""}." else "Go to bin ${countBin() ?: ""}."
        Phase.CHECKIN -> "Check in at $siteLabel. Enter the permit number on the phone."
        Phase.CHECKLIST -> "Before you climb, tick the three checks on the phone."
        Phase.CLIMB -> "Climb-safe is on. At the platform, say harness clipped and tap the button."
        Phase.LINE -> linePrompt()
        Phase.REVIEW -> when (type) {
            JobType.AUDIT -> "Findings ready. Say post to send them."
            else -> "${summary().replaceFirstChar { it.uppercase() }}. Say post when you are done."
        }
        Phase.CONFIRM -> if (voiceStage != null) "${if (postsToSap) "Post" else "Send"} ${summary()}? Say yes or cancel."
            else "Check the screen, then tap yes."
        Phase.WAITING -> if (postsToSap) "Sending to SAP." else "Sending."
        Phase.CLIMB_DOWN -> "Climb down safely. Clip in at every platform."
        Phase.CHECKOUT -> "Check out on the phone before you leave."
        Phase.DONE -> when (doneKind) {
            DoneKind.POSTED -> "Posted. Document ${docNumber?.let(::spokenDoc) ?: "recorded"}."
            DoneKind.APPROVAL -> "Count saved. The office reviews the difference."
            DoneKind.PRACTICE -> "Practice finished. Nothing was sent to SAP."
            DoneKind.CHECKED_OUT -> "Checked out. You can leave the site."
            DoneKind.COMPLETED -> "Done."
        }
        Phase.FAILED -> "Posting failed. Check phone."
    }

    private fun linePrompt(): String {
        val l = activeLine
        return when (sub) {
            Sub.SCAN -> when (type) {
                JobType.RECEIVE -> scanVerb(if (completed.isEmpty()) "a box" else "the next box")
                JobType.COUNT -> scanVerb("a product in the bin")
                JobType.PUTAWAY -> scanVerb("the pallet label")
                JobType.PICK -> "Scan the product."
                JobType.AUDIT -> "${l?.position ?: "Next unit"}. Capture the ${l?.description ?: "unit"} label."
                JobType.SWAP -> "Scan the old unit at ${l?.position ?: "the position"}."
            }
            Sub.GO -> if (type == JobType.PICK) "Stop ${stopNo()} of ${lines.size}. Bin ${l?.bin ?: ""}." else "Put away to ${l?.bin ?: ""}."
            Sub.SCAN_BIN -> "Scan the bin label."
            Sub.COUNT -> {
                val exp = expectedOf(l)
                when {
                    type == JobType.PICK -> "Pick $exp. Say the count, or all here."
                    exp != null -> "${shortLabel(l)}. $exp expected. Say the count, or all here."
                    else -> "${shortLabel(l)}. Say how many you see."
                }
            }
            Sub.STORED -> openLines().size.let { k -> if (k > 0) "Stored. $k more." else "Stored. That was the last one." }
            Sub.SCAN_NEW -> "Scan the new unit."
        }
    }

    private fun scanVerb(what: String): String = when (scanner) {
        ScannerKind.GLASSES -> "Look at $what and press the button."
        ScannerKind.CAMERA -> "Scan $what with the phone."
        ScannerKind.HANDHELD -> "Scan $what."
    }

    private fun whatIsThis(): String {
        val l = activeLine ?: return lastScan?.let { "Last scan: $it." } ?: "Nothing scanned yet."
        return listOfNotNull("Line ${l.lineNo}", l.material, l.description, l.bin?.let { "bin $it" }, l.position)
            .joinToString(". ") + "."
    }

    private val postsToSap: Boolean get() = type != JobType.PUTAWAY && type != JobType.AUDIT

    private fun summary(): String {
        val done = lines.filter { it.id in completed }
        return when (type) {
            JobType.RECEIVE, JobType.PICK -> {
                val pieces = done.sumOf { qtyByLine[it.id] ?: 0.0 }
                val diffs = done.count { l -> l.expectedQty != null && (qtyByLine[l.id] ?: 0.0) != l.expectedQty }
                "${done.size} ${plural(done.size, "item")}, ${qtyText(pieces)} pieces" +
                    if (diffs > 0) ", with $diffs ${plural(diffs, "difference")}" else ""
            }
            JobType.COUNT -> "${done.size} ${plural(done.size, "product")} counted"
            JobType.PUTAWAY -> "${done.size} ${plural(done.size, "pallet")} stored"
            JobType.AUDIT -> "${captured.size} of ${lines.size} units captured"
            JobType.SWAP -> "the swap at ${lines.firstOrNull()?.position ?: "this position"}"
        }
    }

    private fun stopNo(): Int = lines.indexOfFirst { it.id == activeId } + 1

    private fun stepCount(): Int = prefix.size + lines.size.coerceAtLeast(1) * subs.size + suffix.size

    private fun stepNo(): Int {
        val lineSteps = lines.size.coerceAtLeast(1) * subs.size
        return when (phase) {
            Phase.LINE -> prefix.size + completed.size.coerceAtMost(lines.size - 1) * subs.size + subs.indexOf(sub) + 1
            Phase.REVIEW, Phase.CONFIRM, Phase.WAITING, Phase.FAILED -> prefix.size + lineSteps + 1
            Phase.CLIMB_DOWN, Phase.CHECKOUT -> prefix.size + lineSteps + 1 + suffix.indexOf(phase)
            Phase.DONE -> stepCount()
            else -> prefix.indexOf(phase) + 1
        }
    }

    private fun render(): StepView {
        val base = StepView(
            kind = StepKind.INFO,
            jobKind = jobKind(),
            jobTitle = task.title,
            stepNo = stepNo(),
            stepCount = stepCount(),
            title = "",
            banner = if (practice) PRACTICE_BANNER else null,
            message = message,
            messageTone = messageTone,
            prompt = lastPrompt,
            scanHowTo = scanner.howTo,
            busy = busy,
            practice = practice,
            finished = finished,
            exitNote = exitNote,
        )
        val l = activeLine
        return when (phase) {
            Phase.INTRO -> base.copy(
                title = "Check in this delivery",
                body = "Scan each box, count it, then post the receipt to SAP.",
                detail = listOfNotNull(
                    vendor()?.let { Detail("From", it) },
                    Detail("Expected", "${lines.size} ${plural(lines.size, "item")} · ${qtyText(lines.sumOf { it.expectedQty ?: 0.0 })} pieces"),
                    task.refDocNo?.let { Detail("Delivery", spacedDoc(it)) },
                ),
                primary = "Start",
            )
            Phase.GO_BIN -> base.copy(
                banner = task.reason?.takeIf { task.isRecount } ?: base.banner,
                title = if (task.isRecount) "Please count this bin again" else "Go to the bin",
                where = countBin(), whereLabel = if (task.isRecount) "Bin" else "Count bin",
                hint = if (task.isRecount) "The last count did not match the books." else null,
                primary = "I am at the bin",
                secondary = if (task.isRecount) "Cannot do it now" else null,
            )
            Phase.CHECKIN -> {
                val f = fix
                val loc = when {
                    f == null -> "Finding your location…"
                    f.accuracyM > MAX_ACCURACY_M -> "Too rough (±${f.accuracyM.toInt()} m). Move into the open."
                    else -> "Found · ±${f.accuracyM.toInt()} m"
                }
                base.copy(
                    kind = StepKind.CHECKIN,
                    title = "Check in at the site",
                    where = siteLabel, whereLabel = "Tower site",
                    detail = listOf(Detail("Your location", loc), Detail("Permit valid until", "end of today (23:59)")),
                    permit = permit,
                    primary = "Check in",
                    primaryEnabled = !busy && permit.trim().length >= 4 && f != null && f.accuracyM <= MAX_ACCURACY_M && siteId != null,
                )
            }
            Phase.CHECKLIST -> base.copy(
                kind = StepKind.CHECK,
                title = "Before you climb",
                checks = CHECKLIST.mapIndexed { i, s -> CheckItem(s, i in ticked) },
                primary = "Start climb",
                primaryEnabled = !busy && ticked.size == CHECKLIST.size,
            )
            Phase.CLIMB -> base.copy(
                kind = StepKind.CLIMB, dark = true, canGoBack = false,
                title = "Climb to the work platform",
                body = "Clip in at every rest platform. At the work platform say “harness clipped” and tap the button within 10 seconds.",
                primary = "I am clipped in at the platform",
            )
            Phase.LINE -> lineView(base, l)
            Phase.REVIEW -> reviewView(base)
            Phase.CONFIRM -> base.copy(
                kind = StepKind.CONFIRM,
                title = if (postsToSap) "Post to SAP now?" else "Send this now?",
                body = summary().replaceFirstChar { it.uppercase() } + ".",
                detail = reviewView(base).detail,
                primary = if (postsToSap) "Yes, post it" else "Yes, send it",
                primaryEnabled = !busy,
                secondary = "Cancel",
                listening = voiceStage != null,
            )
            Phase.WAITING -> base.copy(
                kind = StepKind.WAITING,
                title = if (postsToSap) "Sending to SAP…" else "Sending…",
                body = "This takes a few seconds. You can wait here, or go back to Today: the result shows there too.",
                secondary = "Back to today",
            )
            Phase.CLIMB_DOWN -> base.copy(
                kind = StepKind.CLIMB, dark = true, canGoBack = false,
                title = "Climb down safely",
                body = "Clip in at every rest platform on the way down. Say clipped at each one.",
                primary = "I am back on the ground",
            )
            Phase.CHECKOUT -> base.copy(
                title = "Check out of the site",
                where = siteLabel, whereLabel = "Tower site",
                body = "So the office knows you have left the tower." +
                    if (pendingClimb.isNotEmpty()) " ${pendingClimb.size} safety ${plural(pendingClimb.size, "record")} could not be sent yet." else "",
                primary = "Check out",
            )
            Phase.DONE -> doneView(base)
            Phase.FAILED -> base.copy(
                kind = StepKind.FAILED,
                title = "SAP did not accept this",
                body = (failure?.let { "$it " } ?: "") + "Your counts are saved. Your supervisor can retry it from the console.",
                primary = "Back to today",
            )
        }
    }

    private fun lineView(base: StepView, l: JobLine?): StepView = when (sub) {
        Sub.SCAN -> when (type) {
            JobType.RECEIVE -> base.copy(kind = StepKind.SCAN, title = if (completed.isEmpty()) "Scan the label on a box" else "Scan the next box")
            JobType.COUNT -> base.copy(kind = StepKind.SCAN, title = "Scan a product in the bin", hint = countBin()?.let { "Bin $it" })
            JobType.PUTAWAY -> base.copy(kind = StepKind.SCAN, title = "Scan the pallet label", body = "The app shows you the bin for it.")
            JobType.PICK -> base.copy(kind = StepKind.SCAN, title = "Scan the product", where = l?.material, whereLabel = l?.description ?: "Product",
                hint = l?.bin?.let { "Bin $it" })
            JobType.AUDIT -> base.copy(kind = StepKind.SCAN, title = "Capture the label", where = l?.position, whereLabel = l?.description ?: l?.material,
                body = "Look at the unit and capture its serial label.", secondary = "It is not there")
            JobType.SWAP -> base.copy(kind = StepKind.SCAN, title = "Scan the old unit", where = l?.position, whereLabel = l?.description ?: l?.material,
                body = "The serial on the unit you are removing.")
        }
        Sub.GO -> if (type == JobType.PICK) base.copy(
            title = if (stopNo() <= 1) "Go to the first stop" else "Go to the next stop",
            where = l?.bin, whereLabel = "Stop ${stopNo()} of ${lines.size} · bin", hint = l?.label,
            primary = "I am at the bin",
        ) else base.copy(
            title = "Take it to this bin", where = l?.bin, whereLabel = "Put away to",
            hint = l?.let { "${qtyText(it.expectedQty ?: 0.0)} ${it.uom} · ${it.label}" },
            primary = "I am at the bin",
        )
        Sub.SCAN_BIN -> base.copy(kind = StepKind.SCAN, title = "Scan the bin label to confirm", where = l?.bin, whereLabel = "Bin")
        Sub.COUNT -> {
            val exp = expectedOf(l)
            val dq = if (exp != null) qty - exp else 0
            val last = openLines().none { it.id != l?.id }
            base.copy(
                kind = StepKind.COUNT,
                title = when (type) { JobType.PICK -> "Pick ${exp ?: ""}".trim(); JobType.COUNT -> "How many do you see?"; else -> "How many did you count?" },
                where = l?.material, whereLabel = l?.description ?: l?.uom,
                body = if (type == JobType.COUNT) "Count what you see. You are not shown the system quantity, so your count stays honest." else null,
                expected = exp,
                qty = qty,
                qtyNote = when {
                    exp == null -> "Tap + and − to set your count"
                    dq == 0 -> "Matches what is expected"
                    dq < 0 -> "${-dq} fewer than expected"
                    else -> "$dq more than expected"
                },
                qtyTone = when { exp == null -> Tone.NEUTRAL; dq == 0 -> Tone.GOOD; else -> Tone.WARN },
                primary = when (type) {
                    JobType.PICK -> if (last) "Picked, check" else "Picked, next stop"
                    JobType.COUNT -> "Save count"
                    else -> if (last) "Save and check" else "Save and scan the next box"
                },
                primaryEnabled = !busy,
            )
        }
        Sub.STORED -> {
            val k = openLines().size
            base.copy(
                kind = StepKind.INFO,
                title = "Stored in ${l?.bin ?: "the bin"}",
                body = if (k > 0) "$k more ${plural(k, "pallet")} to put away." else "That was the last pallet.",
                primary = if (k > 0) "Next pallet" else "Check and finish",
            )
        }
        Sub.SCAN_NEW -> base.copy(kind = StepKind.SCAN, title = "Scan the new unit", where = l?.position, whereLabel = l?.description ?: l?.material,
            body = "The serial on the replacement from the van.")
    }

    private fun reviewView(base: StepView): StepView {
        val counted = { l: JobLine -> qtyByLine[l.id]?.let(::qtyText) }
        return when (type) {
            JobType.RECEIVE -> base.copy(kind = StepKind.REVIEW, title = "Check, then post to SAP",
                detail = lines.map { l -> Detail(l.label, counted(l)?.let { "$it of ${qtyText(l.expectedQty ?: 0.0)}" } ?: "not counted") },
                body = "Any difference is saved with the receipt so the buyer can follow up.",
                primary = "Post goods receipt", primaryEnabled = !busy && postable().isNotEmpty())
            JobType.PICK -> base.copy(kind = StepKind.REVIEW, title = "Check, then post to SAP",
                detail = lines.map { l -> Detail(l.label, counted(l)?.let { "$it of ${qtyText(l.expectedQty ?: 0.0)}" } ?: "not picked") },
                body = "A short pick is flagged so the office can follow up.",
                primary = "Post goods issue", primaryEnabled = !busy && postable().isNotEmpty())
            JobType.COUNT -> base.copy(kind = StepKind.REVIEW, title = "Check your count",
                detail = lines.map { l -> Detail(l.label, counted(l) ?: "not counted") },
                body = "If it differs from the books, an inventory controller reviews it.",
                primary = "Send count", primaryEnabled = !busy && postable().isNotEmpty())
            JobType.PUTAWAY -> base.copy(kind = StepKind.REVIEW, title = "All pallets stored",
                detail = lines.filter { it.id in completed }.map { Detail(it.bin ?: "bin", it.label) },
                body = "Nothing posts to SAP: the stock is recorded in its bins here.",
                primary = "Finish put-away", primaryEnabled = !busy && postable().isNotEmpty())
            JobType.AUDIT -> {
                val different = lines.filter { captured[it.id]?.match == false }
                val notFound = lines.filter { it.id in missing }
                val issues = different.size + notFound.size
                base.copy(kind = StepKind.REVIEW,
                    title = if (issues == 0) "All ${lines.size} units match" else "$issues ${plural(issues, "thing")} ${if (issues == 1) "does" else "do"} not match",
                    detail = listOfNotNull(
                        Detail("Captured", "${captured.size} of ${lines.size} units"),
                        notFound.takeIf { it.isNotEmpty() }?.let { n -> Detail("Not found", n.joinToString { it.label }) },
                        different.takeIf { it.isNotEmpty() }?.let { d -> Detail("Different serial", d.joinToString { it.position ?: it.label }) },
                    ),
                    body = "Nothing changes in SAP from here. Your supervisor reviews the differences.",
                    primary = "Send findings", primaryEnabled = !busy && postable().isNotEmpty())
            }
            JobType.SWAP -> base.copy(kind = StepKind.REVIEW, title = "Confirm the swap",
                detail = listOfNotNull(oldSerial?.let { Detail("Remove", it) }, newSerial?.let { Detail("Install", it) },
                    lines.firstOrNull()?.position?.let { Detail("Position", it) }),
                body = "SAP records two changes: the old unit is dismantled, the new one installed.",
                primary = "Post the swap", primaryEnabled = !busy && postable().isNotEmpty())
        }
    }

    private fun doneView(base: StepView): StepView {
        val doc = docNumber?.let { listOf(Detail("SAP document", spacedDoc(it))) } ?: emptyList()
        val v = base.copy(kind = StepKind.DONE, primary = "Back to today", detail = doc)
        return when {
            doneKind == DoneKind.PRACTICE -> v.copy(title = "Practice finished", body = "Nothing was sent to SAP. You are ready for a real job.")
            doneKind == DoneKind.CHECKED_OUT -> v.copy(title = "Checked out", body = "You can leave the site." +
                if (pendingClimb.isNotEmpty()) " ${pendingClimb.size} safety ${plural(pendingClimb.size, "record")} will need to be re-sent by the office." else "")
            doneKind == DoneKind.APPROVAL -> v.copy(title = if (task.isRecount) "Thank you" else "Count saved",
                body = if (task.isRecount) "Your count goes straight to the case. The controller decides what to post."
                else "It differs from the books, so an inventory controller reviews it. You do not need to do anything.")
            type == JobType.RECEIVE -> v.copy(title = "Goods received", body = "SAP booked the receipt.")
            type == JobType.PICK -> v.copy(title = "Picked and posted", body = "SAP booked the goods issue.")
            type == JobType.COUNT -> v.copy(title = if (task.isRecount) "Thank you" else "Count saved",
                body = if (doc.isEmpty()) "Your count is saved." else "The difference was posted to SAP.")
            type == JobType.PUTAWAY -> v.copy(title = "Put-away finished", body = "${completed.size} ${plural(completed.size, "pallet")} stored.")
            type == JobType.SWAP -> v.copy(title = "Swap recorded", body = "SAP recorded the dismantle and the install.",
                secondary = if (visitId != null) "Check out of the site" else null)
            else -> v.copy(title = "Done", body = null)
        }
    }

    private fun jobKind(): String = when (type) {
        JobType.RECEIVE -> if (practice) "Practice" else "Receive"
        JobType.PUTAWAY -> "Put away"
        JobType.PICK -> "Pick"
        JobType.COUNT -> if (task.isRecount) "Recount" else "Count"
        JobType.AUDIT -> "Site visit"
        JobType.SWAP -> "Swap"
    }

    /** "From SAMPLE-VENDOR-01 · 2 items · 36 pieces" -> "SAMPLE-VENDOR-01". */
    private fun vendor(): String? {
        val s = task.subtitle ?: return null
        if (!s.startsWith("From ")) return null
        return s.removePrefix("From ").substringBefore(" · ").trim().ifEmpty { null }
    }

    private fun shortLabel(l: JobLine?): String = l?.description?.takeIf { it.isNotBlank() } ?: l?.material ?: "This line"

    private fun iso(ms: Long): String = DateTimeFormatter.ISO_OFFSET_DATE_TIME.format(Instant.ofEpochMilli(ms).atZone(zone))

    private fun endOfToday(): String =
        DateTimeFormatter.ISO_OFFSET_DATE_TIME.format(ZonedDateTime.ofInstant(Instant.ofEpochMilli(clock()), zone).with(LocalTime.of(23, 59, 59)))

    companion object {
        const val PRACTICE_BANNER = "Practice — nothing goes to SAP"
        const val OFFLINE = "Not sent: cannot reach the PC. Check the Wi-Fi, then try again."
        const val MAX_ACCURACY_M = 50.0 // field-api refuses a check-in fix rougher than 50 m
        val CHECKLIST = listOf(
            "Harness and lanyards inspected",
            "Weather is safe to climb",
            "Someone on the ground knows you are climbing",
        )
        private val RESUMED_STATUSES = setOf("counted", "confirmed", "done")
        private val STAGE_SAFE = setOf(Command.Yes, Command.Cancel, Command.Repeat, Command.WhatIsThis, Command.Post, Command.Capture)
        private val BIN = Regex("^\\d{2}-\\d{2}-\\d{2}$")

        fun qtyText(q: Double): String = if (q % 1.0 == 0.0) q.toLong().toString() else q.toString()
        fun qtyText(q: Int): String = q.toString()

        /** Long ERP numbers in groups so they can be heard ("4900 0001 01"). */
        fun spokenDoc(n: String): String = n.chunked(4).joinToString(" ")
        fun spacedDoc(n: String): String = spokenDoc(n)

        fun plural(n: Int, word: String): String = if (n == 1) word else "${word}s"

        internal fun norm(s: String): String = s.trim().uppercase().replace(Regex("\\s+"), "")
        internal fun same(a: String?, b: String?): Boolean = a != null && b != null && norm(a) == norm(b)
        internal fun looksLikeBin(code: String): Boolean = BIN.matches(code.trim())

        private fun JsonObject.str(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull
        private fun JsonObject.num(k: String): Double? = (this[k] as? JsonPrimitive)?.doubleOrNull
    }
}
