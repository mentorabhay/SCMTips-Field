package com.scmtips.field.app.ui.homes

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// Local copy of builder A's M5-U theme tokens (docs/design/M5_UI_CONTRACT.md §5: ui/theme/Color.kt and
// ui/Components.kt on feat/m5-ui-shell), same names and values. INTEGRATOR: delete this block and import
// com.scmtips.field.app.ui.theme.* / com.scmtips.field.app.ui.{CardShape, ButtonShape, MinTouch, GradientButton}.
val Ink = Color(0xFF15171C)
val Muted = Color(0xFF5B6170)
val Ground = Color(0xFFF5F6F8)
val Surface = Color(0xFFFFFFFF)
val Border = Color(0xFFE4E7EC)
val Night = Color(0xFF17181C)
val NightTask = Color(0xFF0F1013)
val NightRaised = Color(0xFF23252B)
val NightButton = Color(0xFF2A2C33)
val NightMuted = Color(0xFFC9CCD3)
val Good = Color(0xFF157A3C)
val Warning = Color(0xFFA15C07)
val Danger = Color(0xFFB3261E)
val AccentInk = Color(0xFF5B21B6)
val AccentTint = Color(0xFFEDE9FE)
val BrandStart = Color(0xFF6D28D9)
val BrandEnd = Color(0xFFC2410C)
val BrandGradient = Brush.horizontalGradient(listOf(BrandStart, BrandEnd))
val BrandGradientDiagonal = Brush.linearGradient(listOf(BrandStart, BrandEnd))
val SwitchOff = Color(0xFFC9CDD5)
val RowDivider = Color(0xFFEEF0F3)
val SuccessBg = Color(0xFFE6F4EA)
val WarnBg = Color(0xFFFFF1E6)
val WarnInk = Color(0xFF7C2D12)
val DangerBg = Color(0xFFFDECEA)
val CardShape = RoundedCornerShape(16.dp)
val ButtonShape = RoundedCornerShape(14.dp)
val MinTouch = 48.dp

// Tokens of these screens only (the prototype's), not in A's theme.
/** Sandbox tag ink on [WarnBg] (#9A3412 on #FFF1E6, contrast 6.9:1). */
val SandboxInk = Color(0xFF9A3412)
/** Selected choice background (Site.dc.html). */
val AccentSelected = Color(0xFFF3F0FF)
/** Count badge when zero (WarehouseHome.dc.html). */
val QuietTint = Color(0xFFEEF0F3)
/** The input border of the prototype's fields. */
val FieldLine = Color(0xFFC9CDD5)

/** The drawings' colours (prototype SVGs); never used for text on light ground. */
object ArtInk {
    val Box = Color(0xFF3A3D46)
    val BoxLine = Color(0xFF2A2D35)
    val Live = Color(0xFF4ADE80)
    val Orange = Color(0xFFFB923C)
    val Violet = Color(0xFFA78BFA)
    val Lilac = Color(0xFFC4B5FD)
    val Paper = Color(0xFFF5F6F8)
    val Dot = Color(0xFF4A4D57)
}

/**
 * The one main action of a screen on the brand gradient (A's GradientButton, same parameters). Disabled: the
 * gradient at 45 %, still white text (the reason is said next to it).
 */
@Composable
fun GradientButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, height: Dp = 56.dp) {
    Button(
        onClick = onClick, enabled = enabled, shape = ButtonShape,
        modifier = modifier.fillMaxWidth().height(height).background(BrandGradient, ButtonShape, alpha = if (enabled) 1f else 0.45f),
        colors = ButtonDefaults.buttonColors(containerColor = Color.Transparent, contentColor = Color.White,
            disabledContainerColor = Color.Transparent, disabledContentColor = Color.White.copy(alpha = 0.85f)),
    ) { Text(text, fontSize = 17.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center) }
}

/** A second action: outlined, on light ground ([dark] = on Night, the prototype's #23252B button). */
@Composable
fun QuietButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, dark: Boolean = false, height: Dp = 52.dp) {
    OutlinedButton(
        onClick = onClick, enabled = enabled, shape = ButtonShape,
        border = BorderStroke(1.dp, if (dark) ArtInk.Box else FieldLine),
        modifier = modifier.fillMaxWidth().height(height),
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = if (dark) NightRaised else Surface, contentColor = if (dark) Color.White else Ink,
            disabledContainerColor = if (dark) NightRaised else Surface, disabledContentColor = (if (dark) Color.White else Ink).copy(alpha = 0.45f)),
    ) { Text(text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center) }
}

/** A text link at least 48 dp tall (Forgot password?, Create an account, Skip). */
@Composable
fun LinkButton(text: String, onClick: () -> Unit, color: Color = AccentInk, enabled: Boolean = true, modifier: Modifier = Modifier, size: Int = 15) {
    TextButton(onClick = onClick, enabled = enabled, modifier = modifier.heightIn(min = MinTouch), contentPadding = PaddingValues(horizontal = 8.dp)) {
        Text(text, color = if (enabled) color else color.copy(alpha = 0.5f), fontSize = size.sp, fontWeight = FontWeight.SemiBold)
    }
}

/** White 16 dp card with the 1 dp border; [onClick] makes the whole card one ≥48 dp button (merged semantics). */
@Composable
fun HomeCard(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    enabled: Boolean = true,
    dashed: Boolean = false,
    bg: Color = Surface,
    line: Color = Border,
    shape: RoundedCornerShape = CardShape,
    padding: PaddingValues = PaddingValues(16.dp),
    onClickLabel: String? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val edge = if (dashed) Modifier.drawBehind {
        val r = 14.dp.toPx()
        drawRoundRect(FieldLine, cornerRadius = CornerRadius(r, r),
            style = Stroke(width = 1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx()))))
    } else Modifier.border(1.dp, line, shape)
    Column(
        modifier.fillMaxWidth().heightIn(min = MinTouch).background(bg, shape).then(edge)
            .let { m -> if (onClick != null) m.clickable(enabled = enabled, role = Role.Button, onClickLabel = onClickLabel, onClick = onClick) else m }
            .padding(padding),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        content = content,
    )
}

/** The small all-caps label above a card (NEXT UP, After check-in). */
@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier, color: Color = Muted) {
    Text(text, modifier = modifier, color = color, fontSize = 14.sp, fontWeight = FontWeight.Bold)
}

/** A rounded tag (Sandbox, DECISION, BOX CHECK). */
@Composable
fun Tag(text: String, ink: Color, bg: Color, modifier: Modifier = Modifier) {
    Text(text, modifier = modifier.background(bg, RoundedCornerShape(8.dp)).padding(horizontal = 8.dp, vertical = 3.dp),
        color = ink, fontSize = 12.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.5.sp)
}

/** A tile's round count (purple when there is work, grey at zero). */
@Composable
fun CountBadge(n: Int) {
    Box(
        Modifier.heightIn(min = 28.dp).background(if (n > 0) AccentTint else QuietTint, RoundedCornerShape(14.dp)).padding(horizontal = 9.dp, vertical = 4.dp),
        contentAlignment = Alignment.Center,
    ) { Text("$n", color = if (n > 0) AccentInk else Muted, fontSize = 14.sp, fontWeight = FontWeight.Bold) }
}

/**
 * A home's designed empty state: a small drawing, one sentence, one action. With [enabled] false (view only, or
 * nothing the person may do) the action is drawn disabled, never hidden behind a fake.
 */
@Composable
fun EmptyState(text: String, action: String?, onAction: () -> Unit, enabled: Boolean, art: @Composable () -> Unit) {
    HomeCard(padding = PaddingValues(horizontal = 20.dp, vertical = 24.dp)) {
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { art() }
        Text(text, color = Ink, fontSize = 16.sp, lineHeight = 23.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        if (action != null) QuietButton(action, onAction, enabled = enabled, modifier = Modifier.padding(top = 4.dp))
    }
}

/**
 * The loop position of a drawn hint in [0, 1): an infinite linear transition of [durationMs], or a constant 0 when
 * [reduceMotion] is on (the art then draws its [HintMotion.Still] frame and no transition runs at all). Read it in the
 * draw phase (inside a Canvas) so a frame only redraws, never recomposes.
 */
@Composable
fun loopPosition(durationMs: Int, reduceMotion: Boolean, label: String): State<Float> {
    if (reduceMotion) return remember { mutableFloatStateOf(0f) }
    val t = rememberInfiniteTransition(label = label)
    return t.animateFloat(0f, 1f, infiniteRepeatable(tween(durationMs, easing = LinearEasing), RepeatMode.Restart), label = label)
}
