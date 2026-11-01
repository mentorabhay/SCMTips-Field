package com.scmtips.field.app.ui.homes

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.scmtips.field.app.ui.theme.AccentInk
import com.scmtips.field.app.ui.theme.AccentTint
import com.scmtips.field.app.ui.theme.Good
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Surface
import com.scmtips.field.app.ui.theme.WarnBg

// Drawn art of the homes and first-run screens: the prototype's SVGs redrawn on a Canvas in their own viewBox
// units (k = canvas px per unit). Decorative art is hidden from TalkBack; art that carries meaning has [desc].

/**
 * A Canvas of [w] × [h] viewBox units drawn [width] wide; [desc] null hides it from accessibility services.
 * [draw] runs in the draw phase, so animation state read inside it only redraws.
 */
@Composable
fun Art(w: Float, h: Float, width: Dp, desc: String?, draw: DrawScope.(k: Float) -> Unit) {
    val sem = if (desc == null) Modifier.clearAndSetSemantics { } else Modifier.clearAndSetSemantics { contentDescription = desc }
    Canvas(Modifier.size(width, width * (h / w)).then(sem)) { draw(size.width / w) }
}

/** A polyline (closed when [close]) through viewBox points scaled by [k]. */
fun poly(k: Float, vararg xy: Float, close: Boolean = false): Path = Path().apply {
    moveTo(xy[0] * k, xy[1] * k)
    var i = 2
    while (i < xy.size) { lineTo(xy[i] * k, xy[i + 1] * k); i += 2 }
    if (close) close()
}

fun DrawScope.line(k: Float, color: Color, width: Float, vararg xy: Float) =
    drawPath(poly(k, *xy), color, style = Stroke(width * k, cap = StrokeCap.Round, join = StrokeJoin.Round))

fun DrawScope.roundRect(k: Float, color: Color, x: Float, y: Float, w: Float, h: Float, r: Float, stroke: Float? = null) =
    drawRoundRect(color, Offset(x * k, y * k), Size(w * k, h * k), CornerRadius(r * k, r * k),
        style = stroke?.let { Stroke(it * k, cap = StrokeCap.Round, join = StrokeJoin.Round) } ?: androidx.compose.ui.graphics.drawscope.Fill)

fun DrawScope.dot(k: Float, color: Color, cx: Float, cy: Float, r: Float, alpha: Float = 1f) =
    drawCircle(color, r * k, Offset(cx * k, cy * k), alpha = alpha.coerceIn(0f, 1f))

/** Scales [block] by [f] around the viewBox point (cx, cy). */
fun DrawScope.around(k: Float, cx: Float, cy: Float, f: Float, block: DrawScope.() -> Unit) =
    scale(f, f, Offset(cx * k, cy * k), block)

// ---------------------------------------------------------------- 24-unit line glyphs (prototype icons)

enum class GlyphKind { CAMERA, MIC, BLUETOOTH, BELL, HOUSE, LAYERS, BACK, INFO, BOX, CLOSE, CHEVRON_DOWN, TICK }

/** A 24-unit stroke icon as the prototype draws it (decorative: the text next to it says the same). */
@Composable
fun Glyph(kind: GlyphKind, color: Color, size: Dp = 24.dp, stroke: Float = 2f, scale: State<Float>? = null) {
    Art(24f, 24f, size, desc = null) { k ->
        val f = scale?.value ?: 1f
        around(k, 12f, 12f, f) { glyph(kind, k, color, stroke) }
    }
}

fun DrawScope.glyph(kind: GlyphKind, k: Float, c: Color, sw: Float) {
    val st = Stroke(sw * k, cap = StrokeCap.Round, join = StrokeJoin.Round)
    fun arc(l: Float, t: Float, r: Float, b: Float, start: Float, sweep: Float) =
        drawPath(Path().apply { arcTo(Rect(l * k, t * k, r * k, b * k), start, sweep, true) }, c, style = st)
    when (kind) {
        GlyphKind.CAMERA -> {
            drawPath(poly(k, 4f, 8f, 7f, 8f, 9f, 5f, 15f, 5f, 17f, 8f, 20f, 8f, 20f, 19f, 4f, 19f, close = true), c, style = st)
            drawCircle(c, 3.5f * k, Offset(12f * k, 13f * k), style = st)
        }
        GlyphKind.MIC -> {
            roundRect(k, c, 9f, 3f, 6f, 11f, 3f, stroke = sw)
            arc(5f, 4f, 19f, 18f, 180f, -180f)
            line(k, c, sw, 12f, 18f, 12f, 21f)
        }
        GlyphKind.BLUETOOTH -> drawPath(poly(k, 7f, 7f, 17f, 17f, 12f, 21f, 12f, 3f, 17f, 7f, 7f, 17f), c, style = st)
        GlyphKind.BELL -> {
            drawPath(Path().apply {
                moveTo(6f * k, 16f * k); lineTo(6f * k, 11f * k)
                arcTo(Rect(6f * k, 5f * k, 18f * k, 17f * k), 180f, 180f, false)
                lineTo(18f * k, 16f * k); lineTo(20f * k, 18f * k); lineTo(4f * k, 18f * k); close()
            }, c, style = st)
            arc(10f, 18f, 14f, 22f, 180f, -180f)
        }
        GlyphKind.HOUSE -> {
            line(k, c, sw, 3f, 21f, 3f, 9f, 12f, 3f, 21f, 9f, 21f, 21f)
            line(k, c, sw, 9f, 21f, 9f, 15f, 15f, 15f, 15f, 21f)
        }
        GlyphKind.LAYERS -> {
            drawPath(poly(k, 3f, 7f, 12f, 3f, 21f, 7f, 12f, 11f, close = true), c, style = st)
            line(k, c, sw, 3f, 12f, 12f, 16f, 21f, 12f)
            line(k, c, sw, 3f, 17f, 12f, 21f, 21f, 17f)
        }
        GlyphKind.BACK -> line(k, c, sw, 15f, 18f, 9f, 12f, 15f, 6f)
        GlyphKind.CHEVRON_DOWN -> line(k, c, sw, 6f, 9f, 12f, 15f, 18f, 9f)
        GlyphKind.INFO -> {
            drawCircle(c, 9f * k, Offset(12f * k, 12f * k), style = st)
            line(k, c, sw, 12f, 8f, 12f, 13f); line(k, c, sw, 12f, 16.5f, 12f, 17f)
        }
        GlyphKind.BOX -> {
            drawPath(poly(k, 3f, 7f, 12f, 3f, 21f, 7f, 21f, 17f, 12f, 21f, 3f, 17f, close = true), c, style = st)
            line(k, c, sw, 3f, 7f, 12f, 11f, 21f, 7f); line(k, c, sw, 12f, 11f, 12f, 21f)
        }
        GlyphKind.CLOSE -> { line(k, c, sw, 6f, 6f, 18f, 18f); line(k, c, sw, 18f, 6f, 6f, 18f) }
        GlyphKind.TICK -> line(k, c, sw, 5f, 12.5f, 10f, 17f, 19f, 7f)
    }
}

// ---------------------------------------------------------------- Home art

/** TowerHome.dc.html: the location dot with its ping (the check-in card). */
@Composable
fun LocationPingArt(reduceMotion: Boolean, desc: String?) {
    val t = loopPosition(HintMotion.PING_MS, reduceMotion, "ping")
    Art(56f, 56f, 56.dp, desc) { k ->
        dot(k, AccentTint, 28f, 28f, 26f)
        val f = if (reduceMotion) HintMotion.Still.ping else HintMotion.ping(t.value)
        dot(k, AccentInk, 28f, 28f, 8f * f.scale, alpha = 0.25f * f.alpha / 0.7f)
        dot(k, AccentInk, 28f, 28f, 6f)
    }
}

/** Warehouse empty state: two empty boxes on a dashed shelf, bobbing gently. */
@Composable
fun EmptyShelfArt(reduceMotion: Boolean) {
    val t = loopPosition(3200, reduceMotion, "shelf")
    Art(160f, 96f, 140.dp, desc = null) { k ->
        val dy = if (reduceMotion) HintMotion.Still.BOB else HintMotion.bob(t.value)
        drawLine(FieldLine, Offset(14f * k, 84f * k), Offset(146f * k, 84f * k), 2f * k,
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f * k, 5f * k)), cap = StrokeCap.Round)
        translate(0f, dy * k) {
            drawPath(poly(k, 34f, 40f, 58f, 30f, 82f, 40f, 82f, 70f, 58f, 80f, 34f, 70f, close = true), AccentTint)
            drawPath(poly(k, 34f, 40f, 58f, 30f, 82f, 40f, 82f, 70f, 58f, 80f, 34f, 70f, close = true), AccentInk,
                style = Stroke(2f * k, join = StrokeJoin.Round))
            line(k, AccentInk, 2f, 34f, 40f, 58f, 50f, 82f, 40f); line(k, AccentInk, 2f, 58f, 50f, 58f, 80f)
        }
        translate(0f, -dy * k) {
            roundRect(k, WarnBg, 94f, 46f, 40f, 34f, 5f)
            roundRect(k, SandboxInk, 94f, 46f, 40f, 34f, 5f, stroke = 2f)
            line(k, SandboxInk, 2f, 106f, 46f, 106f, 58f, 122f, 58f, 122f, 46f)
        }
    }
}

/** Tower empty state: a mast with its signal arcs pulsing. */
@Composable
fun EmptyTowerArt(reduceMotion: Boolean) {
    val t = loopPosition(HintMotion.BLINK_MS, reduceMotion, "mast")
    Art(160f, 100f, 140.dp, desc = null) { k ->
        line(k, AccentInk, 2.5f, 80f, 22f, 62f, 92f); line(k, AccentInk, 2.5f, 80f, 22f, 98f, 92f)
        line(k, AccentInk, 2f, 70f, 56f, 90f, 56f); line(k, AccentInk, 2f, 66f, 74f, 94f, 74f)
        line(k, AccentInk, 1.5f, 70f, 56f, 94f, 74f); line(k, AccentInk, 1.5f, 90f, 56f, 66f, 74f)
        roundRect(k, AccentTint, 72f, 26f, 6f, 16f, 2f); roundRect(k, AccentTint, 82f, 26f, 6f, 16f, 2f)
        dot(k, SandboxInk, 80f, 20f, 4f)
        val a = if (reduceMotion) HintMotion.Still.BLINK else HintMotion.blink(t.value)
        for ((i, r) in listOf(14f, 24f).withIndex()) {
            val alpha = a * (1f - i * 0.35f)
            drawArc(ArtInk.Orange, -60f, 120f, false, Offset((80f - r) * k, (20f - r) * k), Size(2 * r * k, 2 * r * k),
                alpha = alpha.coerceIn(0f, 1f), style = Stroke(2.5f * k, cap = StrokeCap.Round))
            drawArc(ArtInk.Orange, 120f, 120f, false, Offset((80f - r) * k, (20f - r) * k), Size(2 * r * k, 2 * r * k),
                alpha = alpha.coerceIn(0f, 1f), style = Stroke(2.5f * k, cap = StrokeCap.Round))
        }
        drawLine(FieldLine, Offset(30f * k, 94f * k), Offset(130f * k, 94f * k), 2f * k, cap = StrokeCap.Round)
    }
}

/** Approvals empty state: an empty tray with a tick that breathes. */
@Composable
fun EmptyInboxArt(reduceMotion: Boolean) {
    val t = loopPosition(HintMotion.BREATHE_MS, reduceMotion, "tray")
    Art(160f, 96f, 140.dp, desc = null) { k ->
        drawPath(poly(k, 30f, 54f, 46f, 24f, 114f, 24f, 130f, 54f, 130f, 82f, 30f, 82f, close = true), Surface)
        drawPath(poly(k, 30f, 54f, 46f, 24f, 114f, 24f, 130f, 54f, 130f, 82f, 30f, 82f, close = true), AccentInk,
            style = Stroke(2f * k, join = StrokeJoin.Round))
        line(k, AccentInk, 2f, 30f, 54f, 62f, 54f, 68f, 64f, 92f, 64f, 98f, 54f, 130f, 54f)
        val f = if (reduceMotion) HintMotion.Still.BREATHE else HintMotion.breathe(t.value)
        around(k, 122f, 22f, f) {
            dot(k, Good, 122f, 22f, 13f)
            line(k, Color.White, 3f, 116f, 22f, 120f, 26f, 128f, 17f)
        }
    }
}

/**
 * Scan home: a box with the maker's seal, the scan frame closing in on its code (ScanSeal.dc.html, without the
 * "Code read" tag: a landing must not claim a code was read).
 */
@Composable
fun SealArt(reduceMotion: Boolean, width: Dp, desc: String?) {
    val t = loopPosition(HintMotion.CLOSE_MS, reduceMotion, "seal")
    Art(358f, 380f, width, desc) { k ->
        translate(0f, -70f * k) {
            drawPath(poly(k, 40f, 150f, 179f, 90f, 318f, 150f, 318f, 370f, 179f, 430f, 40f, 370f, close = true), ArtInk.Box)
            line(k, ArtInk.BoxLine, 3f, 40f, 150f, 179f, 210f, 318f, 150f); line(k, ArtInk.BoxLine, 3f, 179f, 210f, 179f, 430f)
            roundRect(k, ArtInk.Paper, 132f, 250f, 94f, 94f, 8f)
            for ((x, y) in listOf(142f to 260f, 188f to 260f, 142f to 306f)) {
                roundRect(k, Ink, x, y, 28f, 28f, 0f); roundRect(k, ArtInk.Paper, x + 6f, y + 6f, 16f, 16f, 0f)
            }
            roundRect(k, Ink, 190f, 308f, 10f, 10f, 0f); roundRect(k, Ink, 206f, 320f, 10f, 10f, 0f)
            val f = if (reduceMotion) HintMotion.Still.close else HintMotion.close(t.value)
            around(k, 179f, 297f, f.scale) {
                val c = ArtInk.Orange.copy(alpha = f.alpha.coerceIn(0f, 1f))
                line(k, c, 5f, 118f, 262f, 118f, 236f, 144f, 236f); line(k, c, 5f, 214f, 236f, 240f, 236f, 240f, 262f)
                line(k, c, 5f, 240f, 332f, 240f, 358f, 214f, 358f); line(k, c, 5f, 144f, 358f, 118f, 358f, 118f, 332f)
            }
        }
    }
}
