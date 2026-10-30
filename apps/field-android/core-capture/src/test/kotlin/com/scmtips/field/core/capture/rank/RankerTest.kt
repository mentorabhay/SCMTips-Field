package com.scmtips.field.core.capture.rank

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.hypot
import kotlin.math.sqrt
import kotlin.random.Random

/** Capture-zone ranking by the production Ranker (FR2.023 - FR2.026, FR2.030). */
class RankerTest {

    // TC2.004 data: view width 1000 px -> capture circle radius 135 px
    private val ranker = Ranker(viewWidth = 1000f, viewHeight = 1000f)
    private val r = 135.0
    private val circleArea = PI * r * r

    private fun centred(id: String, side: Float, read: Float = 1f, match: Float = 1f, dwell: Long = 800L) =
        RankCandidate(id, ranker.centerX, ranker.centerY, side, side, read, match, dwell)

    private fun scored(id: String, score: Float, x: Float = 0f) =
        ScoredCandidate(RankCandidate(id, x, 0f, 1f, 1f, 0f, 0f), 1f, 0f, 0f, 0f, score, score)

    /** Independent oracle: area fraction by a 600 x 600 point grid over the box. */
    private fun gridCoverage(c: RankCandidate): Double {
        val n = 600
        var inside = 0
        for (i in 0 until n) for (j in 0 until n) {
            val px = c.x - c.width / 2 + c.width * (i + 0.5) / n
            val py = c.y - c.height / 2 + c.height * (j + 0.5) / n
            if (hypot(px - ranker.centerX, py - ranker.centerY) <= r) inside++
        }
        return inside.toDouble() / (n * n)
    }

    @Test
    fun tc2_004_coverage019IsIneligibleEvenWithPerfectComponents_fr2_023() {
        val side = sqrt(circleArea / 0.19).toFloat() // circle fully inside the box: coverage = 0.19
        val c = centred("A", side)
        assertEquals(0.19f, ranker.computeCoverage(c), 1e-5f)
        assertNull(ranker.scoreCandidate(c))
        assertEquals(RankOutcome.None, ranker.rank(listOf(c)))
    }

    @Test
    fun tc2_005_coverageExactly020IsEligible_fr2_023() {
        val c = centred("A", sqrt(circleArea / 0.20).toFloat())
        assertEquals(0.20f, ranker.computeCoverage(c), 1e-5f)
        assertNotNull(ranker.scoreCandidate(c))
    }

    @Test
    fun tc2_006_lowCoverageBoxNeverSelected_fr2_023() {
        val lowCov = RankCandidate("LOW", ranker.centerX + 172f, ranker.centerY, 100f, 100f, 1f, 1f, 800L)
        val highCov = RankCandidate("HIGH", ranker.centerX, ranker.centerY + 40f, 60f, 300f, 0.5f, 0f, 0L)
        assertTrue(ranker.computeCoverage(lowCov) in 0.05f..0.15f)
        val out = ranker.rank(listOf(lowCov, highCov))
        assertTrue(out is RankOutcome.None || (out is RankOutcome.Winner && out.selected.candidate.id == "HIGH"))
    }

    @Test
    fun fr2_023_coverageIsExactAreaFraction() {
        // box fully inside the circle
        assertEquals(1f, ranker.computeCoverage(centred("in", 100f)), 1e-6f)
        // quarter disc: box with a corner at the circle centre, larger than r
        val quarter = RankCandidate("q", ranker.centerX + 150f, ranker.centerY + 150f, 300f, 300f, 0f, 0f)
        assertEquals((circleArea / 4 / 90000.0).toFloat(), ranker.computeCoverage(quarter), 1e-6f)
        // random boxes against the independent grid oracle
        val random = Random(7)
        repeat(60) {
            val c = RankCandidate("r$it", ranker.centerX + random.nextFloat() * 300f - 150f,
                ranker.centerY + random.nextFloat() * 300f - 150f, 10f + random.nextFloat() * 300f, 10f + random.nextFloat() * 300f, 0f, 0f)
            assertEquals("box $c", gridCoverage(c), ranker.computeCoverage(c).toDouble(), 0.003)
        }
    }

    @Test
    fun tc2_016_allComponentsOneScoresOne_fr2_024() {
        assertEquals(1.0, Ranker.weightedScore(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, false), 1e-12)
    }

    @Test
    fun tc2_017_duplicateHalvesScore_fr2_025() {
        assertEquals(0.5, Ranker.weightedScore(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, true), 1e-12)
    }

    @Test
    fun tc2_018_br2_02WorkedExampleScores0_90_fr2_024() {
        assertEquals(0.90, Ranker.weightedScore(0.9, 1.0, 0.8, 1.0, 1.0, 0.4, false), 1e-12)
    }

    @Test
    fun fr2_024_componentsAreClampedSoScoreStaysInUnitRange() {
        assertEquals(1.0, Ranker.weightedScore(2.0, 3.0, 9.0, 1.5, 4.0, 7.0, false), 1e-12)
        assertEquals(0.0, Ranker.weightedScore(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, false), 1e-12)
    }

    @Test
    fun tc2_010_alreadyCapturedCodeScoreHalved_fr2_025() {
        val c = centred("A", 80f, read = 0.9f, match = 1f)
        val fresh = ranker.scoreCandidate(c)!!
        val dup = ranker.scoreCandidate(c.copy(isAlreadyCaptured = true))!!
        assertEquals(fresh.finalScore * 0.5f, dup.finalScore, 1e-6f)
        assertEquals(true, dup.rankDetail["dup"])
    }

    @Test
    fun fr2_024_scoreCandidateUsesTheWeights() {
        // centred (centre 1), fully inside (cov 1), dwell 400 ms (0.5), side 100 (size = 10000 / (pi 135^2))
        val c = RankCandidate("A", ranker.centerX, ranker.centerY, 100f, 100f, readability = 0.6f, taskMatch = 0.3f, dwellMs = 400L)
        val s = ranker.scoreCandidate(c)!!
        val size = 10000.0 / circleArea
        val expected = 0.30 + 0.25 * 0.3 + 0.20 * 0.6 + 0.10 + 0.10 * 0.5 + 0.05 * size
        assertEquals(expected.toFloat(), s.finalScore, 1e-6f)
        assertEquals(setOf("centre", "task", "read", "cov", "dwell", "size", "dup"), s.rankDetail.keys)
    }

    @Test
    fun tc2_007_gapBelow0_05IsTie_fr2_026() {
        assertTrue(ranker.decide(listOf(scored("A", 0.62f), scored("B", 0.60f))) is RankOutcome.Tie)
    }

    @Test
    fun tc2_008_gapOf0_05IsNotTie_fr2_026() {
        val out = ranker.decide(listOf(scored("A", 0.62f), scored("B", 0.57f)))
        assertEquals("A", (out as RankOutcome.Winner).selected.candidate.id)
    }

    @Test
    fun tc2_009_topAtOrBelow0_35IsNone_fr2_024() {
        assertEquals(RankOutcome.None, ranker.decide(listOf(scored("A", 0.34f), scored("B", 0.33f))))
        assertEquals(RankOutcome.None, ranker.decide(listOf(scored("A", 0.35f))))
        assertTrue(ranker.decide(listOf(scored("A", 0.36f))) is RankOutcome.Winner)
    }

    @Test
    fun tc2_013_selectionIndependentOfInputOrder_fr2_030() {
        val out = ranker.decide(listOf(scored("C", 0.40f), scored("A", 0.70f), scored("B", 0.50f)))
        assertEquals("A", (out as RankOutcome.Winner).selected.candidate.id)
    }

    @Test
    fun tc2_014_equalScoresTieWithSameLeftRightInBothOrders_fr2_026() {
        // mirror-image boxes left and right of the centre give exactly equal scores
        val a = RankCandidate("A", ranker.centerX - 40f, ranker.centerY, 60f, 60f, 0.9f, 1f, 800L)
        val b = RankCandidate("B", ranker.centerX + 40f, ranker.centerY, 60f, 60f, 0.9f, 1f, 800L)
        for (order in listOf(listOf(a, b), listOf(b, a))) {
            val tie = ranker.rank(order) as RankOutcome.Tie
            assertEquals("A", tie.left.candidate.id)
            assertEquals("B", tie.right.candidate.id)
        }
    }

    @Test
    fun tc2_015_emptyListIsNone_fr2_030() {
        assertEquals(RankOutcome.None, ranker.rank(emptyList()))
    }

    /** Seeded sweep with deliberate equal scores: every permutation gives the same outcome. */
    @Test
    fun fr2_030_outcomeInvariantUnderPermutation() {
        val random = Random(20261105)
        repeat(500) {
            val n = random.nextInt(0, 7)
            val list = (0 until n).map { i ->
                RankCandidate("I$i", ranker.centerX + random.nextInt(-3, 4) * 20f, ranker.centerY + random.nextInt(-2, 3) * 20f,
                    40f, 40f, random.nextInt(0, 5) * 0.25f, random.nextInt(0, 3) * 0.5f, random.nextInt(0, 3) * 400L)
            }
            val expected = key(ranker.rank(list))
            repeat(6) { assertEquals(expected, key(ranker.rank(list.shuffled(random)))) }
        }
    }

    /** Seeded sweep: a selected or tied box never has coverage below 0.20 by the independent oracle. */
    @Test
    fun fr2_023_selectedBoxAlwaysMeetsCoverageFloor() {
        val random = Random(20261102)
        repeat(200) {
            val list = (0 until random.nextInt(1, 5)).map { i ->
                val d = ranker.circleRadius * (0.6f + random.nextFloat() * 0.8f)
                RankCandidate("B$i", ranker.centerX + d, ranker.centerY + random.nextFloat() * 20f, 60f, 60f, random.nextFloat(), random.nextFloat(), 800L)
            }
            val picked = when (val o = ranker.rank(list)) {
                is RankOutcome.Winner -> listOf(o.selected)
                is RankOutcome.Tie -> listOf(o.first, o.second)
                RankOutcome.None -> emptyList()
            }
            picked.forEach { assertTrue("coverage of ${it.candidate}", gridCoverage(it.candidate) >= 0.197) }
        }
    }

    private fun key(o: RankOutcome): String = when (o) {
        RankOutcome.None -> "none"
        is RankOutcome.Winner -> "win:${o.selected.candidate.id}"
        is RankOutcome.Tie -> "tie:${o.left.candidate.id}<${o.right.candidate.id}"
    }
}
