package com.scmtips.field.app.look

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Outline scaling (image pixels → canvas pixels, letterboxed) and the look photo's on-device blur rules. */
class OutlineGeometryTest {
    private fun near(e: Float, a: Float) = assertEquals(e, a, 0.01f)

    @Test
    fun m5B01_landscapePhotoInATallCanvas_isLetterboxedTopAndBottom() {
        val f = Fit.of(1920, 1440, 960f, 1000f)!!
        near(0.5f, f.scale)
        near(0f, f.offsetX); near(140f, f.offsetY) // 1440 * 0.5 = 720 drawn; (1000 - 720) / 2
        near(960f, f.drawnW); near(720f, f.drawnH)
        val b = f.box(listOf(100.0, 200.0, 300.0, 400.0))!!
        near(50f, b.left); near(240f, b.top); near(150f, b.right); near(340f, b.bottom)
        val (x, y) = f.point(1920.0, 1440.0)
        near(960f, x); near(860f, y)
    }

    @Test
    fun m5B01_portraitPhotoInAWideCanvas_isLetterboxedLeftAndRight() {
        val f = Fit.of(480, 640, 1000f, 400f)!!
        near(0.625f, f.scale)
        near(350f, f.offsetX); near(0f, f.offsetY) // 480 * 0.625 = 300 wide; (1000 - 300) / 2
        val b = f.box(listOf(0.0, 0.0, 480.0, 640.0))!!
        near(350f, b.left); near(650f, b.right); near(0f, b.top); near(400f, b.bottom)
    }

    @Test
    fun m5B01_boxesAreNormalisedClampedAndMalformedOnesDropped() {
        val f = Fit.of(640, 480, 640f, 480f)!!
        near(1f, f.scale)
        val swapped = f.box(listOf(300.0, 200.0, 100.0, 50.0))!!
        near(100f, swapped.left); near(50f, swapped.top); near(300f, swapped.right); near(200f, swapped.bottom)
        val over = f.box(listOf(-20.0, -10.0, 700.0, 500.0))!!
        near(0f, over.left); near(0f, over.top); near(640f, over.right); near(480f, over.bottom)
        assertNull("outside the image", f.box(listOf(700.0, 10.0, 800.0, 50.0)))
        assertNull("three numbers", f.box(listOf(1.0, 2.0, 3.0)))
        assertNull(Fit.of(0, 480, 640f, 480f))
        assertNull(Fit.of(640, 480, 0f, 480f))
    }

    @Test
    fun m5B01_canvasHeightFollowsThePhotoUpToTheCap() {
        near(480f, Fit.heightFor(640, 480, 640f, 1000f))
        near(500f, Fit.heightFor(480, 640, 640f, 500f))
        near(300f, Fit.heightFor(0, 0, 640f, 300f))
    }

    @Test
    fun m5B01_outlinesUseTheLooksImageSize_elseThePhotos() {
        val look = Look("lk", "model", "cap", 1920, 1440, emptyList(), LookCounts(null, null, null, null), 0, null, 0, emptyList(),
            null, "", emptyList(), emptyList())
        assertEquals(1920 to 1440, outlineFrame(look, 640, 480))
        assertEquals(640 to 480, outlineFrame(look.copy(imageWidth = null), 640, 480))
        assertEquals(640 to 480, outlineFrame(null, 640, 480))
    }

    @Test
    fun m5B01_facesArePixelatedInSixteenPixelBlocksOfTheirMeanColour() {
        val w = 32; val h = 16
        val argb = IntArray(w * h) { i -> if (i % 2 == 0) 0xFF000000.toInt() else 0xFFFFFFFF.toInt() }
        FacePixels.pixelate(argb, w, h, listOf(PixelBox(0, 0, 16, 16)))
        val block = (0 until 16).flatMap { y -> (0 until 16).map { x -> argb[y * w + x] } }.toSet()
        assertEquals("one mean colour in the block", 1, block.size)
        assertEquals(0xFF7F7F7F.toInt(), block.single())
        assertNotEquals("outside the face box untouched", argb[16], argb[17])
    }

    @Test
    fun m5B01_faceBoxIsGrownAndClamped_andPhotosAreScaledTo1600WithAnEvenWidth() {
        val b = FacePixels.faceBox(100f, 100f, 40f, 640, 480)!!
        assertEquals(PixelBox(51, 47, 148, 170), b)
        val edge = FacePixels.faceBox(5f, 5f, 40f, 640, 480)!!
        assertEquals(0, edge.left); assertEquals(0, edge.top)
        assertNull(FacePixels.faceBox(10f, 10f, 0f, 640, 480))
        // M5-P01: a look photo is at most 1600 px on its long side (was 640); never scaled up; width even
        assertEquals(1600 to 1200, FacePixels.scaledSize(1920, 1440))
        assertEquals(1200 to 1600, FacePixels.scaledSize(3024, 4032))
        assertEquals(720 to 1280, FacePixels.scaledSize(720, 1280))
        assertEquals(1600 to 900, FacePixels.scaledSize(1601, 901))
        assertEquals(500 to 375, FacePixels.scaledSize(500, 375))
        assertEquals(500 to 375, FacePixels.scaledSize(501, 375))
        // the explicit cap still works for any other caller
        assertEquals(640 to 480, FacePixels.scaledSize(1920, 1440, max = 640))
    }

    @Test
    fun m5P01_lookPhotoIs1600AtQuality85_andCameraFilesAreDecodedAtOneToTwiceThatSize() {
        assertEquals(1600, LookApi.MAX_PX)
        assertEquals(85, LookApi.JPEG_QUALITY)
        assertEquals(1_000_000, LookApi.MAX_BYTES) // the captures API's 1 MB limit is unchanged
        // a 12 MP phone file (4032 x 3024) is decoded at 2016 x 1512 (sample 2), then scaled to 1600 x 1200
        assertEquals(2, FacePixels.sampleFor(4032, 3024))
        assertEquals(1600 to 1200, FacePixels.scaledSize(4032 / 2, 3024 / 2))
        // a 48 MP file (8000 x 6000): sample 4 -> 2000 px; never below the 1600 px look size
        assertEquals(4, FacePixels.sampleFor(8000, 6000))
        assertEquals(1, FacePixels.sampleFor(3199, 2400)) // 3199 / 2 < 1600: decoded full size, then scaled down
        assertEquals(2, FacePixels.sampleFor(3200, 2400))
        assertEquals(1, FacePixels.sampleFor(1280, 960)) // small photos are not sampled (and not scaled up)
        for (w in listOf(1600, 2000, 3000, 4032, 6000, 9000)) {
            val s = FacePixels.sampleFor(w, w * 3 / 4)
            assertTrue("decoded long side ${w / s} >= 1600", w / s >= 1600)
            assertTrue("decoded long side ${w / s} < 3200", w / s < 3200)
        }
    }
}
