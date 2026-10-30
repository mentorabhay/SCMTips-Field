package com.scmtips.field.core.capture.quality

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/** Readability = (0.5 conf + 0.3 sharpness + 0.2 pixel height) x motion factor (FR2.020, FR2.021). */
class ReadabilityTest {

    // base 0.9 = 0.5*1.0 + 0.3*1.0 + 0.2*0.5
    @Test
    fun tc2_040_stillHeadKeepsBase_fr2_020() {
        assertEquals(0.9f, ReadabilityCalculator.computeReadability(1f, 1f, 0.5f, 5f), 1e-5f)
    }

    @Test
    fun tc2_041_34DegPerSecHalvesScore_fr2_021() {
        assertEquals(0.45f, ReadabilityCalculator.computeReadability(1f, 1f, 0.5f, 34f), 1e-5f)
    }

    @Test
    fun tc2_042_above60DegPerSecIsZero_fr2_021() {
        assertEquals(0f, ReadabilityCalculator.computeReadability(1f, 1f, 0.5f, 70f), 0f)
        assertEquals(0f, ReadabilityCalculator.computeMotionFactor(60f), 0f)
    }

    @Test
    fun fr2_021_motionFactorOneAt8LinearTo60() {
        assertEquals(1f, ReadabilityCalculator.computeMotionFactor(8f), 0f)
        assertEquals(0.5f, ReadabilityCalculator.computeMotionFactor(34f), 1e-6f)
        assertEquals(0.25f, ReadabilityCalculator.computeMotionFactor(47f), 1e-6f)
    }

    /** Seeded sweep: monotone non-increasing in head speed and clamped to [0, 1]. */
    @Test
    fun fr2_020_monotoneInHeadSpeedAndBounded() {
        val random = Random(20261114)
        repeat(1000) {
            val conf = random.nextFloat() * 1.4f - 0.2f
            val sharp = random.nextFloat() * 1.4f - 0.2f
            val height = random.nextFloat() * 1.4f - 0.2f
            val w1 = random.nextFloat() * 120f
            val w2 = w1 + random.nextFloat() * 20f
            val r1 = ReadabilityCalculator.computeReadability(conf, sharp, height, w1)
            val r2 = ReadabilityCalculator.computeReadability(conf, sharp, height, w2)
            assertTrue("r($w1)=$r1 < r($w2)=$r2", r1 >= r2)
            assertTrue(r1 in 0f..1f)
        }
    }
}
