package com.scmtips.field.app.home

import com.scmtips.field.app.glasses.GlassesAdvice
import com.scmtips.field.app.glasses.GlassesHelp
import com.scmtips.field.app.glasses.GlassesStatus
import com.scmtips.field.app.jobs.JobLine
import com.scmtips.field.app.jobs.JobTask
import com.scmtips.field.app.jobs.JobType
import com.scmtips.field.app.jobs.ScanLookup
import com.scmtips.field.app.scan.WedgeBuffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

/** Today cards, the avatar, glasses help, the handheld wedge and "Scan anything" (design Main.dc.html). */
class TodayModelTest {
    private fun jwt(claims: String): String {
        val enc = Base64.getUrlEncoder().withoutPadding()
        return enc.encodeToString("""{"alg":"RS256"}""".toByteArray()) + "." + enc.encodeToString(claims.toByteArray()) + ".sig"
    }

    @Test
    fun avatarInitialsComeFromTheCoreTokenSubject() {
        assertEquals(Person("Asha Sharma", "AS"), Person.fromCoreToken(jwt("""{"sub":"asha.sharma","tenant_id":"t"}""")))
        assertEquals(Person("Ravi Kumar", "RK"), Person.fromCoreToken(jwt("""{"sub":"x","name":"Ravi Kumar"}""")))
        assertEquals(Person("Smoke Op", "SO"), Person.fromCoreToken(jwt("""{"sub":"smoke-op"}""")))
        assertEquals(Person("Ravi", "RA"), Person.fromCoreToken(jwt("""{"sub":"ravi"}""")))
        assertEquals(Person.UNKNOWN, Person.fromCoreToken("not-a-jwt"))
        assertEquals(Person.UNKNOWN, Person.fromCoreToken("a.%%%.c"))
    }

    @Test
    fun cardsPerTaskTypeFollowTheDesign() {
        val rcv = JobTask("r", JobType.RECEIVE, "open", "Delivery 1800000022", "From SAMPLE-VENDOR-01 · 2 items", "1800000022",
            lines = listOf(JobLine("l", 10)))
        assertEquals(TaskCard("r", "IN", "Receive · Delivery 1800 0000 22", "From SAMPLE-VENDOR-01 · 2 items", null, false), TodayModel.card(rcv))
        val recount = JobTask("c", JobType.COUNT, "open", "Recount", reason = "Requested by an exception case",
            lines = listOf(JobLine("l", 10, bin = "03-05-02")))
        val rc = TodayModel.card(recount)
        assertEquals("RC", rc.badge); assertEquals("Recount bin 03-05-02", rc.title)
        assertEquals("Requested by an exception case", rc.sub); assertEquals("Today", rc.flag); assertTrue(rc.warm)
        val pa = TodayModel.card(JobTask("p", JobType.PUTAWAY, "in_progress", "Put away", lines = List(3) { JobLine("l$it", it) }))
        assertEquals("Put away · 3 pallets", pa.title); assertEquals("Started", pa.flag)
        assertEquals("TW", TodayModel.card(JobTask("a", JobType.AUDIT, "open", "SAMPLE-TWR-0001")).badge)
        assertEquals("SW", TodayModel.card(JobTask("s", JobType.SWAP, "open", "Radio unit")).badge)
        assertEquals("PK", TodayModel.card(JobTask("k", JobType.PICK, "open", "Order", refDocNo = "7700000012")).badge)
    }

    @Test
    fun startersOpenTheFirstTaskOfTheirKindAndTowerStartersAppearWithTowerWork() {
        val rcv = JobTask("r", JobType.RECEIVE, "open", "D")
        val ware = TodayModel.starters(listOf(rcv))
        assertEquals(listOf("Receive", "Put away", "Pick", "Count a bin"), ware.map { it.label })
        assertEquals(listOf("r", null, null, null), ware.map { it.taskId })
        val tower = TodayModel.starters(listOf(rcv, JobTask("a", JobType.AUDIT, "open", "T")))
        assertEquals("Site visit", tower.first().label); assertEquals("a", tower.first().taskId)
    }

    @Test
    fun glassesHelpIsPlainEnglishWithOneNextStep() {
        assertEquals(
            "Linked, but not awake: take them out of the case, put them on, wait for the chime.",
            GlassesHelp.advise(GlassesStatus(registration = "REGISTERED", devices = 1, lastError = "createSession: No eligible device available"), null).text,
        )
        val notLinked = GlassesHelp.advise(GlassesStatus(registration = "AVAILABLE"), null)
        assertEquals(GlassesAdvice.Action.REGISTER, notLinked.action); assertEquals("Set up", notLinked.button)
        val ready = GlassesHelp.advise(GlassesStatus(registration = "REGISTERED", devices = 1, session = "STARTED", camera = "STREAMING"), null)
        assertTrue(ready.ready); assertNull(ready.button)
        assertTrue(GlassesHelp.advise(GlassesStatus(), "NOT_INITIALIZED").text.contains("Use the phone camera"))
        assertEquals(GlassesAdvice.Action.CONNECT, GlassesHelp.advise(GlassesStatus(registration = "REGISTERED", devices = 1), null).action)
    }

    @Test
    fun handheldWedgeCodesEndWithEnterAndStrayKeysAreDropped() {
        var now = 0L
        val w = WedgeBuffer(clock = { now })
        "03-05-02".forEach { w.type(it); now += 15 }
        assertEquals("03-05-02", w.enter())
        assertNull(w.enter())
        w.type('x'); now += 5_000
        "SN-1".forEach { w.type(it); now += 10 }
        assertEquals("SN-1", w.enter())
    }

    @Test
    fun scanAnythingFindsBinsSerialsAndProductsInOpenJobs() {
        val tasks = listOf(
            JobTask("c", JobType.COUNT, "open", "Count", lines = listOf(JobLine("l", 10, "SAMPLE-MAT-0001", bin = "03-05-02"))),
            JobTask("s", JobType.SWAP, "open", "Swap", lines = listOf(JobLine("m", 10, "RRU", "Radio unit", position = "Sector B · slot 2", expectedSerial = "SN-9"))),
        )
        val bin = ScanLookup.lookup("03-05-02", tasks)
        assertEquals("Bin", bin.kind); assertEquals(listOf("Count this bin" to "c"), bin.actions)
        val serial = ScanLookup.lookup("sn-9", tasks)
        assertEquals("Equipment serial", serial.kind); assertEquals("Radio unit · Sector B · slot 2", serial.about)
        assertEquals("Product", ScanLookup.lookup("SAMPLE-MAT-0001", tasks).kind)
        val none = ScanLookup.lookup("ZZZ", tasks)
        assertTrue(none.actions.isEmpty()); assertFalse(none.about.isBlank())
    }
}
