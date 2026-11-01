package com.scmtips.field.app.ui.homes

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The prototype's CSS keyframes as pure curves, and the still frames drawn when reduce motion is on. */
class HintMotionTest {
    private fun near(e: Float, a: Float) = assertEquals(e, a, 0.01f)

    @Test
    fun m5U02_pulseAndPop_followThePrototypeKeyframes() {
        near(1f, HintMotion.pulse(0f).scale); near(0.55f, HintMotion.pulse(0f).alpha)
        near(1.6f, HintMotion.pulse(0.5f).scale); near(0f, HintMotion.pulse(0.5f).alpha)
        near(0f, HintMotion.pop(0.1f).alpha); near(0.4f, HintMotion.pop(0.1f).scale)
        near(1f, HintMotion.pop(0.5f).alpha); near(1f, HintMotion.pop(0.5f).scale)
        assertTrue(HintMotion.pop(0.95f).alpha < 0.5f)
        // the second and third outlines start 0.3 s and 0.6 s later in a 3 s loop
        near(0.9f, HintMotion.shifted(0f, 300, HintMotion.POP_MS))
        near(0.3f, HintMotion.shifted(0.5f, 600, HintMotion.POP_MS))
    }

    @Test
    fun m5U02_waveRingFlyBreatheTapBlink_stayInTheirRanges() {
        near(0.35f, HintMotion.wave(0f)); near(1f, HintMotion.wave(0.5f))
        near(1f, HintMotion.ring(0f)); near(0.5f, HintMotion.ring(0.5f))
        near(0f, HintMotion.fly(0f).dx); near(70f, HintMotion.fly(0.7f).dx); near(-40f, HintMotion.fly(0.7f).dy)
        near(0f, HintMotion.fly(0.999f).alpha)
        near(1f, HintMotion.breathe(0f)); near(1.08f, HintMotion.breathe(0.5f))
        near(0f, HintMotion.tap(0.3f)); near(4f, HintMotion.tap(0.7f)); near(0f, HintMotion.tap(0.9999f))
        near(1f, HintMotion.blink(0f)); near(0.35f, HintMotion.blink(0.5f))
        near(0.6f, HintMotion.ping(0f).scale); near(0f, HintMotion.ping(0.9999f).alpha)
    }

    @Test
    fun m5U03_theScanFrameClosesIn_andTheCodeReadTagShowsOnlyAfter() {
        near(1.35f, HintMotion.close(0.1f).scale)
        near(1f, HintMotion.close(0.7f).scale); near(1f, HintMotion.close(0.7f).alpha)
        near(0f, HintMotion.found(0.5f)); near(1f, HintMotion.found(0.8f))
    }

    @Test
    fun m5U02_reduceMotionStills_areRestingFrames_neverAClaim() {
        near(0f, HintMotion.Still.pulse.alpha) // a halo is hidden, not drawn solid
        near(1f, HintMotion.Still.pop.alpha)   // outlines are shown
        near(1f, HintMotion.Still.RING)
        near(0f, HintMotion.Still.FOUND)       // a still seal drawing never says "Code read"
        near(1f, HintMotion.Still.close.scale)
        near(0f, HintMotion.Still.ping.alpha)
    }
}
