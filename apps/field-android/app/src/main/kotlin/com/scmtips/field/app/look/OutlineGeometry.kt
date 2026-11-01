package com.scmtips.field.app.look

import kotlin.math.min

/** A rectangle in canvas pixels. */
data class Box(val left: Float, val top: Float, val right: Float, val bottom: Float) {
    val width: Float get() = right - left
    val height: Float get() = bottom - top
}

/**
 * How an image of [imageW] x [imageH] pixels is drawn into a canvas of [canvasW] x [canvasH]: scaled to fit
 * whole (aspect kept) and centred, with bars left/right or top/bottom (letterboxing). The look's outlines
 * are in image pixels of the uploaded photo (contract §2); [box] / [point] map them onto the canvas.
 */
data class Fit(val scale: Float, val offsetX: Float, val offsetY: Float, val drawnW: Float, val drawnH: Float) {
    fun point(x: Double, y: Double): Pair<Float, Float> = (offsetX + x.toFloat() * scale) to (offsetY + y.toFloat() * scale)

    /** [x0, y0, x1, y1] in image pixels → canvas, clamped to the drawn image; null for a malformed box. */
    fun box(b: List<Double>): Box? {
        if (b.size != 4) return null
        val (x0, y0) = point(minOf(b[0], b[2]), minOf(b[1], b[3]))
        val (x1, y1) = point(maxOf(b[0], b[2]), maxOf(b[1], b[3]))
        val l = x0.coerceIn(offsetX, offsetX + drawnW)
        val t = y0.coerceIn(offsetY, offsetY + drawnH)
        val r = x1.coerceIn(offsetX, offsetX + drawnW)
        val bt = y1.coerceIn(offsetY, offsetY + drawnH)
        return if (r <= l || bt <= t) null else Box(l, t, r, bt)
    }

    companion object {
        fun of(imageW: Int, imageH: Int, canvasW: Float, canvasH: Float): Fit? {
            if (imageW <= 0 || imageH <= 0 || canvasW <= 0f || canvasH <= 0f) return null
            val s = min(canvasW / imageW, canvasH / imageH)
            val w = imageW * s
            val h = imageH * s
            return Fit(s, (canvasW - w) / 2f, (canvasH - h) / 2f, w, h)
        }

        /** The canvas height for a full-width image, so a portrait or landscape photo needs no bars. */
        fun heightFor(imageW: Int, imageH: Int, canvasW: Float, maxH: Float): Float =
            if (imageW <= 0 || imageH <= 0) maxH else min(maxH, canvasW * imageH / imageW)
    }
}

/**
 * The image size the outlines refer to: the look's own `image` size when the server sent it, else the
 * photo the phone uploaded (they are the same picture: the phone uploads exactly what it shows).
 */
fun outlineFrame(look: Look?, photoW: Int, photoH: Int): Pair<Int, Int> {
    val w = look?.imageWidth
    val h = look?.imageHeight
    return if (w != null && h != null) w to h else photoW to photoH
}
