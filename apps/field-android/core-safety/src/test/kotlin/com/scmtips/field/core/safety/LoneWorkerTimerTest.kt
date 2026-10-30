package com.scmtips.field.core.safety

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class LoneWorkerTimerTest {
    private fun hm(h: Int, m: Int, s: Int = 0) = ((h * 60L + m) * 60L + s) * 1000L

    /** TC4.055 / FR4.044: last check-in 14:00, 20 + 5 min, no check-in -> escalate at 14:25. */
    @Test
    fun tc4_055_escalatesAtIntervalPlusGrace() {
        val t = LoneWorkerTimer()
        t.onCheckIn(hm(14, 0))
        assertFalse(t.evaluate(hm(14, 24, 59), ClimbState.STATIONARY).isEscalated)
        val st = t.evaluate(hm(14, 25), ClimbState.STATIONARY)
        assertTrue(st.isEscalated)
        assertEquals(LoneWorkerWarningState.ESCALATED, st.state)
        assertEquals(hm(14, 25), st.escalatesAtMs)
    }

    /**
     * TC4.056 / TC4.138 / FR4.043: climbing 14:17–14:24 across the T-2 min warning -> nothing shown
     * while climbing, warning shown at the first stationary window, escalation time unchanged.
     */
    @Test
    fun tc4_138_warningDeferredWhileClimbingShownAtFirstStationaryEscalationUnchanged() {
        val t = LoneWorkerTimer()
        t.onCheckIn(hm(14, 0))
        assertEquals(LoneWorkerWarningState.NORMAL, t.evaluate(hm(14, 17), ClimbState.STATIONARY).state)
        var ms = hm(14, 17)
        while (ms < hm(14, 24)) {
            val st = t.evaluate(ms, ClimbState.CLIMBING)
            assertFalse("shown while climbing at $ms", st.isWarningActive)
            assertEquals(hm(14, 25), st.escalatesAtMs)
            ms += 5_000
        }
        val first = t.evaluate(hm(14, 24), ClimbState.STATIONARY)
        assertTrue(first.isWarningActive)
        assertFalse(first.isEscalated)
        assertEquals(hm(14, 25), first.escalatesAtMs)
    }

    /** TC4.057 / FR4.043: check-in at 14:24:59 -> no escalation; next due 14:44:59. */
    @Test
    fun tc4_057_checkInJustBeforeEscalationRestartsTimer() {
        val t = LoneWorkerTimer()
        t.onCheckIn(hm(14, 0))
        t.onCheckIn(hm(14, 24, 59))
        assertFalse(t.evaluate(hm(14, 25), ClimbState.STATIONARY).isEscalated)
        assertEquals(hm(14, 44, 59), t.nextDueMs)
    }

    /** FR4.043: MSG4.09 at T-2 min when stationary, emitted once per interval. */
    @Test
    fun fr4_043_warningEmittedOnceWithMsg4_09() {
        val t = LoneWorkerTimer()
        t.onCheckIn(0)
        assertEquals(LoneWorkerWarningState.NORMAL, t.evaluate(hm(0, 17, 59), ClimbState.STATIONARY).state)
        val w = t.evaluate(hm(0, 18), ClimbState.GROUND)
        assertEquals(LoneWorkerWarningState.WARNING_EMITTED, w.state)
        assertEquals("Check in due in 2 min. Say check in.", w.message)
        val again = t.evaluate(hm(0, 18, 30), ClimbState.STATIONARY)
        assertEquals(LoneWorkerWarningState.WARNING_DUE, again.state)
        assertFalse(again.isWarningActive)
        t.onCheckIn(hm(0, 19))
        assertEquals(LoneWorkerWarningState.WARNING_EMITTED, t.evaluate(hm(0, 37), ClimbState.STATIONARY).state)
    }

    /** FR4.043: tenant interval range is 10..60 min. */
    @Test
    fun fr4_043_intervalRangeEnforced() {
        LoneWorkerTimer(intervalMinutes = 10)
        LoneWorkerTimer(intervalMinutes = 60)
        for (bad in listOf(9, 61)) {
            try {
                LoneWorkerTimer(intervalMinutes = bad)
                throw AssertionError("interval $bad accepted")
            } catch (e: IllegalArgumentException) {
                assertTrue(e.message!!.contains("10..60"))
            }
        }
    }

    /**
     * FR4.043 / FR4.044 on 500 seeded random schedules (intervals 10–60 min, random check-ins and climb
     * windows): escalation is due iff now >= last check-in + interval + grace, nothing is shown while
     * climbing, and each check-in restarts the timer.
     */
    @Test
    fun fr4_043_seededRandomSchedulesEscalateExactlyAtIntervalPlusGrace() {
        val rnd = Random(419)
        repeat(500) { run ->
            val interval = rnd.nextInt(10, 61)
            val t = LoneWorkerTimer(intervalMinutes = interval)
            var last = 0L
            t.onCheckIn(last)
            var now = 0L
            var climbing = false
            repeat(200) {
                now += rnd.nextLong(1_000, 90_000)
                if (rnd.nextInt(10) == 0) climbing = !climbing
                if (rnd.nextInt(25) == 0) { last = now; t.onCheckIn(now) }
                val st = t.evaluate(now, if (climbing) ClimbState.CLIMBING else ClimbState.STATIONARY)
                val due = now >= last + (interval + 5) * 60_000L
                assertEquals("run $run at $now", due, st.isEscalated)
                if (climbing) assertFalse("run $run shown while climbing", st.isWarningActive)
                assertEquals(last + interval * 60_000L, t.nextDueMs)
            }
        }
    }
}
