package com.scmtips.field.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.session.SessionView
import com.scmtips.field.app.ui.theme.CardBg
import com.scmtips.field.app.ui.theme.InfoBg
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Ink2
import com.scmtips.field.app.ui.theme.Line
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Primary
import com.scmtips.field.app.ui.theme.Success
import com.scmtips.field.app.ui.theme.SuccessBg
import com.scmtips.field.app.ui.theme.SuccessInk
import com.scmtips.field.app.ui.theme.WarnBg
import com.scmtips.field.app.ui.theme.WarnInk
import com.scmtips.field.app.ui.theme.WarnText

/**
 * Today's main action (M3 contract §5): one big "Start work". During the session the card mirrors it:
 * listening / paused / glasses camera, the last words heard and said, the assistant's card.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun WorkCard(w: SessionView, glassesConnected: Boolean, a: Actions) {
    CardBox {
        if (!w.active) {
            Text(if (glassesConnected) "Glasses connected" else "Glasses first", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted)
            Text("Put on the glasses, start once, then the phone can go in your pocket. The assistant tells you the work.",
                color = Ink2, fontSize = 15.sp)
            PrimaryButton("Start work", a.startWork, Modifier.fillMaxWidth(), height = 64.dp)
        } else {
            ActiveWork(w, a)
        }
    }
}

@Composable
private fun ActiveWork(w: SessionView, a: Actions) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("Work session", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted)
        StateChips(w)
        w.heard?.let { Text("You said: “$it”", color = Ink, fontSize = 15.sp, maxLines = 2, overflow = TextOverflow.Ellipsis) }
        w.said?.takeIf { it.isNotBlank() }?.let {
            Text("Assistant: $it", color = Ink2, fontSize = 15.sp, maxLines = 3, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        }
        w.card?.let { (title, body) ->
            Column(Modifier.fillMaxWidth().background(InfoBg, Corner).padding(12.dp)) {
                if (title.isNotBlank()) Text(title, fontWeight = FontWeight.Bold, color = Ink)
                if (body.isNotBlank()) Text(body, color = Ink2, fontSize = 14.sp)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (w.paused == null) SecondaryButton("Pause", a.pauseWork, Modifier.weight(1f))
            else PrimaryButton("Resume", a.resumeWork, Modifier.weight(1f), height = 52.dp)
            SecondaryButton("Stop work", a.stopWork, Modifier.weight(1f), ink = WarnInk)
        }
    }
}

/** Above the job screen during a session: the job screen stays the mirror of the spoken step. */
@Composable
fun SessionStrip(w: SessionView, a: Actions) {
    Row(
        Modifier.fillMaxWidth().background(CardBg).padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Column(Modifier.weight(1f)) { StateChips(w) }
        if (w.paused != null) SmallButton("Resume", a.resumeWork) else SmallButton("Pause", a.pauseWork)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun StateChips(w: SessionView) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        when {
            w.paused != null -> Chip(w.stateText, WarnBg, WarnInk, dot = WarnText)
            w.listening -> Chip(w.stateText, SuccessBg, SuccessInk, dot = Success)
            else -> Chip(w.stateText, CardBg, Ink2, line = Line)
        }
        if (w.cameraOn) Chip("Glasses camera on", InfoBg, Primary)
        if (w.assistantOnline == false) Chip("Assistant offline · fixed words", WarnBg, WarnInk)
        if (w.listenMode == "free") Chip("Answer the question", InfoBg, Primary)
    }
}
