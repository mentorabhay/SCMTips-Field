package com.scmtips.field.core.capture.safety

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/** Phase 2 walking-quiet and data-minimisation policy (FR2.065, FR2.066). */
class QuietModePolicyTest {

    @Test
    fun fr2_065_quietFromConfigZoneFlagOrSpeedAbove1_2() {
        assertFalse(QuietModePolicy().isQuietModeActive(1.2f))
        assertTrue(QuietModePolicy().isQuietModeActive(1.21f))
        assertTrue(QuietModePolicy(walkingQuietConfigEnabled = true).isQuietModeActive(0f))
        assertTrue(QuietModePolicy(zoneWalkingQuietFlag = true).isQuietModeActive(0f))
    }

    /** Seeded sweep: speech and lens prompts are suppressed exactly when quiet, errors always pass. */
    @Test
    fun fr2_065_promptsSuppressedExceptErrors() {
        val random = Random(20261110)
        repeat(1000) {
            val speed = random.nextFloat() * 5f
            val p = QuietModePolicy(random.nextBoolean(), random.nextBoolean())
            val quiet = p.walkingQuietConfigEnabled || p.zoneWalkingQuietFlag || speed > 1.2f
            assertEquals(quiet, p.isQuietModeActive(speed))
            assertEquals(!quiet, p.shouldSpeakAudio(false, speed))
            assertEquals(!quiet, p.shouldRenderPromptOnLens(false, speed))
            assertTrue(p.shouldSpeakAudio(true, speed))
            assertTrue(p.shouldRenderPromptOnLens(true, speed))
        }
    }

    @Test
    fun tc2_110_cropAtMost640x640And256Kb_fr2_066() {
        val p = QuietModePolicy()
        assertTrue(p.validateCropDimensions(640, 640))
        assertFalse(p.validateCropDimensions(641, 100))
        assertTrue(p.validateCropBytes(256 * 1024))
        assertFalse(p.validateCropBytes(256 * 1024 + 1))
        assertFalse(p.validateCropBytes(0))
    }

    @Test
    fun fr2_066_noFullFramesAndNoExifStored() {
        val p = QuietModePolicy()
        assertFalse(p.allowStorage(isFullFrame = true, hasExif = false))
        assertFalse(p.allowStorage(isFullFrame = false, hasExif = true))
        assertTrue(p.allowStorage(isFullFrame = false, hasExif = false))
    }
}
