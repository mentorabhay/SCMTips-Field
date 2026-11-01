package com.scmtips.field.app.ui.firstrun

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.unit.dp
import com.scmtips.field.app.shell.PermissionStep
import com.scmtips.field.app.ui.theme.AccentInk
import com.scmtips.field.app.ui.theme.AccentTint
import com.scmtips.field.app.ui.homes.Art
import com.scmtips.field.app.ui.homes.ArtInk
import com.scmtips.field.app.ui.theme.BrandEnd
import com.scmtips.field.app.ui.theme.BrandGradientDiagonal
import com.scmtips.field.app.ui.theme.BrandStart
import com.scmtips.field.app.ui.homes.Glyph
import com.scmtips.field.app.ui.homes.GlyphKind
import com.scmtips.field.app.ui.homes.HintMotion
import com.scmtips.field.app.ui.homes.around
import com.scmtips.field.app.ui.homes.dot
import com.scmtips.field.app.ui.homes.line
import com.scmtips.field.app.ui.homes.loopPosition
import com.scmtips.field.app.ui.homes.poly
import com.scmtips.field.app.ui.homes.roundRect

// The first-run drawings (Main, Forgot, Permissions, Glasses .dc.html), each with its looping hint; with
// reduceMotion every one draws its HintMotion.Still frame and runs no transition.

/** The SCMTips Field mark: the layers glyph on the diagonal brand gradient (36 dp, 10 dp corners). */
@Composable
fun BrandMark() {
    Box(Modifier.size(36.dp).background(BrandGradientDiagonal, RoundedCornerShape(10.dp)), contentAlignment = Alignment.Center) {
        Glyph(GlyphKind.LAYERS, Color.White, size = 20.dp)
    }
}

/** The drawing of one welcome card (260 × 200 units). */
@Composable
fun WelcomeArt(card: WelcomeCard, reduceMotion: Boolean) {
    when (card) {
        WelcomeCard.LOOK -> LookArt(reduceMotion, card.art)
        WelcomeCard.HEAR -> HearArt(reduceMotion, card.art)
        WelcomeCard.CONFIRM -> ConfirmArt(reduceMotion, card.art)
    }
}

@Composable
private fun LookArt(reduceMotion: Boolean, desc: String) {
    val pop = loopPosition(HintMotion.POP_MS, reduceMotion, "pop")
    val pulse = loopPosition(HintMotion.PULSE_MS, reduceMotion, "pulse")
    Art(260f, 200f, 260.dp, desc) { k ->
        listOf(30f, 102f, 174f).forEach { x -> roundRect(k, ArtInk.Box, x, 120f, 56f, 50f, 6f) }
        listOf(Triple(26f, 0, ArtInk.Live), Triple(98f, 300, ArtInk.Live), Triple(170f, 600, ArtInk.Orange)).forEach { (x, delay, c) ->
            val f = if (reduceMotion) HintMotion.Still.pop else HintMotion.pop(HintMotion.shifted(pop.value, delay, HintMotion.POP_MS))
            around(k, x + 32f, 145f, f.scale) { roundRect(k, c.copy(alpha = f.alpha.coerceIn(0f, 1f)), x, 116f, 64f, 58f, 8f, stroke = 2.5f) }
        }
        roundRect(k, Color.White, 70f, 52f, 54f, 28f, 14f, stroke = 3f)
        roundRect(k, Color.White, 136f, 52f, 54f, 28f, 14f, stroke = 3f)
        line(k, Color.White, 3f, 124f, 64f, 136f, 64f)
        line(k, Color.White, 3f, 70f, 60f, 48f, 52f); line(k, Color.White, 3f, 190f, 60f, 212f, 52f)
        dot(k, ArtInk.Violet, 212f, 52f, 5f)
        val p = if (reduceMotion) HintMotion.Still.pulse else HintMotion.pulse(pulse.value)
        dot(k, ArtInk.Violet, 212f, 52f, 8f * p.scale, alpha = p.alpha)
    }
}

@Composable
private fun HearArt(reduceMotion: Boolean, desc: String) {
    val wave = loopPosition(HintMotion.WAVE_MS, reduceMotion, "wave")
    Art(260f, 180f, 260.dp, desc) { k ->
        // x, top, height, delay (ms); every bar is centred on y = 100 as in the prototype
        listOf(listOf(60f, 60f, 80f, 0f), listOf(88f, 40f, 120f, 150f), listOf(116f, 70f, 60f, 300f),
            listOf(144f, 30f, 140f, 450f), listOf(172f, 55f, 90f, 600f)).forEachIndexed { i, (x, top, h, d) ->
            val f = if (reduceMotion) HintMotion.Still.WAVE else HintMotion.wave(HintMotion.shifted(wave.value, d.toInt(), HintMotion.WAVE_MS))
            val hh = h * f
            roundRect(k, if (i == 2) ArtInk.Orange else ArtInk.Violet, x, top + (h - hh) / 2f, 14f, hh, 7f)
        }
    }
}

@Composable
private fun ConfirmArt(reduceMotion: Boolean, desc: String) {
    val ring = loopPosition(HintMotion.RING_MS, reduceMotion, "ring")
    Art(260f, 180f, 260.dp, desc) { k ->
        val r = 32f
        drawCircle(ArtInk.Box, r * k, Offset(130f * k, 96f * k), style = Stroke(6f * k))
        val share = if (reduceMotion) HintMotion.Still.RING else HintMotion.ring(ring.value)
        drawArc(ArtInk.Orange, -90f, 360f * share, false, Offset((130f - r) * k, (96f - r) * k), Size(2 * r * k, 2 * r * k),
            style = Stroke(6f * k, cap = StrokeCap.Round))
        line(k, Color.White, 5f, 116f, 96f, 126f, 106f, 146f, 84f)
    }
}

/** Forgot.dc.html: an envelope with a paper plane flying off (140 × 96 units). */
@Composable
fun EnvelopeArt(reduceMotion: Boolean) {
    val t = loopPosition(HintMotion.FLY_MS, reduceMotion, "fly")
    Art(140f, 96f, 140.dp, desc = "An envelope with a paper plane flying away") { k ->
        roundRect(k, AccentTint, 20f, 36f, 64f, 44f, 6f)
        roundRect(k, BrandStart, 20f, 36f, 64f, 44f, 6f, stroke = 2f)
        line(k, BrandStart, 2f, 20f, 40f, 52f, 62f, 84f, 40f)
        val f = if (reduceMotion) HintMotion.Still.fly else HintMotion.fly(t.value)
        translate(f.dx * k * 0.35f, f.dy * k * 0.35f) {
            drawPath(poly(k, 96f, 46f, 122f, 36f, 112f, 62f, 107f, 51f, close = true), BrandEnd.copy(alpha = f.alpha.coerceIn(0f, 1f)))
        }
    }
}

/** Permissions.dc.html: the step's glyph breathing on a 140 dp lilac tile. */
@Composable
fun PermissionArt(step: PermissionStep, reduceMotion: Boolean) {
    val t = loopPosition(HintMotion.BREATHE_MS, reduceMotion, "breathe")
    val s: State<Float> = remember(reduceMotion) {
        derivedStateOf { if (reduceMotion) HintMotion.Still.BREATHE else HintMotion.breathe(t.value) }
    }
    val kind = when (step) {
        PermissionStep.CAMERA -> GlyphKind.CAMERA
        PermissionStep.MICROPHONE -> GlyphKind.MIC
        PermissionStep.NEARBY -> GlyphKind.BLUETOOTH
        PermissionStep.NOTIFICATIONS -> GlyphKind.BELL
    }
    Box(Modifier.size(140.dp).background(AccentTint, RoundedCornerShape(40.dp)), contentAlignment = Alignment.Center) {
        Glyph(kind, AccentInk, size = 64.dp, stroke = 1.6f, scale = s)
    }
}

/** Glasses.dc.html: the glasses with the capture button glowing and a finger tapping (280 × 150 units). */
@Composable
fun GlassesArt(reduceMotion: Boolean) {
    val pulse = loopPosition(HintMotion.PULSE_MS, reduceMotion, "pulse")
    val tap = loopPosition(HintMotion.TAP_MS, reduceMotion, "tap")
    Art(280f, 150f, 280.dp, desc = "Ray-Ban Meta glasses with the capture button glowing") { k ->
        roundRect(k, Color.White, 40f, 60f, 92f, 52f, 24f, stroke = 4f)
        roundRect(k, Color.White, 148f, 60f, 92f, 52f, 24f, stroke = 4f)
        line(k, Color.White, 4f, 132f, 72f, 148f, 72f)
        line(k, Color.White, 4f, 40f, 66f, 14f, 52f); line(k, Color.White, 4f, 240f, 66f, 266f, 52f)
        dot(k, ArtInk.Orange, 236f, 56f, 6f)
        val p = if (reduceMotion) HintMotion.Still.pulse else HintMotion.pulse(pulse.value, peak = 1.9f, alpha = 0.6f)
        dot(k, ArtInk.Orange, 236f, 56f, 9f * p.scale, alpha = p.alpha)
        val dy = if (reduceMotion) HintMotion.Still.TAP else HintMotion.tap(tap.value)
        translate(0f, dy * k) {
            val c = Color(0xFFC9CCD3)
            line(k, c, 3f, 246f, 26f, 246f, 44f); line(k, c, 3f, 240f, 38f, 246f, 44f, 252f, 38f)
        }
    }
}
