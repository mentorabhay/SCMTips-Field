package com.scmtips.field.app.ui.shell

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.home.Link
import com.scmtips.field.app.jobs.Tone
import com.scmtips.field.app.shell.Capabilities
import com.scmtips.field.app.shell.FirstRun
import com.scmtips.field.app.shell.Home
import com.scmtips.field.app.shell.HomeChoice
import com.scmtips.field.app.shell.HomeMemory
import com.scmtips.field.app.shell.HomeRules
import com.scmtips.field.app.shell.PillTone
import com.scmtips.field.app.shell.ShellAction
import com.scmtips.field.app.shell.ShellNav
import com.scmtips.field.app.shell.ShellPage
import com.scmtips.field.app.shell.ShellText
import com.scmtips.field.app.shell.StatusPill
import com.scmtips.field.app.shell.Tab
import com.scmtips.field.app.ui.Actions
import com.scmtips.field.app.ui.CardBox
import com.scmtips.field.app.ui.CheckScreen
import com.scmtips.field.app.ui.ClaimReviewScreen
import com.scmtips.field.app.ui.Corner
import com.scmtips.field.app.ui.DecisionScreen
import com.scmtips.field.app.ui.EvidenceScreen
import com.scmtips.field.app.ui.JobScreen
import com.scmtips.field.app.ui.MinTouch
import com.scmtips.field.app.ui.Notice
import com.scmtips.field.app.ui.ScanScreen
import com.scmtips.field.app.ui.SecondaryButton
import com.scmtips.field.app.ui.SessionStrip
import com.scmtips.field.app.ui.StepUpDialog
import com.scmtips.field.app.ui.homes.JobNextUp
import com.scmtips.field.app.ui.kit.NextUp
import com.scmtips.field.app.ui.theme.AccentInk
import com.scmtips.field.app.ui.theme.Border
import com.scmtips.field.app.ui.theme.BrandGradientDiagonal
import com.scmtips.field.app.ui.theme.Ground
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.LocalReduceMotion
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Night
import com.scmtips.field.app.ui.theme.NightButton
import com.scmtips.field.app.ui.theme.NightMuted
import com.scmtips.field.app.ui.theme.Surface
import com.scmtips.field.app.ui.theme.Toast
import com.scmtips.field.app.ui.theme.WarnBg
import com.scmtips.field.app.ui.theme.WarnInk
import kotlinx.coroutines.delay
import java.util.Calendar

/** The full-screen task screens drawn over the shell without a tab bar, in the classic layout's order. */
internal enum class TaskKind { DECISIONS, CLAIMS, LOOK_EVIDENCE, CHECK_EVIDENCE, CHECK, JOB }

internal fun taskScreen(ui: AppUi): TaskKind? = when {
    ui.decisions.reviewing -> TaskKind.DECISIONS
    ui.claims.reviewing -> TaskKind.CLAIMS
    ui.look.evidenceUrl != null -> TaskKind.LOOK_EVIDENCE
    ui.check.evidenceUrl != null -> TaskKind.CHECK_EVIDENCE
    ui.check.open -> TaskKind.CHECK
    ui.job != null -> TaskKind.JOB
    else -> null
}

internal fun connected(ui: AppUi): Boolean = ui.signedIn != null || ui.pairing != null

/** What this account may do, from the state the app already has (docs/design/M5_UI_CONTRACT.md §2). */
internal fun capabilities(ui: AppUi): Capabilities =
    Capabilities(fieldOperator = ui.home.fieldWork, approver = ui.home.decisions, towerTasks = HomeRules.towerTasks(ui.tasks).isNotEmpty())

internal fun whoOf(ui: AppUi): String? = HomeMemory.who(ui.signedIn?.email, ui.signedIn?.name, ui.pairing?.apiBaseUrl, ui.pairing?.tenantId)

/**
 * M5-U01 shell: first run when not signed in or paired (and after a new sign-in until setup is finished), else a task
 * screen when one is open, else the Profile pages, else the role home and the other tabs over the tab bar.
 */
@Composable
fun ShellRoot(ui: AppUi, a: Actions) {
    val isConnected = connected(ui)
    val task = taskScreen(ui)
    val step = FirstRun.step(ui.shell, isConnected)
    val outPage = ShellNav.signedOutPage(ui.shell, isConnected)
    Box(Modifier.fillMaxSize().background(Ground).safeDrawingPadding()) {
        // First, so a screen's own BackHandler (job, check, evidence; builder B's) wins over this one.
        BackHandler(enabled = task == null && ShellNav.back(ui.shell, isConnected) != null) { a.shell(ShellAction.Back) }
        when {
            outPage != null -> ConnectionsPage(ui, a)
            step != null -> FirstRunContent(step, ui, a)
            task != null -> TaskScreens(task, ui, a)
            ui.shell.page != null -> when (ui.shell.page) {
                ShellPage.SETTINGS -> SettingsPage(ui, a)
                ShellPage.CONNECTIONS -> ConnectionsPage(ui, a)
                ShellPage.DIAGNOSTICS -> DiagnosticsPage(ui, a)
            }
            else -> Column(Modifier.fillMaxSize()) {
                Box(Modifier.weight(1f)) {
                    when (ui.shell.tab) {
                        Tab.HOME -> HomeTab(ui, a)
                        Tab.ACTIVITY -> ActivityTab(ui, a)
                        Tab.SCAN -> ScanScreen(ui, a)
                        Tab.INBOX -> InboxTab(ui, a)
                        Tab.PROFILE -> ProfileTab(ui, a)
                    }
                }
                ShellTabBar(ui.shell.tab, (ui.decisions.waiting ?: 0) + (ui.claims.waiting ?: 0), a)
            }
        }
        ui.decisions.stepUp?.let { ask -> StepUpDialog(ask.retryMessage, a) }
        ui.toast?.let { text ->
            LaunchedEffect(text) { delay(4_000); a.dismissToast() }
            Text(
                text, color = Color.White, fontSize = 15.sp,
                modifier = Modifier.align(Alignment.BottomCenter).padding(start = 16.dp, end = 16.dp, bottom = 100.dp)
                    .fillMaxWidth().background(Toast, Corner).padding(horizontal = 16.dp, vertical = 12.dp),
            )
        }
    }
}

@Composable
private fun TaskScreens(task: TaskKind, ui: AppUi, a: Actions) {
    Column(Modifier.fillMaxSize()) {
        if (ui.work.active) SessionStrip(ui.work, a)
        Box(Modifier.weight(1f)) {
            when (task) {
                TaskKind.DECISIONS -> DecisionScreen(ui, a, reduceMotion = LocalReduceMotion.current)
                TaskKind.CLAIMS -> ClaimReviewScreen(ui.claims, a)
                TaskKind.LOOK_EVIDENCE -> ui.look.evidenceUrl?.let { EvidenceScreen(it, a) }
                TaskKind.CHECK_EVIDENCE -> ui.check.evidenceUrl?.let { EvidenceScreen(it, a) }
                TaskKind.CHECK -> CheckScreen(ui.check, ui.work.active, a, reduceMotion = LocalReduceMotion.current)
                TaskKind.JOB -> ui.job?.let { v ->
                    JobScreen(
                        v, ui.audioOnly, a, look = ui.look.takeIf { l -> l.taskId != null }, reduceMotion = LocalReduceMotion.current,
                        // only this job's own look (a put-away after a receipt does not reopen the receipt's page)
                        onEvidence = a.reopenEvidence.takeIf { ui.look.evidenceSeenUrl != null && ui.look.taskId == ui.jobTaskId },
                        nextUp = JobNextUp.of(ui.tasks, ui.jobTaskId, v.practice, linked = ui.pairing != null)?.let { n ->
                            NextUp(n.title, n.sub) { a.openTask(n.taskId) }
                        },
                    )
                }
            }
        }
    }
}

/** The role home: the night header (switcher, status pill, greeting, headline), banners, then the home's content. */
@Composable
private fun HomeTab(ui: AppUi, a: Actions) {
    val caps = capabilities(ui)
    val who = whoOf(ui)
    val home = HomeMemory.current(ui.shell.savedHome, who, caps)
    val canAct = HomeRules.canAct(home, caps)
    Column(Modifier.fillMaxSize()) {
        HomeHeader(ui, home, HomeRules.choices(caps), canAct) { h -> a.shell(ShellAction.PickHome(h, who)) }
        Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            HomeRules.viewOnlyBanner(home, caps)?.let { ViewOnlyBanner(it) }
            ConnectionProblem(ui, a)
        }
        Box(Modifier.weight(1f)) { HomeContent(home, ui, a, canAct) }
    }
}

@Composable
private fun HomeHeader(ui: AppUi, home: Home, choices: List<HomeChoice>, canAct: Boolean, onPick: (Home) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val pill = StatusPill.of(
        offline = ui.link == Link.OFFLINE, connecting = ui.connecting || (ui.link == Link.CONNECTING && ui.pairing != null),
        glassesReady = ui.glassesAdvice.ready, sandbox = ui.sandbox,
    )
    val name = ui.signedIn?.name ?: ui.person.name
    Column(Modifier.fillMaxWidth().background(Night).padding(start = 20.dp, end = 20.dp, top = 20.dp, bottom = 20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.weight(1f, fill = false)) {
                Row(
                    Modifier.heightIn(min = MinTouch).background(NightButton, RoundedCornerShape(24.dp))
                        .clickable(role = Role.Button) { open = true }.padding(horizontal = 14.dp)
                        .semantics { contentDescription = "Working as ${home.label}. Switch home" },
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("Working as ${home.label}", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("▾", color = Color.White, fontSize = 14.sp)
                }
                DropdownMenu(expanded = open, onDismissRequest = { open = false }, modifier = Modifier.background(Surface)) {
                    choices.forEach { c ->
                        DropdownMenuItem(
                            text = {
                                Column(Modifier.widthIn(min = 200.dp)) {
                                    Text(c.home.menuLabel, fontWeight = FontWeight.SemiBold, color = Ink, fontSize = 16.sp)
                                    Text(c.badge, fontSize = 13.sp, color = if (c.canAct) com.scmtips.field.app.ui.theme.Good else Muted)
                                }
                            },
                            onClick = { open = false; onPick(c.home) },
                            modifier = Modifier.heightIn(min = 56.dp).semantics { selected = c.home == home }
                                .let { if (c.home == home) it.background(com.scmtips.field.app.ui.theme.AccentTint) else it },
                        )
                    }
                }
            }
            StatusPillView(pill)
        }
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            val hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
            Text(listOfNotNull("${ShellText.greeting(hour)}, $name", ui.pairing?.siteName).joinToString(" · "),
                color = NightMuted, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                HomeRules.headline(home, HomeRules.warehouseTasks(ui.tasks).size, HomeRules.towerTasks(ui.tasks).size,
                    ui.decisions.waiting, ui.claims.waiting, canAct),
                color = Color.White, fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold,
            )
        }
    }
}

@Composable
private fun StatusPillView(p: StatusPill) {
    val (bg, fg, dot) = when (p.tone) {
        PillTone.GOOD -> Triple(Color(0xFF12301F), Color(0xFF86EFAC), Color(0xFF4ADE80))
        PillTone.NEUTRAL -> Triple(NightButton, NightMuted, NightMuted)
        PillTone.WARN -> Triple(Color(0xFF3B2A12), Color(0xFFFCD34D), Color(0xFFF59E0B))
    }
    val still = LocalReduceMotion.current || !p.live
    val blink = if (still) 1f else {
        val t = rememberInfiniteTransition(label = "pill")
        t.animateFloat(1f, 0.35f, infiniteRepeatable(tween(1_000), RepeatMode.Reverse), label = "dot").value
    }
    Row(Modifier.height(32.dp).background(bg, RoundedCornerShape(16.dp)).padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(Modifier.size(8.dp).alpha(blink).background(dot, CircleShape))
        Text(p.text, color = fg, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
    }
}

@Composable
private fun ViewOnlyBanner(text: String) {
    Text(text, color = WarnInk, fontSize = 14.sp, lineHeight = 20.sp,
        modifier = Modifier.fillMaxWidth().background(WarnBg, Corner).border(1.dp, Color(0xFFFED7AA), Corner).padding(horizontal = 14.dp, vertical = 12.dp))
}

/** The field server could not be reached or refused this phone: the reason, Try again, and the PC code path. */
@Composable
private fun ConnectionProblem(ui: AppUi, a: Actions) {
    val why = ui.connectError ?: return
    if (ui.connecting) return
    CardBox {
        Notice(why, Tone.BAD)
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(top = 6.dp)) {
            SecondaryButton("Try again", a.retryConnect, Modifier.weight(1f))
            if (ui.signedIn == null) SecondaryButton("Scan the code", a.scanPairingCode, Modifier.weight(1f))
        }
    }
}

/** Home · Activity · Scan (centre, raised, gradient) · Inbox · Profile (TabBar.dc.html). */
@Composable
private fun ShellTabBar(current: Tab, inbox: Int, a: Actions) {
    Box(Modifier.fillMaxWidth().height(1.dp).background(Border))
    Row(Modifier.fillMaxWidth().background(Surface).padding(start = 4.dp, end = 4.dp, top = 6.dp, bottom = 10.dp),
        verticalAlignment = Alignment.Bottom) {
        Tab.entries.forEach { t ->
            val on = t == current
            val color = if (on) AccentInk else Muted
            Column(
                Modifier.weight(1f).heightIn(min = 52.dp).clickable(role = Role.Tab) { a.shell(ShellAction.SelectTab(t)) }
                    .semantics { selected = on; role = Role.Tab; contentDescription = if (t == Tab.INBOX && inbox > 0) "Inbox, $inbox waiting" else t.title },
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp, Alignment.Bottom),
            ) {
                if (t == Tab.SCAN) {
                    Box(
                        Modifier.offset(y = (-8).dp).size(60.dp).background(Surface, CircleShape).padding(4.dp)
                            .background(BrandGradientDiagonal, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) { TabGlyph(t, Color.White, 26.dp) }
                } else {
                    Box {
                        TabGlyph(t, color)
                        if (t == Tab.INBOX && inbox > 0) {
                            Text(if (inbox > 99) "99+" else "$inbox", color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                                modifier = Modifier.offset(x = 14.dp, y = (-6).dp).background(com.scmtips.field.app.ui.theme.BrandEnd, RoundedCornerShape(9.dp))
                                    .padding(horizontal = 5.dp))
                        }
                    }
                }
                Text(t.title, color = if (t == Tab.SCAN) (if (on) AccentInk else Ink) else color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}
