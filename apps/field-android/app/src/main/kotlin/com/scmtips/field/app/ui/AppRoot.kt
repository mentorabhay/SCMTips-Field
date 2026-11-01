package com.scmtips.field.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.check.CheckAction
import com.scmtips.field.app.home.CaseStart
import com.scmtips.field.app.home.SandboxStart
import com.scmtips.field.feature.decisions.api.SignInMethod
import com.scmtips.field.feature.decisions.api.StepUpMethod
import com.scmtips.field.app.jobs.JobAction
import com.scmtips.field.app.jobs.JobType
import com.scmtips.field.app.jobs.ScannerKind
import com.scmtips.field.app.navigation.Screen
import com.scmtips.field.app.shell.PermissionStep
import com.scmtips.field.app.shell.ShellAction
import com.scmtips.field.app.ui.shell.ShellRoot
import com.scmtips.field.app.ui.theme.LocalReduceMotion
import androidx.compose.runtime.CompositionLocalProvider
import com.scmtips.field.app.ui.theme.Background
import com.scmtips.field.app.ui.theme.CardBg
import com.scmtips.field.app.ui.theme.Line
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Primary
import com.scmtips.field.app.ui.theme.Toast
import kotlinx.coroutines.delay

/** Everything the screens can ask for; MainActivity binds these to the controller and the platform. */
class Actions(
    val scanPairingCode: () -> Unit,
    val retryConnect: () -> Unit,
    val unpair: () -> Unit,
    val tab: (Screen) -> Unit,
    val refresh: () -> Unit,
    val openTask: (String) -> Unit,
    val openStarter: (JobType) -> Unit,
    val job: (JobAction) -> Unit,
    val scan: () -> Unit,
    val manualCode: (String) -> Unit,
    val manualEntryOpen: (Boolean) -> Unit,
    val talkStart: () -> Unit,
    val talkStop: () -> Unit,
    val startLocation: () -> Unit,
    val stopLocation: () -> Unit,
    val cycleScanner: () -> Unit,
    val nextSite: () -> Unit = {},
    val glassesSetUp: () -> Unit,
    val toggleGlassesMic: () -> Unit,
    val toggleAudioOnly: () -> Unit,
    val languageInfo: () -> Unit,
    val startPractice: () -> Unit,
    val sendFeedback: () -> Unit,
    val dismissToast: () -> Unit,
    /** M3 work session: Today's "Start work" (microphone permission first), stop, pause, resume. */
    val startWork: () -> Unit = {},
    val stopWork: () -> Unit = {},
    val pauseWork: () -> Unit = {},
    val resumeWork: () -> Unit = {},
    /** M4 F2: sign in against the SCMTIPS core (method, core address, field server address). */
    val signIn: (SignInMethod, String, String) -> Unit = { _, _, _ -> },
    /** M4 F1: the approver flow. */
    val startReview: () -> Unit = {},
    val stopReview: () -> Unit = {},
    val refreshDecisions: () -> Unit = {},
    val decisionButton: (String) -> Unit = {},
    val answerStepUp: (StepUpMethod, String?) -> Unit = { _, _ -> },
    /** M3 fix: Today's sandbox starters (a home receipt; a shelf count with its bin). */
    val startSandbox: (SandboxStart, String?) -> Unit = { _, _ -> },
    val toggleAttentionWord: () -> Unit = {},
    /** M5 look and act: the Look button, a claim, photo consent, the evidence page. */
    val look: () -> Unit = {},
    val makeClaim: () -> Unit = {},
    val agreePhotos: () -> Unit = {},
    val closeEvidence: () -> Unit = {},
    /** M5: Today's case starters (grocery, pharmacy). */
    val startCase: (CaseStart) -> Unit = {},
    /** M5: supervisors' claims review. */
    val startClaims: () -> Unit = {},
    val stopClaims: () -> Unit = {},
    val refreshClaims: () -> Unit = {},
    val claimButton: (String) -> Unit = {},
    /** M5: Me → Test glasses camera (G0-5), its Upload (true: after agreeing to photos) and Close. */
    val testCamera: () -> Unit = {},
    val uploadProbe: (Boolean) -> Unit = {},
    val closeProbe: () -> Unit = {},
    /** M5-T05: the C3 box check (Today's card, the check card's buttons). */
    val check: (CheckAction) -> Unit = {},
    /** M5-U01: the shell's navigation (first run, tabs, pages, role switcher, classic layout); rules in ShellNav. */
    val shell: (ShellAction) -> Unit = {},
    /** M5-U01: open a web page (the SCMTIPS reset and sign-up pages) with Intent.ACTION_VIEW. */
    val openUrl: (String) -> Unit = {},
    /** M5-U01: first run's Permissions step "Allow". */
    val requestPermission: (PermissionStep) -> Unit = {},
    /** M5-U01/U05: pick a listed site (first run's Site and role, Profile). */
    val chooseSite: (String) -> Unit = {},
    /** M5-U05: Settings › Scanning with. */
    val setScanner: (ScannerKind) -> Unit = {},
    /** M5-U05: Settings › Connections while signed out (SCMTIPS address, field server address). */
    val setServers: (String, String) -> Unit = { _, _ -> },
)

/**
 * The app's root: the M5-U shell (first run, role homes, tab bar, profile pages; ui/shell/ShellRoot.kt), or the
 * old Connect / Today · Scan · Me screens exactly as before when Settings › Diagnostics › Classic layout is on.
 */
@Composable
fun AppRoot(ui: AppUi, a: Actions) {
    CompositionLocalProvider(LocalReduceMotion provides ui.shell.reduceMotion) {
        if (ui.shell.classic) ClassicRoot(ui, a) else ShellRoot(ui, a)
    }
}

/** The M2 to M5 layout, unchanged (the owner's safety net until the redesign passes his device test). */
@Composable
fun ClassicRoot(ui: AppUi, a: Actions) {
    Box(Modifier.fillMaxSize().background(Background).safeDrawingPadding()) {
        val job = ui.job
        val signed = ui.signedIn
        when {
            // Signed in as an approver: the app is usable at once (field work joins when field-api answers).
            signed == null && (ui.pairing == null || ui.deviceId == null) -> ConnectScreen(ui, a)
            signed != null && !signed.approver && ui.deviceId == null -> ConnectScreen(ui, a)
            ui.decisions.reviewing -> Column(Modifier.fillMaxSize()) {
                if (ui.work.active) SessionStrip(ui.work, a)
                Box(Modifier.weight(1f)) { DecisionScreen(ui, a) }
            }
            ui.claims.reviewing -> Column(Modifier.fillMaxSize()) {
                if (ui.work.active) SessionStrip(ui.work, a)
                Box(Modifier.weight(1f)) { ClaimReviewScreen(ui.claims, a) }
            }
            ui.look.evidenceUrl != null -> Column(Modifier.fillMaxSize()) {
                if (ui.work.active) SessionStrip(ui.work, a)
                Box(Modifier.weight(1f)) { EvidenceScreen(ui.look.evidenceUrl, a) }
            }
            // M5-T05: a box check's evidence page, then its card (over an open job: no task is needed for a check).
            ui.check.evidenceUrl != null -> Column(Modifier.fillMaxSize()) {
                if (ui.work.active) SessionStrip(ui.work, a)
                Box(Modifier.weight(1f)) { EvidenceScreen(ui.check.evidenceUrl, a) }
            }
            ui.check.open -> Column(Modifier.fillMaxSize()) {
                if (ui.work.active) SessionStrip(ui.work, a)
                Box(Modifier.weight(1f)) { CheckScreen(ui.check, ui.work.active, a) }
            }
            job != null -> Column(Modifier.fillMaxSize()) {
                if (ui.work.active) SessionStrip(ui.work, a)
                Box(Modifier.weight(1f)) { JobScreen(job, ui.audioOnly, a, look = ui.look.takeIf { it.taskId != null }) }
            }
            else -> Column(Modifier.fillMaxSize()) {
                Box(Modifier.weight(1f)) {
                    when (ui.tab) {
                        Screen.Scan -> ScanScreen(ui, a)
                        Screen.Me -> MeScreen(ui, a)
                        else -> TodayScreen(ui, a)
                    }
                }
                TabBar(ui.tab, a)
            }
        }
        ui.decisions.stepUp?.let { ask -> StepUpDialog(ask.retryMessage, a) }
        ui.toast?.let { text ->
            LaunchedEffect(text) { delay(4_000); a.dismissToast() }
            Text(
                text, color = Color.White, fontSize = 15.sp,
                modifier = Modifier.align(Alignment.BottomCenter).padding(start = 16.dp, end = 16.dp, bottom = 92.dp)
                    .fillMaxWidth().background(Toast, Corner).padding(horizontal = 16.dp, vertical = 12.dp),
            )
        }
    }
}

@Composable
private fun TabBar(current: Screen, a: Actions) {
    Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
    Row(Modifier.fillMaxWidth().background(CardBg).padding(start = 8.dp, end = 8.dp, top = 6.dp, bottom = 10.dp)) {
        Screen.tabs.forEach { t ->
            val on = t == current
            TextButton(
                onClick = { a.tab(t) },
                modifier = Modifier.weight(1f).heightIn(min = 52.dp).semantics { selected = on; role = Role.Tab },
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Box(Modifier.width(28.dp).height(4.dp).background(if (on) Primary else Color.Transparent, RoundedCornerShape(2.dp)))
                    Text(t.title, color = if (on) Primary else Muted, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}
