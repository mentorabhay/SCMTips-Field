package com.scmtips.field.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.jobs.JobAction
import com.scmtips.field.app.jobs.StepKind
import com.scmtips.field.app.jobs.StepView
import com.scmtips.field.app.jobs.Tone
import com.scmtips.field.app.look.ClaimText
import com.scmtips.field.app.look.Look
import com.scmtips.field.app.look.LookState
import com.scmtips.field.app.look.LookView
import com.scmtips.field.app.ui.kit.AccentBg
import com.scmtips.field.app.ui.theme.AccentInk
import com.scmtips.field.app.ui.kit.Backdrop
import com.scmtips.field.app.ui.theme.Border
import com.scmtips.field.app.ui.kit.BorderStrong
import com.scmtips.field.app.ui.kit.ClipInHint
import com.scmtips.field.app.ui.kit.ConfirmRing
import com.scmtips.field.app.ui.kit.ConfirmRingMath
import com.scmtips.field.app.ui.theme.Danger
import com.scmtips.field.app.ui.theme.DangerBg
import com.scmtips.field.app.ui.kit.DocGlyph
import com.scmtips.field.app.ui.kit.FlagGlyph
import com.scmtips.field.app.ui.theme.Good
import com.scmtips.field.app.ui.kit.GoodBg
import com.scmtips.field.app.ui.kit.GradientButton
import com.scmtips.field.app.ui.kit.GroundColors
import com.scmtips.field.app.ui.kit.Hint
import com.scmtips.field.app.ui.kit.HintArea
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.kit.LavenderInk
import com.scmtips.field.app.ui.kit.LeadIcon
import com.scmtips.field.app.ui.kit.LiveGreen
import com.scmtips.field.app.ui.kit.LookAnswerRules
import com.scmtips.field.app.ui.kit.LookHint
import com.scmtips.field.app.ui.kit.MainActionBar
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.kit.NextUp
import com.scmtips.field.app.ui.kit.NightCard
import com.scmtips.field.app.ui.kit.NightColors
import com.scmtips.field.app.ui.kit.NightInk
import com.scmtips.field.app.ui.theme.NightMuted
import com.scmtips.field.app.ui.theme.NightTask
import com.scmtips.field.app.ui.kit.NoteLine
import com.scmtips.field.app.ui.kit.OutlineAction
import com.scmtips.field.app.ui.kit.QuietButton
import com.scmtips.field.app.ui.kit.ResultCard
import com.scmtips.field.app.ui.kit.ResultMark
import com.scmtips.field.app.ui.kit.SoftAmber
import com.scmtips.field.app.ui.kit.SoftGreen
import com.scmtips.field.app.ui.kit.StepDone
import com.scmtips.field.app.ui.kit.StepHeader
import com.scmtips.field.app.ui.theme.Surface
import com.scmtips.field.app.ui.kit.TaskColors
import com.scmtips.field.app.ui.kit.TaskSteps
import com.scmtips.field.app.ui.kit.TickGlyph
import com.scmtips.field.app.ui.kit.VoiceChip
import com.scmtips.field.app.ui.theme.Warning
import com.scmtips.field.app.ui.kit.WarningBg
import com.scmtips.field.app.ui.kit.colorsFor
import com.scmtips.field.app.ui.kit.rememberHintVisible
import com.scmtips.field.app.ui.kit.rememberSystemReduceMotion
import kotlinx.coroutines.delay

/**
 * The job screen, M5-U task layout (A-07; prototype ReceiveLook, ReceiveAnswer, ReceivePost, ReceiveDone,
 * TowerHarness): full screen, the step header ("Receive grocery delivery · Step 1 of 3 · Look", segment bar,
 * back on the left, "?" on the right), the hint the first time a step opens, the step's content, ONE main button
 * and quiet secondary actions. It draws the same [StepView] as before and calls the same actions: every
 * callback, phrase, deadline and request is the runner's. [classic] draws the old layout ([ClassicJobScreen]).
 *
 * For the integrator: [reduceMotion] should be builder A's LocalReduceMotion.current; [onEvidence] (reopen the
 * look's evidence page) and [nextUp] (the next job for this receipt) need data and an action AppUi does not expose
 * yet; without them the done screen leaves those rows out.
 */
@Composable
fun JobScreen(
    v: StepView,
    audioOnly: Boolean,
    a: Actions,
    look: LookView? = null,
    classic: Boolean = false,
    reduceMotion: Boolean = rememberSystemReduceMotion(),
    onEvidence: (() -> Unit)? = null,
    nextUp: NextUp? = null,
) {
    if (classic) {
        ClassicJobScreen(v, audioOnly, a, look)
        return
    }
    BackHandler { if (v.canGoBack) a.job(JobAction.Back) } // climb-safe: back does nothing
    val view = LocalView.current
    DisposableEffect(v.dark) {
        view.keepScreenOn = v.dark
        onDispose { view.keepScreenOn = false }
    }
    val checkin = v.kind == StepKind.CHECKIN
    LaunchedEffect(checkin) { if (checkin) a.startLocation() else a.stopLocation() }

    val lv = look?.takeIf { !audioOnly }
    val active = lv != null && lv.state != LookState.IDLE
    val chrome = TaskSteps.of(v, lv?.look)
    val c = colorsFor(chrome.backdrop)
    var hintUp by rememberHintVisible(chrome.hintKey)
    // The look and the climb draw their hint as the stage itself; the others show the hint card on top.
    val lookStep = !audioOnly && chrome.hint == Hint.LOOK
    val climbStage = !audioOnly && chrome.hint == Hint.CLIP_IN

    Column(Modifier.fillMaxSize().background(c.bg)) {
        if (v.kind != StepKind.DONE) {
            Column(Modifier.fillMaxWidth().background(NightTask).padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 12.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                StepHeader(
                    title = chrome.title, subtitle = chrome.subtitle, c = NightColors,
                    lead = if (v.stepNo <= 1) LeadIcon.CLOSE else LeadIcon.BACK,
                    onLead = { a.job(JobAction.Back) }, leadEnabled = v.canGoBack && !v.busy,
                    leadLabel = if (!v.canGoBack) "Back is locked on this step" else if (v.stepNo <= 1) "Close" else "Back",
                    onHelp = chrome.hint?.let { { hintUp = true } },
                    segments = chrome.segments, segment = chrome.segment,
                )
                // The check step keeps the look's photo in the dark band (prototype ReceiveAnswer).
                val photo = lv?.photo
                if (chrome.backdrop == Backdrop.GROUND && v.kind == StepKind.COUNT && photo != null) {
                    Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(NightCard).padding(6.dp)) {
                        OutlinedPhoto(photo, lv?.look, maxHeight = 160.dp)
                    }
                }
            }
        }
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            val hint = chrome.hint
            if (hintUp && hint != null && !lookStep && !climbStage) HintArea(hint, reduceMotion, { hintUp = false })
            v.banner?.let { Banner(it) }
            when {
                audioOnly -> TaskAudioOnly(v, c, a, look)
                lookStep -> LookStepBody(v, c, a, lv, hintUp, reduceMotion) { hintUp = false }
                else -> TaskStepBody(v, c, a, lv, climbStage && hintUp, reduceMotion, onEvidence, nextUp)
            }
            if (active && !lookStep && v.kind != StepKind.COUNT && v.kind != StepKind.DONE) LookStatus(lv!!, c, a)
            v.message?.let { Box(Modifier.semantics { liveRegion = LiveRegionMode.Polite }) { Notice(it, v.messageTone) } }
            chrome.voice?.let { VoiceChip(it, c) }
        }
        MainActionBar(c) {
            if (lookStep) {
                val busy = lv?.busy == true
                GradientButton(
                    if (busy) lv?.state?.text ?: "Looking…" else if (lv?.look != null) "Look again" else "Look now",
                    a.look, enabled = !busy,
                )
                v.primary?.let { QuietButton(if (v.kind == StepKind.INFO) "Scan the boxes instead" else it, { a.job(JobAction.Primary) }, c,
                    enabled = v.primaryEnabled && !v.busy) }
            } else {
                v.primary?.let { GradientButton(it, { a.job(JobAction.Primary) }, enabled = v.primaryEnabled && !v.busy) }
                if (v.canLook) QuietButton(if (lv?.busy == true) lv.state.text else if (lv?.look != null) "Look again" else "Look · count with the camera",
                    a.look, c, enabled = lv?.busy != true)
            }
            v.secondary?.let { QuietButton(it, { a.job(JobAction.Secondary) }, c, enabled = !v.busy) }
            if (lv?.look != null && v.kind != StepKind.DONE) ClaimQuiet(lv, c, a)
            TaskHoldToTalk(c, a)
        }
    }
}

// --- the look step (prototype ReceiveLook) ---------------------------------------------------------------------------

@Composable
private fun LookStepBody(v: StepView, c: TaskColors, a: Actions, lv: LookView?, hintUp: Boolean, reduceMotion: Boolean, hide: () -> Unit) {
    Box(Modifier.fillMaxWidth().heightIn(min = 300.dp).clip(RoundedCornerShape(24.dp)).background(NightCard)) {
        val photo = lv?.photo
        if (photo != null) Box(Modifier.padding(8.dp)) { OutlinedPhoto(photo, lv?.look, maxHeight = 380.dp) }
        else LookHint(reduceMotion = true, modifier = Modifier.fillMaxWidth().height(300.dp).padding(24.dp)) // the camera view, still
        if (hintUp) HintArea(Hint.LOOK, reduceMotion, hide, Modifier.align(Alignment.TopCenter).padding(12.dp))
    }
    if (lv != null && lv.state != LookState.IDLE) LookStatus(lv, c, a)
    Text(v.title, fontSize = 20.sp, lineHeight = 26.sp, fontWeight = FontWeight.Bold, color = c.ink)
    v.body?.let { Text(it, fontSize = 15.sp, color = c.muted) }
    DetailRows(v, c)
    if (v.kind == StepKind.SCAN) {
        ScanArea(v.scanHowTo ?: "Scan the barcode", 150.dp, a.scan)
        ManualCode(a, ink = LavenderInk, onDark = true)
    }
}

/** Chips, progress, the consent button and the drafted claim of the current look (what LookPanel showed). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LookStatus(l: LookView, c: TaskColors, a: Actions) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Chip("SAMPLE", WarningBg, Warning)
            l.camera?.let { Chip(it.label, AccentBg, AccentInk) }
            l.look?.let { Chip(if (it.rulesOnly) "No model answered · count aloud" else "Read by ${it.models.joinToString { m -> m.model }.ifEmpty { "the server" }}",
                Surface, Ink, line = Border) }
        }
        if (l.busy) Busy(l.state.text, c)
        l.message?.let { Text(it, color = if (l.state == LookState.FAILED) Danger.takeIf { c === GroundColors } ?: Color(0xFFFCA5A5) else c.muted, fontSize = 15.sp) }
        if (l.state == LookState.CONSENT) OutlineAction("Agree for this site", a.agreePhotos, Modifier.fillMaxWidth())
        l.claim?.let { cl ->
            Column(Modifier.fillMaxWidth().background(WarningBg, CardShape).padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("SAMPLE claim · ${cl.status}", fontWeight = FontWeight.Bold, color = Warning)
                Text(cl.text.ifBlank { ClaimText.lines(cl) }, color = Ink)
                Text("A supervisor approves it by voice before anything is sent (simulated).", fontSize = 13.sp, color = Muted)
            }
        }
    }
}

@Composable
private fun ClaimQuiet(l: LookView, c: TaskColors, a: Actions) {
    QuietButton(if (l.claim != null) "Claim drafted" else if (l.claimBusy) "Making claim…" else "Make a claim", a.makeClaim, c,
        enabled = l.claim == null && !l.claimBusy && !l.labelsPending)
}

/** The two answers (prototype ReceiveAnswer): the first at once, "Reading the labels…", then the second. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LookAnswers(l: LookView, c: TaskColors) {
    val look = l.look ?: return
    val first = remember(look.lookId) { mutableStateOf<String?>(null) }
    LaunchedEffect(look.lookId, l.labelsPending) {
        if (l.labelsPending && first.value == null) first.value = look.say.takeIf { it.isNotBlank() }
    }
    val ans = LookAnswerRules.of(look, l.labelsPending, first.value)
    ans.first?.let { AnswerCard(if (ans.second != null || ans.reading) "FIRST ANSWER" else "ANSWER", it) }
    if (ans.reading) {
        Row(Modifier.fillMaxWidth().background(Surface, CardShape).border(1.dp, BorderStrong, CardShape).padding(14.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            CircularProgressIndicator(Modifier.size(18.dp), color = AccentInk, strokeWidth = 2.dp)
            Text("Reading the labels…", color = Muted, fontSize = 15.sp)
        }
    }
    ans.second?.let { AnswerCard("SECOND ANSWER", it) }
    LookChips(look)
    look.proposal?.reasons?.forEach { Text("· $it", color = c.muted, fontSize = 14.sp) }
}

@Composable
private fun AnswerCard(label: String, text: String) {
    Row(Modifier.fillMaxWidth().background(Surface, CardShape).border(1.dp, Border, CardShape).padding(horizontal = 14.dp, vertical = 12.dp)
        .semantics { liveRegion = LiveRegionMode.Polite }, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("“", color = AccentInk, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Column {
            Text(label, fontSize = 12.sp, fontWeight = FontWeight.Bold, color = Muted)
            Text(text, fontSize = 16.sp, lineHeight = 23.sp, color = Ink)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LookChips(l: Look) {
    val n = l.counts
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        n.seen?.let { Chip("Seen $it${n.expected?.let { e -> " of $e" } ?: ""}", Surface, Ink, line = Border) }
        n.good?.let { Chip("$it good", GoodBg, Good) }
        n.damaged?.takeIf { it > 0 }?.let { Chip("$it damaged", DangerBg, Danger) }
        if (l.packMismatches > 0) Chip("${l.packMismatches} wrong pack size", WarningBg, Warning)
        if (l.expiryFlagged > 0) Chip("${l.expiryFlagged} expired or near expiry", WarningBg, Warning)
        if (l.batches.size > 1) Chip("Mixed batches: ${l.batches.joinToString()}", WarningBg, Warning)
    }
}

// --- every other step -----------------------------------------------------------------------------------------------------

@Composable
private fun TaskStepBody(v: StepView, c: TaskColors, a: Actions, lv: LookView?, climbHint: Boolean, reduceMotion: Boolean,
                         onEvidence: (() -> Unit)?, nextUp: NextUp?) {
    when (v.kind) {
        StepKind.DONE -> return DoneBody(v, lv, a, reduceMotion, onEvidence, nextUp)
        StepKind.CONFIRM -> return ConfirmBody(v, c)
        else -> Unit
    }
    if (v.kind == StepKind.CLIMB && TaskSteps.segmentOf(v) == 1) {
        Box(Modifier.fillMaxWidth().height(220.dp).clip(RoundedCornerShape(24.dp)).background(NightCard), contentAlignment = Alignment.Center) {
            ClipInHint(reduceMotion || !climbHint, Modifier.fillMaxWidth().height(200.dp).padding(16.dp))
        }
    }
    if (v.kind == StepKind.COUNT && lv != null && lv.state != LookState.IDLE) {
        LookStatus(lv, c, a)
        LookAnswers(lv, c)
    }
    Text(v.title, fontSize = if (v.kind == StepKind.CLIMB) 26.sp else 22.sp, lineHeight = 30.sp, fontWeight = FontWeight.Bold,
        color = if (v.kind == StepKind.FAILED) Danger else c.ink)
    v.where?.let { where ->
        Column(Modifier.fillMaxWidth().background(c.card, CardShape).border(1.dp, c.line, CardShape).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)) {
            v.whereLabel?.let { Text(it, fontSize = 13.sp, color = c.muted) }
            Text(where, fontFamily = FontFamily.Monospace, fontSize = 28.sp, fontWeight = FontWeight.Medium, color = c.ink)
            v.hint?.let { Text(it, fontSize = 15.sp, color = c.muted) }
        }
    }
    if (v.where == null) v.hint?.let { Text(it, fontSize = 15.sp, color = c.muted) }
    v.body?.let { Text(it, fontSize = 15.sp, color = c.muted) }
    if (v.kind != StepKind.COUNT) DetailRows(v, c)
    when (v.kind) {
        StepKind.SCAN -> {
            ScanArea(v.scanHowTo ?: "Scan the barcode", 170.dp, a.scan)
            ManualCode(a, ink = LavenderInk, onDark = true)
        }
        StepKind.COUNT -> CountNumbers(v, c, a)
        StepKind.REVIEW -> v.flagged?.let { f ->
            Text("+ $f flagged for quality inspection", fontSize = 15.sp, color = Warning, fontWeight = FontWeight.SemiBold)
        }
        StepKind.CHECK -> v.checks.forEachIndexed { i, item -> TaskCheckRow(item.label, item.ticked, c) { a.job(JobAction.ToggleCheck(i)) } }
        StepKind.CHECKIN -> OutlinedTextField(
            value = v.permit.orEmpty(), onValueChange = { a.job(JobAction.Permit(it)) }, singleLine = true,
            label = { Text("Work permit number") },
            colors = OutlinedTextFieldDefaults.colors(
                focusedTextColor = Color.White, unfocusedTextColor = Color.White, focusedLabelColor = NightMuted,
                unfocusedLabelColor = NightMuted, cursorColor = Color.White, focusedBorderColor = LavenderInk, unfocusedBorderColor = NightMuted,
            ),
            modifier = Modifier.fillMaxWidth().onFocusChanged { a.manualEntryOpen(it.isFocused) }
                .semantics { contentDescription = "Work permit number" },
        )
        StepKind.CLIMB -> Column(
            Modifier.fillMaxWidth().border(2.dp, StepDone, CardShape).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text("Climb-safe mode is on", fontSize = 15.sp, color = SoftAmber, fontWeight = FontWeight.Bold)
            Text("The phone stays locked. Your glasses only speak when you are clipped in at a platform.", fontSize = 16.sp, color = Color.White)
            Text("Say “harness clipped” and tap the button: both are needed. Your supervisor sees your safety check-ins.", fontSize = 15.sp, color = NightMuted)
        }
        StepKind.WAITING -> Box(Modifier.fillMaxWidth().padding(vertical = 12.dp), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(Modifier.size(48.dp), color = LavenderInk)
        }
        else -> Unit
    }
}

@Composable
private fun DetailRows(v: StepView, c: TaskColors) {
    if (v.detail.isEmpty()) return
    Column(Modifier.fillMaxWidth().background(c.card, CardShape).border(1.dp, c.line, CardShape).padding(horizontal = 16.dp, vertical = 4.dp)) {
        v.detail.forEachIndexed { i, d ->
            Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(d.k, color = c.muted, fontSize = 15.sp, modifier = Modifier.weight(1f))
                Text(d.v, fontWeight = FontWeight.Bold, color = c.ink, fontSize = 15.sp, textAlign = TextAlign.End, modifier = Modifier.weight(1f))
            }
            if (i < v.detail.lastIndex) Box(Modifier.fillMaxWidth().height(1.dp).background(c.line))
        }
    }
}

/** The receive / flag numbers big, with − and + (prototype ReceiveAnswer); the flag changes by voice only, as before. */
@Composable
private fun CountNumbers(v: StepView, c: TaskColors, a: Actions) {
    val receive = v.jobKind == "Receive" || v.jobKind == "Practice"
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Column(Modifier.weight(1f).background(Surface, CardShape).border(1.dp, Border, CardShape).padding(horizontal = 12.dp, vertical = 12.dp)) {
            Text(when { receive -> "Receive"; v.jobKind == "Pick" -> "Picked"; else -> "Count" }, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Muted)
            Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Stepper("−", "One less") { a.job(JobAction.SetQty(v.qty - 1)) }
                BasicTextField(
                    value = v.qty.toString(),
                    onValueChange = { t -> a.job(JobAction.SetQty(t.filter(Char::isDigit).take(4).toIntOrNull() ?: 0)) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    textStyle = TextStyle(fontSize = 32.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, color = Good),
                    modifier = Modifier.weight(1f).onFocusChanged { a.manualEntryOpen(it.isFocused) }.semantics { contentDescription = "Your count" },
                )
                Stepper("+", "One more") { a.job(JobAction.SetQty(v.qty + 1)) }
            }
        }
        v.flagged?.let { f ->
            Column(Modifier.weight(1f).background(Surface, CardShape).border(1.dp, Border, CardShape).padding(horizontal = 12.dp, vertical = 12.dp)
                .semantics { contentDescription = "$f flagged for quality inspection" }) {
                Text("Flag (quality)", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Muted)
                Box(Modifier.fillMaxWidth().height(MinTouch).padding(top = 4.dp), contentAlignment = Alignment.Center) {
                    Text("$f", fontSize = 32.sp, fontWeight = FontWeight.Bold, color = Warning)
                }
                Text("Say “flag ${f.coerceAtLeast(1)}” to change", fontSize = 12.sp, color = Muted, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
            }
        }
    }
    v.qtyNote?.let {
        Text(it, fontSize = 15.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth(),
            color = when (v.qtyTone) { Tone.GOOD -> Good; Tone.WARN, Tone.BAD -> Warning; Tone.NEUTRAL -> c.muted })
    }
    v.expected?.let { exp -> OutlineAction("All $exp are here", { a.job(JobAction.AllHere) }, Modifier.fillMaxWidth(), enabled = !v.busy, height = 52.dp) }
    if (v.jobKind == "Receive") NoteLine("Say your numbers, like “receive 7, flag 1”. What posts is always what you say.", c)
}

@Composable
private fun Stepper(sign: String, label: String, onClick: () -> Unit) {
    Box(
        Modifier.size(MinTouch).clip(RoundedCornerShape(12.dp)).background(Surface).border(1.dp, BorderStrong, RoundedCornerShape(12.dp))
            .clickable(role = Role.Button, onClick = onClick).semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) { Text(sign, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Ink) }
}

@Composable
private fun TaskCheckRow(label: String, on: Boolean, c: TaskColors, onToggle: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 60.dp).clip(CardShape).background(c.card).border(2.dp, if (on) LiveGreen else c.line, CardShape)
            .clickable(role = Role.Checkbox, onClick = onToggle).semantics { selected = on }.padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(28.dp).background(if (on) LiveGreen else c.track, RoundedCornerShape(14.dp)), contentAlignment = Alignment.Center) {
            if (on) TickGlyph(NightTask, side = 24.dp, stroke = 3.dp)
        }
        Text(label, fontWeight = FontWeight.SemiBold, color = c.ink, fontSize = 16.sp)
    }
}

// --- confirm (prototype ReceivePost) ---------------------------------------------------------------------------------------

/**
 * The confirm step. A spoken "post" waits 10 s for "yes" ([StepView.listening]): the ring counts that window down from
 * the moment the step starts listening (the runner's deadline; FieldController's 1 s tick ends it). A touch confirm
 * has no deadline: the ring is full with a tick.
 */
@Composable
private fun ConfirmBody(v: StepView, c: TaskColors) {
    val startedAt = remember(v.listening) { System.currentTimeMillis() }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    if (v.listening) LaunchedEffect(startedAt) {
        while (true) { now = System.currentTimeMillis(); delay(100) }
    }
    val left = ConfirmRingMath.secondsLeft(startedAt, now)
    Column(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(18.dp)) {
        if (v.listening) {
            ConfirmRing(ConfirmRingMath.progress(startedAt, now), ConfirmRingMath.urgent(left), "$left seconds left to confirm") {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("$left", fontSize = 56.sp, fontWeight = FontWeight.Bold, color = Color.White, lineHeight = 60.sp)
                    Text("seconds", fontSize = 14.sp, color = NightMuted)
                }
            }
        } else {
            ConfirmRing(1f, false, "Waiting for your confirm", side = 160.dp) { TickGlyph(LiveGreen, side = 88.dp) }
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(if (v.listening) "Say “yes” to confirm" else v.title, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = c.ink, textAlign = TextAlign.Center)
            Text((v.body?.let { "$it " } ?: "") + "Nothing posts until you confirm.", fontSize = 15.sp, lineHeight = 22.sp, color = c.muted, textAlign = TextAlign.Center)
        }
        if (v.detail.isNotEmpty()) {
            Column(Modifier.fillMaxWidth().background(NightCard, RoundedCornerShape(18.dp)).padding(horizontal = 16.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)) {
                v.detail.forEach { d ->
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text(d.k, fontSize = 16.sp, color = Color.White, modifier = Modifier.weight(1f))
                        Text(d.v, fontSize = 16.sp, fontWeight = FontWeight.Bold, color = if ("flagged" in d.v) SoftAmber else SoftGreen, textAlign = TextAlign.End)
                    }
                }
            }
        }
    }
}

// --- done (prototype ReceiveDone) --------------------------------------------------------------------------------------------

@Composable
private fun DoneBody(v: StepView, lv: LookView?, a: Actions, reduceMotion: Boolean, onEvidence: (() -> Unit)?, nextUp: NextUp?) {
    val tick = remember { Animatable(if (reduceMotion) 1f else 0f) }
    LaunchedEffect(Unit) { if (!reduceMotion) tick.animateTo(1f, tween(durationMillis = 600, delayMillis = 300)) }
    Column(Modifier.fillMaxWidth().padding(top = 40.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ResultMark(GoodBg, Good, v.title, tick.value)
        Text(v.title, fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold, color = Ink, textAlign = TextAlign.Center,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        val doc = v.detail.firstOrNull { it.k == "SAP document" }?.v
        Text(listOfNotNull(doc?.let { "Document $it" }, v.body).joinToString(" · "), fontSize = 16.sp, color = Muted, textAlign = TextAlign.Center)
    }
    v.detail.filter { it.k != "SAP document" }.takeIf { it.isNotEmpty() }?.let { rest -> DetailRows(v.copy(detail = rest), GroundColors) }
    val l = lv?.look
    if (onEvidence != null && l != null) ResultCard("Evidence page", "Photo, outlines, the check, two hashes", { DocGlyph() }, onEvidence)
    if (lv != null && l != null) {
        val claim = lv.claim
        if (claim == null) {
            ResultCard(
                if (lv.claimBusy) "Making claim…" else "Make a supplier claim",
                "Goes to a supervisor, who approves it by voice", { FlagGlyph() },
                onClick = a.makeClaim, enabled = !lv.claimBusy && !lv.labelsPending,
            )
        } else {
            Column(Modifier.fillMaxWidth().background(WarningBg, CardShape).padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("SAMPLE claim · ${claim.status}", fontWeight = FontWeight.Bold, color = Warning)
                Text(claim.text.ifBlank { ClaimText.lines(claim) }, color = Ink)
                Text("A supervisor approves it by voice before anything is sent (simulated).", fontSize = 13.sp, color = Muted)
            }
        }
        lv.message?.let { Text(it, color = Muted, fontSize = 14.sp) }
    }
    nextUp?.let { n ->
        Row(Modifier.fillMaxWidth().background(AccentBg, RoundedCornerShape(18.dp)).padding(16.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Column(Modifier.weight(1f)) {
                Text("NEXT UP", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = AccentInk)
                Text(n.title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                n.sub?.let { Text(it, fontSize = 13.sp, color = Muted) }
            }
            Box(Modifier.heightIn(min = MinTouch).clip(RoundedCornerShape(12.dp)).background(AccentInk).clickable(role = Role.Button, onClick = n.onStart)
                .padding(horizontal = 16.dp), contentAlignment = Alignment.Center) {
                Text("Start", color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
            }
        }
    }
}

// --- small parts ---------------------------------------------------------------------------------------------------------------

@Composable
private fun Banner(text: String) {
    Text(text, color = Warning, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier.fillMaxWidth().background(WarningBg, CardShape).padding(horizontal = 14.dp, vertical = 10.dp))
}

@Composable
private fun Busy(text: String, c: TaskColors) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) {
        CircularProgressIndicator(Modifier.size(20.dp), color = if (c === GroundColors) AccentInk else LavenderInk, strokeWidth = 2.dp)
        Text(text, color = c.muted, fontSize = 15.sp)
    }
}

/** Audio-only mode: prompts are spoken, never shown; the buttons stay as a fallback (as before). */
@Composable
private fun TaskAudioOnly(v: StepView, c: TaskColors, a: Actions, look: LookView? = null) {
    Column(Modifier.fillMaxWidth().background(c.card, CardShape).border(1.dp, c.line, CardShape).padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Audio-only mode", fontWeight = FontWeight.Bold, color = c.ink, fontSize = 20.sp)
        Text("Listen to your glasses. Say “repeat” to hear the step again.", color = c.muted)
    }
    if (v.kind == StepKind.SCAN) ScanArea(v.scanHowTo ?: "Scan the barcode", 160.dp, a.scan)
    OutlineAction("Repeat", { a.job(JobAction.Heard("repeat", 1f)) }, Modifier.fillMaxWidth(), height = 52.dp)
    // Owner's test, 4 Nov 2026: the photo consent was spoken but its button was hidden in audio-only mode.
    if (look?.state == LookState.CONSENT) OutlineAction("Agree for this site", a.agreePhotos, Modifier.fillMaxWidth(), height = 52.dp)
}

/** Phone microphone, hold while speaking (fallback when the glasses do not listen); same calls as before. */
@Composable
private fun TaskHoldToTalk(c: TaskColors, a: Actions) {
    var held by remember { mutableStateOf(false) }
    Box(
        Modifier.fillMaxWidth().heightIn(min = MinTouch).clip(ButtonShape).border(1.dp, c.line, ButtonShape)
            .background(if (held) AccentInk else Color.Transparent)
            .pointerInput(Unit) { detectTapGestures(onPress = { held = true; a.talkStart(); tryAwaitRelease(); held = false; a.talkStop() }) }
            .semantics { role = Role.Button; contentDescription = "Hold to talk" },
        contentAlignment = Alignment.Center,
    ) { Text(if (held) "Listening… let go when done" else "Hold to talk", color = if (held) Color.White else if (c === GroundColors) Ink else NightInk, fontWeight = FontWeight.SemiBold) }
}
