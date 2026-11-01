package com.scmtips.field.app.ui.kit

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/*
 * The six hint animations of the M5-U task screens (blueprint; prototype ReceiveLook, ReceivePost, TowerHarness,
 * ScanSeal). Compose Canvas drawing and rememberInfiniteTransition only: no image files, no Lottie, no new
 * dependency. Each loops over 3 seconds, draws one still frame when [reduceMotion] is true, and carries the hint's
 * description for TalkBack. All drawing is in a 240 x 150 design box scaled to the canvas.
 */

private const val W = 240f
private const val H = 150f
private const val PERIOD_MS = 3_000

/** The hint's animation for [hint]; pass LocalReduceMotion.current (builder A) or [rememberSystemReduceMotion]. */
@Composable
fun HintAnimation(hint: Hint, reduceMotion: Boolean, modifier: Modifier = Modifier) {
    when (hint) {
        Hint.LOOK -> LookHint(reduceMotion, modifier)
        Hint.SAY_NUMBERS -> SayNumbersHint(reduceMotion, modifier)
        Hint.CONFIRM -> ConfirmHint(reduceMotion, modifier)
        Hint.SCAN_BIN_PRODUCT -> ScanBinProductHint(reduceMotion, modifier)
        Hint.SEAL_CODE -> SealCodeHint(reduceMotion, modifier)
        Hint.CLIP_IN -> ClipInHint(reduceMotion, modifier)
    }
}

/** 0..1 over [PERIOD_MS], looping; a fixed [still] frame when motion is off. Read it inside the draw lambda only. */
@Composable
private fun loop(reduceMotion: Boolean, still: Float): State<Float> {
    if (reduceMotion) return remember(still) { mutableFloatStateOf(still) }
    val tr = rememberInfiniteTransition(label = "hint")
    return tr.animateFloat(0f, 1f, infiniteRepeatable(tween(PERIOD_MS, easing = LinearEasing), RepeatMode.Restart), label = "hint-t")
}

/** Draws [block] in the 240 x 150 design box, centred and scaled to fit. */
private fun DrawScope.design(block: DrawScope.() -> Unit) {
    val k = minOf(size.width / W, size.height / H)
    translate((size.width - W * k) / 2f, (size.height - H * k) / 2f) {
        scale(k, k, pivot = Offset.Zero) { block() }
    }
}

/** 0 before [from], 1 after [to], linear between. */
private fun phase(t: Float, from: Float, to: Float): Float = ((t - from) / (to - from)).coerceIn(0f, 1f)

@Composable
private fun HintCanvas(description: String, modifier: Modifier, draw: DrawScope.() -> Unit) {
    Box(modifier.semantics { contentDescription = description }) { Canvas(Modifier.fillMaxSize(), onDraw = draw) }
}

private fun DrawScope.label(m: TextMeasurer, text: String, at: Offset, color: Color, size: Float = 12f, bold: Boolean = true) {
    drawText(m, text, topLeft = at, style = TextStyle(color = color, fontSize = size.sp, fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal))
}

// (1) Look at the delivery: glasses outline, the capture button pulsing, numbered outlines popping onto the boxes.
@Composable
fun LookHint(reduceMotion: Boolean, modifier: Modifier = Modifier) {
    val t = loop(reduceMotion, still = 0.8f)
    val m = rememberTextMeasurer()
    HintCanvas(Hint.LOOK.description, modifier) {
        design {
            val tv = t.value
            val s = Stroke(width = 3f, cap = StrokeCap.Round, join = StrokeJoin.Round)
            // glasses
            drawRoundRect(Color.White, Offset(70f, 10f), Size(40f, 26f), CornerRadius(10f), style = s)
            drawRoundRect(Color.White, Offset(130f, 10f), Size(40f, 26f), CornerRadius(10f), style = s)
            drawLine(Color.White, Offset(110f, 20f), Offset(130f, 20f), strokeWidth = 3f, cap = StrokeCap.Round)
            // capture button with pulse
            val pulse = (tv * 2f) % 1f
            drawCircle(StepDone.copy(alpha = 0.6f * (1f - pulse)), radius = 5f + 9f * pulse, center = Offset(178f, 10f))
            drawCircle(StepDone, radius = 5f, center = Offset(178f, 10f))
            // boxes and their outlines
            val fade = 1f - phase(tv, 0.92f, 1f)
            for (i in 0 until 4) {
                val x = 22f + i * 52f
                drawRoundRect(Color(0xFF4B4F5C), Offset(x, 70f), Size(44f, 56f), CornerRadius(5f))
                val p = phase(tv, 0.25f + i * 0.1f, 0.35f + i * 0.1f)
                if (p > 0f) {
                    val k = 0.5f + 0.5f * p
                    val col = if (i == 2) StepDone else LiveGreen
                    scale(k, k, pivot = Offset(x + 22f, 98f)) {
                        drawRoundRect(col.copy(alpha = fade * p), Offset(x - 4f, 66f), Size(52f, 64f), CornerRadius(7f), style = Stroke(width = 3f))
                    }
                    if (p >= 1f) label(m, "${i + 1}", Offset(x + 2f, 72f), col.copy(alpha = fade), 11f)
                }
            }
        }
    }
}

// (2) Say your numbers: a speech bubble typing "receive 7, flag 1", then the two number boxes filling.
@Composable
fun SayNumbersHint(reduceMotion: Boolean, modifier: Modifier = Modifier) {
    val t = loop(reduceMotion, still = 0.9f)
    val m = rememberTextMeasurer()
    val phrase = "receive 7, flag 1"
    HintCanvas(Hint.SAY_NUMBERS.description, modifier) {
        design {
            val tv = t.value
            drawRoundRect(NightRaised, Offset(20f, 8f), Size(200f, 44f), CornerRadius(14f))
            drawPath(Path().apply { moveTo(48f, 52f); lineTo(58f, 64f); lineTo(64f, 52f); close() }, NightRaised)
            val shown = (phrase.length * phase(tv, 0.05f, 0.5f)).toInt()
            label(m, "“" + phrase.take(shown) + if (shown < phrase.length && (tv * 6f).toInt() % 2 == 0) "|" else "", Offset(34f, 18f), Color.White, 15f, bold = false)
            val boxes = listOf(Triple("Receive", "7", SoftGreen) to 0.55f, Triple("Flag", "1", SoftAmber) to 0.7f)
            boxes.forEachIndexed { i, (b, at) ->
                val (name, value, col) = b
                val x = 20f + i * 104f
                val f = phase(tv, at, at + 0.1f)
                drawRoundRect(NightCard, Offset(x, 76f), Size(96f, 66f), CornerRadius(12f))
                drawRoundRect(col.copy(alpha = 0.25f + 0.75f * f), Offset(x, 76f), Size(96f, 66f), CornerRadius(12f), style = Stroke(width = 2.5f))
                label(m, name, Offset(x + 10f, 82f), NightMuted, 11f, bold = false)
                if (f > 0f) label(m, value, Offset(x + 38f, 98f), col.copy(alpha = f), 26f)
            }
        }
    }
}

// (3) Confirm within 10 seconds: the real ConfirmRing (TaskChrome.kt) counting down around a tick.
@Composable
fun ConfirmHint(reduceMotion: Boolean, modifier: Modifier = Modifier) {
    val t = loop(reduceMotion, still = 0.3f)
    val left = 1f - t.value
    Box(modifier, contentAlignment = Alignment.Center) {
        ConfirmRing(progress = left, urgent = left <= 0.3f, description = Hint.CONFIRM.description, side = 56.dp, stroke = 6.dp) {
            TickGlyph(LiveGreen, side = 32.dp, stroke = 4.dp)
        }
    }
}

// (4) Scan the bin, then the product: a scan line sweeps a bin label, a tick; then a product label, a tick.
@Composable
fun ScanBinProductHint(reduceMotion: Boolean, modifier: Modifier = Modifier) {
    val t = loop(reduceMotion, still = 0.9f)
    val m = rememberTextMeasurer()
    HintCanvas(Hint.SCAN_BIN_PRODUCT.description, modifier) {
        design {
            val tv = t.value
            val labels = listOf(Offset(14f, 30f) to "BIN", Offset(128f, 30f) to "ITEM")
            labels.forEachIndexed { i, (o, name) ->
                drawRoundRect(Ground, o, Size(98f, 76f), CornerRadius(8f))
                label(m, name, Offset(o.x + 8f, o.y + 6f), Ink, 11f)
                // barcode bars
                listOf(0f, 7f, 11f, 19f, 24f, 31f, 36f, 44f, 50f, 57f, 63f, 70f).forEachIndexed { k, dx ->
                    drawRect(Ink, Offset(o.x + 12f + dx, o.y + 26f), Size(if (k % 3 == 0) 4f else 2f, 34f))
                }
                val start = if (i == 0) 0.05f else 0.45f
                val sweep = phase(tv, start, start + 0.32f)
                if (sweep > 0f && sweep < 1f) {
                    drawRoundRect(Lavender, Offset(o.x - 4f, o.y + 4f + 68f * sweep), Size(106f, 3f), CornerRadius(1.5f))
                }
                if (sweep >= 1f) {
                    drawCircle(LiveGreen, radius = 14f, center = Offset(o.x + 86f, o.y + 4f))
                    val p = Path().apply { moveTo(o.x + 79f, o.y + 4f); lineTo(o.x + 84f, o.y + 9f); lineTo(o.x + 93f, o.y - 2f) }
                    drawPath(p, NightTask, style = Stroke(width = 3.5f, cap = StrokeCap.Round, join = StrokeJoin.Round))
                }
            }
            label(m, "1", Offset(58f, 112f), NightMuted, 13f)
            label(m, "2", Offset(172f, 112f), NightMuted, 13f)
        }
    }
}

// (5) Point at the seal code: a corner frame closes on a QR code, then "Code read".
@Composable
fun SealCodeHint(reduceMotion: Boolean, modifier: Modifier = Modifier) {
    val t = loop(reduceMotion, still = 0.75f)
    val m = rememberTextMeasurer()
    HintCanvas(Hint.SEAL_CODE.description, modifier) {
        design {
            val tv = t.value
            val qx = 90f
            val qy = 22f
            drawRoundRect(Ground, Offset(qx, qy), Size(60f, 60f), CornerRadius(6f))
            listOf(Offset(qx + 6f, qy + 6f), Offset(qx + 36f, qy + 6f), Offset(qx + 6f, qy + 36f)).forEach { f ->
                drawRect(Ink, f, Size(18f, 18f)); drawRect(Ground, f + Offset(4f, 4f), Size(10f, 10f)); drawRect(Ink, f + Offset(7f, 7f), Size(4f, 4f))
            }
            drawRect(Ink, Offset(qx + 38f, qy + 38f), Size(7f, 7f)); drawRect(Ink, Offset(qx + 47f, qy + 47f), Size(7f, 7f))
            val close = phase(tv, 0.2f, 0.55f)
            val gone = phase(tv, 0.92f, 1f)
            val k = 1.35f - 0.35f * close
            val a = (0.4f + 0.6f * close) * (1f - gone)
            val s = Stroke(width = 4f, cap = StrokeCap.Round, join = StrokeJoin.Round)
            scale(k, k, pivot = Offset(qx + 30f, qy + 30f)) {
                val l = qx - 10f; val r = qx + 70f; val tp = qy - 10f; val b = qy + 70f
                val c = 16f
                val frame = Path().apply {
                    moveTo(l, tp + c); lineTo(l, tp); lineTo(l + c, tp)
                    moveTo(r - c, tp); lineTo(r, tp); lineTo(r, tp + c)
                    moveTo(r, b - c); lineTo(r, b); lineTo(r - c, b)
                    moveTo(l + c, b); lineTo(l, b); lineTo(l, b - c)
                }
                drawPath(frame, StepDone.copy(alpha = a), style = s)
            }
            val found = phase(tv, 0.58f, 0.66f) * (1f - gone)
            if (found > 0f) {
                drawRoundRect(LiveGreen.copy(alpha = found), Offset(80f, 112f), Size(80f, 26f), CornerRadius(13f))
                label(m, "Code read", Offset(91f, 117f), NightTask.copy(alpha = found), 12f)
            }
        }
    }
}

// (6) Clip in before you climb: a harness hook snaps shut, then the button and the phrase light together.
@Composable
fun ClipInHint(reduceMotion: Boolean, modifier: Modifier = Modifier) {
    val t = loop(reduceMotion, still = 0.8f)
    val m = rememberTextMeasurer()
    HintCanvas(Hint.CLIP_IN.description, modifier) {
        design {
            val tv = t.value
            drawRoundRect(NightTrack, Offset(20f, 8f), Size(10f, 134f), CornerRadius(4f))
            drawRoundRect(NightTrack, Offset(20f, 38f), Size(76f, 9f), CornerRadius(4f))
            val shut = phase(tv, 0.35f, 0.5f)
            rotate(-38f * (1f - shut), pivot = Offset(62f, 42f)) {
                val hook = Path().apply {
                    moveTo(62f, 42f)
                    cubicTo(62f, 22f, 96f, 22f, 96f, 42f)
                    lineTo(96f, 76f)
                    cubicTo(96f, 92f, 72f, 92f, 72f, 76f)
                }
                drawPath(hook, StepDone, style = Stroke(width = 8f, cap = StrokeCap.Round))
            }
            val lit = phase(tv, 0.55f, 0.62f) * (1f - phase(tv, 0.94f, 1f))
            val on = { base: Color -> if (lit > 0f) LiveGreen.copy(alpha = 0.25f + 0.75f * lit) else base }
            drawRoundRect(NightRaised, Offset(120f, 34f), Size(108f, 30f), CornerRadius(15f))
            drawRoundRect(on(NightTrack), Offset(120f, 34f), Size(108f, 30f), CornerRadius(15f), style = Stroke(width = 2.5f))
            label(m, "“harness clipped”", Offset(128f, 41f), if (lit > 0f) SoftGreen else NightMuted, 10f, bold = false)
            drawRoundRect(on(NightRaised), Offset(120f, 82f), Size(108f, 34f), CornerRadius(12f))
            label(m, "I am clipped in", Offset(131f, 91f), if (lit > 0f) NightTask else Color.White, 11f)
        }
    }
}
