package com.scmtips.field.app.check

import com.scmtips.field.app.jobs.Command
import com.scmtips.field.app.jobs.JobGrammar
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/** What the phone does with words or a tap about a box check (contract §7 "Start" and "Voice after the answer"). */
enum class CheckAction {
    /** "check this box", "is this new", "check the seal" (and close variants), or Today's card. */
    START,

    /** "check again": a new check with a new Idempotency-Key. */
    AGAIN,

    /** "make a claim" while the check card is open: `POST /v1/claims {check_id}`. */
    CLAIM,

    /** "show evidence": the signed evidence page, opened on the phone. */
    EVIDENCE,

    /** "done": the check card closes (its poll stops). */
    DONE,

    /** "try again" after a network failure: the same request with the same Idempotency-Key. */
    RETRY,

    /** "scan with the phone" when the photo gave no code: the phone's code scanner reads the QR. */
    PHONE_SCAN,

    /** Buttons only: photo consent for the site, or checking by the code alone without the photo. */
    AGREE,
    CODE_ONLY,
}

/**
 * The phone's own words for box checks. Start phrases work any time in a work session (and by hold-to-talk); the
 * others only while the check card is open, so "done" or "evidence" never reach anything else then. Words below
 * the 0.80 floor are never acted on.
 */
object CheckGrammar {
    private val START = setOf(
        "check this box", "check the box", "check a box", "check box", "check my box", "check this delivered box",
        "check a delivered box", "check the delivered box", "check this unit", "check the unit",
        "is this new", "is it new", "is this box new", "is this unit new", "is this really new", "is this unit really new",
        "is this box really new", "is this product new", "check the seal", "check this seal", "check seal",
    )
    private val AGAIN = setOf("check again", "check it again", "check this box again", "check the box again", "check once more")
    private val EVIDENCE = setOf(
        "show evidence", "show the evidence", "show evidence page", "show the evidence page", "evidence", "evidence page",
        "the evidence page", "open evidence", "open the evidence", "open the evidence page",
    )
    private val DONE = setOf("done", "close", "close it", "close the check", "done checking", "finished", "thats all", "that is all")
    private val RETRY = setOf("try again", "retry", "send again", "send it again")
    private val PHONE_SCAN = setOf(
        "scan with the phone", "scan with phone", "scan it with the phone", "scan the code", "scan the code with the phone",
        "scan the seal", "scan the seal code", "phone scan", "use the phone",
    )

    /** The action for these words, or null (they are someone else's: the job grammar, the assistant). */
    fun action(text: String, confidence: Float, cardOpen: Boolean): CheckAction? {
        if (confidence < JobGrammar.FLOOR) return null
        val t = JobGrammar.normalise(text)
        return when {
            t.isEmpty() -> null
            t in START -> CheckAction.START
            t in AGAIN -> if (cardOpen) CheckAction.AGAIN else CheckAction.START
            !cardOpen -> null
            t in EVIDENCE -> CheckAction.EVIDENCE
            t in DONE -> CheckAction.DONE
            t in RETRY -> CheckAction.RETRY
            t in PHONE_SCAN -> CheckAction.PHONE_SCAN
            JobGrammar.parse(text, confidence) == Command.Claim -> CheckAction.CLAIM
            else -> null
        }
    }
}

/** Which QR code of a photo is the seal's, and whether a code can be sent at all (pure; contract §2.1, §4.1, §7). */
object SealCode {
    const val PREFIX = "SEAL1."

    /** A `SEAL1.` code first; else the first code read (the server answers "It is not a seal code."). */
    fun pick(codes: List<String>): String? {
        val read = codes.map { it.trim() }.filter { it.isNotEmpty() }
        return read.firstOrNull { it.startsWith(PREFIX) } ?: read.firstOrNull()
    }

    /** More than the server's 1024 characters is never a seal code (the server would answer 422). */
    fun sendable(code: String): Boolean = code.length in 1..CheckApi.MAX_CODE
}

/** The words and labels of the check card (pure, JVM-tested). Everything is SAMPLE: the maker is a simulator. */
object CheckText {
    const val SHOW_ME = "Show me the seal code."
    const val NO_CODE = "I can't read the seal code. Hold the seal closer and say check this box, or say scan with the phone."
    const val NO_SCAN = "No code was scanned. Say check this box to try again."
    const val TOO_LONG = "That code is too long to be a seal code."
    const val CODE_ONLY = "The seal photo was not sent, so only the code is checked."
    const val PHOTO_GONE = "The seal photo was not found. Checking the code only."
    const val VISUAL_TIMEOUT = "I couldn't check the seal."
    const val VISUAL_PENDING = "Still checking the seal. Say make a claim in a moment."
    const val NOTHING_TO_CLAIM = "There is nothing to claim: the unit is new and the seal looks intact."
    const val CHECK_FIRST = "Check a box first, then say make a claim."
    const val EVIDENCE_OPEN = "The evidence page is open on the phone."
    const val CLOSED = "Box check closed."
    const val BUSY = "Still checking. One moment."
    const val CONSENT_SPOKEN = "Photos on this site need your OK once. Faces are blurred on the phone. Tap Agree, or say I agree. Or tap Check by code only."

    /** The spoken answer when the server sent no `say` (an older or broken body): the headline only, no numbers. */
    fun fallbackSay(c: AuthenticityCheck): String = c.verdict.headline + "."

    /** True when a claim can be made from this check (contract §4.4): final, and not genuine-new with an intact seal. */
    fun claimable(c: AuthenticityCheck): Boolean = c.final && !(c.verdict == Verdict.GENUINE_NEW && c.tamper != true)

    /** S1 as one line. */
    fun signature(c: SealSignal?): String = when (c?.status) {
        null -> "Seal code: not read"
        "valid" -> "Signed by the maker: ${c.oemName ?: c.oem ?: "the maker"}"
        "bad_signature", "unknown_key" -> "Not signed by the maker's key"
        "not_a_seal_code" -> "Not a seal code"
        "unknown_oem" -> "The maker is not known"
        "bad_payload" -> "The code is not in the maker's format"
        "oem_unavailable" -> "The maker's records cannot be reached"
        "oem_not_configured" -> "No maker is connected for this check"
        else -> "Seal code: ${c.status.replace('_', ' ')}"
    }

    /** The unit's identity as the seal says it, or null when the payload did not parse. */
    fun unit(c: SealSignal?): String? = c?.serial?.let { s -> "Serial $s" + (c.sku?.let { " · $it" } ?: "") }

    /** S3 as one line. */
    fun firstCheck(f: FirstCheckSignal?): String = when (f?.status) {
        "first" -> "First check: this one"
        "same_checker" -> "You checked it first${f.firstCheckedAt?.let { ", on ${date(it)}" } ?: ""}"
        "other_checker" -> "First checked${f.firstCheckedAt?.let { " on ${date(it)}" } ?: ""} by someone else"
        else -> "First check: not recorded"
    }

    /** S4 as one line; [pending] while the poll waits for the visual check. */
    fun visual(v: VisualSignal?, tamper: Boolean?): String = when {
        v == null || v.status == "none" -> "Seal photo: none sent"
        v.status == "pending" -> "Checking the seal…"
        v.status == "failed" -> "The seal could not be checked"
        tamper == true || v.signs.isNotEmpty() -> "Seal: " + v.signs.joinToString(", ") { sign(it) }.ifEmpty { "tamper signs seen" }
        v.sealFound == false -> "Seal not found in the photo"
        else -> "Seal looks intact"
    }

    fun sign(s: String): String = when (s) {
        "tape_over_seal" -> "tape over the original"
        "seal_torn" -> "a torn seal"
        "reglued" -> "signs of re-gluing"
        "sticker_over_seal" -> "a sticker over the seal"
        "seal_missing" -> "no seal"
        else -> s.replace('_', ' ')
    }

    fun event(type: String): String = when (type) {
        "manufactured" -> "Made"
        "shipped_to_seller" -> "Shipped to the seller"
        "delivered" -> "Delivered"
        "activated" -> "Activated"
        "returned" -> "Returned"
        "refurbished" -> "Refurbished"
        else -> type.replace('_', ' ').replaceFirstChar { it.uppercase() }
    }

    /** True for the events that make a unit not new (shown in amber on the timeline). */
    fun notNewEvent(type: String): Boolean = type == "activated" || type == "returned" || type == "refurbished"

    /** The history timeline, oldest first as the server sent it: "30 Sep 2026 · Made". */
    fun timeline(r: RegistrySignal?): List<String> = r?.events.orEmpty().map { e ->
        listOfNotNull(e.at?.let(::date), event(e.type), e.area).joinToString(" · ")
    }

    /** The registry when it has no events to show. */
    fun registry(r: RegistrySignal?): String? = when (r?.status) {
        null, "found" -> null
        "not_asked" -> "History: not asked (the code did not verify)"
        "unknown_unit" -> "History: the maker has no record of this unit"
        "sku_mismatch" -> "History: the maker's records do not match this code"
        "unavailable" -> "History: the maker's records cannot be reached"
        else -> "History: ${r.status.replace('_', ' ')}"
    }

    private val DAY = DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH)

    /** "2026-09-30" or an ISO time -> "30 Sep 2026"; anything else as it came. */
    fun date(s: String): String =
        runCatching { LocalDate.parse(s.take(10)).format(DAY) }.getOrNull()
            ?: runCatching { OffsetDateTime.parse(s).toLocalDate().format(DAY) }.getOrNull()
            ?: s

    /** Today's "Check a delivered box" card: whenever the phone is linked to a Field site and the server has not said 403. */
    fun cardVisible(linkedToSite: Boolean, allowed: Boolean): Boolean = linkedToSite && allowed
}
