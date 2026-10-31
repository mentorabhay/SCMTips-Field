package com.scmtips.field.app.scan

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Scan by looking (M3 contract §5): two consecutive frames, no repeat within 3 s; I420 to NV21 for ML Kit. */
class FrameScanFilterTest {

    @Test
    fun aCodeInOneFrameIsNotAScanTwoConsecutiveFramesAre() {
        val f = FrameScanFilter()
        assertTrue(f.onFrame(listOf("SAMPLE-MAT-0001"), 0).isEmpty())
        assertEquals(listOf("SAMPLE-MAT-0001"), f.onFrame(listOf("SAMPLE-MAT-0001"), 500))
    }

    @Test
    fun aFrameWithoutTheCodeBreaksTheRun() {
        val f = FrameScanFilter()
        f.onFrame(listOf("A"), 0)
        f.onFrame(emptyList(), 500) // e.g. a frame that could not be decoded
        assertTrue(f.onFrame(listOf("A"), 1_000).isEmpty())
        assertEquals(listOf("A"), f.onFrame(listOf("A"), 1_500))
    }

    @Test
    fun theSameCodeIsNotReportedAgainWithinThreeSeconds() {
        val f = FrameScanFilter(repeatMs = 3_000)
        f.onFrame(listOf("A"), 0)
        assertEquals(listOf("A"), f.onFrame(listOf("A"), 500))
        assertTrue((1..4).all { f.onFrame(listOf("A"), 500L + it * 500).isEmpty() }) // still looking at it: 1.0..2.5 s
        assertTrue(f.onFrame(listOf("A"), 3_499).isEmpty())
        assertEquals("3 s after its report it counts again", listOf("A"), f.onFrame(listOf("A"), 3_500))
    }

    @Test
    fun codesAreComparedTrimmedAndCaseInsensitiveAndEachIsTrackedOnItsOwn() {
        val f = FrameScanFilter()
        f.onFrame(listOf(" sample-mat-0001 ", "03-05-02"), 0)
        assertEquals(listOf("SAMPLE-MAT-0001", "03-05-02"), f.onFrame(listOf("SAMPLE-MAT-0001", "03-05-02", "NEW"), 500))
        assertEquals(listOf("NEW"), f.onFrame(listOf("SAMPLE-MAT-0001", "NEW", "new"), 1_000))
        assertTrue(f.onFrame(listOf("", "  "), 1_500).isEmpty())
    }

    @Test
    fun resetNeedsTwoFreshFramesAndForgetsReports() {
        val f = FrameScanFilter()
        f.onFrame(listOf("A"), 0)
        f.onFrame(listOf("A"), 500)
        f.reset()
        assertTrue(f.onFrame(listOf("A"), 1_000).isEmpty())
        assertEquals(listOf("A"), f.onFrame(listOf("A"), 1_500))
    }

    @Test
    fun i420BecomesNv21WithVuInterleaved() {
        // 4x2 frame: 8 Y bytes, 2 U, 2 V.
        val y = ByteArray(8) { it.toByte() }
        val src = y + byteArrayOf(100, 101) + byteArrayOf(-56, -55)
        val out = Yuv.i420ToNv21(src, 4, 2)!!
        assertArrayEquals(y + byteArrayOf(-56, 100, -55, 101), out)
        assertNull("padded or compressed buffer", Yuv.i420ToNv21(src + byteArrayOf(0), 4, 2))
        assertNull("odd sizes are not 4:2:0", Yuv.i420ToNv21(ByteArray(15), 5, 2))
        assertNull(Yuv.i420ToNv21(ByteArray(0), 0, 0))
    }
}
