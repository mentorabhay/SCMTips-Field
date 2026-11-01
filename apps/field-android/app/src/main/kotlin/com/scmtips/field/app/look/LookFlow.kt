package com.scmtips.field.app.look

import com.scmtips.field.app.jobs.LookFill
import com.scmtips.field.app.jobs.Speaker
import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** A photo from a camera, or why there is none. [note] is spoken first (e.g. the glasses fell back to the phone). */
sealed interface Shot {
    data class Taken(val photo: LookPhoto, val note: String? = null) : Shot
    data class Failed(val text: String) : Shot
}

/** The glasses camera through the Meta toolkit, the phone camera when the glasses give no photo (FieldController). */
fun interface LookCamera {
    suspend fun take(): Shot
}

/** Where a look belongs: the open receive job and its line, the site, and the case (contract §1). */
data class LookTarget(val taskId: String, val lineId: String?, val siteId: String, val case: LookCase)

enum class LookState(val text: String) {
    IDLE(""),
    CAPTURING("Taking the photo…"),
    UPLOADING("Sending the photo…"),
    READING("Counting and reading labels…"),
    SHOWN("Look ready"),
    CONSENT("Photos need your OK for this site"),
    FAILED("No look"),
}

/** Everything the phone shows about the current look, its claim and the evidence page. */
data class LookView(
    val state: LookState = LookState.IDLE,
    val taskId: String? = null,
    val case: LookCase = LookCase.GENERIC,
    val photo: LookPhoto? = null,
    val look: Look? = null,
    val message: String? = null,
    val claim: Claim? = null,
    val claimBusy: Boolean = false,
    val evidenceUrl: String? = null,
    /** M5-S01: the look's first answer is shown (count, outlines) and its labels are still being read. */
    val labelsPending: Boolean = false,
) {
    val busy: Boolean get() = state == LookState.CAPTURING || state == LookState.UPLOADING || state == LookState.READING
    val camera: CameraUsed? get() = photo?.camera
}

/**
 * The operator's look (docs/design/M5_CONTRACT.md §4): photo (glasses, else phone) → captures API →
 * `POST /v1/vision/looks` → outlines on the phone, `say` spoken on the glasses, and the proposal handed to
 * the receive job ([onLook]) as a pre-fill only. Posting stays the operator's spoken numbers + "post" +
 * "yes". Then "make a claim" (`POST /v1/claims`) and, after the posting, the evidence link.
 *
 * Two steps (M5-S01): when the first answer is not `final` (counted, labels still being read) its `say` is spoken
 * at once, then `GET /v1/vision/looks/{id}` is polled every [LookApi.POLL_MS] up to [LookApi.POLL_MAX] times on
 * [scope]; when the look is final the screen is updated and its second part (`say_next`, else `say`) is spoken
 * once, with the hint. A new look, another job, [leave] or [clear] cancels the poll; no answer within the polls
 * says [LABELS_TIMEOUT_SAY]. A claim waits for the final look.
 *
 * Pure Kotlin over ports; every path is JVM-tested in LookFlowTest. One look at a time.
 */
class LookFlow(
    private val camera: LookCamera,
    private val client: LookClient,
    private val speaker: Speaker,
    private val onLook: suspend (LookFill) -> Unit,
    private val baseUrl: () -> String?,
    private val log: (String) -> Unit = {},
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default),
    private val sleep: suspend (Long) -> Unit = { delay(it) },
) {
    private val mutex = Mutex()
    @Volatile private var poll: Job? = null

    /** The running poll of a two-step look (tests join it); null when none. */
    internal val polling: Job? get() = poll
    private val _view = MutableStateFlow(LookView())
    val view: StateFlow<LookView> = _view.asStateFlow()
    private var target: LookTarget? = null
    private var pending: LookPhoto? = null

    val consentPending: Boolean get() = _view.value.state == LookState.CONSENT

    /** The last look id (for "make a claim"); null before a look answered. */
    val lastLookId: String? get() = _view.value.look?.lookId

    /** A new job: an old job's look is not shown on it (and its poll stops). */
    fun forTask(taskId: String?, case: LookCase) {
        if (_view.value.taskId != taskId) {
            stopPolling()
            _view.value = LookView(taskId = taskId, case = case)
        } else _view.value = _view.value.copy(case = case)
    }

    /** Leaving the job screen: the poll stops (nothing more is spoken); the look stays for "make a claim". */
    fun leave() {
        if (stopPolling()) update { it.copy(labelsPending = false) }
    }

    fun clear() {
        stopPolling()
        target = null
        pending = null
        _view.value = LookView()
    }

    /** "look" / "take a look" / the Look button. */
    suspend fun look(t: LookTarget) {
        if (_view.value.busy) return speaker.say("Still looking. One moment.")
        stopPolling() // a new look: the last one's labels are not spoken any more
        mutex.withLock {
            target = t
            update { LookView(state = LookState.CAPTURING, taskId = t.taskId, case = t.case, claim = null) }
            speaker.earcon(EarconCue.CAPTURED)
            when (val shot = camera.take()) {
                is Shot.Failed -> return fail(shot.text, spoken = shot.text)
                is Shot.Taken -> {
                    shot.note?.let(speaker::say)
                    update { it.copy(photo = shot.photo) }
                    sendLocked(t, shot.photo)
                }
            }
        }
    }

    /** "I agree" or the Agree button: records the site's photo consent, then sends the waiting photo. */
    suspend fun agree() = mutex.withLock {
        val t = target ?: return@withLock
        val photo = pending ?: return@withLock
        if (!client.consent(t.siteId)) return@withLock fail("The consent was not recorded. Try again.", spoken = "Consent not recorded.")
        log("look: photo consent recorded for site ${t.siteId}")
        sendLocked(t, photo)
    }

    private suspend fun sendLocked(t: LookTarget, photo: LookPhoto) {
        update { it.copy(state = LookState.UPLOADING, message = null) }
        val captureId = when (val up = client.upload(photo, t.taskId, t.siteId, t.case.noun)) {
            is UploadResult.Uploaded -> up.captureId
            UploadResult.NeedsConsent -> {
                pending = photo
                update { it.copy(state = LookState.CONSENT, message = CONSENT_TEXT) }
                return speaker.say(CONSENT_SPOKEN)
            }
            is UploadResult.Failed -> return fail(up.text, spoken = "The photo was not sent. ${up.text}")
        }
        pending = null
        update { it.copy(state = LookState.READING) }
        when (val r = client.look(t.taskId, t.lineId, captureId, t.case)) {
            is LookResult.Failed -> fail(r.text, spoken = r.text)
            is LookResult.Ok -> {
                val look = r.look
                log("look ${look.lookId} (${look.source}${if (look.final) "" else ", reading labels"}, ${photo.camera.label}): ${look.counts}; models ${look.models.joinToString { "${it.model} ${it.outcome}" }}")
                if (look.final) {
                    val fill = LookFill(look.lookId, look.captureId ?: captureId, t.lineId, look.proposal?.receive, look.proposal?.flag, hint(look))
                    update { it.copy(state = LookState.SHOWN, look = look, labelsPending = false) }
                    onLook(fill)
                    speaker.say(listOf(look.say.ifBlank { null }, fill.hint).filterNotNull().joinToString(" "))
                } else {
                    // M5-S01: counted; the labels are read on the server. Nothing is proposed yet.
                    val fill = LookFill(look.lookId, look.captureId ?: captureId, t.lineId, null, null, PENDING_HINT)
                    update { it.copy(state = LookState.SHOWN, look = look, labelsPending = true) }
                    onLook(fill)
                    speaker.say(look.say.ifBlank { "Counted. Reading the labels." })
                    poll = scope.launch { pollLabels(t, look.lookId, look.captureId ?: captureId) }
                }
            }
        }
    }

    /** M5-S01: GET the look every second until it is final (at most [LookApi.POLL_MAX] times). */
    private suspend fun pollLabels(t: LookTarget, lookId: String, captureId: String) {
        repeat(LookApi.POLL_MAX) {
            sleep(LookApi.POLL_MS)
            val now = (client.lookNow(lookId) as? LookResult.Ok)?.look ?: return@repeat // a failed poll: try again
            if (now.final) return finishLabels(t, now, captureId)
        }
        if (_view.value.look?.lookId != lookId) return
        log("look $lookId: labels not read within ${LookApi.POLL_MAX} polls")
        update { it.copy(labelsPending = false, message = LABELS_TIMEOUT_SAY) }
        onLook(LookFill(lookId, captureId, t.lineId, null, null, "Say receive and the number you count. Or say look again."))
        speaker.queue(LABELS_TIMEOUT_SAY)
        pollDone()
    }

    private suspend fun finishLabels(t: LookTarget, look: Look, captureId: String) {
        if (_view.value.look?.lookId != look.lookId) return // another look replaced it
        log("look ${look.lookId} final (${look.source}): ${look.counts}; models ${look.models.joinToString { "${it.model} ${it.outcome}" }}")
        val fill = LookFill(look.lookId, look.captureId ?: captureId, t.lineId, look.proposal?.receive, look.proposal?.flag, hint(look))
        update { it.copy(look = look, labelsPending = false) }
        onLook(fill)
        speaker.queue(listOf((look.sayNext ?: look.say).ifBlank { null }, fill.hint).filterNotNull().joinToString(" "))
        pollDone()
    }

    /** The poll that is ending forgets itself (never a newer poll that replaced it). */
    private suspend fun pollDone() {
        val me = currentCoroutineContext()[Job]
        if (poll === me) poll = null
    }

    /** Cancels a running poll; true when there was one. */
    private fun stopPolling(): Boolean {
        val p = poll ?: return false
        poll = null
        p.cancel()
        return true
    }

    /** "make a claim": a supplier claim from the last look; its draft text is read out. */
    suspend fun claim() {
        val lookId = lastLookId ?: return speaker.say("Take a look first, then say make a claim.")
        if (_view.value.labelsPending) return speaker.say("Still reading the labels. Say make a claim in a moment.")
        if (_view.value.claimBusy) return
        update { it.copy(claimBusy = true) }
        when (val r = client.claim(lookId)) {
            is ClaimResult.Ok -> {
                update { it.copy(claimBusy = false, claim = r.claim) }
                speaker.say(ClaimText.drafted(r.claim))
            }
            is ClaimResult.Failed -> {
                update { it.copy(claimBusy = false, message = r.text) }
                speaker.say("No claim made. ${r.text}")
            }
        }
    }

    /** After "yes" posted the receipt: the evidence page's signed link, opened on the phone. */
    suspend fun evidence(docNumber: String, year: String?): String? {
        val (url, why) = client.evidenceLink(docNumber, year)
        if (url == null) {
            update { it.copy(message = why) }
            log("evidence: ${why ?: "no link"}")
            return null
        }
        val abs = baseUrl()?.let { LookApi.absolute(it, url) } ?: url
        update { it.copy(evidenceUrl = abs) }
        speaker.queue("The evidence page is open on the phone.${if (_view.value.claim == null && lastLookId != null) " Say make a claim if something was wrong." else ""}")
        return abs
    }

    fun closeEvidence() = update { it.copy(evidenceUrl = null) }

    private fun fail(text: String, spoken: String) {
        update { it.copy(state = LookState.FAILED, message = text) }
        speaker.earcon(EarconCue.ERROR)
        speaker.say("${sentence(spoken)} Say look again, or count aloud.")
    }

    private inline fun update(f: (LookView) -> LookView) {
        _view.value = f(_view.value)
    }

    companion object {
        const val CONSENT_TEXT = "Photos taken on this site are sent to the Field server. Faces are blurred on the phone " +
            "before sending, and photos are kept 30 days. Agree once for this site."
        const val CONSENT_SPOKEN = "Photos on this site need your OK once. Faces are blurred on the phone. Say I agree, or tap Agree."
        /** M5-S01: the look's labels did not come back within the polls (the server's own failure says the same). */
        const val LABELS_TIMEOUT_SAY = "I couldn't read the labels. Say your numbers."
        const val PENDING_HINT = "Reading the labels. Or say receive and the number you count."

        /** The next step after a look: the proposal as words to say back, or a spoken count. */
        fun hint(look: Look): String {
            val p = look.proposal
            val receive = p?.receive
            return when {
                look.rulesOnly || receive == null -> "Say receive and the number you count. Or say look again."
                (p.flag ?: 0) > 0 -> "Say receive $receive, flag ${p.flag}. Or say count again."
                else -> "Say receive $receive. Or say count again."
            }
        }
    }
}

internal fun sentence(s: String): String = s.trim().let { if (it.isEmpty() || it.last() in ".!?") it else "$it." }

object ClaimText {
    private fun reason(r: String): String = when (r) {
        "damaged" -> "damaged"
        "short" -> "short"
        "pack_size" -> "wrong pack size"
        "expired" -> "expired"
        "near_expiry" -> "near expiry"
        else -> r.replace('_', ' ')
    }

    /** "2 damaged, 4 pieces wrong pack size": the lines as words (numbers straight from the server). */
    fun lines(c: Claim): String = c.lines.joinToString(", ") { l ->
        listOfNotNull(l.units?.let { "$it ${if (it == 1) "unit" else "units"}" }, l.pieces?.let { "$it ${if (it == 1) "piece" else "pieces"}" })
            .joinToString(", ").ifEmpty { "some" } + " " + reason(l.reason)
    }.ifEmpty { "no lines" }

    fun drafted(c: Claim): String = "Claim drafted. ${sentence(c.text.ifBlank { lines(c) })} A supervisor approves it before it is sent."
}
