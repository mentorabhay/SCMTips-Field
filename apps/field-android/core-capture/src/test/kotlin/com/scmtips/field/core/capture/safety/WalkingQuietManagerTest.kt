package com.scmtips.field.core.capture.safety

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Forklift-zone walking-quiet of the production WalkingQuietManager (FR3.052). */
class WalkingQuietManagerTest {

    @Test
    fun tc3_142_noPromptWhileMovingQueuedPromptsAfter1_5sStationary_fr3_052() {
        val wq = WalkingQuietManager()
        wq.update(inForkliftZone = true, speedMps = 1.0f, nowMs = 0)
        assertTrue("not yet 1 s", wq.handlePrompt("p0"))
        wq.update(true, 1.0f, 999)
        assertTrue(wq.isCaptureAllowed())
        wq.update(true, 1.0f, 1000)
        assertTrue(wq.shouldSuppressPrompts())
        assertFalse(wq.isCaptureAllowed())
        assertEquals("Walking. Prompts paused.", wq.lensMessage())
        assertFalse(wq.handlePrompt("p1"))
        assertFalse(wq.handlePrompt("p2"))

        assertEquals(emptyList<String>(), wq.update(true, 0.0f, 2000)) // stops
        assertEquals(emptyList<String>(), wq.update(true, 0.0f, 3499))
        assertTrue(wq.shouldSuppressPrompts())
        assertEquals(listOf("p1", "p2"), wq.update(true, 0.0f, 3500))
        assertFalse(wq.shouldSuppressPrompts())
        assertTrue(wq.isCaptureAllowed())
        assertNull(wq.lensMessage())
        assertEquals(0, wq.queuedCount())
    }

    @Test
    fun fr3_052_briefStopDoesNotReleaseAndThresholdIsStrict() {
        val wq = WalkingQuietManager()
        wq.update(true, 0.8f, 0)
        wq.update(true, 0.8f, 1000)
        wq.handlePrompt("p")
        wq.update(true, 0.5f, 1100) // at threshold: not moving
        wq.update(true, 0.8f, 2000) // moving again before 1.5 s
        assertEquals(emptyList<String>(), wq.update(true, 0.0f, 3000))
        assertTrue(wq.shouldSuppressPrompts())
        assertEquals(listOf("p"), wq.update(true, 0.0f, 4500))
    }

    @Test
    fun fr3_052_fastOutsideForkliftZoneIsNotSuppressed() {
        val wq = WalkingQuietManager()
        wq.update(false, 3f, 0)
        wq.update(false, 3f, 5000)
        assertFalse(wq.shouldSuppressPrompts())
        assertTrue(wq.handlePrompt("x"))
    }
}
