package com.scmtips.field.core.safety

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs
import kotlin.random.Random

class HarnessCheckTest {

    /** TC4.013 / FR4.040 / FR4.041: phrase 0.85 + tap after 4 s -> capture accepted on structure. */
    @Test
    fun tc4_013_phraseThenTapWithin10sAcceptsCapture() {
        val h = HarnessCheck()
        h.update(ClimbState.STATIONARY, 20.0)
        assertTrue(h.onVoicePhrase("Harness clipped", 0.85, 1_000))
        h.onTap(5_000)
        assertTrue(h.update(ClimbState.STATIONARY, 20.0))
        val d = h.decideCapture(ClimbState.STATIONARY, isOnStructure = true)
        assertTrue(d.accepted)
        assertNull(d.message)
    }

    /** TC4.014 / TC4.135 / FR4.040: phrase only -> capture rejected with MSG4.07. */
    @Test
    fun tc4_014_phraseOnlyRejectsCaptureWithMsg4_07() {
        val h = HarnessCheck()
        h.onVoicePhrase("harness clipped", 0.9, 0)
        val d = h.decideCapture(ClimbState.STATIONARY, isOnStructure = true)
        assertFalse(d.accepted)
        assertEquals("Capture is paused until your harness is confirmed.", d.message)
    }

    /** TC4.015 / FR4.041: confirmed, then climbed 1.6 m -> rejected until re-confirmed. */
    @Test
    fun tc4_015_altitudeChangeOver1_5mClearsConfirmationUntilReconfirm() {
        val h = HarnessCheck()
        h.update(ClimbState.STATIONARY, 20.0)
        h.onTap(0)
        h.onVoicePhrase("harness clipped", 0.9, 3_000) // phrase after tap: altitude must still be pinned
        assertEquals(20.0, h.confirmedAltitudeM!!, 1e-9)
        assertTrue(h.update(ClimbState.STATIONARY, 21.4))
        assertFalse(h.update(ClimbState.STATIONARY, 21.6))
        assertFalse(h.decideCapture(ClimbState.STATIONARY, true).accepted)
        h.onVoicePhrase("harness clipped", 0.9, 20_000)
        h.onTap(21_000)
        assertTrue(h.update(ClimbState.STATIONARY, 21.6))
        assertTrue(h.decideCapture(ClimbState.STATIONARY, true).accepted)
    }

    /** TC4.136 / FR4.041: voice only or tap only stays unconfirmed; both attempts are logged. */
    @Test
    fun tc4_136_voiceOnlyOrTapOnlyStaysUnconfirmedAndIsLogged() {
        val voiceOnly = HarnessCheck()
        voiceOnly.onVoicePhrase("harness clipped", 0.95, 0)
        assertFalse(voiceOnly.isConfirmed)
        assertEquals(listOf(HarnessAttempt("voice", 0, true)), voiceOnly.attempts)

        val tapOnly = HarnessCheck()
        tapOnly.onTap(0)
        assertFalse(tapOnly.isConfirmed)
        assertEquals(listOf(HarnessAttempt("tap", 0, true)), tapOnly.attempts)
    }

    /** FR4.041: confidence floor 0.80 and the 10 s window are inclusive bounds. */
    @Test
    fun fr4_041_confidenceFloorAndWindowBounds() {
        val low = HarnessCheck()
        assertFalse(low.onVoicePhrase("harness clipped", 0.79, 0))
        low.onTap(1)
        assertFalse(low.isConfirmed)
        assertEquals(HarnessAttempt("voice", 0, false), low.attempts.first())

        val edge = HarnessCheck()
        edge.onVoicePhrase("harness clipped", 0.80, 0)
        edge.onTap(10_000)
        assertTrue(edge.isConfirmed)

        val late = HarnessCheck()
        late.onVoicePhrase("harness clipped", 0.99, 0)
        late.onTap(10_010) // PR4.05 shrinking case: tap at 10.01 s
        assertFalse(late.isConfirmed)

        val wrong = HarnessCheck()
        assertFalse(wrong.onVoicePhrase("harness clip", 0.99, 0))
    }

    /** FR4.041: a climb clears the pending phrase, so a phrase before the climb cannot pair with a tap after it. */
    @Test
    fun fr4_041_climbClearsPendingHalf() {
        val h = HarnessCheck()
        h.onVoicePhrase("harness clipped", 0.9, 0)
        h.update(ClimbState.CLIMBING, 10.0)
        h.onTap(2_000)
        assertFalse(h.isConfirmed)
    }

    /** FR4.040: on structure only STATIONARY is acceptable, even when confirmed; off structure capture is not gated. */
    @Test
    fun fr4_040_onlyStationaryAcceptsOnStructure() {
        val h = HarnessCheck()
        h.onVoicePhrase("harness clipped", 0.9, 0)
        h.onTap(1)
        assertTrue(h.decideCapture(ClimbState.STATIONARY, true).accepted)
        assertFalse(h.decideCapture(ClimbState.GROUND, true).accepted)
        assertFalse(h.decideCapture(ClimbState.CLIMBING, true).accepted)
        assertTrue(HarnessCheck().decideCapture(ClimbState.GROUND, isOnStructure = false).accepted)
    }

    /**
     * FR4.040 / FR4.041 on 1000 seeded random event sequences: a capture is accepted on structure only
     * if the state is STATIONARY and an accepted phrase and a tap happened within 10 s of each other with
     * no climbing or > 1.5 m altitude change since the pair completed.
     */
    @Test
    fun fr4_041_seededRandomCaptureGateMatchesEventHistory() {
        val rnd = Random(405)
        repeat(1000) { run ->
            val h = HarnessCheck()
            var t = 0L
            var alt = 15.0
            var phraseAt: Long? = null
            var tapAt: Long? = null
            var pairAlt: Double? = null
            var paired = false
            repeat(40) {
                t += rnd.nextLong(100, 6000)
                when (rnd.nextInt(5)) {
                    0 -> {
                        val conf = rnd.nextDouble(0.6, 1.0)
                        if (h.onVoicePhrase("harness clipped", conf, t, alt)) {
                            phraseAt = t
                            if (tapAt != null && abs(t - tapAt!!) <= 10_000) { paired = true; pairAlt = alt }
                        }
                    }
                    1 -> {
                        h.onTap(t, alt); tapAt = t
                        if (phraseAt != null && abs(t - phraseAt!!) <= 10_000) { paired = true; pairAlt = alt }
                    }
                    2 -> {
                        h.update(ClimbState.CLIMBING, alt)
                        phraseAt = null; tapAt = null; paired = false; pairAlt = null
                    }
                    else -> {
                        alt += rnd.nextDouble(-3.0, 3.0) * if (rnd.nextBoolean()) 0.2 else 1.0
                        h.update(ClimbState.STATIONARY, alt)
                        if (paired && abs(alt - pairAlt!!) > 1.5) {
                            phraseAt = null; tapAt = null; paired = false; pairAlt = null
                        }
                    }
                }
                val expected = paired
                assertEquals("run $run at $t", expected, h.decideCapture(ClimbState.STATIONARY, true).accepted)
            }
        }
    }
}
