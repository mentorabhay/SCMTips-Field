package com.scmtips.field.core.safety

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class PromptGateTest {

    private fun prompt(i: Int, type: String = "audio", t: Long = i * 100L) = SafetyPrompt("p$i", type, "msg $i", t)

    /** TC4.134 / FR4.039: 5 prompts due while climbing; stop for 3 s; only the 3 newest released, MSG4.25 count shown. */
    @Test
    fun tc4_134_fiveHeldWhileClimbingThreeNewestReleasedAfter3sWithMsg4_25() {
        val gate = PromptGate()
        for (i in 1..5) {
            gate.enqueuePrompt(prompt(i), ClimbState.CLIMBING, i * 100L)
            assertTrue(gate.evaluate(ClimbState.CLIMBING, true, true, i * 100L).releasedPrompts.isEmpty())
        }
        // Stationary from t=1000; nothing before 3.0 s.
        assertTrue(gate.evaluate(ClimbState.STATIONARY, true, true, 1000).releasedPrompts.isEmpty())
        assertTrue(gate.evaluate(ClimbState.STATIONARY, true, true, 3999).releasedPrompts.isEmpty())
        val r = gate.evaluate(ClimbState.STATIONARY, true, true, 4000)
        assertEquals(listOf("p3", "p4", "p5"), r.releasedPrompts.map { it.id })
        assertEquals(2, r.droppedCount)
        assertEquals("5 messages held while climbing.", r.message)
        assertEquals(0, gate.heldCount)
    }

    /** FR4.039: a climb before the 3 s are up restarts the stationary count. */
    @Test
    fun fr4_039_climbDuringHoldRestartsStationaryWindow() {
        val gate = PromptGate()
        gate.enqueuePrompt(prompt(1), ClimbState.STATIONARY, 0)
        gate.evaluate(ClimbState.STATIONARY, true, false, 0)
        gate.evaluate(ClimbState.CLIMBING, true, false, 2500)
        assertTrue(gate.evaluate(ClimbState.STATIONARY, true, false, 3000).releasedPrompts.isEmpty())
        assertTrue(gate.evaluate(ClimbState.STATIONARY, true, false, 5999).releasedPrompts.isEmpty())
        assertEquals(1, gate.evaluate(ClimbState.STATIONARY, true, false, 6000).releasedPrompts.size)
    }

    /** TC4.011 / FR4.039: UNKNOWN (sensor gap) holds prompts exactly like CLIMBING. */
    @Test
    fun tc4_011_unknownStateHoldsPrompts() {
        val gate = PromptGate()
        gate.enqueuePrompt(prompt(1, "lens"), ClimbState.UNKNOWN, 0)
        for (t in 0L..10_000L step 500L) {
            assertTrue(gate.evaluate(ClimbState.UNKNOWN, true, true, t).releasedPrompts.isEmpty())
        }
        assertEquals(1, gate.heldCount)
    }

    /**
     * TC4.012 / FR4.040: stationary on structure with harness unconfirmed — the task prompt is not
     * emitted (only the harness check is requested) and it is kept, not dropped; after confirmation it is released.
     */
    @Test
    fun tc4_012_taskPromptWaitsForHarnessAndIsNotDropped() {
        val gate = PromptGate()
        gate.enqueuePrompt(prompt(1, "task"), ClimbState.STATIONARY, 0)
        gate.evaluate(ClimbState.STATIONARY, false, true, 0)
        val r = gate.evaluate(ClimbState.STATIONARY, false, true, 3000)
        assertTrue(r.releasedPrompts.isEmpty())
        assertTrue(r.harnessCheckRequested)
        assertEquals(0, r.droppedCount)
        assertEquals(1, gate.heldCount)
        val after = gate.evaluate(ClimbState.STATIONARY, true, true, 3500)
        assertEquals(listOf("p1"), after.releasedPrompts.map { it.id })
        assertFalse(after.harnessCheckRequested)
    }

    /** FR4.039 / FR4.040: non-task prompts still flow while a task prompt waits for the harness. */
    @Test
    fun fr4_040_nonTaskPromptsReleasedWhileTaskPromptWaits() {
        val gate = PromptGate()
        gate.enqueuePrompt(prompt(1, "task"), ClimbState.STATIONARY, 0)
        gate.enqueuePrompt(prompt(2, "audio"), ClimbState.STATIONARY, 0)
        gate.evaluate(ClimbState.STATIONARY, false, true, 0)
        val r = gate.evaluate(ClimbState.STATIONARY, false, true, 3000)
        assertEquals(listOf("p2"), r.releasedPrompts.map { it.id })
        assertTrue(r.harnessCheckRequested)
        assertNull(r.message)
        assertEquals(1, gate.heldCount)
    }

    /**
     * TC4.010 / FR4.039 / FR4.043: lone-worker warning comes due during a 0.22 m/s climb; it is
     * deferred, and delivered through the gate after 3 s stationary.
     */
    @Test
    fun tc4_010_loneWorkerWarningDuringClimbDeliveredAfterStationary3s() {
        val timer = LoneWorkerTimer(intervalMinutes = 20)
        timer.start(0)
        val gate = PromptGate()
        val detector = ClimbStateDetector()
        val t0 = (18 * 60 + 5) * 1000L // inside the T-2 min window
        var alt = 8.0
        var t = t0
        var state = ClimbState.UNKNOWN
        repeat(100) { // 4 s climbing at 0.22 m/s
            alt += 0.22 * 0.04
            state = detector.onSensorSample(SensorSample(t, 0.1, alt))
            val st = timer.evaluate(t, state)
            assertFalse("warning shown while climbing at $t", st.isWarningActive)
            assertTrue(gate.evaluate(state, true, true, t).releasedPrompts.isEmpty())
            t += 40
        }
        assertTrue(state.isClimbingOrFailSafe)
        var released: List<SafetyPrompt> = emptyList()
        var firstStationaryMs = -1L
        repeat(150) { // then 6 s holding still
            state = detector.onSensorSample(SensorSample(t, 0.0, alt))
            val st = timer.evaluate(t, state)
            if (st.isWarningActive && st.message != null) {
                gate.enqueuePrompt(SafetyPrompt("lw", "audio", st.message!!, t), state, t)
            }
            if (!state.isClimbingOrFailSafe && firstStationaryMs < 0) firstStationaryMs = t
            val r = gate.evaluate(state, true, true, t)
            if (r.releasedPrompts.isNotEmpty()) {
                released = r.releasedPrompts
                assertTrue("released at $t before 3 s stationary (from $firstStationaryMs)", t - firstStationaryMs >= 3000)
            }
            t += 40
        }
        assertEquals(listOf(LoneWorkerTimer.MSG_CHECK_IN_DUE), released.map { it.text })
    }

    /**
     * FR4.039 / FR4.040 timeline invariant on 500 seeded random runs (synthetic climbs 0.1–0.6 m/s,
     * pauses 0–30 s, sensor gaps, random prompts): every release falls in a stationary window >= 3 s,
     * nothing is released while climbing/unknown, and no task prompt is released unharnessed on structure.
     */
    @Test
    fun fr4_039_seededRandomTimelinesNeverEmitWhileClimbing() {
        val rnd = Random(404)
        repeat(500) { run ->
            val detector = ClimbStateDetector()
            val gate = PromptGate()
            var t = 0L
            var alt = rnd.nextDouble(3.0, 20.0)
            var stationarySince = -1L
            var harness = rnd.nextBoolean()
            repeat(rnd.nextInt(3, 8)) {
                val climbing = rnd.nextBoolean()
                val speed = if (climbing) rnd.nextDouble(0.1, 0.6) else 0.0
                val steps = if (climbing) rnd.nextInt(10, 150) else rnd.nextInt(0, 750) // pause 0..30 s
                repeat(steps) {
                    t += if (rnd.nextInt(400) == 0) rnd.nextLong(1001, 2000) else 40L
                    alt += speed * 0.04
                    val s = detector.onSensorSample(SensorSample(t, if (climbing) 0.3 else 0.0, alt))
                    if (s.isClimbingOrFailSafe) stationarySince = -1L else if (stationarySince < 0) stationarySince = t
                    if (rnd.nextInt(50) == 0) {
                        gate.enqueuePrompt(SafetyPrompt("p$t", if (rnd.nextBoolean()) "task" else "audio", "x", t), s, t)
                    }
                    if (rnd.nextInt(200) == 0) harness = !harness
                    val r = gate.evaluate(s, harness, true, t)
                    if (r.releasedPrompts.isNotEmpty()) {
                        assertFalse("run $run: release while $s at $t", s.isClimbingOrFailSafe)
                        assertTrue("run $run: release at $t only ${t - stationarySince} ms stationary", t - stationarySince >= 3000)
                        if (!harness) {
                            assertTrue("run $run: task prompt released unharnessed", r.releasedPrompts.none { it.type == "task" })
                        }
                        assertTrue(r.releasedPrompts.size <= 3)
                    }
                }
            }
        }
    }
}
