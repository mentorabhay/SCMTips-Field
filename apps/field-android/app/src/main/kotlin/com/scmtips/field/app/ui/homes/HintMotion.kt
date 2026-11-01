package com.scmtips.field.app.ui.homes

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/** One frame of a drawn hint: scale, opacity and an offset in drawing units (the prototype's SVG units). */
data class Frame(val scale: Float = 1f, val alpha: Float = 1f, val dx: Float = 0f, val dy: Float = 0f)

/**
 * The prototype's CSS keyframes (Main, Forgot, Permissions, Glasses, WarehouseHome, TowerHome, ScanSeal .dc.html) as
 * pure functions of the loop position [t] in [0, 1). The Compose art drives [t] with rememberInfiniteTransition; with
 * reduce motion on it draws [still] frames instead (the prototype's `prefers-reduced-motion: reduce` = no animation).
 * Pure Kotlin so every curve is JVM-tested (HintMotionTest).
 */
object HintMotion {
    /** Loop lengths in milliseconds, as in the prototype. */
    const val PULSE_MS = 1600
    const val POP_MS = 3000
    const val WAVE_MS = 1000
    const val RING_MS = 3000
    const val FLY_MS = 2400
    const val BREATHE_MS = 2400
    const val TAP_MS = 2000
    const val BLINK_MS = 2000
    const val PING_MS = 1800
    const val CLOSE_MS = 2800

    /** [t] shifted by [delayMs] of a [loopMs] loop, wrapped into [0, 1). */
    fun shifted(t: Float, delayMs: Int, loopMs: Int): Float {
        val u = t - delayMs.toFloat() / loopMs
        return u - kotlin.math.floor(u)
    }

    private fun lerp(a: Float, b: Float, f: Float) = a + (b - a) * f.coerceIn(0f, 1f)
    private fun easeOut(f: Float) = 1f - (1f - f) * (1f - f)
    private fun easeIn(f: Float) = f * f

    /** `pulse`: 0 % and 100 % scale 1, opacity 0.55; 50 % scale [peak], opacity 0 (ease-out). */
    fun pulse(t: Float, peak: Float = 1.6f, alpha: Float = 0.55f): Frame {
        val f = easeOut(if (t < 0.5f) t * 2f else (1f - t) * 2f)
        return Frame(scale = lerp(1f, peak, f), alpha = lerp(alpha, 0f, f))
    }

    /** `pop`: hidden and small until 20 %, grows in by 35 %, holds to 85 %, fades out by 100 %. */
    fun pop(t: Float): Frame = when {
        t < 0.20f -> Frame(0.4f, 0f)
        t < 0.35f -> easeOut((t - 0.20f) / 0.15f).let { Frame(lerp(0.4f, 1f, it), it) }
        t < 0.85f -> Frame(1f, 1f)
        else -> Frame(1f, 1f - (t - 0.85f) / 0.15f)
    }

    /** `wave`: a bar's height factor, 0.35 at the ends of the loop, 1 at half (ease-in-out). */
    fun wave(t: Float): Float = 0.35f + 0.65f * (0.5f - 0.5f * cos(2f * PI.toFloat() * t))

    /** `ring`: the share of the countdown ring still drawn (1 → 0, linear). */
    fun ring(t: Float): Float = (1f - t).coerceIn(0f, 1f)

    /** `fly`: the paper plane leaves to (70, -40) by 70 %, then to (90, -52) while fading (ease-in). */
    fun fly(t: Float): Frame = if (t < 0.7f) {
        val f = easeIn(t / 0.7f)
        Frame(dx = 70f * f, dy = -40f * f)
    } else {
        val f = (t - 0.7f) / 0.3f
        Frame(dx = lerp(70f, 90f, f), dy = lerp(-40f, -52f, f), alpha = 1f - f)
    }

    /** `breathe`: scale 1 → 1.08 → 1. */
    fun breathe(t: Float): Float = 1f + 0.04f * (1f - cos(2f * PI.toFloat() * t))

    /** `tap`: still until 60 %, down 4 units at 70 %, back up by 100 %. */
    fun tap(t: Float): Float = when {
        t < 0.6f -> 0f
        t < 0.7f -> 4f * (t - 0.6f) / 0.1f
        else -> 4f * (1f - (t - 0.7f) / 0.3f)
    }

    /** `blink`: opacity 1 → 0.35 → 1. */
    fun blink(t: Float): Float = 1f - 0.65f * (0.5f - 0.5f * cos(2f * PI.toFloat() * t))

    /** `ping`: a ring grows from 0.6 to 2.2 while fading from 0.7 to 0. */
    fun ping(t: Float): Frame = easeOut(t).let { Frame(scale = lerp(0.6f, 2.2f, it), alpha = lerp(0.7f, 0f, it)) }

    /** `close`: the scan frame closes in from 1.35 (faint) to 1 by 55 %, holds to 85 %, then fades. */
    fun close(t: Float): Frame = when {
        t < 0.20f -> Frame(1.35f, 0.4f)
        t < 0.55f -> easeOut((t - 0.20f) / 0.35f).let { Frame(lerp(1.35f, 1f, it), lerp(0.4f, 1f, it)) }
        t < 0.85f -> Frame(1f, 1f)
        else -> Frame(1f, 1f - (t - 0.85f) / 0.15f)
    }

    /** `found`: the "Code read" tag, hidden to 55 %, in by 65 %, shown to 90 %, out by 100 %. */
    fun found(t: Float): Float = when {
        t < 0.55f -> 0f
        t < 0.65f -> (t - 0.55f) / 0.1f
        t < 0.90f -> 1f
        else -> 1f - (t - 0.90f) / 0.1f
    }

    /** A gentle bob for empty-state drawings (± [amp] units, one sine period). */
    fun bob(t: Float, amp: Float = 3f): Float = amp * sin(2f * PI.toFloat() * t)

    /**
     * The still frames drawn when reduce motion is on: everything in its resting, readable place. Halos and pings
     * are hidden (a solid halo would read as a bigger dot), outlines and the frame are shown, the "Code read" tag is
     * hidden (a still drawing must not claim a code was read), the ring is full.
     */
    object Still {
        val pulse = Frame(1f, 0f)
        val pop = Frame(1f, 1f)
        const val WAVE = 0.7f
        const val RING = 1f
        val fly = Frame()
        const val BREATHE = 1f
        const val TAP = 0f
        const val BLINK = 1f
        val ping = Frame(1f, 0f)
        val close = Frame(1f, 1f)
        const val FOUND = 0f
        const val BOB = 0f
    }
}
