package com.scmtips.field.core.safety

import kotlin.math.abs

/**
 * Technician climb state classification (Task T4.039 / FR4.038 / TC4.133).
 *
 * Fuses vertical acceleration and barometric altitude at 25 Hz.
 * Enforces fail-safe classification: UNKNOWN is treated as CLIMBING.
 */
enum class ClimbState {
    GROUND,
    CLIMBING,
    STATIONARY,
    UNKNOWN;

    val isClimbingOrFailSafe: Boolean
        get() = this == CLIMBING || this == UNKNOWN
}

data class SensorSample(
    val timestampMs: Long,
    val verticalAccelMps2: Double, // Gravity-aligned vertical acceleration
    val altitudeM: Double,         // Barometric altitude
)

class ClimbStateDetector(
    baselineAltitudeM: Double = 0.0,
    private val climbSpeedThresholdMps: Double = 0.15,
    private val stationarySpeedThresholdMps: Double = 0.05,
    private val groundThresholdM: Double = 2.0,
    private val maxSensorGapMs: Long = 1000L,
) {
    private var baselineAltitudeM: Double = baselineAltitudeM
    private var lastSample: SensorSample? = null
    private var currentFilteredSpeedMps: Double = 0.0
    private var filterPrimed: Boolean = false
    private var stationaryDurationMs: Long = 0L

    var currentState: ClimbState = ClimbState.GROUND
        private set

    /**
     * Ingest next sensor sample at ~25 Hz and update climb state.
     */
    fun onSensorSample(sample: SensorSample): ClimbState {
        val prev = lastSample
        lastSample = sample

        if (prev == null) {
            // No speed history yet: at height that is UNKNOWN, which the gates treat as climbing.
            currentState = if (sample.altitudeM - baselineAltitudeM <= groundThresholdM) {
                ClimbState.GROUND
            } else {
                ClimbState.UNKNOWN
            }
            return currentState
        }

        val dtMs = sample.timestampMs - prev.timestampMs
        if (dtMs <= 0) return currentState

        // Sensor gap > 1.0 s -> UNKNOWN (fail-safe)
        if (dtMs > maxSensorGapMs) {
            currentState = ClimbState.UNKNOWN
            currentFilteredSpeedMps = 0.0
            filterPrimed = false
            stationaryDurationMs = 0L
            return currentState
        }

        val dtS = dtMs / 1000.0
        val rawSpeedMps = (sample.altitudeM - prev.altitudeM) / dtS
        // Exponential moving average filter (alpha = 0.3), primed with the first measured speed so a
        // slow climb is not read as "stationary" while the filter warms up from zero.
        currentFilteredSpeedMps = if (filterPrimed) 0.7 * currentFilteredSpeedMps + 0.3 * rawSpeedMps else rawSpeedMps
        filterPrimed = true

        val heightAboveBaseline = sample.altitudeM - baselineAltitudeM

        currentState = when {
            heightAboveBaseline <= groundThresholdM && abs(currentFilteredSpeedMps) < stationarySpeedThresholdMps -> {
                stationaryDurationMs += dtMs
                ClimbState.GROUND
            }
            abs(currentFilteredSpeedMps) >= climbSpeedThresholdMps || abs(sample.verticalAccelMps2) > 0.8 -> {
                stationaryDurationMs = 0L
                ClimbState.CLIMBING
            }
            abs(currentFilteredSpeedMps) < stationarySpeedThresholdMps -> {
                stationaryDurationMs += dtMs
                ClimbState.STATIONARY
            }
            else -> {
                // Ambiguous speed -> fail safe to CLIMBING
                ClimbState.CLIMBING
            }
        }

        return currentState
    }

    fun reset(baselineM: Double = baselineAltitudeM) {
        baselineAltitudeM = baselineM
        lastSample = null
        currentFilteredSpeedMps = 0.0
        filterPrimed = false
        stationaryDurationMs = 0L
        currentState = ClimbState.GROUND
    }
}
