package com.scmtips.field.core.capture.rank

import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min

data class RankCandidate(
    val id: String,
    val x: Float, // Center X
    val y: Float, // Center Y
    val width: Float,
    val height: Float,
    val readability: Float, // [0, 1]
    val taskMatch: Float, // [0, 1] (1.0 exact, 0.6 material/GTIN, 0.3 class, 0.0 none)
    val dwellMs: Long = 0L,
    val isAlreadyCaptured: Boolean = false,
    val barcodeValue: String? = null
)

data class ScoredCandidate(
    val candidate: RankCandidate,
    val coverage: Float,
    val centerScore: Float,
    val sizeScore: Float,
    val dwellScore: Float,
    val rawScore: Float,
    val finalScore: Float
)

sealed class RankOutcome {
    object None : RankOutcome()
    data class Tie(val first: ScoredCandidate, val second: ScoredCandidate) : RankOutcome()
    data class Winner(val selected: ScoredCandidate) : RankOutcome()
}

/**
 * Pure Kotlin Capture-Zone Ranking Engine (Task T2.024 / FR2.023 - FR2.026 / FR2.030 / Decision D2.01).
 * Zero Android dependencies; deterministic ordering across input permutations.
 */
class Ranker(
    val viewWidth: Float = 504f,
    val viewHeight: Float = 896f
) {
    // Capture circle of radius 13.5% of view width (FR2.023)
    val circleRadius: Float = viewWidth * 0.135f
    val centerX: Float = viewWidth / 2f
    val centerY: Float = viewHeight / 2f
    private val circleArea: Float = (Math.PI * circleRadius * circleRadius).toFloat()

    companion object {
        const val MIN_COVERAGE_THRESHOLD = 0.20f // 20% coverage required (FR2.023)
        const val MIN_SCORE_THRESHOLD = 0.35f // Score floor (D2.01 / FR2.026)
        const val TIE_MARGIN = 0.05f // Difference < 0.05 triggers tie (FR2.026)
        const val DUPLICATE_MULTIPLIER = 0.5f // 50% penalty for duplicates (FR2.025)
        const val DWELL_MAX_MS = 800f // 800ms full dwell (FR2.027)

        // Weight distribution summing to 1.00 (FR2.024)
        const val W_CENTER = 0.30f
        const val W_MATCH = 0.25f
        const val W_READABILITY = 0.20f
        const val W_COVERAGE = 0.10f
        const val W_DWELL = 0.10f
        const val W_SIZE = 0.05f
    }

    /**
     * Estimates coverage: fraction of object area inside the capture circle using a 6x6 grid.
     */
    fun computeCoverage(c: RankCandidate): Float {
        var pointsInside = 0
        val gridDim = 6
        for (i in 0 until gridDim) {
            for (j in 0 until gridDim) {
                val px = (c.x - c.width / 2f) + c.width * (i + 0.5f) / gridDim
                val py = (c.y - c.height / 2f) + c.height * (j + 0.5f) / gridDim
                val dist = hypot(px - centerX, py - centerY)
                if (dist <= circleRadius) {
                    pointsInside++
                }
            }
        }
        return pointsInside.toFloat() / (gridDim * gridDim)
    }

    /**
     * Evaluates a candidate and computes its 6-factor score.
     */
    fun scoreCandidate(c: RankCandidate): ScoredCandidate? {
        val coverage = computeCoverage(c)
        if (coverage < MIN_COVERAGE_THRESHOLD) {
            return null // Ineligible: under 20% coverage inside circle (FR2.023 / PR2.02)
        }

        val distToCenter = hypot(c.x - centerX, c.y - centerY)
        val centerScore = max(0f, 1f - distToCenter / circleRadius)
        val sizeScore = min(1f, (c.width * c.height) / circleArea)
        val dwellScore = min(1f, c.dwellMs.toFloat() / DWELL_MAX_MS)

        var rawScore = (W_CENTER * centerScore) +
                (W_MATCH * c.taskMatch) +
                (W_READABILITY * c.readability) +
                (W_COVERAGE * coverage) +
                (W_DWELL * dwellScore) +
                (W_SIZE * sizeScore)

        // Duplicate penalty (FR2.025)
        val finalScore = if (c.isAlreadyCaptured) rawScore * DUPLICATE_MULTIPLIER else rawScore

        return ScoredCandidate(
            candidate = c,
            coverage = coverage,
            centerScore = centerScore,
            sizeScore = sizeScore,
            dwellScore = dwellScore,
            rawScore = rawScore,
            finalScore = finalScore
        )
    }

    /**
     * Ranks all candidates and produces a deterministic outcome (PR2.01 - PR2.06 / PR2.30).
     */
    fun rank(candidates: List<RankCandidate>): RankOutcome {
        val scoredList = candidates.mapNotNull { scoreCandidate(it) }
        if (scoredList.isEmpty()) {
            return RankOutcome.None
        }

        // Deterministic sorting: primary by finalScore descending, secondary by id
        val sorted = scoredList.sortedWith(
            compareByDescending<ScoredCandidate> { it.finalScore }
                .thenBy { it.candidate.id }
        )

        val top = sorted[0]
        if (top.finalScore <= MIN_SCORE_THRESHOLD) {
            return RankOutcome.None // Below 0.35 floor (D2.01 / FR2.026)
        }

        if (sorted.size > 1) {
            val second = sorted[1]
            if (top.finalScore - second.finalScore < TIE_MARGIN) {
                return RankOutcome.Tie(top, second) // Disambiguation required (FR2.026)
            }
        }

        return RankOutcome.Winner(top)
    }
}
