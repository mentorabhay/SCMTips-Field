package com.scmtips.field.core.safety

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.sin
import kotlin.random.Random

/** Labelled sensor trace for replay through the production [ClimbStateDetector]. */
internal data class LabelledTrace(val id: String, val expected: ClimbState, val samples: List<SensorSample>)

internal object ClimbTraces {
    /** 40 labelled traces at 25 Hz (TC4.133): 20 climbs, 10 platform stops, 5 ground, 5 sensor gaps. */
    fun forty(): List<LabelledTrace> {
        val out = mutableListOf<LabelledTrace>()
        for (i in 1..20) {
            val speed = 0.1 + i * 0.025 // 0.125 .. 0.60 m/s (PR4.04 generator range 0.1..0.6)
            var alt = 5.0
            out += LabelledTrace("climb_%02d".format(i), ClimbState.CLIMBING, (0 until 75).map { step ->
                alt += speed * 0.04
                SensorSample(step * 40L, 0.3 * sin(step * 0.5), alt)
            })
        }
        listOf(10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 60.0).forEachIndexed { i, h ->
            out += LabelledTrace("stop_%02d".format(i + 1), ClimbState.STATIONARY, (0 until 75).map { step ->
                SensorSample(step * 40L, 0.02, h + (step % 3 - 1) * 0.005)
            })
        }
        for (i in 1..5) {
            out += LabelledTrace("ground_%02d".format(i), ClimbState.GROUND, (0 until 75).map { step ->
                SensorSample(step * 40L, 0.01, 0.2 + i * 0.2)
            })
        }
        for (i in 1..5) {
            val gap = 1000L + i * 100L // 1.1 .. 1.5 s
            out += LabelledTrace("gap_%02d".format(i), ClimbState.UNKNOWN, listOf(
                SensorSample(0L, 0.0, 25.0), SensorSample(40L, 0.0, 25.0), SensorSample(40L + gap, 0.0, 25.0),
            ))
        }
        return out
    }
}

class ClimbStateDetectorTest {

    /** TC4.133 / FR4.038: 40 labelled traces, zero climbing samples classified stationary or ground; unknown on gaps. */
    @Test
    fun tc4_133_fortyLabelledTracesNoClimbClassifiedStationaryUnknownOnGaps() {
        val traces = ClimbTraces.forty()
        assertEquals(40, traces.size)
        for (t in traces) {
            val d = ClimbStateDetector(baselineAltitudeM = 0.0)
            val states = t.samples.map { d.onSensorSample(it) }
            when (t.expected) {
                ClimbState.CLIMBING -> assertTrue(
                    "${t.id} classified a climbing sample as resting: $states",
                    states.none { it == ClimbState.STATIONARY || it == ClimbState.GROUND },
                )
                else -> assertEquals(t.id, t.expected, states.last())
            }
        }
    }

    /** TC4.011 / FR4.038: a 1.4 s sensor gap at height gives UNKNOWN, which counts as climbing. */
    @Test
    fun tc4_011_sensorGapAtHeightIsUnknownAndFailSafe() {
        val d = ClimbStateDetector()
        d.onSensorSample(SensorSample(0, 0.0, 30.0))
        d.onSensorSample(SensorSample(40, 0.0, 30.0))
        val s = d.onSensorSample(SensorSample(1440, 0.0, 30.0))
        assertEquals(ClimbState.UNKNOWN, s)
        assertTrue(s.isClimbingOrFailSafe)
    }

    /** FR4.038: with no speed history at height the state is UNKNOWN (fail-safe), not STATIONARY. */
    @Test
    fun fr4_038_firstSampleAtHeightIsUnknown() {
        assertEquals(ClimbState.UNKNOWN, ClimbStateDetector().onSensorSample(SensorSample(0, 0.0, 12.0)))
        assertEquals(ClimbState.GROUND, ClimbStateDetector().onSensorSample(SensorSample(0, 0.0, 1.0)))
    }

    /** reset(baselineM) re-bases the detector (regression: the argument used to be ignored). */
    @Test
    fun resetAppliesNewBaseline() {
        val d = ClimbStateDetector(baselineAltitudeM = 0.0)
        d.reset(baselineM = 30.0)
        var s = ClimbState.UNKNOWN
        for (i in 0 until 50) s = d.onSensorSample(SensorSample(i * 40L, 0.0, 31.0))
        assertEquals(ClimbState.GROUND, s)
    }

    /** FR4.038: random slow/fast climbs (0.1..0.6 m/s, noisy) are never classified as resting once moving. */
    @Test
    fun fr4_038_seededRandomClimbsNeverRest() {
        val rnd = Random(4038)
        repeat(500) { run ->
            val speed = rnd.nextDouble(0.1, 0.6)
            val d = ClimbStateDetector()
            var alt = rnd.nextDouble(3.0, 40.0)
            for (step in 0 until 60) {
                alt += speed * 0.04 + rnd.nextDouble(-0.002, 0.002)
                val s = d.onSensorSample(SensorSample(step * 40L, rnd.nextDouble(-0.5, 0.5), alt))
                assertFalse("run $run step $step speed $speed -> $s", s == ClimbState.STATIONARY || s == ClimbState.GROUND)
            }
        }
    }
}
