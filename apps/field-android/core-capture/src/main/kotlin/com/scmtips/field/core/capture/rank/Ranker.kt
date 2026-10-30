package com.scmtips.field.core.capture.rank

import kotlin.math.asin
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

data class RankCandidate(
    val id: String,
    val x: Float, // Center X (px)
    val y: Float, // Center Y (px)
    val width: Float,
    val height: Float,
    val readability: Float, // [0, 1]
    val taskMatch: Float, // [0, 1] (1.0 exact, 0.6 material/GTIN, 0.3 class, 0.0 none)
    val dwellMs: Long = 0L,
    val isAlreadyCaptured: Boolean = false,
    val barcodeValue: String? = null,
    /** capture.code_type: sscc, gs1_dm, serial_text, qr or gauge. */
    val codeType: String? = null
)

data class ScoredCandidate(
    val candidate: RankCandidate,
    val coverage: Float,
    val centerScore: Float,
    val sizeScore: Float,
    val dwellScore: Float,
    val rawScore: Float,
    val finalScore: Float
) {
    /** capture.rank_detail payload (API2: centre, task, read, cov, dwell, size, dup). */
    val rankDetail: Map<String, Any>
        get() = mapOf(
            "centre" to centerScore,
            "task" to candidate.taskMatch.coerceIn(0f, 1f),
            "read" to candidate.readability.coerceIn(0f, 1f),
            "cov" to coverage,
            "dwell" to dwellScore,
            "size" to sizeScore,
            "dup" to candidate.isAlreadyCaptured
        )
}

sealed class RankOutcome {
    object None : RankOutcome()

    /**
     * Top two within 0.05 (FR2.026). [first]/[second] are by score; [left]/[right] are by screen
     * position (x, then id) so "left"/"right" resolution does not depend on input order (TC2.014).
     */
    data class Tie(val first: ScoredCandidate, val second: ScoredCandidate) : RankOutcome() {
        private val ordered = listOf(first, second).sortedWith(compareBy({ it.candidate.x }, { it.candidate.id }))
        val left: ScoredCandidate get() = ordered[0]
        val right: ScoredCandidate get() = ordered[1]
    }

    data class Winner(val selected: ScoredCandidate) : RankOutcome()
}

/**
 * Pure Kotlin capture-zone ranking engine (Task T2.024 / FR2.023 - FR2.026 / FR2.030 / D2.01).
 *
 * - Eligibility: at least 20% of the box area inside the capture circle of radius 13.5% of view
 *   width (FR2.023, BR2.01). Coverage is the exact circle/rectangle intersection area.
 * - Score: 0.30 centre + 0.25 task + 0.20 readability + 0.10 coverage + 0.10 dwell + 0.05 size,
 *   x 0.5 when the code is already captured for the task (FR2.024, FR2.025, BR2.02).
 * - No record when the top score is 0.35 or less; Tie when the top two differ by less than 0.05.
 * - The outcome does not depend on input order (FR2.030).
 * Scores are computed in Double; thresholds compare with a 1e-6 tolerance so decimal boundaries
 * such as a gap of exactly 0.05 are not flipped by binary rounding.
 */
class Ranker(
    val viewWidth: Float = 504f,
    val viewHeight: Float = 896f
) {
    val circleRadius: Float = viewWidth * 0.135f
    val centerX: Float = viewWidth / 2f
    val centerY: Float = viewHeight / 2f
    private val circleArea: Double = Math.PI * circleRadius.toDouble() * circleRadius.toDouble()

    companion object {
        const val MIN_COVERAGE_THRESHOLD = 0.20f
        const val MIN_SCORE_THRESHOLD = 0.35f
        const val TIE_MARGIN = 0.05f
        const val DUPLICATE_MULTIPLIER = 0.5f
        const val DWELL_MAX_MS = 800f
        const val EPS = 1e-6

        const val W_CENTER = 0.30
        const val W_MATCH = 0.25
        const val W_READABILITY = 0.20
        const val W_COVERAGE = 0.10
        const val W_DWELL = 0.10
        const val W_SIZE = 0.05

        /** BR2.02 weighted sum; each component is clamped to [0, 1]. */
        fun weightedScore(
            centre: Double,
            taskMatch: Double,
            readability: Double,
            coverage: Double,
            dwell: Double,
            size: Double,
            duplicate: Boolean
        ): Double {
            fun c(v: Double) = v.coerceIn(0.0, 1.0)
            val raw = W_CENTER * c(centre) + W_MATCH * c(taskMatch) + W_READABILITY * c(readability) +
                W_COVERAGE * c(coverage) + W_DWELL * c(dwell) + W_SIZE * c(size)
            return if (duplicate) raw * DUPLICATE_MULTIPLIER else raw
        }

        /**
         * Exact area of the intersection of the circle (cx, cy, r) with the axis-aligned rectangle
         * [x0, x1] x [y0, y1], by integrating vertical chord overlap piecewise in closed form.
         */
        fun circleRectIntersectionArea(
            cx: Double, cy: Double, r: Double,
            x0: Double, y0: Double, x1: Double, y1: Double
        ): Double {
            if (r <= 0 || x1 <= x0 || y1 <= y0) return 0.0
            val a = max(x0 - cx, -r)
            val b = min(x1 - cx, r)
            if (b <= a) return 0.0
            val v0 = y0 - cy
            val v1 = y1 - cy
            fun s(u: Double) = sqrt(max(0.0, r * r - u * u))
            fun prim(u: Double) = 0.5 * (u * s(u) + r * r * asin((u / r).coerceIn(-1.0, 1.0)))
            val cuts = sortedSetOf(a, b)
            for (v in doubleArrayOf(v0, v1)) {
                if (kotlin.math.abs(v) < r) {
                    val u = sqrt(r * r - v * v)
                    if (u > a && u < b) cuts.add(u)
                    if (-u > a && -u < b) cuts.add(-u)
                }
            }
            val pts = cuts.toList()
            var area = 0.0
            for (i in 0 until pts.size - 1) {
                val lo = pts[i]
                val hi = pts[i + 1]
                if (hi <= lo) continue
                val mid = (lo + hi) / 2
                val sm = s(mid)
                val topIsChord = sm < v1
                val bottomIsChord = -sm > v0
                val top = if (topIsChord) sm else v1
                val bottom = if (bottomIsChord) -sm else v0
                if (top <= bottom) continue
                val chordIntegral = prim(hi) - prim(lo)
                val width = hi - lo
                val topInt = if (topIsChord) chordIntegral else v1 * width
                val bottomInt = if (bottomIsChord) -chordIntegral else v0 * width
                area += topInt - bottomInt
            }
            return max(0.0, area)
        }
    }

    /** Fraction of the candidate's box area inside the capture circle (FR2.023). */
    fun computeCoverage(c: RankCandidate): Float = coverageOf(c).toFloat()

    private fun coverageOf(c: RankCandidate): Double {
        val boxArea = c.width.toDouble() * c.height.toDouble()
        if (boxArea <= 0) return 0.0
        val inside = circleRectIntersectionArea(
            centerX.toDouble(), centerY.toDouble(), circleRadius.toDouble(),
            (c.x - c.width / 2f).toDouble(), (c.y - c.height / 2f).toDouble(),
            (c.x + c.width / 2f).toDouble(), (c.y + c.height / 2f).toDouble()
        )
        return (inside / boxArea).coerceIn(0.0, 1.0)
    }

    /** Scores one candidate, or returns null when it is ineligible (coverage < 0.20). */
    fun scoreCandidate(c: RankCandidate): ScoredCandidate? {
        val coverage = coverageOf(c)
        if (coverage < MIN_COVERAGE_THRESHOLD - EPS) return null

        val distToCenter = hypot((c.x - centerX).toDouble(), (c.y - centerY).toDouble())
        val centerScore = max(0.0, 1.0 - distToCenter / circleRadius)
        val sizeScore = min(1.0, c.width.toDouble() * c.height.toDouble() / circleArea)
        val dwellScore = min(1.0, max(0L, c.dwellMs).toDouble() / DWELL_MAX_MS)
        val raw = weightedScore(centerScore, c.taskMatch.toDouble(), c.readability.toDouble(), coverage, dwellScore, sizeScore, false)
        val final = if (c.isAlreadyCaptured) raw * DUPLICATE_MULTIPLIER else raw
        return ScoredCandidate(
            candidate = c,
            coverage = coverage.toFloat(),
            centerScore = centerScore.toFloat(),
            sizeScore = sizeScore.toFloat(),
            dwellScore = dwellScore.toFloat(),
            rawScore = raw.toFloat(),
            finalScore = final.toFloat()
        )
    }

    /** Ranks candidates; deterministic for any input order (FR2.030). */
    fun rank(candidates: List<RankCandidate>): RankOutcome = decide(candidates.mapNotNull { scoreCandidate(it) })

    /** Applies the floor and tie rules (FR2.024, FR2.026) to already-scored eligible candidates. */
    fun decide(scored: List<ScoredCandidate>): RankOutcome {
        if (scored.isEmpty()) return RankOutcome.None
        val sorted = scored.sortedWith(
            compareByDescending<ScoredCandidate> { it.finalScore }.thenBy { it.candidate.id }
        )
        val top = sorted[0]
        if (top.finalScore <= MIN_SCORE_THRESHOLD + EPS) return RankOutcome.None
        if (sorted.size > 1) {
            val second = sorted[1]
            if (top.finalScore.toDouble() - second.finalScore.toDouble() < TIE_MARGIN - EPS) {
                return RankOutcome.Tie(top, second)
            }
        }
        return RankOutcome.Winner(top)
    }
}
