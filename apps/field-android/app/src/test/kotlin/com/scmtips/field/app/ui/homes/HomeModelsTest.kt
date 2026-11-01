package com.scmtips.field.app.ui.homes

import com.scmtips.field.app.check.CheckState
import com.scmtips.field.app.home.CaseStart
import com.scmtips.field.app.home.SandboxStart
import com.scmtips.field.app.jobs.JobLine
import com.scmtips.field.app.jobs.JobTask
import com.scmtips.field.app.jobs.JobType
import com.scmtips.field.app.look.Claim
import com.scmtips.field.app.look.ClaimLine
import com.scmtips.field.feature.decisions.api.ItemOption
import com.scmtips.field.feature.decisions.api.NextItem
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/** The role homes' models from real app state (M5-U03): never sample data, designed empty states. */
class HomeModelsTest {
    // UUIDv7-like ids: lexical order is creation order
    private fun task(id: String, type: JobType, status: String = "pending", ref: String? = null, lines: Int = 1) =
        JobTask(id, type, status, "T $id", refDocNo = ref, lines = (1..lines).map { JobLine("$id-$it", it) })

    private val tasks = listOf(
        task("0192-c", JobType.RECEIVE, ref = "45000003"),
        task("0192-a", JobType.RECEIVE, ref = "45000001"),
        task("0192-b", JobType.PUTAWAY, lines = 2),
        task("0192-d", JobType.PICK),
        task("0192-e", JobType.AUDIT),
    )

    @Test
    fun m5U03_warehouse_nextUpIsTheOldestReceive_tilesCountRealJobs_towerJobsLeftOut() {
        val m = WarehouseHomeModel.of(tasks, sandbox = false, fieldWork = true, linked = true, loading = false)
        val next = m.nextUp as NextUp.Task
        assertEquals("0192-a", next.taskId)
        assertTrue(next.look)
        assertEquals("Receive · Delivery 4500 0001", next.title)
        assertEquals("4 tasks today", m.headline) // the site visit belongs to the Tower home
        assertEquals(listOf(2, 1, 1, 0), m.tiles.map { it.count })
        assertEquals(listOf("Receive", "Put away", "Pick", "Count a bin"), m.tiles.map { it.label })
        assertEquals(listOf("Deliveries waiting", "To store", "Order to pick", "No count assigned"), m.tiles.map { it.sub })
        assertNull(m.tiles[3].taskId)
        assertTrue(m.cases.isEmpty() && m.sandboxStarts.isEmpty())
        assertFalse(m.empty)
    }

    @Test
    fun m5U03_warehouse_aStartedJobComesFirst_elseTheOldestOfAnyKind() {
        val started = tasks + task("0192-z", JobType.RECEIVE, status = "in_progress")
        assertEquals("0192-z", (WarehouseHomeModel.of(started, false, true, true, false).nextUp as NextUp.Task).taskId)
        assertTrue((WarehouseHomeModel.of(started, false, true, true, false).nextUp as NextUp.Task).started)
        val noReceive = tasks.filter { it.type != JobType.RECEIVE }
        val n = WarehouseHomeModel.of(noReceive, false, true, true, false).nextUp as NextUp.Task
        assertEquals("0192-b", n.taskId); assertFalse(n.look)
    }

    @Test
    fun m5U03_warehouse_sandboxWithoutAReceive_offersTheFirstHomeCase_andTheStarters() {
        val m = WarehouseHomeModel.of(emptyList(), sandbox = true, fieldWork = true, linked = true, loading = false)
        assertEquals(NextUp.Case(CaseStart.GROCERY), m.nextUp)
        assertEquals(listOf(CaseStart.GROCERY, CaseStart.PHARMACY), m.cases)
        assertEquals(listOf(SandboxStart.HOME_RECEIPT, SandboxStart.COUNT_SHELF), m.sandboxStarts)
        assertFalse(m.empty)
        // sandbox starters need field work and a linked site, exactly as Today
        assertTrue(WarehouseHomeModel.of(emptyList(), true, fieldWork = false, linked = true, loading = false).cases.isEmpty())
    }

    @Test
    fun m5U03_warehouse_emptyAndUnlinked_areSaidAsTheyAre() {
        val empty = WarehouseHomeModel.of(emptyList(), false, true, linked = true, loading = false)
        assertTrue(empty.empty); assertNull(empty.nextUp); assertEquals("Nothing assigned right now", empty.headline)
        assertFalse(WarehouseHomeModel.of(emptyList(), false, true, linked = true, loading = true).empty) // still loading
        val unlinked = WarehouseHomeModel.of(tasks, false, true, linked = false, loading = false)
        assertEquals("No field site linked", unlinked.headline)
        assertTrue(unlinked.tiles.isEmpty()); assertNull(unlinked.nextUp); assertFalse(unlinked.empty)
    }

    @Test
    fun m5U03_tower_jobsAndCheckIn_fromTheOpenVisitAtThisSite() {
        val t = listOf(task("0192-b", JobType.SWAP), task("0192-a", JobType.AUDIT), task("0192-c", JobType.RECEIVE))
        val notIn = TowerHomeModel.of(t, siteId = "s1", visitId = null, visitSiteId = null, linked = true, loading = false)
        assertFalse(notIn.checkedIn)
        assertEquals("2 tower jobs", notIn.headline)
        assertEquals(listOf("A", "S"), notIn.jobs.map { it.letter })
        assertEquals("0192-a", notIn.checkInTaskId)
        assertTrue(TowerHomeModel.of(t, "s1", "v1", "s1", true, false).checkedIn)
        assertTrue(TowerHomeModel.of(t, "s1", "v1", null, true, false).checkedIn)
        assertFalse(TowerHomeModel.of(t, "s1", "v1", "s2", true, false).checkedIn) // a visit at another site
        val none = TowerHomeModel.of(listOf(t[2]), "s1", null, null, true, false)
        assertTrue(none.empty); assertNull(none.checkInTaskId); assertEquals("No tower jobs right now", none.headline)
    }

    private val now = Instant.parse("2026-11-01T10:00:00Z").toEpochMilli()

    @Test
    fun m5U03_approvals_countsOnly_giveHonestSummaryRows() {
        val m = ApprovalsHomeModel.of(decisionsWaiting = 2, claimsWaiting = 3, approver = true, nowMs = now)
        assertEquals("5 waiting for you", m.headline)
        assertEquals(listOf("All 5", "Decisions 2", "Claims 3"), ApprovalFilter.entries.map(m::chip))
        assertEquals(listOf("2 decisions waiting", "3 draft claims waiting"), m.items.map { it.title })
        assertEquals(listOf(ApprovalTarget.DECISIONS), m.shown(ApprovalFilter.DECISIONS).map { it.target })
        assertEquals(1, m.shown(ApprovalFilter.CLAIMS).size)
    }

    @Test
    fun m5U03_approvals_realItems_decisionByTimeLeft_thenClaimsNewestFirst_boxChecksAreMarked() {
        val next = NextItem("d1", "Magnet export curbs: choose the response", "", "", options = listOf(
            ItemOption("A", "o1", "x"), ItemOption("B", "o2", "y"), ItemOption("C", "o3", "z")), deadlineAt = "2026-11-04T09:00:00Z", waiting = 2)
        val oldest = Claim("c1", "draft", listOf(ClaimLine("damaged", 1, null), ClaimLine("pack_size", 1, null)), "", null, null, "grocery delivery")
        val newest = Claim("c2", "draft", listOf(ClaimLine("not_new", 1, 0)), "", null, null, null, kind = Claim.KIND_AUTHENTICITY, checkId = "k1")
        val m = ApprovalsHomeModel.of(decisionsWaiting = 2, claimsWaiting = 2, nextDecision = next, draftClaims = listOf(oldest, newest),
            approver = true, nowMs = now)
        assertEquals(listOf("decision:d1", "decisions:more", "claim:c2", "claim:c1"), m.items.map { it.key })
        assertEquals("2 d 23 h left", m.items[0].time); assertFalse(m.items[0].urgent)
        assertEquals("3 options · listen to the brief", m.items[0].sub)
        assertEquals("1 more decision waiting", m.items[1].title)
        assertEquals(ApprovalKind.BOX_CHECK, m.items[2].kind); assertEquals("Not a new unit", m.items[2].sub)
        assertEquals("Supplier claim: grocery delivery", m.items[3].title)
        assertEquals("1 unit damaged, 1 unit wrong pack size", m.items[3].sub)
        assertEquals("All 4", m.chip(ApprovalFilter.ALL))
        assertEquals(2, m.shown(ApprovalFilter.CLAIMS).size)
    }

    @Test
    fun m5U06_approvals_fromTheKeptNextDecisionAndDraftList_haveRealTitles() {
        // What FieldController now keeps from the calls it already makes (GET /v1/wearable/next, GET /v1/claims).
        val next = NextItem("d7", "Reroute PO 4500 0007 via Pune", "", "", options = listOf(ItemOption("A", "o1", "Reroute"),
            ItemOption("B", "o2", "Wait")), deadlineAt = "2026-11-01T20:00:00Z", waiting = 1)
        val decisions = com.scmtips.field.app.decisions.DecisionsView(waiting = 1, next = next)
        val draft = Claim("c9", "draft", listOf(ClaimLine("short", 2, null)), "", null, null, "pharmacy delivery")
        val claims = com.scmtips.field.app.look.ClaimsView(waiting = 1, drafts = listOf(draft))
        val m = ApprovalsHomeModel.of(decisions.waiting, claims.waiting, decisions.next, claims.drafts, approver = true, nowMs = now)
        assertEquals(listOf("decision:d7", "claim:c9"), m.items.map { it.key })
        assertEquals("Reroute PO 4500 0007 via Pune", m.items[0].title)
        assertEquals("2 options · listen to the brief", m.items[0].sub)
        assertTrue(m.items[0].urgent) // 10 h left
        assertEquals("Supplier claim: pharmacy delivery", m.items[1].title)
        assertEquals("2 waiting for you", m.headline)
        // Before the first answer the views carry nothing: the honest summary rows, never invented titles.
        val none = ApprovalsHomeModel.of(2, 1, com.scmtips.field.app.decisions.DecisionsView(waiting = 2).next,
            com.scmtips.field.app.look.ClaimsView(waiting = 1).drafts, approver = true, nowMs = now)
        assertEquals(listOf("decisions:more", "claims:summary"), none.items.map { it.key })
    }

    @Test
    fun m5U06_jobNextUp_isTheNextOtherJob_receiptsFirst_towerAfterTower_noneForPractice() {
        // Finishing the oldest receipt: the other receipt is next (never the job just done, never a sandbox case).
        val afterReceipt = JobNextUp.of(tasks, "0192-a", practice = false, linked = true)!!
        assertEquals("0192-c", afterReceipt.taskId)
        assertTrue(afterReceipt.look)
        // Finishing the put-away with both receipts done: the pick (the oldest left of any warehouse kind).
        val left = tasks.filter { it.id !in setOf("0192-a", "0192-c") }
        assertEquals("0192-d", JobNextUp.of(left, "0192-b", practice = false, linked = true)!!.taskId)
        // A tower job is followed by the next tower job only.
        val tower = tasks + task("0192-f", JobType.SWAP)
        assertEquals("0192-f", JobNextUp.of(tower, "0192-e", practice = false, linked = true)!!.taskId)
        assertNull(JobNextUp.of(tasks, "0192-e", practice = false, linked = true))
        // Practice, an unknown job, nothing left, or no site: none.
        assertNull(JobNextUp.of(tasks, "0192-a", practice = true, linked = true))
        assertNull(JobNextUp.of(tasks, null, practice = false, linked = true))
        assertNull(JobNextUp.of(listOf(task("0192-a", JobType.RECEIVE)), "0192-a", practice = false, linked = true))
        assertNull(JobNextUp.of(tasks, "0192-a", practice = false, linked = false))
    }

    @Test
    fun m5U03_approvals_timeLeft_wordsAndUrgency() {
        val h = 3_600_000L
        assertEquals("5 h 10 min left", ApprovalsHomeModel.timeLeft("2026-11-01T15:10:00Z", now)?.text)
        assertTrue(ApprovalsHomeModel.timeLeft("2026-11-01T15:10:00Z", now)!!.urgent)
        assertEquals("12 min left", ApprovalsHomeModel.timeLeft("2026-11-01T10:12:00Z", now)?.text)
        assertEquals("Overdue", ApprovalsHomeModel.timeLeft("2026-11-01T09:00:00Z", now)?.text)
        assertEquals("1 d 0 h left", ApprovalsHomeModel.timeLeft("2026-11-02T15:30:00+05:30", now)?.text)
        assertNull(ApprovalsHomeModel.timeLeft("soon", now)); assertNull(ApprovalsHomeModel.timeLeft(null, now + h))
    }

    @Test
    fun m5U03_approvals_emptyAndChecking() {
        val empty = ApprovalsHomeModel.of(0, null, approver = true, nowMs = now)
        assertTrue(empty.empty); assertEquals("Nothing waiting for you", empty.headline)
        val checking = ApprovalsHomeModel.of(null, null, approver = true, nowMs = now)
        assertTrue(checking.checking); assertFalse(checking.empty); assertEquals("Checking what waits for you…", checking.headline)
        assertTrue(ApprovalsHomeModel.of(null, null, approver = false, nowMs = now).empty) // not an approver: nothing to ask
    }

    @Test
    fun m5U03_scan_followsTodaysCardRule_andAnOpenCheck() {
        assertEquals(ScanHomeState.READY, ScanHomeModel.of(true, true, CheckState.IDLE).state)
        assertEquals(ScanHomeState.NOT_LINKED, ScanHomeModel.of(false, true, CheckState.IDLE).state)
        assertEquals(ScanHomeState.NOT_ALLOWED, ScanHomeModel.of(true, false, CheckState.IDLE).state)
        val running = ScanHomeModel.of(true, true, CheckState.CHECKING)
        assertEquals(ScanHomeState.RUNNING, running.state); assertEquals(CheckState.CHECKING.text, running.running)
    }
}
