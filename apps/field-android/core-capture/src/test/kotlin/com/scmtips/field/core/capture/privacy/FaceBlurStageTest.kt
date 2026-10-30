package com.scmtips.field.core.capture.privacy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer

/**
 * Bystander blur by the production FaceBlurStage (FR2.022). The detector and JPEG encoder are
 * platform pieces (ML Kit, Bitmap.compress); here the encoder writes raw ARGB so the test can
 * inspect exactly the pixels that would be encoded.
 */
class FaceBlurStageTest {

    private val rawEncoder = CropEncoder { crop ->
        ByteBuffer.allocate(crop.argb.size * 4).also { b -> crop.argb.forEach { b.putInt(it) } }.array()
    }

    private fun decode(bytes: ByteArray, w: Int, h: Int): PixelCrop {
        val b = ByteBuffer.wrap(bytes)
        return PixelCrop(w, h, IntArray(w * h) { b.getInt() })
    }

    /** High-frequency "face" texture: 2 px checkerboard, plus a smooth gradient background. */
    private fun scene(w: Int, h: Int, face: FaceBox): PixelCrop = PixelCrop(w, h, IntArray(w * h) { i ->
        val x = i % w
        val y = i / w
        if (x in face.left until face.right && y in face.top until face.bottom) {
            if ((x / 2 + y / 2) % 2 == 0) 0xFFFFFFFF.toInt() else 0xFF000000.toInt()
        } else {
            (0xFF shl 24) or ((x % 256) shl 16) or ((y % 256) shl 8) or 0x40
        }
    })

    @Test
    fun tc2_037_bystanderFacePixelatedAndCounted_fr2_022() {
        val face = FaceBox(70, 50, 130, 110, 0.9f) // 60 x 60 px
        val src = scene(200, 200, face)
        val stage = FaceBlurStage(FaceDetector { listOf(face) }, rawEncoder, clock = { 1L })
        val res = stage.processCrop(src) as BlurResult.Success
        assertTrue(res.crop.blurApplied)
        assertEquals(1, res.crop.facesBlurred)

        val out = decode(res.crop.jpegBytes, 200, 200)
        val e = stage.expandMargin(face, 200, 200) // 64,44 .. 136,116
        // every 16 px block of the expanded box is one colour: no face texture survives
        var by = e.top
        while (by < e.bottom) {
            var bx = e.left
            while (bx < e.right) {
                val colours = mutableSetOf<Int>()
                for (y in by until minOf(by + 16, e.bottom)) for (x in bx until minOf(bx + 16, e.right)) colours.add(out.pixel(x, y))
                assertEquals("block at $bx,$by", 1, colours.size)
                bx += 16
            }
            by += 16
        }
        // pixels outside the expanded box are untouched
        for (y in 0 until 200) for (x in 0 until 200) {
            if (x !in e.left until e.right || y !in e.top until e.bottom) assertEquals(src.pixel(x, y), out.pixel(x, y))
        }
        // the input crop object was not modified in place
        assertEquals(0xFFFFFFFF.toInt(), src.pixel(70, 50))
    }

    @Test
    fun tc2_038_detectorFailureWithholdsCrop_fr2_022() {
        val stage = FaceBlurStage(FaceDetector { throw IllegalStateException("model not loaded") }, rawEncoder)
        val res = stage.processCrop(scene(64, 64, FaceBox(0, 0, 1, 1, 1f)))
        assertTrue(res is BlurResult.Withheld)
        assertEquals("evidence_withheld", (res as BlurResult.Withheld).evidenceStatus)
    }

    @Test
    fun fr2_022_cropWithNoFaceStillCarriesBlurApplied() {
        // the server rejects blur_applied=false (FIELD-CAP-422-BLUR-MISSING); faces_blurred is 0
        val src = scene(32, 32, FaceBox(0, 0, 0, 0, 0f))
        val res = FaceBlurStage(FaceDetector { emptyList() }, rawEncoder).processCrop(src) as BlurResult.Success
        assertTrue(res.crop.blurApplied)
        assertEquals(0, res.crop.facesBlurred)
        assertEquals(src.argb.toList(), decode(res.crop.jpegBytes, 32, 32).argb.toList())
    }

    @Test
    fun fr2_022_detectionThresholdIs0_30AndMarginIsTenPercentClamped() {
        val weak = FaceBox(0, 0, 20, 20, 0.29f)
        val atFloor = FaceBox(20, 20, 40, 40, 0.30f)
        val res = FaceBlurStage(FaceDetector { listOf(weak, atFloor) }, rawEncoder)
            .processCrop(scene(64, 64, atFloor)) as BlurResult.Success
        assertEquals(1, res.crop.facesBlurred)
        val stage = FaceBlurStage(FaceDetector { emptyList() }, rawEncoder)
        assertEquals(FaceBox(16, 16, 64, 64, 1f), stage.expandMargin(FaceBox(20, 20, 60, 60, 1f), 100, 100))
        assertEquals(FaceBox(0, 0, 64, 64, 1f), stage.expandMargin(FaceBox(0, 0, 60, 60, 1f), 64, 64))
    }

    @Test
    fun fr2_066_cropAbove640IsWithheld() {
        val stage = FaceBlurStage(FaceDetector { emptyList() }, rawEncoder)
        assertTrue(stage.processCrop(PixelCrop(641, 10, IntArray(6410))) is BlurResult.Withheld)
        assertFalse(stage.processCrop(PixelCrop(640, 10, IntArray(6400))) is BlurResult.Withheld)
    }
}
