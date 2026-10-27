package com.scmtips.field.core.capture.quality

import kotlin.math.max
import kotlin.math.min

/**
 * Calculates visual readability score with head-motion penalty
 * (Task T2.027 / FR2.020 / FR2.021 / PR2.14 / TC2.122).
 */
object ReadabilityCalculator {

    const val MIN_SPEED_FULL_FACTOR = 8.0f // deg/s
    const val MAX_SPEED_ZERO_FACTOR = 60.0f // deg/s

    /**
     * Motion factor: 1.0 at <= 8 deg/s, linear drop to 0.0 at 60 deg/s.
     */
    fun computeMotionFactor(angularSpeedDegPerSec: Float): Float {
        if (angularSpeedDegPerSec <= MIN_SPEED_FULL_FACTOR) {
            return 1.0f
        }
        if (angularSpeedDegPerSec >= MAX_SPEED_ZERO_FACTOR) {
            return 0.0f
        }
        val range = MAX_SPEED_ZERO_FACTOR - MIN_SPEED_FULL_FACTOR
        return (MAX_SPEED_ZERO_FACTOR - angularSpeedDegPerSec) / range
    }

    /**
     * Readability = (0.5 confidence + 0.3 sharpness + 0.2 pixelHeight) * motionFactor.
     * Clamped to [0.0, 1.0].
     */
    fun computeReadability(
        confidence: Float,
        sharpness: Float,
        pixelHeightNormalized: Float,
        angularSpeedDegPerSec: Float
    ): Float {
        val baseScore = (0.50f * confidence.coerceIn(0f, 1f)) +
                (0.30f * sharpness.coerceIn(0f, 1f)) +
                (0.20f * pixelHeightNormalized.coerceIn(0f, 1f))

        val motionFactor = computeMotionFactor(angularSpeedDegPerSec)
        val finalScore = baseScore * motionFactor
        return max(0.0f, min(1.0f, finalScore))
    }
}
