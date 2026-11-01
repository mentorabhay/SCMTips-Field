package com.scmtips.field.app.ui.shell

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.ui.Actions
import com.scmtips.field.app.ui.CardBox
import com.scmtips.field.app.ui.CardShape
import com.scmtips.field.app.ui.ClaimsCard
import com.scmtips.field.app.ui.DecisionsCard
import com.scmtips.field.app.ui.SecondaryButton
import com.scmtips.field.app.ui.theme.Border
import com.scmtips.field.app.ui.theme.Ground
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Ink2
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Surface

/** A scrolling page on the ground colour (the shell's tabs and pages). */
@Composable
internal fun Scroll(content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxSize().background(Ground).verticalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp), content = content)
}

@Composable
internal fun TabTitle(text: String) {
    Text(text, fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink, modifier = Modifier.padding(start = 4.dp, top = 16.dp, bottom = 4.dp))
}

/** Activity: the work session now and what happened on this phone (the real app log), newest first. */
@Composable
internal fun ActivityTab(ui: AppUi, a: Actions) = Scroll {
    TabTitle("Activity")
    CardBox {
        Text("Work session", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted)
        Text(ui.work.stateText, fontWeight = FontWeight.Bold, color = Ink, fontSize = 18.sp)
        ui.work.heard?.let { Text("Heard: “$it”", color = Ink2, fontSize = 14.sp) }
        ui.work.said?.let { Text("Said: “$it”", color = Ink2, fontSize = 14.sp) }
        if (!ui.work.active && ui.home.fieldWork && ui.pairing != null) {
            SecondaryButton("Start work", a.startWork, Modifier.padding(top = 6.dp))
        }
    }
    Text("On this phone", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted, modifier = Modifier.padding(start = 4.dp, top = 6.dp))
    if (ui.log.isEmpty()) {
        CardBox {
            Text("Nothing yet", fontWeight = FontWeight.Bold, color = Ink)
            Text("Looks, postings, checks and decisions show up here as they happen.", color = Muted, fontSize = 14.sp)
        }
    } else {
        Column(Modifier.fillMaxWidth().background(Surface, CardShape)
            .border(1.dp, Border, CardShape).padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)) {
            ui.log.takeLast(40).asReversed().forEach { Text(it, fontSize = 13.sp, color = Ink2) }
        }
    }
}

/** Inbox: decisions waiting for an approver and a supervisor's draft claims. */
@Composable
internal fun InboxTab(ui: AppUi, a: Actions) = Scroll {
    TabTitle("Inbox")
    if (ui.home.decisions) DecisionsCard(ui.decisions, ui.work.active, a)
    if (ui.claims.waiting != null) ClaimsCard(ui.claims, ui.work.active, a)
    if (!ui.home.decisions && ui.claims.waiting == null) {
        CardBox {
            Text("Nothing for you here", fontWeight = FontWeight.Bold, color = Ink)
            Text("Decisions from SCMTIPS appear here for an approver; draft claims for a supervisor.", color = Muted, fontSize = 14.sp)
        }
    }
}
