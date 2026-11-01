package com.scmtips.field.app.ui.homes

import com.scmtips.field.app.check.CheckState
import com.scmtips.field.app.home.CaseStart
import com.scmtips.field.app.home.SandboxStart
import com.scmtips.field.app.home.SandboxStarters
import com.scmtips.field.app.home.TodayModel
import com.scmtips.field.app.jobs.JobTask
import com.scmtips.field.app.jobs.JobType
import com.scmtips.field.app.jobs.JobRunner
import com.scmtips.field.app.look.Claim
import com.scmtips.field.app.look.ClaimText
import com.scmtips.field.app.shell.HomeRules
import com.scmtips.field.feature.decisions.api.NextItem
import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime

// Pure models of the four role homes (M5-U03, prototype WarehouseHome / TowerHome / ApprovalsInbox / ScanSeal
// .dc.html). Each is built from the app's real state only (HomeModelsFromUi.kt reads AppUi into these builders); a
// home with nothing real to show is empty, never filled with sample data. JVM-tested in HomeModelsTest.

/** Open work in the order the phone should offer it: a started job first, then the oldest (UUIDv7 ids sort by time). */
object WorkOrder {
    fun next(tasks: List<JobTask>): JobTask? =
        tasks.firstOrNull { it.status == "in_progress" } ?: tasks.minByOrNull { it.id.lowercase() }
}

// ---------------------------------------------------------------- Warehouse

sealed interface NextUp {
    /** An assigned job; [look] when it is a receipt (one look counts it: "Start · say look"). */
    data class Task(val taskId: String, val title: String, val sub: String, val started: Boolean, val look: Boolean) : NextUp

    /** Nothing to receive on a sandbox site: the first home test case, as Today offers it. */
    data class Case(val start: CaseStart) : NextUp
}

/** One of the four work tiles (receive, put away, pick, count) with the real count of open jobs of that kind. */
data class WorkTile(val type: JobType, val label: String, val count: Int, val sub: String, val taskId: String?)

data class WarehouseHomeModel(
    val headline: String,
    val nextUp: NextUp?,
    val tiles: List<WorkTile>,
    /** The M5 home test cases (sandbox sites only), then the M3 sandbox starters. */
    val cases: List<CaseStart>,
    val sandboxStarts: List<SandboxStart>,
    val sandbox: Boolean,
    /** Linked to a Field site; false: no jobs can come yet (the shell's connection card says why). */
    val linked: Boolean,
    val loading: Boolean,
) {
    /** Linked, loaded, and nothing assigned or startable: the designed empty state. */
    val empty: Boolean get() = linked && !loading && nextUp == null && tiles.all { it.count == 0 } && cases.isEmpty() && sandboxStarts.isEmpty()

    companion object {
        val TILE_TYPES = listOf(JobType.RECEIVE, JobType.PUTAWAY, JobType.PICK, JobType.COUNT)

        fun of(tasks: List<JobTask>, sandbox: Boolean, fieldWork: Boolean, linked: Boolean, loading: Boolean): WarehouseHomeModel {
            val work = if (linked) HomeRules.warehouseTasks(tasks) else emptyList()
            val offerSandbox = sandbox && fieldWork && linked
            val cases = CaseStart.offered(offerSandbox)
            val receive = WorkOrder.next(work.filter { it.type == JobType.RECEIVE })
            val next = when {
                receive != null -> task(receive)
                cases.isNotEmpty() -> NextUp.Case(cases.first())
                else -> WorkOrder.next(work)?.let(::task)
            }
            val starters = TodayModel.starters(work).associateBy { it.type }
            val tiles = if (!linked) emptyList() else TILE_TYPES.map { type ->
                val n = work.count { it.type == type }
                WorkTile(type, starters[type]?.label ?: type.wire, n, tileSub(type, n), starters[type]?.taskId)
            }
            return WarehouseHomeModel(
                headline = headline(work.size, linked),
                nextUp = next,
                tiles = tiles,
                cases = cases,
                sandboxStarts = SandboxStarters.offered(offerSandbox),
                sandbox = sandbox,
                linked = linked,
                loading = loading,
            )
        }

        private fun task(t: JobTask): NextUp.Task = TodayModel.card(t).let { c ->
            NextUp.Task(t.id, c.title, c.sub, t.status == "in_progress", t.type == JobType.RECEIVE)
        }

        fun headline(n: Int, linked: Boolean): String = when {
            !linked -> "No field site linked"
            n == 0 -> "Nothing assigned right now"
            else -> "$n ${JobRunner.plural(n, "task")} today"
        }

        fun tileSub(type: JobType, n: Int): String = when (type) {
            JobType.RECEIVE -> if (n == 0) "No delivery waiting" else if (n == 1) "Delivery waiting" else "Deliveries waiting"
            JobType.PUTAWAY -> if (n == 0) "Nothing to store" else "To store"
            JobType.PICK -> if (n == 0) "No order to pick" else if (n == 1) "Order to pick" else "Orders to pick"
            JobType.COUNT -> if (n == 0) "No count assigned" else if (n == 1) "Bin to count" else "Bins to count"
            JobType.AUDIT, JobType.SWAP -> ""
        }
    }
}

// ---------------------------------------------------------------- Tower

data class TowerJob(val taskId: String, val letter: String, val title: String, val sub: String, val started: Boolean)

data class TowerHomeModel(
    val headline: String,
    /** An open site visit at this site (the job runner's check-in: location and work permit). */
    val checkedIn: Boolean,
    /** The job the check-in card opens (its first step is the check-in); null when there is no tower job. */
    val checkInTaskId: String?,
    val jobs: List<TowerJob>,
    val linked: Boolean,
    val loading: Boolean,
) {
    val empty: Boolean get() = linked && !loading && jobs.isEmpty()

    companion object {
        fun of(tasks: List<JobTask>, siteId: String?, visitId: String?, visitSiteId: String?, linked: Boolean, loading: Boolean): TowerHomeModel {
            val tower = if (linked) HomeRules.towerTasks(tasks) else emptyList()
            val checkedIn = visitId != null && (visitSiteId == null || visitSiteId == siteId)
            val first = WorkOrder.next(tower)
            val ordered = listOfNotNull(first) + tower.filter { it.id != first?.id }.sortedBy { it.id.lowercase() }
            val jobs = ordered.map { t ->
                TowerJob(t.id, if (t.type == JobType.SWAP) "S" else "A", t.title, TodayModel.card(t).sub, t.status == "in_progress")
            }
            val n = jobs.size
            return TowerHomeModel(
                headline = when {
                    !linked -> "No field site linked"
                    n == 0 -> "No tower jobs right now"
                    else -> "$n tower ${JobRunner.plural(n, "job")}"
                },
                checkedIn = checkedIn,
                checkInTaskId = first?.id,
                jobs = jobs,
                linked = linked,
                loading = loading,
            )
        }
    }
}

// ---------------------------------------------------------------- Approvals

enum class ApprovalFilter(val label: String) { ALL("All"), DECISIONS("Decisions"), CLAIMS("Claims") }

enum class ApprovalKind(val label: String) { DECISION("DECISION"), CLAIM("CLAIM"), BOX_CHECK("BOX CHECK") }

/** Where a tap goes: the voice review of decisions (one at a time, longest waiting first) or of draft claims. */
enum class ApprovalTarget { DECISIONS, CLAIMS }

data class ApprovalItem(
    val key: String,
    val kind: ApprovalKind,
    val title: String,
    val sub: String,
    val time: String,
    /** Less than a day left, or overdue: the time is drawn in the warning colour. */
    val urgent: Boolean,
    val target: ApprovalTarget,
)

data class ApprovalsHomeModel(
    val headline: String,
    val decisions: Int,
    val claims: Int,
    val items: List<ApprovalItem>,
    /** Still asking the core / field-api how much is waiting. */
    val checking: Boolean,
) {
    val total: Int get() = decisions + claims
    val empty: Boolean get() = !checking && items.isEmpty()

    fun count(f: ApprovalFilter): Int = when (f) {
        ApprovalFilter.ALL -> total
        ApprovalFilter.DECISIONS -> decisions
        ApprovalFilter.CLAIMS -> claims
    }

    /** "All 3", "Decisions 1", "Claims 2" (ApprovalsInbox.dc.html's filter chips). */
    fun chip(f: ApprovalFilter): String = "${f.label} ${count(f)}"

    fun shown(f: ApprovalFilter): List<ApprovalItem> = when (f) {
        ApprovalFilter.ALL -> items
        ApprovalFilter.DECISIONS -> items.filter { it.target == ApprovalTarget.DECISIONS }
        ApprovalFilter.CLAIMS -> items.filter { it.target == ApprovalTarget.CLAIMS }
    }

    companion object {
        /**
         * [decisionsWaiting] and [claimsWaiting] are the counts AppUi has today (null: not asked or not this person's
         * to decide). [nextDecision] (the core's `GET /v1/wearable/next` item) and [draftClaims] (field-api's
         * `GET /v1/claims?status=draft` list) give real titles when the integrator passes them; without them the
         * home lists one honest summary row per kind ("2 decisions waiting"), never invented titles.
         * Order: decisions with a deadline by time left, other decisions, then claims newest first (field-api lists
         * oldest first).
         */
        fun of(
            decisionsWaiting: Int?,
            claimsWaiting: Int?,
            nextDecision: NextItem? = null,
            draftClaims: List<Claim>? = null,
            approver: Boolean,
            nowMs: Long,
        ): ApprovalsHomeModel {
            val items = mutableListOf<ApprovalItem>()
            val decisions = maxOf(decisionsWaiting ?: 0, if (nextDecision != null) 1 else 0)
            nextDecision?.let { d ->
                val left = timeLeft(d.deadlineAt, nowMs)
                items += ApprovalItem(
                    key = "decision:${d.decisionId}",
                    kind = ApprovalKind.DECISION,
                    title = d.title.ifBlank { "Decision waiting" },
                    sub = if (d.options.isEmpty()) "Listen to the brief" else "${d.options.size} ${JobRunner.plural(d.options.size, "option")} · listen to the brief",
                    time = left?.text ?: "Waiting",
                    urgent = left?.urgent ?: false,
                    target = ApprovalTarget.DECISIONS,
                )
            }
            val more = decisions - (if (nextDecision != null) 1 else 0)
            if (more > 0) {
                items += ApprovalItem(
                    key = "decisions:more",
                    kind = ApprovalKind.DECISION,
                    title = if (nextDecision != null) "$more more ${JobRunner.plural(more, "decision")} waiting"
                    else "$more ${JobRunner.plural(more, "decision")} waiting",
                    sub = "Hear the longest waiting first and decide by voice",
                    time = "Waiting",
                    urgent = false,
                    target = ApprovalTarget.DECISIONS,
                )
            }
            val claims = draftClaims?.size ?: claimsWaiting ?: 0
            if (draftClaims != null) {
                draftClaims.asReversed().forEach { c -> items += claimItem(c) }
            } else if (claims > 0) {
                items += ApprovalItem(
                    key = "claims:summary",
                    kind = ApprovalKind.CLAIM,
                    title = "$claims draft ${JobRunner.plural(claims, "claim")} waiting",
                    sub = "Hear each one, then approve or reject by voice",
                    time = "Draft",
                    urgent = false,
                    target = ApprovalTarget.CLAIMS,
                )
            }
            val checking = approver && decisionsWaiting == null && nextDecision == null
            val total = decisions + claims
            return ApprovalsHomeModel(
                headline = when {
                    total > 0 -> "$total waiting for you"
                    checking -> "Checking what waits for you…"
                    else -> "Nothing waiting for you"
                },
                decisions = decisions,
                claims = claims,
                items = items,
                checking = checking && total == 0,
            )
        }

        fun claimItem(c: Claim): ApprovalItem = ApprovalItem(
            key = "claim:${c.claimId}",
            kind = if (c.authenticity) ApprovalKind.BOX_CHECK else ApprovalKind.CLAIM,
            title = c.title?.let { if (c.authenticity) it else "Supplier claim: $it" }
                ?: if (c.authenticity) "Box check: unit may not be new" else "Supplier claim",
            sub = ClaimText.lines(c).replaceFirstChar(Char::uppercaseChar),
            time = "Draft",
            urgent = false,
            target = ApprovalTarget.CLAIMS,
        )

        data class TimeLeft(val text: String, val urgent: Boolean)

        /** "2 d 23 h left", "5 h 10 min left", "12 min left", "Overdue"; null when there is no readable deadline. */
        fun timeLeft(deadlineIso: String?, nowMs: Long): TimeLeft? {
            val at = parse(deadlineIso) ?: return null
            val left = Duration.ofMillis(at.toEpochMilli() - nowMs)
            if (left.isNegative || left.isZero) return TimeLeft("Overdue", true)
            val d = left.toDays()
            val h = left.toHours() % 24
            val m = left.toMinutes() % 60
            val text = when {
                d > 0 -> "$d d $h h left"
                h > 0 -> "$h h $m min left"
                else -> "${maxOf(m, 1)} min left"
            }
            return TimeLeft(text, left < Duration.ofDays(1))
        }

        private fun parse(s: String?): Instant? {
            val v = s?.trim()?.takeIf { it.isNotEmpty() } ?: return null
            return runCatching { Instant.parse(v) }.getOrNull() ?: runCatching { OffsetDateTime.parse(v).toInstant() }.getOrNull()
        }
    }
}

// ---------------------------------------------------------------- Scan product

enum class ScanHomeState { READY, RUNNING, NOT_LINKED, NOT_ALLOWED }

data class ScanHomeModel(val state: ScanHomeState, val running: String?) {
    companion object {
        const val TITLE = "Is this unit really new?"
        const val BODY = "Scan the maker's seal. The maker's records show if this unit was sold, returned or activated before."
        const val VOICE_HINT = "Say \"check this box\" · hold it 20 to 30 cm away"
        const val NOT_LINKED = "Link this phone to a Field site first. Then any Field role can check a box."
        const val NOT_ALLOWED = "You are not allowed to check boxes at this site. Another site or sign-in may allow it."

        /** As Today's card (CheckText.cardVisible): linked to a site and no 403 from field-api yet. */
        fun of(linked: Boolean, allowed: Boolean, checkState: CheckState): ScanHomeModel = when {
            !linked -> ScanHomeModel(ScanHomeState.NOT_LINKED, null)
            !allowed -> ScanHomeModel(ScanHomeState.NOT_ALLOWED, null)
            checkState != CheckState.IDLE -> ScanHomeModel(ScanHomeState.RUNNING, checkState.text)
            else -> ScanHomeModel(ScanHomeState.READY, null)
        }
    }
}
