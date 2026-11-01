package com.scmtips.field.app.look

import com.scmtips.field.app.jobs.LookFill
import com.scmtips.field.app.jobs.Speaker
import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
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
 * Pure Kotlin over ports; every path is JVM-tested in LookFlowTest. One look at a time.
 */
class LookFlow(
    private val camera: LookCamera,
    private val client: LookClient,
    private val speaker: Speaker,
    private val onLook: suspend (LookFill) -> Unit,
    private val baseUrl: () -> String?,
    private val log: (String) -> Unit = {},
) {
    private val mutex = Mutex()
    private val _view = MutableStateFlow(LookView())
    val view: StateFlow<LookView> = _view.asStateFlow()
    private var target: LookTarget? = null
    private var pending: LookPhoto? = null

    val consentPending: Boolean get() = _view.value.state == LookState.CONSENT

    /** The last look id (for "make a claim"); null before a look answered. */
    val lastLookId: String? get() = _view.value.look?.lookId

    /** A new job: an old job's look is not shown on it. */
    fun forTask(taskId: String?, case: LookCase) {
        if (_view.value.taskId != taskId) _view.value = LookView(taskId = taskId, case = case)
        else _view.value = _view.value.copy(case = case)
    }

    fun clear() {
        target = null
        pending = null
        _view.value = LookView()
    }

    /** "look" / "take a look" / the Look button. */
    suspend fun look(t: LookTarget) {
        if (_view.value.busy) return speaker.say("Still looking. One moment.")
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
                log("look ${look.lookId} (${look.source}, ${photo.camera.label}): ${look.counts}; models ${look.models.joinToString { "${it.model} ${it.outcome}" }}")
                val fill = LookFill(look.lookId, look.captureId ?: captureId, t.lineId, look.proposal?.receive, look.proposal?.flag, hint(look))
                update { it.copy(state = LookState.SHOWN, look = look) }
                onLook(fill)
                speaker.say(listOf(look.say.ifBlank { null }, fill.hint).filterNotNull().joinToString(" "))
            }
        }
    }

    /** "make a claim": a supplier claim from the last look; its draft text is read out. */
    suspend fun claim() {
        val lookId = lastLookId ?: return speaker.say("Take a look first, then say make a claim.")
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
