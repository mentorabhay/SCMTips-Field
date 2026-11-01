package com.scmtips.field.app.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.ui.kit.AccentInk
import com.scmtips.field.app.ui.kit.AccentSoft
import com.scmtips.field.app.ui.kit.Border
import com.scmtips.field.app.ui.kit.BrandEnd
import com.scmtips.field.app.ui.kit.BrandStart
import com.scmtips.field.app.ui.kit.ButtonShape
import com.scmtips.field.app.ui.kit.CardShape
import com.scmtips.field.app.ui.kit.Chevron
import com.scmtips.field.app.ui.kit.DecisionLayout
import com.scmtips.field.app.ui.kit.Good
import com.scmtips.field.app.ui.kit.GoodBg
import com.scmtips.field.app.ui.kit.GradientButton
import com.scmtips.field.app.ui.kit.GroundColors
import com.scmtips.field.app.ui.kit.Ink
import com.scmtips.field.app.ui.kit.Lavender
import com.scmtips.field.app.ui.kit.LeadIcon
import com.scmtips.field.app.ui.kit.MainActionBar
import com.scmtips.field.app.ui.kit.MinTouch
import com.scmtips.field.app.ui.kit.Muted
import com.scmtips.field.app.ui.kit.Night
import com.scmtips.field.app.ui.kit.NightMuted
import com.scmtips.field.app.ui.kit.NoteLine
import com.scmtips.field.app.ui.kit.OutlineAction
import com.scmtips.field.app.ui.kit.QuietButton
import com.scmtips.field.app.ui.kit.ResultMark
import com.scmtips.field.app.ui.kit.StepDone
import com.scmtips.field.app.ui.kit.StepHeader
import com.scmtips.field.app.ui.kit.Surface
import com.scmtips.field.app.ui.kit.Warning
import com.scmtips.field.app.ui.kit.rememberSystemReduceMotion

/**
 * The running review, M5-U decision detail (A-07; prototype DecisionDetail, DecisionDone): the title, the state,
 * the brief's status with a waveform while it is spoken, the card's text, one card per option (tap to pick), and at
 * the bottom Reject and ONE main "Approve option X" (or Confirm / Cancel on the read-back). Every button is a card
 * button of the flow ([Actions.decisionButton] with its id), so the core still decides every intent. An option card
 * adds the option's title and the core's amounts when DecisionsView.next is this decision (M5-U06). [classic] draws
 * the old screen ([ClassicDecisionScreen]). The brief cannot be replayed by a tap yet (say "repeat"): see the report.
 */
@Composable
fun DecisionScreen(ui: AppUi, a: Actions, classic: Boolean = false, reduceMotion: Boolean = rememberSystemReduceMotion()) {
    if (classic) {
        ClassicDecisionScreen(ui, a)
        return
    }
    val d = ui.decisions
    val g = GroundColors
    val card = d.card
    var tapped by remember(card) { mutableStateOf<String?>(null) }
    val picked = DecisionLayout.picked(card, tapped)
    val ids = card?.buttons.orEmpty().associate { it.id to it.label }
    val details = DecisionLayout.optionDetails(card, d.next)
    Column(Modifier.fillMaxSize().background(g.bg)) {
        Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 8.dp)) {
            StepHeader("Decision", null, g, LeadIcon.BACK, a.stopReview, leadLabel = "Stop the review")
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            card?.let { Text(it.title, fontSize = 24.sp, lineHeight = 30.sp, fontWeight = FontWeight.Bold, color = Ink) }
            if (d.state.isNotBlank()) {
                Text(d.state, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = if (d.listening) Good else Warning,
                    modifier = Modifier.background(if (d.listening) GoodBg else Color(0xFFFFF7ED), RoundedCornerShape(10.dp))
                        .padding(horizontal = 10.dp, vertical = 4.dp).semantics { liveRegion = LiveRegionMode.Polite })
            }
            BriefPill(DecisionLayout.briefPlaying(d.state), reduceMotion)
            if (d.briefSource == "template") Text("The brief is SCMTIPS's own wording.", color = Muted, fontSize = 13.sp)
            when {
                card != null -> {
                    if (card.body.isNotBlank()) Text(card.body, fontSize = 15.sp, lineHeight = 22.sp, color = Ink,
                        modifier = Modifier.fillMaxWidth().background(Surface, CardShape).border(1.dp, Border, CardShape).padding(14.dp))
                    val options = DecisionLayout.options(card)
                    if (options.isNotEmpty()) {
                        Text("Options", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted, modifier = Modifier.padding(top = 4.dp))
                        options.forEach { o ->
                            val on = o == picked
                            Row(
                                Modifier.fillMaxWidth().heightIn(min = 64.dp).clip(CardShape).background(Surface)
                                    .border(if (on) 2.dp else 1.dp, if (on) BrandStart else Border, CardShape)
                                    .clickable(role = Role.RadioButton) { tapped = o.letter }.semantics { selected = on }.padding(14.dp),
                                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
                            ) {
                                Box(Modifier.size(22.dp).border(2.dp, if (on) BrandStart else Chevron, CircleShape), contentAlignment = Alignment.Center) {
                                    if (on) Box(Modifier.size(12.dp).background(BrandStart, CircleShape))
                                }
                                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                    val detail = details[o.letter]
                                    Text(detail?.title?.let { "Option ${o.letter} · $it" } ?: "Option ${o.letter}",
                                        fontSize = 16.sp, fontWeight = FontWeight.Bold, color = Ink)
                                    detail?.cost?.let { Text(it, fontSize = 14.sp, color = Ink) }
                                    Text("Say “approve option ${o.letter}”", fontSize = 13.sp, color = Muted)
                                }
                            }
                        }
                    }
                }
                ui.audioOnly -> Notice("Audio-only mode: the decision is spoken, not shown. Answer by voice.", com.scmtips.field.app.jobs.Tone.NEUTRAL)
                d.state == "Committed" -> Column(Modifier.fillMaxWidth().padding(top = 24.dp), horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    ResultMark(AccentSoft, AccentInk, "Committed", 1f)
                    Text("Committed", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink)
                    Text("SCMTIPS records your decision and starts the next steps.", fontSize = 16.sp, color = Muted, textAlign = TextAlign.Center)
                    d.last?.let { Text("Last: $it", fontSize = 14.sp, color = Muted) }
                }
                else -> d.last?.let { Text("Last: $it", color = Muted, fontSize = 13.sp) }
            }
            if (!ui.work.active) DecisionHoldToTalk(a) else NoteLine("The work session is listening: just speak.", g)
        }
        MainActionBar(g) {
            if (card != null && DecisionLayout.confirmStage(card)) {
                GradientButton(ids["confirm"] ?: "Confirm", { a.decisionButton("confirm") })
                if ("cancel" in ids) QuietButton(ids.getValue("cancel"), { a.decisionButton("cancel") }, g)
            } else if (card != null) {
                picked?.let { NoteLine("Or say “approve option ${it.letter}”", g) }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    if ("reject" in ids) OutlineAction(ids.getValue("reject"), { a.decisionButton("reject") }, Modifier.weight(1f))
                    picked?.let { p -> Box(Modifier.weight(2f)) { GradientButton("Approve option ${p.letter}", { a.decisionButton(p.buttonId) }, height = 56.dp) } }
                }
            }
            DecisionLayout.others(card).forEach { id -> QuietButton(ids[id] ?: id, { a.decisionButton(id) }, g) }
            QuietButton("Stop", a.stopReview, g, ink = Warning)
        }
    }
}

/** The spoken brief's status (Night pill): a waveform while it plays; otherwise how to hear it again. */
@Composable
private fun BriefPill(playing: Boolean, reduceMotion: Boolean) {
    Row(
        Modifier.fillMaxWidth().background(Night, RoundedCornerShape(18.dp)).padding(horizontal = 16.dp, vertical = 14.dp)
            .semantics { contentDescription = if (playing) "Playing the brief" else "The brief. Say repeat to hear it again" },
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(Modifier.size(MinTouch).background(Brush.linearGradient(listOf(BrandStart, BrandEnd)), CircleShape), contentAlignment = Alignment.Center) {
            Canvas(Modifier.size(18.dp)) {
                if (playing) {
                    drawRoundRect(Color.White, Offset(size.width * 0.25f, size.height * 0.2f), Size(size.width * 0.17f, size.height * 0.6f), CornerRadius(2f))
                    drawRoundRect(Color.White, Offset(size.width * 0.58f, size.height * 0.2f), Size(size.width * 0.17f, size.height * 0.6f), CornerRadius(2f))
                } else {
                    drawPath(Path().apply { moveTo(size.width * 0.33f, size.height * 0.2f); lineTo(size.width * 0.8f, size.height * 0.5f); lineTo(size.width * 0.33f, size.height * 0.8f); close() }, Color.White)
                }
            }
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(if (playing) "Playing the brief" else "The spoken brief", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
            Text(if (playing) "Also in your glasses" else "Say “repeat” to hear it again", color = NightMuted, fontSize = 13.sp)
        }
        if (playing) Waveform(reduceMotion)
    }
}

/** Five bars rising and falling while the brief plays (still when motion is off). */
@Composable
private fun Waveform(reduceMotion: Boolean) {
    val t = if (reduceMotion) remember { mutableFloatStateOf(0.5f) } else rememberInfiniteTransition(label = "wave")
        .animateFloat(0f, 1f, infiniteRepeatable(tween(1_000, easing = LinearEasing), RepeatMode.Restart), label = "wave-t")
    Canvas(Modifier.size(width = 48.dp, height = 28.dp)) {
        val bars = 5
        val w = size.width / (bars * 2f - 1f)
        for (i in 0 until bars) {
            val ph = (t.value + i * 0.15f) % 1f
            val k = 0.35f + 0.65f * (if (ph < 0.5f) ph * 2f else (1f - ph) * 2f)
            val h = size.height * k
            drawRoundRect(if (i == 2) StepDone else Lavender, Offset(i * 2f * w, (size.height - h) / 2f), Size(w, h), CornerRadius(w / 2f))
        }
    }
}

@Composable
private fun DecisionHoldToTalk(a: Actions) {
    var held by remember { mutableStateOf(false) }
    Box(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).clip(ButtonShape).background(if (held) AccentInk else AccentSoft)
            .pointerInput(Unit) {
                detectTapGestures(onPress = {
                    held = true
                    a.talkStart()
                    tryAwaitRelease()
                    held = false
                    a.talkStop()
                })
            }
            .semantics { role = Role.Button; contentDescription = "Hold to talk" },
        contentAlignment = Alignment.Center,
    ) {
        Text(if (held) "Listening… let go when done" else "Hold to talk", color = if (held) Color.White else AccentInk, fontWeight = FontWeight.Bold, fontSize = 17.sp)
    }
}
