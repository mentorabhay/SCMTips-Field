package com.scmtips.field.app.ui.kit

import com.scmtips.field.app.check.AuthenticityCheck
import com.scmtips.field.app.check.CheckState
import com.scmtips.field.app.check.CheckText
import com.scmtips.field.app.check.Verdict
import com.scmtips.field.app.check.VerdictTone
import com.scmtips.field.app.jobs.StepKind
import com.scmtips.field.app.jobs.StepView
import com.scmtips.field.app.look.Look
import com.scmtips.field.feature.decisions.api.NextItem
import com.scmtips.field.feature.decisions.flow.CardFormatter
import com.scmtips.field.feature.decisions.flow.DecisionCard

/*
 * The pure rules behind the M5-U task screens (A-07; prototype ReceiveLook … ScanVerdict). Pure Kotlin, no Android
 * or Compose imports: the JVM job tests every rule here (TaskModelTest). The Compose layer (TaskChrome.kt,
 * HintAnimations.kt and the screens) only draws what these functions return. Nothing here changes what a job, a
 * check or a decision does: the step a screen shows, its words and its callbacks all come from the existing views.
 */

/** The six drawn hints of the blueprint; each has its own short text and a description for TalkBack. */
enum class Hint(val title: String, val text: String, val description: String) {
    LOOK(
        "Look at the delivery",
        "Stand 40 to 50 cm back so all packs fit. Press the glasses button or say “look”.",
        "Glasses with a pulsing capture button; numbered outlines pop onto the boxes",
    ),
    SAY_NUMBERS(
        "Say your numbers",
        "Say “receive 7, flag 1”. What posts is always what you say.",
        "A speech bubble types receive 7, flag 1 and two number boxes fill",
    ),
    CONFIRM(
        "Confirm within 10 seconds",
        "Nothing posts until you confirm. Say “yes” or “confirm” within 10 seconds.",
        "A ring counts down around a tick",
    ),
    SCAN_BIN_PRODUCT(
        "Scan the bin, then the product",
        "Scan the bin label first, then the label on the product.",
        "A scan line sweeps a bin label, then a product label, and each gets a tick",
    ),
    SEAL_CODE(
        "Point at the seal code",
        "Hold the box 20 to 30 cm away and point at the maker's seal code.",
        "A corner frame closes on a QR code, then Code read appears",
    ),
    CLIP_IN(
        "Clip in before you climb",
        "Both are needed within 10 seconds: say “harness clipped” and tap the button.",
        "A harness hook snaps shut; the button and the phrase light up together",
    ),
}

/** Which background a task step is drawn on: Night (#0F1013) for camera and task steps, Ground for results. */
enum class Backdrop { NIGHT, GROUND }

/**
 * What the step header and the chrome show for one job step: "Receive grocery delivery · Step 1 of 3 · Look",
 * the segment bar, which hint plays (and its first-time key), the voice chip and the backdrop.
 */
data class StepChrome(
    val title: String,
    /** 1-based segment of [segments]. */
    val segment: Int,
    val segments: Int,
    val segmentName: String,
    val hint: Hint?,
    /** Key of the first-time rule (task type + step); null when no hint plays. */
    val hintKey: String?,
    /** "Say “look”" and the like; only phrases the job grammar understands. Null: no chip. */
    val voice: String?,
    val backdrop: Backdrop,
) {
    val subtitle: String get() = "Step $segment of $segments · $segmentName"
}

/** Step numbering per task type: three named segments for every job type (blueprint), mapped from the runner's step. */
object TaskSteps {
    private val SEGMENTS = mapOf(
        "Receive" to listOf("Look", "Check", "Confirm"),
        "Practice" to listOf("Scan", "Count", "Confirm"),
        "Pick" to listOf("Go", "Pick", "Post"),
        "Put away" to listOf("Scan", "Store", "Finish"),
        "Count" to listOf("Go", "Count", "Send"),
        "Recount" to listOf("Go", "Count", "Send"),
        "Site visit" to listOf("Safety", "Slots", "Finish"),
        "Swap" to listOf("Check in", "Swap", "Post"),
    )

    /** The segment names of a job kind ([StepView.jobKind]); empty for a kind this table does not know. */
    fun segmentsFor(jobKind: String): List<String> = SEGMENTS[jobKind].orEmpty()

    private val AFTER_WORK = setOf(StepKind.REVIEW, StepKind.CONFIRM, StepKind.WAITING, StepKind.DONE, StepKind.FAILED)

    /** 1-based segment for this step; the runner's own n of m when the kind is unknown. */
    fun segmentOf(v: StepView): Int {
        val k = v.kind
        return when (v.jobKind) {
            "Receive", "Practice" -> when (k) {
                StepKind.INFO, StepKind.SCAN -> 1
                StepKind.COUNT, StepKind.REVIEW -> 2
                else -> 3
            }
            "Pick", "Count", "Recount" -> when {
                k in AFTER_WORK -> 3
                k == StepKind.INFO -> 1
                else -> 2
            }
            "Put away" -> when {
                k in AFTER_WORK -> 3
                k == StepKind.SCAN && v.where == null -> 1 // the pallet label; the bin scan shows its bin
                else -> 2
            }
            "Site visit" -> when {
                k == StepKind.SCAN -> 2
                k == StepKind.CHECKIN || k == StepKind.CHECK -> 1
                k == StepKind.CLIMB -> if (v.stepNo * 2 <= v.stepCount) 1 else 3 // the climb up comes before the slots
                k == StepKind.INFO -> 3 // check out
                else -> 3
            }
            "Swap" -> when {
                k == StepKind.CHECKIN -> 1
                k in AFTER_WORK -> 3
                else -> 2
            }
            else -> v.stepNo.coerceIn(1, v.stepCount.coerceAtLeast(1))
        }
    }

    /** Which hint plays on this step, or null. [canLook] is the step's own flag (receive jobs, not practice). */
    fun hintFor(v: StepView): Hint? {
        val seg = segmentOf(v)
        return when {
            v.kind == StepKind.CONFIRM -> Hint.CONFIRM
            v.jobKind == "Receive" && seg == 1 && v.canLook -> Hint.LOOK
            v.jobKind == "Receive" && v.kind == StepKind.COUNT -> Hint.SAY_NUMBERS
            v.kind == StepKind.SCAN && v.jobKind in setOf("Pick", "Put away", "Count", "Recount") -> Hint.SCAN_BIN_PRODUCT
            v.kind == StepKind.CLIMB && v.jobKind == "Site visit" && seg == 1 -> Hint.CLIP_IN
            else -> null
        }
    }

    /** The voice chip: only words the job grammar parses (look, receive N flag M, all here, post, yes, cancel, clipped). */
    fun voiceFor(v: StepView, look: Look?): String? {
        val p = look?.proposal
        return when (v.kind) {
            StepKind.CONFIRM -> if (v.listening) "Say “yes” or “cancel”" else null
            StepKind.REVIEW -> if (v.primary != null && v.primaryEnabled) "Say “post”" else null
            StepKind.COUNT -> when {
                v.jobKind == "Receive" && p?.receive != null ->
                    "Say “receive ${p.receive}${p.flag?.takeIf { it > 0 }?.let { ", flag $it" } ?: ""}”"
                v.expected != null -> "Say a number, or “all here”"
                else -> "Say a number"
            }
            StepKind.CLIMB -> if (segmentOf(v) == 1) "Say “harness clipped”" else "Say “clipped” at each platform"
            StepKind.INFO, StepKind.SCAN -> if (v.canLook) "Say “look” · Glasses camera" else null
            else -> null
        }
    }

    /** Night for camera and work steps (and every climb-safe step), Ground for the check, review and result steps. */
    fun backdropFor(v: StepView): Backdrop = when {
        v.dark || v.jobKind == "Site visit" -> Backdrop.NIGHT
        v.kind in setOf(StepKind.COUNT, StepKind.REVIEW, StepKind.DONE, StepKind.FAILED) -> Backdrop.GROUND
        else -> Backdrop.NIGHT
    }

    fun of(v: StepView, look: Look? = null): StepChrome {
        val names = segmentsFor(v.jobKind)
        val seg = segmentOf(v)
        val hint = hintFor(v)
        return StepChrome(
            title = v.jobTitle,
            segment = seg,
            segments = if (names.isEmpty()) v.stepCount.coerceAtLeast(1) else names.size,
            segmentName = names.getOrNull(seg - 1) ?: v.jobKind,
            hint = hint,
            hintKey = hint?.let { hintKey(v.jobKind, seg, it) },
            voice = voiceFor(v, look),
            backdrop = backdropFor(v),
        )
    }

    /** First-time key: task type + step (+ the hint, so a step that changes hint is new again). */
    fun hintKey(taskType: String, segment: Int, hint: Hint): String = "$taskType|$segment|${hint.name}"

    /** The box check's hint: the seal code, while no verdict is up (prototype ScanSeal). */
    fun checkHint(state: CheckState, hasVerdict: Boolean): Hint? =
        if (!hasVerdict && state in setOf(CheckState.IDLE, CheckState.CAPTURING, CheckState.NO_CODE, CheckState.SCANNING)) Hint.SEAL_CODE else null

    const val CHECK_HINT_KEY = "Box check|1|SEAL_CODE"
}

/** Where the "already shown" keys live (SharedPreferences on the phone, a set in tests). */
interface HintStore {
    fun load(): Set<String>
    fun save(keys: Set<String>)
}

class MemoryHintStore(initial: Set<String> = emptySet()) : HintStore {
    private var keys = initial
    override fun load(): Set<String> = keys
    override fun save(keys: Set<String>) { this.keys = keys }
}

/**
 * The first-time rule: a hint plays by itself the first time its step opens (per task type and step), never again
 * by itself; "?" replays it at any time ([replay] does not need the memory).
 */
class HintMemory(private val store: HintStore) {
    private val shown = store.load().toMutableSet()

    /** True the first time [key] is asked; it is remembered at once, so the next open of that step stays quiet. */
    fun autoShow(key: String?): Boolean {
        if (key == null) return false
        if (key in shown) return false
        shown += key
        store.save(shown.toSet())
        return true
    }

    fun seen(key: String): Boolean = key in shown
}

/**
 * The confirm ring (prototype ReceivePost): driven by the job's spoken-confirm deadline. The runner gives a staged
 * "post" [WINDOW_MS] to hear "yes" (JobRunner confirmWindowMs, FieldController's 1 s tick cancels it after); the
 * screen anchors the ring at the moment the step starts listening.
 */
object ConfirmRingMath {
    /** JobRunner's default confirm window (FieldController builds the runner without changing it). */
    const val WINDOW_MS = 10_000L

    fun remainingMs(startedAtMs: Long, nowMs: Long, windowMs: Long = WINDOW_MS): Long =
        (windowMs - (nowMs - startedAtMs)).coerceIn(0L, windowMs)

    /** 1 at the start, 0 when the window is over (the ring's sweep). */
    fun progress(startedAtMs: Long, nowMs: Long, windowMs: Long = WINDOW_MS): Float =
        if (windowMs <= 0) 0f else remainingMs(startedAtMs, nowMs, windowMs).toFloat() / windowMs

    /** Whole seconds left, rounded up: 10 at the start, 0 only when the window is over. */
    fun secondsLeft(startedAtMs: Long, nowMs: Long, windowMs: Long = WINDOW_MS): Int =
        ((remainingMs(startedAtMs, nowMs, windowMs) + 999) / 1000).toInt()

    /** The ring turns red for the last 3 seconds. */
    fun urgent(secondsLeft: Int): Boolean = secondsLeft <= 3
}

enum class VerdictIcon { TICK, WARN, CROSS }

/** The verdict card (prototype ScanVerdict): colours as ARGB, so this stays pure. */
data class VerdictLook(val title: String, val ink: Long, val bg: Long, val icon: VerdictIcon)

enum class SignalTone(val dot: Long) { GOOD(0xFF157A3C), AMBER(0xFFA15C07), BAD(0xFFB3261E), GREY(0xFF4B5160) }

data class SignalRow(val name: String, val value: String, val tone: SignalTone)

object VerdictStyle {
    fun of(v: Verdict): VerdictLook = when (v.tone) {
        VerdictTone.GREEN -> VerdictLook(v.headline, 0xFF157A3C, 0xFFE6F4EA, VerdictIcon.TICK)
        VerdictTone.AMBER -> VerdictLook(v.headline, 0xFFA15C07, 0xFFFEF3C7, VerdictIcon.WARN)
        VerdictTone.RED -> VerdictLook(v.headline, 0xFFB3261E, 0xFFFDECEA, VerdictIcon.CROSS)
        VerdictTone.GREY -> VerdictLook(v.headline, 0xFF4B5160, 0xFFEEF0F3, VerdictIcon.WARN)
    }

    /** The four signals in the prototype's order: signed code, history, first check, seal; words from [CheckText]. */
    fun signals(c: AuthenticityCheck, visualPending: Boolean): List<SignalRow> {
        val code = c.code
        val sig = when (code?.status) {
            "valid" -> SignalTone.GOOD
            null, "oem_unavailable", "oem_not_configured" -> SignalTone.GREY
            else -> SignalTone.BAD
        }
        val events = c.registry?.events.orEmpty()
        val history = CheckText.registry(c.registry)
            ?: CheckText.timeline(c.registry).joinToString(", ").ifEmpty { "No history sent" }
        val historyTone = when {
            events.any { CheckText.notNewEvent(it.type) } -> SignalTone.AMBER
            c.registry?.status == "found" && events.isNotEmpty() -> SignalTone.GOOD
            c.registry?.status in setOf("unknown_unit", "sku_mismatch") -> SignalTone.BAD
            else -> SignalTone.GREY
        }
        val first = when (c.firstCheck?.status) {
            "first", "same_checker" -> SignalTone.GOOD
            "other_checker" -> SignalTone.AMBER
            else -> SignalTone.GREY
        }
        val v = c.visual
        val seal = when {
            visualPending -> SignalTone.GREY
            c.tamper == true -> SignalTone.AMBER
            v != null && v.status == "done" && v.sealFound != false -> SignalTone.GOOD
            v?.sealFound == false -> SignalTone.AMBER
            else -> SignalTone.GREY
        }
        return listOf(
            SignalRow("Signed code", CheckText.signature(code) + (CheckText.unit(code)?.let { " · $it" } ?: ""), sig),
            SignalRow("History", history, historyTone),
            SignalRow("First check", CheckText.firstCheck(c.firstCheck), first),
            SignalRow("Seal", if (visualPending) "Checking the seal…" else CheckText.visual(v, c.tamper), seal),
        )
    }
}

/** One option card of a decision: the "Approve X" buttons of the card, in order. */
data class OptionRow(val letter: String, val buttonId: String)

/** The decision detail (prototype DecisionDetail): options as cards, Approve / Reject at the bottom. */
object DecisionLayout {
    private const val APPROVE = "approve:"

    /** The brief is being spoken (DecisionText.state for FlowState.Presenting): the waveform plays. */
    fun briefPlaying(state: String): Boolean = state.startsWith("Speaking the brief")

    fun options(card: DecisionCard?): List<OptionRow> =
        card?.buttons.orEmpty().filter { it.id.startsWith(APPROVE) }.map { OptionRow(it.id.removePrefix(APPROVE), it.id) }

    /** The option picked on the phone: the one tapped if it is still on the card, else the card's primary, else the first. */
    fun picked(card: DecisionCard?, tapped: String?): OptionRow? {
        val opts = options(card)
        opts.firstOrNull { it.letter == tapped }?.let { return it }
        val primary = card?.buttons?.firstOrNull { it.primary && it.id.startsWith(APPROVE) }?.id
        return opts.firstOrNull { it.buttonId == primary } ?: opts.firstOrNull()
    }

    /** The read-back stage: the card asks Confirm / Cancel. */
    fun confirmStage(card: DecisionCard?): Boolean = card?.buttons.orEmpty().any { it.id == "confirm" }

    /** Card buttons this layout does not place (shown as quiet text buttons, so nothing the flow offers is lost). */
    fun others(card: DecisionCard?): List<String> =
        card?.buttons.orEmpty().map { it.id }.filterNot { it.startsWith(APPROVE) || it in setOf("reject", "confirm", "cancel") }

    /**
     * M5-U06: the option titles and amounts of the core's [next] item, by letter, when it is the decision on [card]
     * (the card carries no decision id, so its title is matched as CardFormatter built it). Another decision, no item,
     * or a letter the item does not have: no detail, and the card keeps "Option X". The amounts are the core's own
     * strings ("committed", "net"), never computed here.
     */
    fun optionDetails(card: DecisionCard?, next: NextItem?): Map<String, OptionDetail> {
        if (card == null || next == null) return emptyMap()
        if (CardFormatter.truncate(next.title, CardFormatter.MAX_TITLE_CHARS) != card.title) return emptyMap()
        val letters = options(card).map { it.letter }.toSet()
        return next.options.filter { it.letter in letters }.associate { o ->
            val cost = listOfNotNull(o.committed.trim().ifEmpty { null }?.let { "Commits $it" }, o.net.trim().ifEmpty { null }?.let { "Net $it" })
                .joinToString(" · ").ifEmpty { null }
            o.letter to OptionDetail(o.title.trim().ifEmpty { null }, cost)
        }.filterValues { it.title != null || it.cost != null }
    }
}

/** What an option card shows under "Option X" when the core's item is known (DecisionLayout.optionDetails). */
data class OptionDetail(val title: String?, val cost: String?)

/** The two answers of a look (prototype ReceiveAnswer): the first at once, "Reading the labels…", then the second. */
data class LookAnswers(val first: String?, val second: String?, val reading: Boolean)

object LookAnswerRules {
    /**
     * [rememberedFirst] is the first answer the screen saw while the labels were being read (the final look may not
     * carry it again). A one-step look has one answer, shown as the first.
     */
    fun of(look: Look?, labelsPending: Boolean, rememberedFirst: String?): LookAnswers {
        if (look == null) return LookAnswers(null, null, false)
        val say = look.say.takeIf { it.isNotBlank() }
        return when {
            labelsPending -> LookAnswers(say ?: rememberedFirst, null, true)
            look.sayNext != null -> LookAnswers(rememberedFirst ?: say, look.sayNext, false)
            rememberedFirst != null && say != null && say != rememberedFirst -> LookAnswers(rememberedFirst, say, false)
            else -> LookAnswers(say, null, false)
        }
    }
}
