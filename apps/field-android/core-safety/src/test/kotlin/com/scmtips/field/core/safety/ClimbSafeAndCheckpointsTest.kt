package com.scmtips.field.core.safety

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ClimbSafeAndCheckpointsTest {

    /** TC4.141 / FR4.045: climbing to 2.5 m turns climb-safe on and disabling is refused on structure. */
    @Test
    fun tc4_141_climbSafeActivatesAbove2mAndCannotBeDisabledOnStructure() {
        val c = ClimbSafeController(baselineAltitudeM = 100.0)
        assertFalse(c.updateAltitude(101.5))
        assertTrue(c.updateAltitude(102.5))
        assertTrue(c.isOnStructure)
        assertFalse(c.isDisableAllowed)
        assertFalse(c.attemptDisable())
        assertTrue(c.isClimbSafeActive)
    }

    /** FR4.045: lower rungs on the way down are still on structure; only back at the base may it be disabled. */
    @Test
    fun fr4_045_staysOnStructureUntilBackAtBase() {
        val c = ClimbSafeController()
        c.updateAltitude(10.0)
        c.updateAltitude(1.8)
        assertTrue(c.isOnStructure)
        assertFalse(c.attemptDisable())
        c.updateAltitude(0.3)
        assertFalse(c.isOnStructure)
        assertTrue(c.attemptDisable())
        assertFalse(c.isClimbSafeActive)
    }

    /** FR4.045: a climb edge activates climb-safe even below 2 m. */
    @Test
    fun fr4_045_climbEdgeActivates() {
        val c = ClimbSafeController()
        assertTrue(c.updateAltitude(1.0, isClimbEdge = true))
        assertFalse(c.attemptDisable())
    }

    /** TC4.137 / FR4.042: L2 platform at 20 m; climb to it and stop -> checkpoint with MSG4.08, once. */
    @Test
    fun tc4_137_restPlatformCheckpointShowsMsg4_08Once() {
        val d = RestPlatformDetector(listOf(RestPlatform("p1", "L1", 10.0), RestPlatform("p2", "L2", 20.0)))
        assertNull(d.evaluate(ClimbState.CLIMBING, 20.0))
        val hit = d.evaluate(ClimbState.STATIONARY, 20.8)
        assertNotNull(hit)
        assertEquals("L2", hit!!.platform.name)
        assertEquals("Rest platform L2. Clip in before you continue.", hit.message)
        assertEquals(0.8, hit.recalibratedBaselineM, 1e-9)
        assertNull(d.evaluate(ClimbState.STATIONARY, 20.8))
    }

    /** FR4.042: outside +/-1.5 m of every platform there is no checkpoint. */
    @Test
    fun fr4_042_toleranceIsPlusMinus1_5m() {
        val d = RestPlatformDetector(listOf(RestPlatform("p2", "L2", 20.0)))
        assertNull(d.evaluate(ClimbState.STATIONARY, 21.6))
        assertNull(d.evaluate(ClimbState.STATIONARY, 18.4))
        assertNotNull(d.evaluate(ClimbState.STATIONARY, 18.5))
    }
}
