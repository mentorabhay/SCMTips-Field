package com.scmtips.field.app.ui.kit

import android.content.Context
import android.provider.Settings
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.ui.theme.AccentInk
import com.scmtips.field.app.ui.theme.Border
import com.scmtips.field.app.ui.theme.BrandGradient
import com.scmtips.field.app.ui.ButtonShape
import com.scmtips.field.app.ui.CardShape
import com.scmtips.field.app.ui.theme.Ground
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.MinTouch
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.NightMuted
import com.scmtips.field.app.ui.theme.NightRaised
import com.scmtips.field.app.ui.theme.NightTask
import com.scmtips.field.app.ui.theme.Surface

/*
 * M5-U04 task chrome (prototype ReceiveLook … ScanVerdict). Builder A's tokens come from ui/theme
 * (docs/design/M5_UI_CONTRACT.md §5); only the task screens' own prototype colours are declared here.
 * Everything else here is the step header, the hint area, the voice chip, the one main action, the confirm ring and
 * the result rows. Behaviour stays with the callers: these composables only draw and call what they are given.
 */

// builder A's tokens (Ink … BrandGradient, CardShape, ButtonShape, MinTouch) are imported from ui/theme and ui/Components.kt
// since the M5-U06 integration; NightRaised, NightMuted, DangerBg and Divider too (same values).

// --- task-screen colours from the prototype (only here) ----------------------------------------------------------------
val NightCard = Color(0xFF1E2026)
val NightTrack = Color(0xFF3A3D46)
val NightLine = Color(0xFF2A2D35)
val NightInk = Color(0xFFE5E7EB)
val StepDone = Color(0xFFFB923C)
val LiveGreen = Color(0xFF4ADE80)
val Lavender = Color(0xFFA78BFA)
val LavenderInk = Color(0xFFC4B5FD)
val SoftGreen = Color(0xFF86EFAC)
val SoftAmber = Color(0xFFFCD34D)
val SoftOrange = Color(0xFFFDBA74)
val Alarm = Color(0xFFF87171)
val BorderStrong = Color(0xFFC9CDD5)
val Chevron = Color(0xFF9CA3AF)
val GoodBg = Color(0xFFE6F4EA)
val AccentBg = Color(0xFFF3F0FF)
val AccentSoft = Color(0xFFEDE9FE)
val WarningBg = Color(0xFFFEF3C7)
val HintScrim = Color(0xDB0F1013)

/** One step's palette: Night (#0F1013) or Ground. */
class TaskColors(val bg: Color, val ink: Color, val muted: Color, val card: Color, val line: Color, val track: Color, val raised: Color)

val NightColors = TaskColors(NightTask, Color.White, NightMuted, NightCard, NightLine, NightTrack, NightRaised)
val GroundColors = TaskColors(Ground, Ink, Muted, Surface, Border, Border, Surface)

fun colorsFor(b: Backdrop): TaskColors = if (b == Backdrop.NIGHT) NightColors else GroundColors

/** Settings › Accessibility › Remove animations (animator scale 0). Builder A's LocalReduceMotion replaces this. */
@Composable
fun rememberSystemReduceMotion(): Boolean {
    val ctx = LocalContext.current
    return remember(ctx) {
        runCatching { Settings.Global.getFloat(ctx.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }.getOrDefault(false)
    }
}

// --- the first-time rule, kept on the phone ------------------------------------------------------------------------------

private class PrefsHintStore(ctx: Context) : HintStore {
    private val prefs = ctx.getSharedPreferences("m5u_hints", Context.MODE_PRIVATE)
    override fun load(): Set<String> = prefs.getStringSet("shown", emptySet()).orEmpty().toSet()
    override fun save(keys: Set<String>) { prefs.edit().putStringSet("shown", keys).apply() }
}

private var hintMemory: HintMemory? = null

@Composable
fun rememberHintMemory(): HintMemory {
    val ctx = LocalContext.current.applicationContext
    return remember(ctx) { hintMemory ?: HintMemory(PrefsHintStore(ctx)).also { hintMemory = it } }
}

/** Whether the hint for [key] is up: true by itself the first time the step opens; "?" sets it again. */
@Composable
fun rememberHintVisible(key: String?): MutableState<Boolean> {
    val memory = rememberHintMemory()
    return remember(key) { mutableStateOf(memory.autoShow(key)) }
}

// --- step header ---------------------------------------------------------------------------------------------------------

enum class LeadIcon { CLOSE, BACK }

/**
 * The step header: close/back on the left, the job's title and "Step n of m · Name" in the middle, "?" on the right
 * (replays the hint; a spacer when the step has none), then the segment bar.
 */
@Composable
fun StepHeader(
    title: String,
    subtitle: String?,
    c: TaskColors,
    lead: LeadIcon,
    onLead: () -> Unit,
    leadEnabled: Boolean = true,
    leadLabel: String = if (lead == LeadIcon.CLOSE) "Close" else "Back",
    onHelp: (() -> Unit)? = null,
    segments: Int = 0,
    segment: Int = 0,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            RoundIcon(c, onLead, leadEnabled, leadLabel) { color ->
                if (lead == LeadIcon.CLOSE) CloseGlyph(color) else ChevronGlyph(color, left = true)
            }
            Column(Modifier.weight(1f).padding(horizontal = 8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text(title, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                subtitle?.let { Text(it, fontSize = 13.sp, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            }
            if (onHelp != null) {
                RoundIcon(c, onHelp, true, "Show me how") { color -> Text("?", color = color, fontSize = 18.sp, fontWeight = FontWeight.Bold) }
            } else Box(Modifier.size(44.dp))
        }
        if (segments > 0) SegmentBar(segments, segment, c)
    }
}

@Composable
fun SegmentBar(segments: Int, segment: Int, c: TaskColors) {
    Row(
        Modifier.fillMaxWidth().semantics { contentDescription = "Step $segment of $segments" },
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        repeat(segments) { i ->
            Box(Modifier.weight(1f).height(4.dp).background(if (i < segment) StepDone else c.track, RoundedCornerShape(2.dp)))
        }
    }
}

@Composable
private fun RoundIcon(c: TaskColors, onClick: () -> Unit, enabled: Boolean, label: String, content: @Composable (Color) -> Unit) {
    val ground = c.bg == Ground
    Box(
        Modifier.size(MinTouch).clip(CircleShape).background(c.raised)
            .then(if (ground) Modifier.border(1.dp, Border, CircleShape) else Modifier)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) { content(if (enabled) c.ink else c.muted.copy(alpha = 0.5f)) }
}

@Composable
fun CloseGlyph(color: Color) = Canvas(Modifier.size(20.dp)) {
    val s = Stroke(width = 2.2.dp.toPx(), cap = StrokeCap.Round)
    val p = Path().apply {
        moveTo(size.width * 0.25f, size.height * 0.25f); lineTo(size.width * 0.75f, size.height * 0.75f)
        moveTo(size.width * 0.75f, size.height * 0.25f); lineTo(size.width * 0.25f, size.height * 0.75f)
    }
    drawPath(p, color, style = s)
}

@Composable
fun ChevronGlyph(color: Color, left: Boolean, side: Dp = 20.dp) = Canvas(Modifier.size(side)) {
    val p = Path().apply {
        val a = if (left) 0.62f else 0.38f
        val b = if (left) 0.38f else 0.62f
        moveTo(size.width * a, size.height * 0.25f); lineTo(size.width * b, size.height * 0.5f); lineTo(size.width * a, size.height * 0.75f)
    }
    drawPath(p, color, style = Stroke(width = 2.2.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
}

// --- hint area -------------------------------------------------------------------------------------------------------------

/**
 * The hint: a 3-second looping drawn animation with the hint's words and "OK". Drawn on a dark scrim so it reads on
 * a camera view and on a light screen alike.
 */
@Composable
fun HintArea(hint: Hint, reduceMotion: Boolean, onHide: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().background(HintScrim, CardShape).padding(start = 12.dp, end = 4.dp, top = 10.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        HintAnimation(hint, reduceMotion, Modifier.size(width = 96.dp, height = 64.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(hint.title, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            Text(hint.text, color = NightInk, fontSize = 14.sp, lineHeight = 20.sp)
        }
        Box(
            Modifier.heightIn(min = MinTouch).widthIn(min = MinTouch).clickable(role = Role.Button, onClick = onHide)
                .semantics { contentDescription = "Hide hint" },
            contentAlignment = Alignment.Center,
        ) { Text("OK", color = NightMuted, fontWeight = FontWeight.SemiBold, fontSize = 14.sp) }
    }
}

// --- voice chip --------------------------------------------------------------------------------------------------------------

@Composable
fun VoiceChip(text: String, c: TaskColors) {
    val ground = c.bg == Ground
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
        Row(
            Modifier.background(if (ground) Surface else NightRaised, RoundedCornerShape(20.dp))
                .then(if (ground) Modifier.border(1.dp, Border, RoundedCornerShape(20.dp)) else Modifier)
                .padding(horizontal = 14.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            MicGlyph(if (ground) AccentInk else LavenderInk)
            Text(text, fontSize = 14.sp, color = if (ground) Ink else NightInk)
        }
    }
}

@Composable
fun MicGlyph(color: Color, side: Dp = 16.dp) = Canvas(Modifier.size(side)) {
    val u = size.width / 24f
    val s = Stroke(width = 2f * u, cap = StrokeCap.Round)
    drawRoundRect(color, topLeft = Offset(9 * u, 3 * u), size = Size(6 * u, 11 * u),
        cornerRadius = androidx.compose.ui.geometry.CornerRadius(3 * u), style = s)
    drawArc(color, 0f, 180f, false, topLeft = Offset(5 * u, 4 * u), size = Size(14 * u, 14 * u), style = s)
    drawLine(color, Offset(12 * u, 18 * u), Offset(12 * u, 21 * u), strokeWidth = 2f * u, cap = StrokeCap.Round)
}

// --- the one main action ---------------------------------------------------------------------------------------------------

/** The one main button of a screen (brand gradient). Builder A's GradientButton has the same parameters. */
@Composable
fun GradientButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, height: Dp = 58.dp) {
    Box(
        modifier.alpha(if (enabled) 1f else 0.45f).fillMaxWidth().height(height).clip(ButtonShape).background(BrandGradient)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Text(text, color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center, maxLines = 2) }
}

/** A secondary action as quiet text (48 dp tall). */
@Composable
fun QuietButton(text: String, onClick: () -> Unit, c: TaskColors, enabled: Boolean = true, ink: Color? = null, modifier: Modifier = Modifier) {
    Box(
        modifier.fillMaxWidth().heightIn(min = MinTouch).clip(ButtonShape).clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, color = (ink ?: if (c.bg == Ground) Ink else NightInk).copy(alpha = if (enabled) 1f else 0.45f),
            fontSize = 15.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
    }
}

/** An outlined button for the second of two side-by-side actions (Reject, Evidence). */
@Composable
fun OutlineAction(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, height: Dp = 56.dp) {
    Box(
        modifier.height(height).clip(ButtonShape).background(Surface).border(1.dp, BorderStrong, ButtonShape)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Text(text, color = Ink.copy(alpha = if (enabled) 1f else 0.45f), fontSize = 16.sp, fontWeight = FontWeight.SemiBold) }
}

/** The bottom of a task screen: ONE main button, then the quiet secondary actions. */
@Composable
fun MainActionBar(c: TaskColors, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp), content = content)
}

// --- confirm ring ------------------------------------------------------------------------------------------------------------

/** Draws the confirm ring: the track, then the remaining [progress] (1 full, 0 empty) clockwise from the top. */
fun DrawScope.drawConfirmRing(progress: Float, color: Color, track: Color, strokePx: Float) {
    val d = size.minDimension - strokePx
    val tl = Offset((size.width - d) / 2f, (size.height - d) / 2f)
    drawArc(track, 0f, 360f, false, topLeft = tl, size = Size(d, d), style = Stroke(width = strokePx))
    val sweep = 360f * progress.coerceIn(0f, 1f)
    if (sweep > 0f) drawArc(color, -90f, sweep, false, topLeft = tl, size = Size(d, d), style = Stroke(width = strokePx, cap = StrokeCap.Round))
}

/**
 * The real countdown of the confirm step (and of hint 3): [progress] of the 10 s window left, red for the last
 * 3 seconds; [center] draws the seconds or a tick.
 */
@Composable
fun ConfirmRing(progress: Float, urgent: Boolean, description: String, modifier: Modifier = Modifier, side: Dp = 200.dp,
                stroke: Dp = 12.dp, center: @Composable () -> Unit) {
    Box(modifier.size(side).semantics { contentDescription = description }, contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) { drawConfirmRing(progress, if (urgent) Alarm else StepDone, NightLine, stroke.toPx()) }
        center()
    }
}

@Composable
fun TickGlyph(color: Color, side: Dp, stroke: Dp = 7.dp, drawn: Float = 1f) = Canvas(Modifier.size(side)) {
    drawTick(color, stroke.toPx(), drawn)
}

/** A tick drawn up to [drawn] (0..1) of its length, so it can be animated. */
fun DrawScope.drawTick(color: Color, strokePx: Float, drawn: Float = 1f) {
    val a = Offset(size.width * 0.31f, size.height * 0.51f)
    val b = Offset(size.width * 0.44f, size.height * 0.64f)
    val e = Offset(size.width * 0.69f, size.height * 0.36f)
    val l1 = (b - a).getDistance()
    val l2 = (e - b).getDistance()
    val len = (l1 + l2) * drawn.coerceIn(0f, 1f)
    val p = Path().apply {
        moveTo(a.x, a.y)
        if (len <= l1) lineTo(a.x + (b.x - a.x) * len / l1, a.y + (b.y - a.y) * len / l1)
        else { lineTo(b.x, b.y); val r = (len - l1) / l2; lineTo(b.x + (e.x - b.x) * r, b.y + (e.y - b.y) * r) }
    }
    if (len > 0f) drawPath(p, color, style = Stroke(width = strokePx, cap = StrokeCap.Round, join = StrokeJoin.Round))
}

// --- result rows ----------------------------------------------------------------------------------------------------------------

/** One row of a result card (Evidence page, Make a claim): icon, title, line, chevron; dimmed when [onClick] is null. */
@Composable
fun ResultCard(title: String, sub: String?, icon: @Composable () -> Unit, onClick: (() -> Unit)?, enabled: Boolean = true) {
    val live = onClick != null && enabled
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).background(Surface, CardShape).border(1.dp, Border, CardShape).clip(CardShape)
            .then(if (onClick != null) Modifier.clickable(enabled = enabled, role = Role.Button, onClick = onClick) else Modifier)
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        icon()
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Ink.copy(alpha = if (live || onClick == null) 1f else 0.5f))
            sub?.let { Text(it, fontSize = 13.sp, color = Muted) }
        }
        if (onClick != null) ChevronGlyph(Chevron, left = false, side = 18.dp)
    }
}

@Composable
fun DocGlyph(color: Color = AccentInk) = Canvas(Modifier.size(22.dp)) {
    val u = size.width / 24f
    val s = Stroke(width = 2f * u, cap = StrokeCap.Round, join = StrokeJoin.Round)
    drawPath(Path().apply { moveTo(6 * u, 3 * u); lineTo(15 * u, 3 * u); lineTo(19 * u, 7 * u); lineTo(19 * u, 21 * u); lineTo(6 * u, 21 * u); close() }, color, style = s)
    drawLine(color, Offset(9 * u, 12 * u), Offset(16 * u, 12 * u), strokeWidth = 2f * u, cap = StrokeCap.Round)
    drawLine(color, Offset(9 * u, 16 * u), Offset(16 * u, 16 * u), strokeWidth = 2f * u, cap = StrokeCap.Round)
}

@Composable
fun FlagGlyph(color: Color = Color(0xFF9A3412)) = Canvas(Modifier.size(22.dp)) {
    val u = size.width / 24f
    drawPath(Path().apply { moveTo(5 * u, 21 * u); lineTo(5 * u, 4 * u); lineTo(16 * u, 4 * u); lineTo(14 * u, 8 * u); lineTo(16 * u, 12 * u); lineTo(5 * u, 12 * u) },
        color, style = Stroke(width = 2f * u, cap = StrokeCap.Round, join = StrokeJoin.Round))
}

/** The big result mark: a soft disc and a tick drawn in (once; still when reduce motion is on). */
@Composable
fun ResultMark(disc: Color, ink: Color, description: String, drawn: Float) {
    Box(Modifier.size(96.dp).background(disc, CircleShape).semantics { contentDescription = description }, contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(96.dp)) { drawTick(ink, 7.dp.toPx(), drawn) }
    }
}

/** A small "Say …" or note line under the main area, centred. */
@Composable
fun NoteLine(text: String, c: TaskColors) {
    Text(text, fontSize = 13.sp, color = c.muted, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
}

/** The done screen's "Next up" card (e.g. the put-away job made for this receipt); the integrator builds it from AppUi. */
data class NextUp(val title: String, val sub: String?, val onStart: () -> Unit)
