package com.scmtips.field.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.check.AuthenticityCheck
import com.scmtips.field.app.check.CheckAction
import com.scmtips.field.app.check.CheckState
import com.scmtips.field.app.check.CheckView
import com.scmtips.field.app.look.ClaimText
import com.scmtips.field.app.look.LookFlow
import com.scmtips.field.app.ui.kit.AccentBg
import com.scmtips.field.app.ui.kit.AccentInk
import com.scmtips.field.app.ui.kit.Border
import com.scmtips.field.app.ui.kit.CardShape
import com.scmtips.field.app.ui.kit.Danger
import com.scmtips.field.app.ui.kit.DangerBg
import com.scmtips.field.app.ui.kit.Divider
import com.scmtips.field.app.ui.kit.GradientButton
import com.scmtips.field.app.ui.kit.GroundColors
import com.scmtips.field.app.ui.kit.Hint
import com.scmtips.field.app.ui.kit.HintArea
import com.scmtips.field.app.ui.kit.Ink
import com.scmtips.field.app.ui.kit.LavenderInk
import com.scmtips.field.app.ui.kit.LeadIcon
import com.scmtips.field.app.ui.kit.MainActionBar
import com.scmtips.field.app.ui.kit.Muted
import com.scmtips.field.app.ui.kit.NightCard
import com.scmtips.field.app.ui.kit.NightColors
import com.scmtips.field.app.ui.kit.NightMuted
import com.scmtips.field.app.ui.kit.NoteLine
import com.scmtips.field.app.ui.kit.OutlineAction
import com.scmtips.field.app.ui.kit.QuietButton
import com.scmtips.field.app.ui.kit.SealCodeHint
import com.scmtips.field.app.ui.kit.StepHeader
import com.scmtips.field.app.ui.kit.Surface
import com.scmtips.field.app.ui.kit.TaskSteps
import com.scmtips.field.app.ui.kit.VerdictIcon
import com.scmtips.field.app.ui.kit.VerdictStyle
import com.scmtips.field.app.ui.kit.VoiceChip
import com.scmtips.field.app.ui.kit.Warning
import com.scmtips.field.app.ui.kit.WarningBg
import com.scmtips.field.app.ui.kit.rememberHintVisible
import com.scmtips.field.app.ui.kit.rememberSystemReduceMotion

/**
 * The box check, M5-U task layout (A-07; prototype ScanSeal, ScanVerdict). Before the verdict: a Night camera
 * screen with the seal-code hint, the photo when there is one, and the step's own buttons (scan with the phone,
 * photo consent, try again). With the verdict: a light screen with the colour-coded verdict card, the four signals,
 * the seal photo, then Evidence and ONE main button (make a claim, or check another box). Every button calls the
 * same [CheckAction] as before; [classic] draws the old card ([ClassicCheckScreen]).
 */
@Composable
fun CheckScreen(
    v: CheckView,
    workActive: Boolean,
    a: Actions,
    classic: Boolean = false,
    reduceMotion: Boolean = rememberSystemReduceMotion(),
) {
    if (classic) {
        ClassicCheckScreen(v, workActive, a)
        return
    }
    BackHandler { a.check(CheckAction.DONE) }
    val c = v.check
    if (c == null) SealStep(v, workActive, a, reduceMotion) else VerdictStep(v, c, workActive, a)
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SealStep(v: CheckView, workActive: Boolean, a: Actions, reduceMotion: Boolean) {
    val n = NightColors
    val hint = TaskSteps.checkHint(v.state, hasVerdict = false)
    var hintUp by rememberHintVisible(hint?.let { TaskSteps.CHECK_HINT_KEY })
    Column(Modifier.fillMaxSize().background(n.bg)) {
        Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 8.dp)) {
            StepHeader("Is this unit really new?", "Scan the maker's seal", n, LeadIcon.CLOSE, { a.check(CheckAction.DONE) },
                onHelp = { hintUp = true })
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.fillMaxWidth().heightIn(min = 280.dp).clip(RoundedCornerShape(24.dp)).background(NightCard)) {
                val photo = v.photo
                if (photo != null) Box(Modifier.padding(8.dp)) { SealPhoto(photo, null) }
                else SealCodeHint(reduceMotion = reduceMotion || !hintUp, modifier = Modifier.fillMaxWidth().height(280.dp).padding(20.dp))
                if (hintUp) HintArea(Hint.SEAL_CODE, reduceMotion, { hintUp = false }, Modifier.align(Alignment.TopCenter).padding(12.dp))
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Chip("SAMPLE · the maker is a simulator", WarningBg, Warning)
                v.camera?.let { Chip(it.label, AccentBg, AccentInk) }
                v.codeSource?.let { Chip(it.label, Surface, Ink, line = Border) }
            }
            if (v.busy) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                CircularProgressIndicator(Modifier.size(20.dp), color = LavenderInk, strokeWidth = 2.dp)
                Text(v.state.text, color = NightMuted, fontSize = 15.sp, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
            }
            v.message?.let {
                Text(it, color = if (v.state == CheckState.FAILED || v.state == CheckState.NO_CODE) Color(0xFFFCA5A5) else NightMuted, fontSize = 15.sp,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
            }
            if (v.state == CheckState.CONSENT) Text(LookFlow.CONSENT_TEXT, color = NightMuted, fontSize = 14.sp)
            VoiceChip("Say “check this box” · hold it 20 to 30 cm away", n)
        }
        MainActionBar(n) {
            when (v.state) {
                CheckState.NO_CODE -> {
                    GradientButton("Scan the code with the phone", { a.check(CheckAction.PHONE_SCAN) })
                    QuietButton("Take the photo again", { a.check(CheckAction.START) }, n)
                }
                CheckState.CONSENT -> {
                    GradientButton("Agree for this site", { a.check(CheckAction.AGREE) })
                    QuietButton("Check by code only", { a.check(CheckAction.CODE_ONLY) }, n)
                }
                CheckState.FAILED -> if (v.canRetry) GradientButton("Try again", { a.check(CheckAction.RETRY) })
                    else GradientButton("Check again", { a.check(CheckAction.AGAIN) })
                else -> GradientButton(if (v.busy) v.state.text else "Check this box", { a.check(CheckAction.AGAIN) }, enabled = !v.busy)
            }
            QuietButton("Done", { a.check(CheckAction.DONE) }, n)
            if (!workActive) NoteLine("Hold to talk on a job screen, or start work to use your voice.", n)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun VerdictStep(v: CheckView, c: AuthenticityCheck, workActive: Boolean, a: Actions) {
    val g = GroundColors
    val look = VerdictStyle.of(c.verdict)
    val ink = Color(look.ink)
    Column(Modifier.fillMaxSize().background(g.bg)) {
        Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 8.dp)) {
            StepHeader("Is this unit really new?", c.code?.oemName?.let { "$it · simulated maker" } ?: "SAMPLE · simulated maker", g, LeadIcon.BACK,
                { a.check(CheckAction.DONE) }, leadLabel = "Close the check")
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.fillMaxWidth().background(Color(look.bg), RoundedCornerShape(22.dp)).padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Box(Modifier.size(36.dp).background(ink, CircleShape), contentAlignment = Alignment.Center) { VerdictGlyph(look.icon) }
                    Text(look.title, fontSize = 24.sp, lineHeight = 28.sp, fontWeight = FontWeight.Bold, color = ink,
                        modifier = Modifier.weight(1f).semantics { liveRegion = LiveRegionMode.Polite })
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (c.tamper == true) Chip("Seal tampered", DangerBg, Danger, dot = Danger)
                    if (v.visualPending) Chip("Checking the seal…", Surface, Ink, line = Border)
                    Chip("SAMPLE", WarningBg, Warning)
                    if (v.photoSent == false) Chip("Code only · no photo sent", Surface, Ink, line = Border)
                }
                if (c.say.isNotBlank()) Text("“${c.say}”", fontSize = 16.sp, lineHeight = 23.sp, color = Ink)
            }
            Column(Modifier.fillMaxWidth().background(Surface, RoundedCornerShape(18.dp)).border(1.dp, Border, RoundedCornerShape(18.dp))) {
                val rows = VerdictStyle.signals(c, v.visualPending)
                rows.forEachIndexed { i, s ->
                    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Box(Modifier.padding(top = 6.dp).size(10.dp).background(Color(s.tone.dot), CircleShape))
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text(s.name, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                            Text(s.value, fontSize = 14.sp, color = Muted)
                        }
                    }
                    if (i < rows.lastIndex) Box(Modifier.fillMaxWidth().height(1.dp).background(Divider))
                }
            }
            Text("The verdict comes from the signed code, the maker's history and the first check. The seal photo only adds evidence.",
                fontSize = 13.sp, lineHeight = 18.sp, color = Muted)
            v.photo?.let { SealPhoto(it, c) }
            v.claim?.let { cl ->
                Column(Modifier.fillMaxWidth().background(WarningBg, CardShape).padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("SAMPLE claim · ${cl.status}", fontWeight = FontWeight.Bold, color = Warning)
                    Text(ClaimText.body(cl), color = Ink)
                    Text("A supervisor approves it by voice before anything is sent (simulated).", fontSize = 13.sp, color = Muted)
                }
            }
            v.message?.let { Text(it, color = if (v.state == CheckState.FAILED) Danger else Muted, fontSize = 15.sp,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
            NoteLine(if (workActive) "You can say: make a claim, show evidence, check again, done."
                else "Hold to talk on a job screen, or start work to use your voice.", g)
        }
        MainActionBar(g) {
            val claimFirst = v.claimable || v.claim != null || v.claimBusy || v.visualPending
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlineAction("Evidence", { a.check(CheckAction.EVIDENCE) }, Modifier.weight(1f))
                Box(Modifier.weight(2f)) {
                    if (claimFirst) GradientButton(
                        when {
                            v.claim != null -> "Claim drafted"
                            v.claimBusy -> "Making claim…"
                            v.visualPending -> "Checking the seal…"
                            else -> "Make a claim"
                        },
                        { a.check(CheckAction.CLAIM) }, enabled = v.claimable && v.claim == null && !v.claimBusy, height = 56.dp,
                    ) else GradientButton("Check another box", { a.check(CheckAction.AGAIN) }, enabled = !v.busy, height = 56.dp)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (claimFirst) QuietButton("Check again", { a.check(CheckAction.AGAIN) }, g, enabled = !v.busy, modifier = Modifier.weight(1f))
                QuietButton("Done", { a.check(CheckAction.DONE) }, g, modifier = Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun VerdictGlyph(icon: VerdictIcon) = Canvas(Modifier.size(20.dp)) {
    val u = size.width / 24f
    val s = Stroke(width = 2.6f * u, cap = StrokeCap.Round)
    val p = Path()
    when (icon) {
        VerdictIcon.TICK -> { p.moveTo(5 * u, 12 * u); p.lineTo(10 * u, 17 * u); p.lineTo(19 * u, 7 * u) }
        VerdictIcon.WARN -> { p.moveTo(12 * u, 7 * u); p.lineTo(12 * u, 13 * u); drawCircle(Color.White, 1.6f * u, Offset(12 * u, 17.5f * u)) }
        VerdictIcon.CROSS -> { p.moveTo(7 * u, 7 * u); p.lineTo(17 * u, 17 * u); p.moveTo(17 * u, 7 * u); p.lineTo(7 * u, 17 * u) }
    }
    drawPath(p, Color.White, style = s)
}
