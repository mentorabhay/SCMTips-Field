package com.scmtips.field.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.decisions.DecisionText
import com.scmtips.field.app.decisions.DecisionsView
import com.scmtips.field.app.ui.theme.InfoBg
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Ink2
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Primary
import com.scmtips.field.app.ui.theme.SuccessBg
import com.scmtips.field.app.ui.theme.SuccessInk
import com.scmtips.field.app.ui.theme.WarnInk
import com.scmtips.field.feature.decisions.api.StepUpMethod

/** Today's Decisions card (approvers only): how many wait, and "Review now". */
@Composable
fun DecisionsCard(d: DecisionsView, workActive: Boolean, a: Actions) {
    CardBox {
        Text("Decisions", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted)
        Text(DecisionText.chip(d.waiting), fontWeight = FontWeight.Bold, color = Ink, fontSize = 17.sp)
        Text(
            if (workActive) "Say “decisions” to hear the brief on the glasses, then “approve option one” or “two”, “reject” or “repeat”."
            else "The brief is spoken on the glasses (or this phone). Answer by voice: hold the talk button, or start work and just speak.",
            color = Ink2, fontSize = 14.sp,
        )
        d.last?.let { Text("Last: $it", color = Muted, fontSize = 13.sp) }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            PrimaryButton("Review now", a.startReview, Modifier.weight(1f), enabled = d.waiting != 0, height = 52.dp)
            SecondaryButton("Check again", a.refreshDecisions, Modifier.weight(1f))
        }
    }
}

/**
 * The classic running review (kept behind "Classic layout", A-07), drawn over the tabs: the card (when not audio-only), what is happening, the card's
 * buttons (shortcuts for words the core's grammar understands), hold-to-talk outside a work session.
 */
@Composable
internal fun ClassicDecisionScreen(ui: AppUi, a: Actions) {
    val d = ui.decisions
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Decision", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink)
        Text(d.state, color = if (d.listening) SuccessInk else Ink2, fontSize = 15.sp,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
                .then(if (d.listening) Modifier.background(SuccessBg, Corner).padding(horizontal = 10.dp, vertical = 6.dp) else Modifier))
        val card = d.card
        if (card != null) {
            CardBox {
                Text(card.title, fontWeight = FontWeight.Bold, color = Ink, fontSize = 18.sp)
                Text(card.body, color = Ink2, fontSize = 15.sp)
                card.buttons.forEach { b ->
                    if (b.primary) PrimaryButton(b.label, { a.decisionButton(b.id) }, Modifier.fillMaxWidth(), height = 52.dp)
                    else SecondaryButton(b.label, { a.decisionButton(b.id) }, Modifier.fillMaxWidth())
                }
            }
        } else if (ui.audioOnly) {
            Notice("Audio-only mode: the decision is spoken, not shown. Answer by voice.", com.scmtips.field.app.jobs.Tone.NEUTRAL)
        }
        if (d.briefSource == "template") Text("The brief is SCMTIPS's own wording.", color = Muted, fontSize = 13.sp)
        if (!ui.work.active) ReviewHoldToTalk(a)
        else Text("The work session is listening: just speak.", color = Muted, fontSize = 14.sp)
        SecondaryButton("Stop", a.stopReview, Modifier.fillMaxWidth(), ink = WarnInk)
    }
}

@Composable
private fun ReviewHoldToTalk(a: Actions) {
    var held by remember { mutableStateOf(false) }
    Box(
        Modifier.fillMaxWidth().heightIn(min = 72.dp).background(if (held) Primary else InfoBg, Corner)
            .pointerInput(Unit) {
                detectTapGestures(onPress = {
                    held = true
                    a.talkStart()
                    tryAwaitRelease()
                    held = false
                    a.talkStop()
                })
            },
        contentAlignment = Alignment.Center,
    ) {
        Text(if (held) "Listening… let go when done" else "Hold to talk", color = if (held) Color.White else Primary, fontWeight = FontWeight.Bold, fontSize = 17.sp)
    }
}

/** The phone step-up (TOTP or backup code). The code is typed, never spoken, and never logged. */
@Composable
fun StepUpDialog(retryMessage: String?, a: Actions) {
    var code by remember { mutableStateOf("") }
    var backup by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = { a.answerStepUp(StepUpMethod.TOTP, null) },
        title = { Text("Verify it is you") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(if (backup) "Enter one of your SCMTIPS backup codes." else "Enter the 6-digit code from your authenticator app.", color = Ink2)
                retryMessage?.let { Notice(it, com.scmtips.field.app.jobs.Tone.BAD) }
                OutlinedTextField(
                    value = code, onValueChange = { code = it.take(32) }, singleLine = true,
                    label = { Text(if (backup) "Backup code" else "Code") },
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = if (backup) KeyboardType.Password else KeyboardType.NumberPassword),
                )
                TextButton(onClick = { backup = !backup; code = "" }) {
                    Text(if (backup) "Use the authenticator code" else "Use a backup code", color = Primary)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { a.answerStepUp(if (backup) StepUpMethod.BACKUP_CODE else StepUpMethod.TOTP, code) }, enabled = code.isNotBlank()) {
                Text("Verify", fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = { TextButton(onClick = { a.answerStepUp(StepUpMethod.TOTP, null) }) { Text("Cancel") } },
    )
}

/** Today on a sandbox site: "Count a shelf" asks which shelf first. */
@Composable
fun CountShelfDialog(onStart: (String) -> Unit, onDismiss: () -> Unit) {
    var bin by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Count a shelf") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Type the shelf or bin label (or the code on it).", color = Ink2)
                OutlinedTextField(value = bin, onValueChange = { bin = it.take(64) }, singleLine = true, label = { Text("Shelf or bin") })
            }
        },
        confirmButton = { TextButton(onClick = { onStart(bin) }, enabled = bin.isNotBlank()) { Text("Start count", fontWeight = FontWeight.Bold) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
