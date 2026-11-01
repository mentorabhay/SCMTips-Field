package com.scmtips.field.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.home.Link
import com.scmtips.field.app.home.SandboxStart
import com.scmtips.field.app.home.SandboxStarters
import com.scmtips.field.app.home.TaskCard
import com.scmtips.field.app.home.TodayModel
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
 * Today: who you are, connection and scanner, the work session (M3: "Start work" is the main action;
 * the glasses lead from there), jobs assigned to you (the phone fallback), then anything you can start.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun TodayScreen(ui: AppUi, a: Actions) {
    val cards = ui.tasks.map(TodayModel::card)
    var askShelf by remember { mutableStateOf(false) }
    if (askShelf) CountShelfDialog(onStart = { bin -> askShelf = false; a.startSandbox(SandboxStart.COUNT_SHELF, bin) }, onDismiss = { askShelf = false })
    val sandbox = SandboxStarters.offered(ui.sandbox && ui.home.fieldWork && ui.pairing != null)
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(start = 20.dp, end = 20.dp, top = 20.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Avatar(ui.person.initials)
                    Column(Modifier.weight(1f)) {
                        Text(listOfNotNull(ui.person.name, ui.pairing?.siteName).joinToString(" · "), color = Muted, fontSize = 14.sp,
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text("Your work today", fontSize = 26.sp, fontWeight = FontWeight.Bold, color = Ink, lineHeight = 30.sp)
                    }
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    when (ui.link) {
                        Link.ONLINE -> Chip(ui.link.text, SuccessBg, SuccessInk, dot = Success)
                        Link.OFFLINE -> Chip(ui.link.text, WarnBg, WarnInk, dot = WarnText)
                        Link.CONNECTING -> Chip(ui.link.text, CardBg, Ink2, line = Line)
                    }
                    Chip("Scanning with: ${ui.scanner.label}", CardBg, Ink2, line = Line)
                    if (ui.visitId != null) Chip("On site · checked in", InfoBg, Primary)
                    if (ui.glassesAdvice.ready) Chip("Glasses ready", InfoBg, Primary)
                    if (ui.sandbox) Chip("Sandbox site", WarnBg, WarnInk)
                }
            }
        }
        if (ui.home.decisions) item { DecisionsCard(ui.decisions, ui.work.active, a) }
        if (ui.claims.waiting != null) item { ClaimsCard(ui.claims, ui.work.active, a) }
        // M5-T05: any Field role may check a box (field.authenticity.check); the server's 403 hides the card.
        if (com.scmtips.field.app.check.CheckText.cardVisible(ui.pairing != null && ui.deviceId != null, ui.check.allowed)) {
            item { CheckBoxCard(ui.work.active, a) }
        }
        item { WorkCard(ui.work, ui.glasses.session == "STARTED", a) }
        // M5: the two test cases first on a sandbox site (contract §1), above the rest of the list.
        val cases = com.scmtips.field.app.home.CaseStart.offered(ui.sandbox && ui.home.fieldWork && ui.pairing != null)
        if (cases.isNotEmpty()) item { CaseStarterCards(cases, ui.work.active, a) }
        if (ui.home.fieldWork && ui.pairing == null) {
            item {
                CardBox {
                    Text(if (ui.connecting) "Connecting to the SCMTips Field server…" else "No field site linked", fontWeight = FontWeight.Bold, color = Ink)
                    Text(ui.connectError ?: "Your jobs appear here once the field server knows your site.", color = Muted, fontSize = 14.sp)
                }
            }
        }
        if (ui.home.fieldWork && ui.pairing != null) item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Assigned to you", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted, modifier = Modifier.weight(1f))
                if (ui.loading) CircularProgressIndicator(Modifier.size(20.dp), color = Primary, strokeWidth = 2.dp)
                else SmallButton("Refresh", a.refresh)
            }
        }
        if (ui.home.fieldWork && ui.pairing != null && cards.isEmpty()) {
            item {
                CardBox {
                    Text("Nothing assigned to you right now.", fontWeight = FontWeight.Bold, color = Ink)
                    Text(
                        if (sandbox.isNotEmpty()) "This is a sandbox site: start a new home receipt or count a shelf right here."
                        else "New jobs appear here by themselves. You can also start a practice task in Me.",
                        color = Muted, fontSize = 14.sp,
                    )
                    if (sandbox.isNotEmpty()) {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(top = 6.dp)) {
                            PrimaryButton(SandboxStart.HOME_RECEIPT.label, { a.startSandbox(SandboxStart.HOME_RECEIPT, null) }, Modifier.weight(1f), height = 52.dp)
                            SecondaryButton(SandboxStart.COUNT_SHELF.label, { askShelf = true }, Modifier.weight(1f))
                        }
                    }
                }
            }
        }
        if (ui.home.fieldWork && ui.pairing != null) items(cards, key = { it.taskId }) { c -> TaskCardRow(c) { a.openTask(c.taskId) } }
        if (ui.home.fieldWork && ui.pairing != null) item {
            Text("Start something else", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted, modifier = Modifier.padding(top = 8.dp))
        }
        if (sandbox.isNotEmpty()) item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                sandbox.forEach { st ->
                    Column(
                        Modifier.weight(1f).heightIn(min = 64.dp).background(WarnBg, Corner).border(1.dp, Line, Corner)
                            .clickable(role = Role.Button) {
                                if (st == SandboxStart.COUNT_SHELF) askShelf = true else a.startSandbox(st, null)
                            }.padding(14.dp),
                    ) {
                        Text(st.label, fontWeight = FontWeight.Bold, color = Ink)
                        Text(st.sub, fontSize = 13.sp, color = Muted)
                    }
                }
            }
        }
        if (ui.home.fieldWork && ui.pairing != null) item {
            val starters = TodayModel.starters(ui.tasks)
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                starters.chunked(2).forEach { pair ->
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        pair.forEach { s ->
                            Box(
                                Modifier.weight(1f).heightIn(min = 64.dp).background(CardBg, Corner).border(1.dp, Line, Corner)
                                    .clickable(role = Role.Button) { a.openStarter(s.type) }.padding(14.dp),
                                contentAlignment = Alignment.CenterStart,
                            ) { Text(s.label, fontWeight = FontWeight.Bold, color = if (s.taskId != null) Ink else Muted) }
                        }
                        if (pair.size == 1) Box(Modifier.weight(1f))
                    }
                }
            }
        }
    }
}

@Composable
private fun TaskCardRow(c: TaskCard, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().background(CardBg, Corner).border(1.dp, Line, Corner)
            .clickable(role = Role.Button, onClick = onClick).padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(Modifier.size(44.dp).background(if (c.warm) WarnBg else InfoBg, Corner), contentAlignment = Alignment.Center) {
            Text(c.badge, color = if (c.warm) WarnText else Primary, fontWeight = FontWeight.Bold, fontSize = 15.sp)
        }
        Column(Modifier.weight(1f)) {
            Text(c.title, fontWeight = FontWeight.Bold, color = Ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(c.sub, fontSize = 14.sp, color = Muted, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        c.flag?.let {
            Text(it, fontSize = 12.sp, fontWeight = FontWeight.Bold, color = WarnInk,
                modifier = Modifier.background(WarnBg, androidx.compose.foundation.shape.RoundedCornerShape(999.dp)).padding(horizontal = 8.dp, vertical = 3.dp))
        }
    }
}
