package com.scmtips.field.app.shell

import com.scmtips.field.app.jobs.JobTask
import com.scmtips.field.app.jobs.JobType
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** M5-U01: the role switcher, the default home, view-only banners and the remembered home (A-07, M5_UI_CONTRACT §2). */
class HomeRulesTest {
    private val operator = Capabilities(fieldOperator = true, approver = false, towerTasks = false)
    private val approverOnly = Capabilities(fieldOperator = false, approver = true, towerTasks = false)
    private val both = Capabilities(fieldOperator = true, approver = true, towerTasks = false)
    private val nobody = Capabilities(fieldOperator = false, approver = false, towerTasks = false)
    private val technician = Capabilities(fieldOperator = true, approver = false, towerTasks = true)

    @Test
    fun m5_u01_theSwitcherAlwaysListsAllFourHomesInOrderWithCanActOrViewOnly() {
        for (c in listOf(operator, approverOnly, both, nobody, technician)) {
            assertEquals(listOf(Home.WAREHOUSE, Home.TOWER, Home.APPROVALS, Home.SCAN), HomeRules.choices(c).map { it.home })
        }
        assertEquals(listOf("can act", "view only", "view only", "can act"), HomeRules.choices(operator).map { it.badge })
        assertEquals(listOf("view only", "view only", "can act", "can act"), HomeRules.choices(approverOnly).map { it.badge })
        assertEquals(listOf(true, true, false, true), HomeRules.choices(technician).map { it.canAct })
        assertEquals(listOf(false, false, false, true), HomeRules.choices(nobody).map { it.canAct })
    }

    @Test
    fun m5_u01_defaultHomeIsTheFirstTheAccountCanActIn() {
        assertEquals(Home.WAREHOUSE, HomeRules.defaultHome(operator))
        assertEquals(Home.WAREHOUSE, HomeRules.defaultHome(both))
        assertEquals(Home.WAREHOUSE, HomeRules.defaultHome(technician))
        assertEquals(Home.APPROVALS, HomeRules.defaultHome(approverOnly))
        assertEquals(Home.SCAN, HomeRules.defaultHome(nobody))
    }

    @Test
    fun m5_u01_viewOnlyHomesSayWhatTheAccountCannotDoAndWhoCan() {
        assertEquals(
            "View only: your account can't do warehouse work here. Sign in as an operator (e.g. tester01) to act.",
            HomeRules.viewOnlyBanner(Home.WAREHOUSE, approverOnly),
        )
        assertEquals(
            "View only: your account can't do approvals here. Sign in as an approver (e.g. tester01) to act.",
            HomeRules.viewOnlyBanner(Home.APPROVALS, operator),
        )
        assertTrue(HomeRules.viewOnlyBanner(Home.TOWER, operator)!!.startsWith("View only: your account can't do tower work here."))
        assertNull(HomeRules.viewOnlyBanner(Home.WAREHOUSE, operator))
        assertNull(HomeRules.viewOnlyBanner(Home.SCAN, nobody)) // any Field role may check a box
        assertNull(HomeRules.viewOnlyBanner(Home.TOWER, technician))
    }

    @Test
    fun m5_u01_theChosenHomeIsRememberedPerAccountEvenWhenViewOnly() {
        val who = HomeMemory.who("Tester01@Sample.example", "Tester 01", null, null)
        assertEquals("tester01@sample.example", who)
        val stored = HomeMemory.encode(who, Home.TOWER)
        assertEquals(Home.TOWER, HomeMemory.current(stored, who, approverOnly)) // a reviewer's view-only pick stays
        assertEquals(Home.APPROVALS, HomeMemory.current(stored, "someone.else@sample.example", approverOnly))
        assertEquals(Home.WAREHOUSE, HomeMemory.current(null, who, operator))
        assertNull(HomeMemory.decode("garbage", who))
        assertNull(HomeMemory.decode(HomeMemory.encode(who, Home.SCAN).replace("scan", "nope"), who))
        val pc = HomeMemory.who(null, null, "http://192.168.1.20:8020", "t-1")
        assertEquals("pc:http://192.168.1.20:8020#t-1", pc)
        assertEquals(Home.SCAN, HomeMemory.decode(HomeMemory.encode(pc, Home.SCAN), pc))
        assertEquals("name:Tester 01", HomeMemory.who(" ", "Tester 01", null, null))
        assertNull(HomeMemory.who(null, null, null, null))
    }

    @Test
    fun m5_u01_towerAndWarehouseHomesSplitTheAssignedJobs() {
        val tasks = listOf(
            JobTask("r", JobType.RECEIVE, "open", "R"), JobTask("a", JobType.AUDIT, "open", "A"),
            JobTask("c", JobType.COUNT, "open", "C"), JobTask("s", JobType.SWAP, "open", "S"),
        )
        assertEquals(listOf("a", "s"), HomeRules.towerTasks(tasks).map { it.id })
        assertEquals(listOf("r", "c"), HomeRules.warehouseTasks(tasks).map { it.id })
    }

    @Test
    fun m5_u01_headlinesUseRealCountsOnly() {
        assertEquals("6 tasks today", HomeRules.headline(Home.WAREHOUSE, 6, 0, null, null, canAct = true))
        assertEquals("1 task today", HomeRules.headline(Home.WAREHOUSE, 1, 0, null, null, canAct = true))
        assertEquals("Nothing assigned yet", HomeRules.headline(Home.WAREHOUSE, 0, 0, null, null, canAct = true))
        assertEquals("Warehouse work", HomeRules.headline(Home.WAREHOUSE, 3, 0, null, null, canAct = false))
        assertEquals("2 tower jobs today", HomeRules.headline(Home.TOWER, 0, 2, null, null, canAct = true))
        assertEquals("Your decisions", HomeRules.headline(Home.APPROVALS, 0, 0, null, null, canAct = true))
        assertEquals("3 items waiting", HomeRules.headline(Home.APPROVALS, 0, 0, 2, 1, canAct = true))
        assertEquals("Nothing waiting", HomeRules.headline(Home.APPROVALS, 0, 0, 0, null, canAct = true))
        assertEquals("Scan a product", HomeRules.headline(Home.SCAN, 0, 0, null, null, canAct = true))
        assertFalse(HomeRules.canAct(Home.APPROVALS, operator))
    }
}
