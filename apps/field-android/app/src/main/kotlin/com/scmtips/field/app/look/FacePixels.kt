package com.scmtips.field.app.look

/** A face area in image pixels (right/bottom exclusive). */
data class PixelBox(val left: Int, val top: Int, val right: Int, val bottom: Int)

/**
 * The on-device bystander blur for look photos, with the same rules as core-capture's FaceBlurStage
 * (FR2.022): every face at confidence >= 0.30, its box grown by 10 % on each side, pixelated in 16 px
 * blocks (each block its mean colour) before the JPEG is made. The face finder is Android's own
 * android.media.FaceDetector (no extra library); it reports an eye midpoint and the eye distance.
 * The blur runs on the full look photo that is uploaded (at most [LookApi.MAX_PX] = 1600 px on its long side, M5-P01),
 * so every model call on the server sees only blurred faces.
 */
object FacePixels {
    const val MIN_CONFIDENCE = 0.30f
    const val MARGIN = 0.10f
    const val BLOCK = 16

    /**
     * A face box from the detector's eye midpoint and eye distance: about 2.2 eye distances wide and
     * 2.8 tall (forehead to chin), grown by [MARGIN] and clamped to the image.
     */
    fun faceBox(midX: Float, midY: Float, eyes: Float, w: Int, h: Int): PixelBox? {
        if (eyes <= 0f) return null
        val halfW = eyes * 1.1f * (1 + MARGIN)
        val up = eyes * 1.2f * (1 + MARGIN)
        val down = eyes * 1.6f * (1 + MARGIN)
        val l = (midX - halfW).toInt().coerceIn(0, w)
        val t = (midY - up).toInt().coerceIn(0, h)
        val r = (midX + halfW).toInt().coerceIn(0, w)
        val b = (midY + down).toInt().coerceIn(0, h)
        return if (r > l && b > t) PixelBox(l, t, r, b) else null
    }

    /** Pixelates [boxes] in [argb] (row-major, [w] x [h]) in place. */
    fun pixelate(argb: IntArray, w: Int, h: Int, boxes: List<PixelBox>) {
        require(argb.size == w * h) { "argb has ${argb.size} pixels, expected ${w * h}" }
        for (box in boxes) {
            var by = box.top.coerceIn(0, h)
            val bottom = box.bottom.coerceIn(0, h)
            val right = box.right.coerceIn(0, w)
            while (by < bottom) {
                val yEnd = minOf(by + BLOCK, bottom)
                var bx = box.left.coerceIn(0, w)
                while (bx < right) {
                    val xEnd = minOf(bx + BLOCK, right)
                    var a = 0L; var r = 0L; var g = 0L; var bl = 0L
                    val n = (yEnd - by) * (xEnd - bx)
                    for (y in by until yEnd) for (x in bx until xEnd) {
                        val p = argb[y * w + x]
                        a += (p ushr 24) and 0xFF; r += (p ushr 16) and 0xFF; g += (p ushr 8) and 0xFF; bl += p and 0xFF
                    }
                    val mean = ((a / n).toInt() shl 24) or ((r / n).toInt() shl 16) or ((g / n).toInt() shl 8) or (bl / n).toInt()
                    for (y in by until yEnd) for (x in bx until xEnd) argb[y * w + x] = mean
                    bx = xEnd
                }
                by = yEnd
            }
        }
    }

    /** The size a photo is scaled to: the long side at most [max] px, aspect kept, width even (the face finder needs it). */
    fun scaledSize(w: Int, h: Int, max: Int = LookApi.MAX_PX): Pair<Int, Int> {
        val longest = maxOf(w, h)
        // integer arithmetic: a float factor (1600 / 1920f) can land a pixel short of the cap
        fun scale(v: Int): Int = if (longest > max) (v.toLong() * max / longest).toInt() else v
        val sw = scale(w).coerceAtLeast(2).let { if (it % 2 == 1) it - 1 else it }
        val sh = scale(h).coerceAtLeast(1)
        return sw to sh
    }

    /**
     * The BitmapFactory inSampleSize for decoding a [w] x [h] camera file: the largest power of two that still leaves
     * the long side at least [max] (so the photo is scaled down to [max], never up), 1 for small files.
     */
    fun sampleFor(w: Int, h: Int, max: Int = LookApi.MAX_PX): Int {
        val longest = maxOf(w, h)
        var sample = 1
        while (longest / (sample * 2) >= max) sample *= 2
        return sample
    }
}
