package com.scmtips.field.app.look

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
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
    fun m5B01_faceBoxIsGrownAndClamped_andPhotosAreScaledTo640WithAnEvenWidth() {
        val b = FacePixels.faceBox(100f, 100f, 40f, 640, 480)!!
        assertEquals(PixelBox(51, 47, 148, 170), b)
        val edge = FacePixels.faceBox(5f, 5f, 40f, 640, 480)!!
        assertEquals(0, edge.left); assertEquals(0, edge.top)
        assertNull(FacePixels.faceBox(10f, 10f, 0f, 640, 480))
        assertEquals(640 to 480, FacePixels.scaledSize(1920, 1440))
        assertEquals(360 to 640, FacePixels.scaledSize(720, 1280))
        assertEquals(500 to 375, FacePixels.scaledSize(500, 375))
        assertEquals(500 to 375, FacePixels.scaledSize(501, 375))
    }
}
