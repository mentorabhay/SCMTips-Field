package com.scmtips.field.core.capture.rank

import com.scmtips.field.core.capture.detect.BoundingBox
import com.scmtips.field.core.capture.detect.DetectedObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** Head-gaze dwell by the production DwellTracker (FR2.027). View 504 px: circle radius 68.04 px at (252, 448). */
class DwellTrackerTest {

    private fun det(x: Float) = DetectedObject("d", "carton", 0.9f, BoundingBox(x, 448f, 40f, 40f))

    @Test
    fun tc2_125_dwellGrowsToFullAt800msWhileInsideAndResetsOnExit_fr2_027() {
        val t = DwellTracker()
        // the box drifts right 5 px per 100 ms frame: outside, crosses the left edge at x ~ 184, stays inside
        val xs = listOf(150f, 160f, 170f, 180f, 190f, 195f, 200f, 205f, 210f, 215f, 220f, 225f, 230f)
        val seen = xs.mapIndexed { i, x -> t.update(listOf(det(x)), i * 100L).single() }
        assertEquals("one track for the whole pass", 1, seen.map { it.trackId }.toSet().size)
        assertEquals(listOf(0L, 0L, 0L, 0L), seen.take(4).map { it.accumulatedDwellMs })
        assertEquals("entry frame starts at 0", 0L, seen[4].accumulatedDwellMs)
        assertEquals(700L, seen[11].accumulatedDwellMs)
        assertEquals(800L, seen[12].accumulatedDwellMs)
        assertEquals(1f, seen[12].dwellScore, 0f)
        assertEquals(0.875f, seen[11].dwellScore, 1e-6f)

        // keeps drifting right in 15 px steps (IoU stays >= 0.4) until the centre leaves at x > 320
        var last = seen.last()
        var x = 230f
        var ts = 1200L
        while (x <= 320f) {
            x += 15f; ts += 100L
            last = t.update(listOf(det(x)), ts).single()
            assertEquals(seen[0].trackId, last.trackId)
        }
        assertEquals("reset on exit", 0L, last.accumulatedDwellMs)
    }

    @Test
    fun fr2_027_reentryDoesNotCountTimeSpentOutside() {
        val t = DwellTracker()
        val wideIn = DetectedObject("d", "carton", 0.9f, BoundingBox(300f, 448f, 200f, 40f)) // centre 48 px from circle centre
        val wideOut = DetectedObject("d", "carton", 0.9f, BoundingBox(330f, 448f, 200f, 40f)) // 78 px: outside, IoU 0.74
        assertEquals(0L, t.update(listOf(wideIn), 0L).single().accumulatedDwellMs)
        assertEquals(200L, t.update(listOf(wideIn), 200L).single().accumulatedDwellMs)
        assertEquals(0L, t.update(listOf(wideOut), 1200L).single().accumulatedDwellMs)
        assertEquals("re-entry starts from 0", 0L, t.update(listOf(wideIn), 2200L).single().accumulatedDwellMs)
        assertEquals(100L, t.update(listOf(wideIn), 2300L).single().accumulatedDwellMs)
        assertEquals(1, t.activeTrackCount())
    }

    @Test
    fun fr2_027_unmatchedTracksDropAndNewObjectsGetNewTracks() {
        val t = DwellTracker()
        val first = t.update(listOf(det(252f)), 0L).single()
        val far = DetectedObject("e", "label", 0.9f, BoundingBox(50f, 100f, 40f, 40f))
        val second = t.update(listOf(far), 100L).single()
        assertEquals(1, t.activeTrackCount())
        org.junit.Assert.assertNotEquals(first.trackId, second.trackId)
    }

    @Test
    fun fr2_027_iou() {
        val a = BoundingBox(10f, 10f, 20f, 20f)
        assertEquals(1f, DwellTracker.computeIoU(a, a), 0f)
        assertEquals(0f, DwellTracker.computeIoU(a, BoundingBox(100f, 100f, 20f, 20f)), 0f)
        // shifted by half a width: overlap 200, union 600
        assertEquals(1f / 3f, DwellTracker.computeIoU(a, BoundingBox(20f, 10f, 20f, 20f)), 1e-6f)
    }
}
