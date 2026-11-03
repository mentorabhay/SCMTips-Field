package com.scmtips.field.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.jobs.JobAction
import com.scmtips.field.app.jobs.StepKind
import com.scmtips.field.app.jobs.StepView
import com.scmtips.field.app.jobs.Tone
import com.scmtips.field.app.ui.theme.Amber
import com.scmtips.field.app.ui.theme.AmberText
import com.scmtips.field.app.ui.theme.Background
import com.scmtips.field.app.ui.theme.CardBg
import com.scmtips.field.app.ui.theme.ClimbBg
import com.scmtips.field.app.ui.theme.ClimbCard
import com.scmtips.field.app.ui.theme.ClimbLine
import com.scmtips.field.app.ui.theme.ClimbMuted
import com.scmtips.field.app.ui.theme.ClimbTrack
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Line
import com.scmtips.field.app.ui.theme.LineStrong
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Primary
import com.scmtips.field.app.ui.theme.Success
import com.scmtips.field.app.ui.theme.SuccessBg
import com.scmtips.field.app.ui.theme.WarnBg
import com.scmtips.field.app.ui.theme.WarnInk
import com.scmtips.field.app.ui.theme.WarnText

private class JobColors(val bg: Color, val ink: Color, val muted: Color, val card: Color, val line: Color, val track: Color,
                        val accent: Color, val primaryBg: Color, val primaryFg: Color)

private val Light = JobColors(Background, Ink, Muted, CardBg, Line, Line, Primary, Primary, Color.White)
private val Climb = JobColors(ClimbBg, Color.White, ClimbMuted, ClimbCard, ClimbLine, ClimbTrack, Amber, Amber, ClimbBg)

/**
 * The classic job screen (M2/M5 layout, kept behind Settings › Diagnostics › "Classic layout", A-07; design:
 * Main.dc.html job runner). It draws whatever step the [StepView] describes:
 * header with step n of m, progress, banner, title, the "where" card, body, details, then the step's own
 * control (scan area, count, checklist, check-in, climb-safe, done), then the primary/secondary buttons.
 */
@Composable
internal fun ClassicJobScreen(v: StepView, audioOnly: Boolean, a: Actions, look: com.scmtips.field.app.look.LookView? = null) {
    val c = if (v.dark) Climb else Light
    BackHandler { if (v.canGoBack) a.job(JobAction.Back) } // climb-safe: back does nothing
    val view = LocalView.current
    DisposableEffect(v.dark) {
        view.keepScreenOn = v.dark
        onDispose { view.keepScreenOn = false }
    }
    val checkin = v.kind == StepKind.CHECKIN
    LaunchedEffect(checkin) { if (checkin) a.startLocation() else a.stopLocation() }

    Column(Modifier.fillMaxSize().background(c.bg)) {
        Row(Modifier.padding(start = 12.dp, end = 12.dp, top = 18.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            IconButton(onClick = { a.job(JobAction.Back) }, enabled = v.canGoBack && !v.busy,
                modifier = Modifier.size(48.dp).semantics { contentDescription = "Back" }) { BackArrow(if (v.canGoBack) c.ink else c.muted) }
            Column(Modifier.weight(1f)) {
                Text(v.jobTitle, fontWeight = FontWeight.Bold, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("Step ${v.stepNo} of ${v.stepCount} · ${v.jobKind}", fontSize = 13.sp, color = c.muted)
            }
        }
        Box(Modifier.padding(horizontal = 20.dp).fillMaxWidth().height(6.dp).background(c.track, Corner)) {
            Box(Modifier.fillMaxWidth(v.stepNo.toFloat() / v.stepCount.coerceAtLeast(1)).height(6.dp).background(c.accent, Corner))
        }
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(start = 20.dp, end = 20.dp, top = 16.dp, bottom = 12.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            v.banner?.let { Text(it, color = WarnInk, fontSize = 15.sp, modifier = Modifier.fillMaxWidth().background(WarnBg, Corner).padding(horizontal = 14.dp, vertical = 10.dp)) }
            // M5: the look (photo with outlines, counts, proposal, claim) above the step it pre-fills.
            if (look != null && !audioOnly) LookPanel(look, a)
            if (audioOnly) AudioOnly(v, c, a, look) else StepBody(v, c, a)
            v.message?.let { Box(Modifier.semantics { liveRegion = LiveRegionMode.Polite }) { Notice(it, v.messageTone) } }
        }
        Column(Modifier.padding(start = 20.dp, end = 20.dp, bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (v.canLook) LookButton(look, a)
            v.primary?.let { PrimaryButton(it, { a.job(JobAction.Primary) }, enabled = v.primaryEnabled && !v.busy, bg = c.primaryBg, fg = c.primaryFg) }
            v.secondary?.let { SecondaryButton(it, { a.job(JobAction.Secondary) }, ink = c.ink, line = c.line, enabled = !v.busy) }
            HoldToTalk(c, a)
        }
    }
}

@Composable
private fun StepBody(v: StepView, c: JobColors, a: Actions) {
    Text(v.title, fontSize = 27.sp, lineHeight = 32.sp, fontWeight = FontWeight.Bold, color = c.ink)
    v.where?.let { where ->
        CardBox(bg = c.card, line = c.line) {
            v.whereLabel?.let { Text(it, fontSize = 13.sp, color = c.muted) }
            Text(where, fontFamily = FontFamily.Monospace, fontSize = 30.sp, fontWeight = FontWeight.Medium, color = c.ink)
            v.hint?.let { Text(it, fontSize = 15.sp, color = c.muted) }
        }
    }
    if (v.where == null) v.hint?.let { Text(it, fontSize = 15.sp, color = c.muted) }
    v.body?.let { Text(it, color = c.muted) }
    if (v.detail.isNotEmpty()) {
        CardBox(bg = c.card, line = c.line, padding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 4.dp)) {
            v.detail.forEachIndexed { i, d ->
                Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(d.k, color = c.muted, modifier = Modifier.weight(1f))
                    Text(d.v, fontWeight = FontWeight.Bold, color = c.ink, textAlign = TextAlign.End, modifier = Modifier.weight(1f))
                }
                if (i < v.detail.lastIndex) Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
            }
        }
    }
    when (v.kind) {
        StepKind.SCAN -> {
            ScanArea(v.scanHowTo ?: "Scan the barcode", 190.dp, a.scan)
            ManualCode(a)
        }
        StepKind.COUNT -> CountControl(v, a)
        StepKind.CHECK -> v.checks.forEachIndexed { i, item -> CheckRow(item.label, item.ticked) { a.job(JobAction.ToggleCheck(i)) } }
        StepKind.CHECKIN -> OutlinedTextField(
            value = v.permit.orEmpty(), onValueChange = { a.job(JobAction.Permit(it)) }, singleLine = true,
            label = { Text("Work permit number") },
            modifier = Modifier.fillMaxWidth().onFocusChanged { a.manualEntryOpen(it.isFocused) }
                .semantics { contentDescription = "Work permit number" },
        )
        StepKind.CLIMB -> Column(
            Modifier.fillMaxWidth().border(2.dp, Amber, Corner).padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("Climb-safe mode is on", fontSize = 15.sp, color = AmberText, fontWeight = FontWeight.Bold)
            Text("The phone stays locked. Your glasses only speak when you are clipped in at a platform.", fontSize = 17.sp, color = Color.White)
            Text("Say “harness clipped” and tap the button: both are needed. Your supervisor sees your safety check-ins.", fontSize = 15.sp, color = ClimbMuted)
        }
        StepKind.CONFIRM -> if (v.listening) Text("Listening for “yes” or “cancel”…", color = Primary, fontWeight = FontWeight.Bold)
        StepKind.WAITING -> Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(Modifier.size(48.dp), color = Primary)
        }
        StepKind.DONE -> Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { DoneBadge() }
        else -> Unit
    }
}

@Composable
private fun CountControl(v: StepView, a: Actions) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        v.expected?.let { exp ->
            PrimaryButton("All $exp are here", { a.job(JobAction.AllHere) }, enabled = !v.busy)
            Text("or enter a different number", fontSize = 14.sp, color = Muted, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            StepperButton("−", "One less") { a.job(JobAction.SetQty(v.qty - 1)) }
            BasicTextField(
                value = v.qty.toString(),
                onValueChange = { t -> a.job(JobAction.SetQty(t.filter(Char::isDigit).take(4).toIntOrNull() ?: 0)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                textStyle = TextStyle(fontSize = 34.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, color = Ink),
                modifier = Modifier.weight(1f).height(64.dp).background(CardBg, Corner).border(2.dp, Primary, Corner)
                    .onFocusChanged { a.manualEntryOpen(it.isFocused) }
                    .padding(top = 8.dp).semantics { contentDescription = "Your count" },
            )
            StepperButton("+", "One more") { a.job(JobAction.SetQty(v.qty + 1)) }
        }
        v.flagged?.let { f ->
            Text("+ $f flagged for quality inspection (say “flag” and a number to change)", fontSize = 15.sp, color = WarnText,
                textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        }
        v.qtyNote?.let {
            Text(it, fontSize = 15.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth(),
                color = when (v.qtyTone) { Tone.GOOD -> Success; Tone.WARN, Tone.BAD -> WarnText; Tone.NEUTRAL -> Muted })
        }
    }
}

@Composable
private fun StepperButton(sign: String, label: String, onClick: () -> Unit) {
    Box(
        Modifier.size(64.dp).background(CardBg, Corner).border(1.dp, LineStrong, Corner)
            .clickable(role = Role.Button, onClick = onClick).semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) { Text(sign, fontSize = 30.sp, fontWeight = FontWeight.Bold, color = Ink) }
}

@Composable
private fun CheckRow(label: String, on: Boolean, onToggle: () -> Unit) {
    val line = if (on) Success else LineStrong
    Row(
        Modifier.fillMaxWidth().heightIn(min = 60.dp).background(if (on) SuccessBg else CardBg, Corner).border(2.dp, line, Corner)
            .clickable(role = Role.Checkbox, onClick = onToggle).semantics { selected = on }.padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(26.dp).background(if (on) Success else CardBg, Corner).border(2.dp, line, Corner), contentAlignment = Alignment.Center) {
            if (on) CheckGlyph(side = 20.dp)
        }
        Text(label, fontWeight = FontWeight.Bold, color = Ink)
    }
}

/** Audio-only mode: prompts are spoken, never shown; the buttons stay as a fallback. */
@Composable
private fun AudioOnly(v: StepView, c: JobColors, a: Actions, look: com.scmtips.field.app.look.LookView? = null) {
    CardBox(bg = c.card, line = c.line) {
        Text("Audio-only mode", fontWeight = FontWeight.Bold, color = c.ink, fontSize = 20.sp)
        Text("Listen to your glasses. Say “repeat” to hear the step again.", color = c.muted)
    }
    if (v.kind == StepKind.SCAN) ScanArea(v.scanHowTo ?: "Scan the barcode", 160.dp, a.scan)
    SecondaryButton("Repeat", { a.job(JobAction.Heard("repeat", 1f)) }, ink = c.ink, line = c.line)
    if (look?.state == com.scmtips.field.app.look.LookState.CONSENT) SecondaryButton("Agree for this site", a.agreePhotos, ink = c.ink, line = c.line)
}

/** Phone microphone, hold while speaking (fallback when the glasses do not listen). */
@Composable
private fun HoldToTalk(c: JobColors, a: Actions) {
    Box(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).border(1.dp, c.line, Corner)
            .pointerInput(Unit) { detectTapGestures(onPress = { a.talkStart(); tryAwaitRelease(); a.talkStop() }) }
            .semantics { role = Role.Button; contentDescription = "Hold to talk" },
        contentAlignment = Alignment.Center,
    ) { Text("Hold to talk", color = c.ink, fontWeight = FontWeight.Bold) }
}
