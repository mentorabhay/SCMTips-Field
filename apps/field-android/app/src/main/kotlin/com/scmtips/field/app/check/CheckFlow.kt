package com.scmtips.field.app.check

import com.scmtips.field.app.jobs.Speaker
import com.scmtips.field.app.look.CameraUsed
import com.scmtips.field.app.look.Claim
import com.scmtips.field.app.look.ClaimText
import com.scmtips.field.app.look.LookApi
import com.scmtips.field.app.look.LookFlow
import com.scmtips.field.app.look.LookPhoto
import com.scmtips.field.app.look.UploadResult
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

/**
 * One photo of the seal and the QR codes read from it on the phone, or why there is none. [photo] is the blurred,
 * look-size copy to upload (null when its face check failed: then only the code is checked). [note] is spoken
 * first (e.g. the glasses fell back to the phone camera).
 */
sealed interface SealShot {
    data class Taken(
        val photo: LookPhoto?,
        val codes: List<String>,
        val camera: CameraUsed,
        val note: String? = null,
    ) : SealShot

    data class Failed(val text: String) : SealShot
}

/** The glasses camera through the Meta toolkit, the phone camera when the glasses give no photo (FieldController). */
fun interface SealCamera {
    suspend fun take(): SealShot
}

/** The phone's own code scanner, for a QR the photo could not read; null when nothing was scanned. */
fun interface CodeScanner {
    suspend fun scan(): String?
}

/** Where the code that was checked came from (the card says it, as it says which camera took the photo). */
enum class CodeSource(val label: String) { PHOTO("Code read from the photo"), PHONE_SCAN("Code scanned with the phone") }

enum class CheckState(val text: String) {
    IDLE(""),
    CAPTURING("Taking a photo of the seal…"),
    NO_CODE("No seal code read"),
    SCANNING("Scan the seal code with the phone…"),
    UPLOADING("Sending the seal photo…"),
    CONSENT("Photos need your OK for this site"),
    CHECKING("Checking the code with the maker…"),
    SHOWN("Checked"),
    FAILED("Not checked"),
}

/** Everything the phone shows about the current box check, its claim and its evidence page. */
data class CheckView(
    val state: CheckState = CheckState.IDLE,
    val photo: LookPhoto? = null,
    val camera: CameraUsed? = null,
    val code: String? = null,
    val codeSource: CodeSource? = null,
    val check: AuthenticityCheck? = null,
    /** Two steps: the verdict is shown and spoken; the visual seal check still runs on the server. */
    val visualPending: Boolean = false,
    /** True when the seal photo went with the check (false: code only; null: not sent yet). */
    val photoSent: Boolean? = null,
    val message: String? = null,
    val claim: Claim? = null,
    val claimBusy: Boolean = false,
    val evidenceUrl: String? = null,
    /** A network failure: "try again" resends the same request with the same Idempotency-Key. */
    val canRetry: Boolean = false,
    /** False once the server said 403 (no field.authenticity.check, or the site is out of scope): Today hides its card. */
    val allowed: Boolean = true,
) {
    val open: Boolean get() = state != CheckState.IDLE
    val busy: Boolean get() = state in BUSY
    val claimable: Boolean get() = check?.let(CheckText::claimable) == true && !visualPending

    private companion object {
        val BUSY = setOf(CheckState.CAPTURING, CheckState.SCANNING, CheckState.UPLOADING, CheckState.CHECKING)
    }
}

/**
 * The C3 phone flow, "Is this unit really new?" (docs/design/M5_CONTRACT C3 §7): "Show me the seal code." → a
 * photo (glasses, else phone) → the QR decoded on the phone from that photo (if it cannot be, "hold the seal
 * closer" or a direct phone scan) → the photo through the captures API (consent and blur gates as for looks; a
 * person who may not upload photos is checked by code only) → `POST /v1/authenticity/checks` → `say` spoken at
 * once → when not `final`, `GET` every [CheckApi.POLL_MS] up to [CheckApi.POLL_MAX] times on [scope] and
 * `say_next` spoken once → the card. Then "make a claim" (`POST /v1/claims {check_id}`), "show evidence" (the
 * signed link), "check again" (a new check, a new key), "done". A new check, [leave], [done] or [clear] cancels
 * the poll. The verdict is the server's (deterministic rules); the phone never decides it.
 *
 * Pure Kotlin over ports; every path is JVM-tested in AuthenticityFlowTest. One check at a time.
 */
class CheckFlow(
    private val camera: SealCamera,
    private val scanner: CodeScanner,
    private val client: CheckClient,
    private val speaker: Speaker,
    private val baseUrl: () -> String?,
    private val log: (String) -> Unit = {},
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default),
    private val sleep: suspend (Long) -> Unit = { delay(it) },
    /** After "Show me the seal code." the person turns the box to the camera before the photo is taken. */
    private val aimMs: Long = AIM_MS,
) {
    private val mutex = Mutex()
    @Volatile private var poll: Job? = null

    /** The running poll of a two-step check (tests join it); null when none. */
    internal val polling: Job? get() = poll
    private val _view = MutableStateFlow(CheckView())
    val view: StateFlow<CheckView> = _view.asStateFlow()

    private var siteId: String? = null
    private var pendingPhoto: LookPhoto? = null
    private var pendingCode: String? = null

    /** The last check request, for "try again" after a network failure (same Idempotency-Key). */
    private data class Sent(val code: String, val captureId: String?, val key: String)
    private var lastSent: Sent? = null

    val consentPending: Boolean get() = _view.value.state == CheckState.CONSENT

    /** "check this box" / Today's card / "check again": a new check with a new key. */
    suspend fun start(site: String?) {
        if (_view.value.busy) return speaker.say(CheckText.BUSY)
        stopPolling() // a new check: the last one's seal result is not spoken any more
        mutex.withLock {
            siteId = site
            pendingPhoto = null
            pendingCode = null
            lastSent = null
            update { CheckView(state = CheckState.CAPTURING, allowed = it.allowed) }
            speaker.say(CheckText.SHOW_ME)
            sleep(aimMs)
            speaker.earcon(EarconCue.CAPTURED)
            when (val shot = camera.take()) {
                is SealShot.Failed -> noCode(shot.text, spoken = "${sentenceOf(shot.text)} ${CheckText.NO_CODE}")
                is SealShot.Taken -> {
                    shot.note?.let(speaker::say)
                    update { it.copy(photo = shot.photo, camera = shot.camera) }
                    val code = SealCode.pick(shot.codes)
                    log("check: photo from the ${shot.camera.label.lowercase()}, ${shot.codes.size} code(s) read${if (shot.photo == null) ", photo not sendable" else ""}")
                    if (code == null) {
                        pendingPhoto = shot.photo
                        noCode(CheckText.NO_CODE, spoken = CheckText.NO_CODE)
                    } else {
                        proceedLocked(code, CodeSource.PHOTO, shot.photo)
                    }
                }
            }
        }
    }

    /** "scan with the phone" / the button after a photo without a readable code: the phone's code scanner. */
    suspend fun scanWithPhone() {
        if (_view.value.busy) return speaker.say(CheckText.BUSY)
        mutex.withLock {
            update { it.copy(state = CheckState.SCANNING, message = null) }
            val code = scanner.scan()?.trim()?.takeIf { it.isNotEmpty() }
            if (code == null) return@withLock noCode(CheckText.NO_SCAN, spoken = CheckText.NO_SCAN)
            // The photo taken before (if any) still goes with the check as the seal's photo.
            proceedLocked(code, CodeSource.PHONE_SCAN, pendingPhoto)
        }
    }

    /** "I agree" or Agree: records the site's photo consent, then sends the waiting photo and checks. */
    suspend fun agree() = mutex.withLock {
        val code = pendingCode ?: return@withLock
        val site = siteId ?: return@withLock
        if (!client.consent(site)) {
            update { it.copy(message = "The consent was not recorded. Try again, or tap Check by code only.") }
            return@withLock speaker.say("Consent not recorded.")
        }
        log("check: photo consent recorded for site $site")
        proceedLocked(code, _view.value.codeSource ?: CodeSource.PHOTO, pendingPhoto)
    }

    /** "Check by code only" while photo consent is asked: the check goes without the photo. */
    suspend fun codeOnly() = mutex.withLock {
        val code = pendingCode ?: return@withLock
        pendingPhoto = null
        sendLocked(code, null, client.key())
    }

    /** "try again" after "I couldn't reach Field": the same request, the same Idempotency-Key. */
    suspend fun retry() {
        if (_view.value.busy) return speaker.say(CheckText.BUSY)
        mutex.withLock {
            val s = lastSent?.takeIf { _view.value.canRetry } ?: return@withLock speaker.say("Nothing to try again. Say check this box.")
            sendLocked(s.code, s.captureId, s.key)
        }
    }

    private suspend fun proceedLocked(code: String, source: CodeSource, photo: LookPhoto?) {
        if (!SealCode.sendable(code)) return fail(CheckText.TOO_LONG, retry = false)
        update { it.copy(code = code, codeSource = source) }
        pendingCode = code
        val site = siteId
        var captureId: String? = null
        if (photo != null && site != null) {
            update { it.copy(state = CheckState.UPLOADING, message = null) }
            when (val up = client.uploadSeal(photo, site)) {
                is UploadResult.Uploaded -> captureId = up.captureId
                UploadResult.NeedsConsent -> {
                    pendingPhoto = photo
                    update { it.copy(state = CheckState.CONSENT, message = LookFlow.CONSENT_TEXT) }
                    return speaker.say(CheckText.CONSENT_SPOKEN)
                }
                is UploadResult.Failed -> {
                    // e.g. a field.viewer may not upload photos (no field.capture.create): check by code only.
                    log("check: seal photo not sent (${up.text}); code only")
                    update { it.copy(message = "${CheckText.CODE_ONLY} (${up.text.trimEnd('.')}.)") }
                    speaker.say(CheckText.CODE_ONLY)
                }
            }
        }
        pendingPhoto = null
        sendLocked(code, captureId, client.key())
    }

    private suspend fun sendLocked(code: String, captureId: String?, key: String) {
        lastSent = Sent(code, captureId, key)
        update { it.copy(state = CheckState.CHECKING, canRetry = false, photoSent = captureId != null) }
        when (val r = client.check(key, code, captureId, siteId)) {
            is CheckResult.Ok -> show(r.check)
            is CheckResult.Failed -> when (r.error) {
                CheckError.OFFLINE -> fail(r.text, retry = true)
                CheckError.FORBIDDEN -> { update { it.copy(allowed = false) }; fail(r.text, retry = false) }
                CheckError.CAPTURE_GONE -> if (captureId != null) {
                    log("check: the seal photo $captureId was not found; code only")
                    speaker.say(CheckText.PHOTO_GONE)
                    sendLocked(code, null, client.key()) // another body: another key
                } else fail(r.text, retry = false)
                else -> fail(r.text, retry = false)
            }
        }
    }

    private fun show(c: AuthenticityCheck) {
        log("check ${c.checkId}: ${c.verdictWire ?: "?"}${if (c.final) "" else ", checking the seal"}; reasons ${c.reasons.joinToString()}")
        update { it.copy(state = CheckState.SHOWN, check = c, visualPending = !c.final, message = null, canRetry = false, claim = null) }
        speaker.earcon(if (c.verdict == Verdict.GENUINE_NEW && c.tamper != true) EarconCue.CAPTURED else EarconCue.ERROR)
        speaker.say(c.say.ifBlank { CheckText.fallbackSay(c) })
        if (!c.final) poll = scope.launch { pollVisual(c.checkId) }
    }

    /** Two steps: GET the check every second until it is final (at most [CheckApi.POLL_MAX] times). */
    private suspend fun pollVisual(checkId: String) {
        repeat(CheckApi.POLL_MAX) {
            sleep(CheckApi.POLL_MS)
            val now = (client.checkNow(checkId) as? CheckResult.Ok)?.check ?: return@repeat // a failed poll: try again
            if (now.final) return finishVisual(now)
        }
        if (_view.value.check?.checkId != checkId) return
        log("check $checkId: the seal was not checked within ${CheckApi.POLL_MAX} polls")
        update { it.copy(visualPending = false, message = CheckText.VISUAL_TIMEOUT) }
        speaker.queue(CheckText.VISUAL_TIMEOUT)
        pollDone()
    }

    private suspend fun finishVisual(c: AuthenticityCheck) {
        if (_view.value.check?.checkId != c.checkId) return // another check replaced it
        log("check ${c.checkId} final: tamper ${c.tamper}; reasons ${c.reasons.joinToString()}; models ${c.models.joinToString { "${it.model} ${it.outcome}" }}")
        update { it.copy(check = c, visualPending = false) }
        c.sayNext?.let(speaker::queue)
        pollDone()
    }

    private suspend fun pollDone() {
        val me = currentCoroutineContext()[Job]
        if (poll === me) poll = null
    }

    private fun stopPolling(): Boolean {
        val p = poll ?: return false
        poll = null
        p.cancel()
        return true
    }

    /** "make a claim" while the card is open: a claim of kind authenticity from this check; its text is read out. */
    suspend fun claim() {
        val c = _view.value.check ?: return speaker.say(CheckText.CHECK_FIRST)
        if (_view.value.visualPending) return speaker.say(CheckText.VISUAL_PENDING)
        if (_view.value.claimBusy) return
        update { it.copy(claimBusy = true) }
        when (val r = client.claim(c.checkId)) {
            is CheckClaimResult.Ok -> {
                update { it.copy(claimBusy = false, claim = r.claim) }
                speaker.say(ClaimText.drafted(r.claim))
            }
            CheckClaimResult.NothingToClaim -> {
                update { it.copy(claimBusy = false, message = CheckText.NOTHING_TO_CLAIM) }
                speaker.say(CheckText.NOTHING_TO_CLAIM)
            }
            CheckClaimResult.Pending -> {
                update { it.copy(claimBusy = false) }
                speaker.say(CheckText.VISUAL_PENDING)
            }
            is CheckClaimResult.Failed -> {
                update { it.copy(claimBusy = false, message = r.text) }
                speaker.say("No claim made. ${sentenceOf(r.text)}")
            }
        }
    }

    /** "show evidence" / the Evidence page button: the signed page of this check, opened on the phone. */
    suspend fun evidence(): String? {
        val c = _view.value.check ?: run { speaker.say("Check a box first."); return null }
        val (url, why) = client.evidenceLink(c.checkId)
        if (url == null) {
            update { it.copy(message = why) }
            log("check evidence: ${why ?: "no link"}")
            speaker.say("No evidence page. ${sentenceOf(why ?: "The server sent no link.")}")
            return null
        }
        val abs = baseUrl()?.let { LookApi.absolute(it, url) } ?: url
        update { it.copy(evidenceUrl = abs) }
        speaker.say(CheckText.EVIDENCE_OPEN)
        return abs
    }

    fun closeEvidence() = update { it.copy(evidenceUrl = null) }

    /** Leaving the card: the poll stops and nothing more is said; the card stays as it is. */
    fun leave() {
        if (stopPolling()) update { it.copy(visualPending = false) }
    }

    /** "done" / Done: the card closes. */
    fun done() {
        clear()
        speaker.say(CheckText.CLOSED)
    }

    /** Closes the card and stops the poll; a 403 already heard stays (Today keeps its card hidden). */
    fun clear() {
        stopPolling()
        pendingPhoto = null
        pendingCode = null
        lastSent = null
        _view.value = CheckView(allowed = _view.value.allowed)
    }

    /** Another site or another sign-in: as [clear], and the server is asked again whether checks are allowed. */
    fun reset() {
        clear()
        _view.value = CheckView()
    }

    private fun noCode(text: String, spoken: String) {
        update { it.copy(state = CheckState.NO_CODE, message = text) }
        speaker.earcon(EarconCue.ERROR)
        speaker.say(spoken)
    }

    private fun fail(text: String, retry: Boolean) {
        update { it.copy(state = CheckState.FAILED, message = text, canRetry = retry) }
        speaker.earcon(EarconCue.ERROR)
        speaker.say(text)
    }

    private inline fun update(f: (CheckView) -> CheckView) {
        _view.value = f(_view.value)
    }

    companion object {
        /** Time to turn the seal to the camera after "Show me the seal code." (the glasses take the photo at once). */
        const val AIM_MS = 2_500L

        private fun sentenceOf(s: String): String = s.trim().let { if (it.isEmpty() || it.last() in ".!?") it else "$it." }
    }
}
