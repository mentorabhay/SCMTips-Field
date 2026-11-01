package com.scmtips.field.app.ui.shell

import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.BuildConfig
import com.scmtips.field.app.home.Link
import com.scmtips.field.app.shell.PillTone
import com.scmtips.field.app.shell.ShellAction
import com.scmtips.field.app.shell.ShellPage
import com.scmtips.field.app.shell.ShellText
import com.scmtips.field.app.ui.Actions
import com.scmtips.field.app.ui.ButtonShape
import com.scmtips.field.app.ui.CameraTestCard
import com.scmtips.field.app.ui.CardBox
import com.scmtips.field.app.ui.MinTouch
import com.scmtips.field.app.ui.PrimaryButton
import com.scmtips.field.app.ui.SecondaryButton
import com.scmtips.field.app.ui.theme.AccentInk
import com.scmtips.field.app.ui.theme.AccentTint
import com.scmtips.field.app.ui.theme.BrandGradientDiagonal
import com.scmtips.field.app.ui.theme.Danger
import com.scmtips.field.app.ui.theme.Good
import com.scmtips.field.app.ui.theme.Ground
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Ink2
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Surface
import com.scmtips.field.app.ui.theme.Warning

/** M5-U05 Profile (Profile.dc.html): who, roles, site, glasses, Settings, Help, Sign out. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ProfileTab(ui: AppUi, a: Actions) {
    var sites by remember { mutableStateOf(false) }
    var help by remember { mutableStateOf(false) }
    val signed = ui.signedIn
    val name = signed?.name ?: ui.person.name
    if (sites) SiteDialog(ui, onPick = { id -> sites = false; a.chooseSite(id) }, onDismiss = { sites = false })
    if (help) HelpDialog(onPractice = { help = false; a.startPractice() }, onDismiss = { help = false })
    Scroll {
        Column(Modifier.fillMaxWidth().padding(top = 24.dp, bottom = 8.dp), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(Modifier.size(84.dp).background(BrandGradientDiagonal, CircleShape), contentAlignment = Alignment.Center) {
                Text(ui.person.initials, color = Color.White, fontSize = 30.sp, fontWeight = FontWeight.Bold)
            }
            Text(name, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Ink, textAlign = TextAlign.Center)
            signed?.email?.let { Text(it, fontSize = 15.sp, color = Muted) }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                ShellText.roleChips(approver = ui.home.decisions, fieldOperator = ui.home.fieldWork, signedIn = signed != null).forEach {
                    Text(it, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = AccentInk,
                        modifier = Modifier.background(AccentTint, RoundedCornerShape(10.dp)).padding(horizontal = 10.dp, vertical = 4.dp))
                }
            }
        }
        Group {
            val site = (ui.pairing?.siteName ?: "No field site") + if (ui.sandbox) " · sandbox" else ""
            NavRow("Site", site, action = if (signed != null && ui.sites.size > 1) "Change" else null,
                onClick = if (signed != null && ui.sites.size > 1) ({ sites = true }) else null)
            NavRow("Glasses", "Ray-Ban Meta Gen 2 · ${ui.glassesAdvice.text}", action = ui.glassesAdvice.button ?: "Manage",
                onClick = if (ui.glassesAdvice.button != null) a.glassesSetUp else ({ a.shell(ShellAction.Open(ShellPage.CONNECTIONS)) }), last = true)
        }
        Group {
            NavRow("Settings", "Glasses and voice, scanning, privacy, connections", onClick = { a.shell(ShellAction.Open(ShellPage.SETTINGS)) })
            NavRow("Help and practice", "Talking to the glasses; a practice task", onClick = { help = true }, last = true)
        }
        SecondaryButton(if (signed != null) "Sign out" else "Disconnect from the PC", a.unpair, ink = Danger, line = Color(0xFFF3C4C0))
    }
}

@Composable
private fun SiteDialog(ui: AppUi, onPick: (String) -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close", color = AccentInk) } },
        title = { Text("Where are you working?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                ui.sites.forEach { s ->
                    val on = s.id == ui.pairing?.siteId
                    Text(s.name + if (s.mode == com.scmtips.field.app.assistant.SiteModes.SANDBOX) " · sandbox" else "",
                        fontWeight = if (on) FontWeight.Bold else FontWeight.Normal, color = if (on) AccentInk else Ink, fontSize = 16.sp,
                        modifier = Modifier.fillMaxWidth().heightIn(min = MinTouch).clickable(role = Role.RadioButton) { onPick(s.id) }
                            .semantics { selected = on }.padding(vertical = 12.dp))
                }
            }
        },
    )
}

@Composable
private fun HelpDialog(onPractice: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onPractice) { Text("Start a practice task", color = AccentInk, fontWeight = FontWeight.Bold) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Close", color = Muted) } },
        title = { Text("Talking to the glasses") },
        text = {
            Text("During a work session the glasses' microphone hears you; just speak (or start with “Field” when the attention word is on). " +
                "“Hey Meta” is Meta's own wake word: the glasses hand it to Meta AI before this app hears anything, so it cannot be used for " +
                "SCMTips Field commands. Where Meta AI supports it, “Hey Meta, start SCMTips Field” opens this app at your decisions.\n\n" +
                "A practice task sends nothing to SAP.", fontSize = 15.sp, color = Ink2)
        },
    )
}

/** M5-U05 Settings (Settings.dc.html): glasses and voice, scanning with, privacy and data, advanced. */
@Composable
internal fun SettingsPage(ui: AppUi, a: Actions) = Column(Modifier.fillMaxSize().background(Ground)) {
    PageHeader("Settings") { a.shell(ShellAction.Back) }
    Scroll {
        SectionLabel("Glasses and voice")
        Group {
            ToggleRow("Glasses microphone", if (ui.glassesSpeech) "The glasses listen during a work session" else "A work session uses the phone's recogniser",
                ui.glassesSpeech, a.toggleGlassesMic)
            ToggleRow("Attention word", "Only what starts with “Field” is acted on, like “Field, next”", ui.attentionWord, a.toggleAttentionWord)
            ToggleRow("Audio only", "Prompts are spoken, never shown", ui.audioOnly, a.toggleAudioOnly)
            NavRow("Language", "English · Hindi is coming", onClick = a.languageInfo, last = true)
        }
        SectionLabel("Scanning with")
        Row(Modifier.fillMaxWidth().background(Color(0xFFE9EBEF), ButtonShape).padding(4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            ShellText.scannerChoices.forEach { (k, label) ->
                val on = ui.scanner == k
                Box(
                    Modifier.weight(1f).heightIn(min = MinTouch).background(if (on) Surface else Color.Transparent, RoundedCornerShape(11.dp))
                        .clickable(role = Role.RadioButton) { a.setScanner(k) }.semantics { selected = on },
                    contentAlignment = Alignment.Center,
                ) { Text(label, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = Ink) }
            }
        }
        Text(ui.scanner.howTo, fontSize = 13.sp, color = Muted, modifier = Modifier.padding(start = 4.dp))
        SectionLabel("Privacy and data")
        CardBox {
            Text("Voice text and photos are kept 30 days. Faces are blurred before any photo leaves the phone. " +
                "The microphone listens only during a work session.", fontSize = 14.sp, color = Ink2, lineHeight = 20.sp)
        }
        SectionLabel("Advanced")
        Group {
            NavRow("Connections", "Servers, PC pairing code, camera test", onClick = { a.shell(ShellAction.Open(ShellPage.CONNECTIONS)) })
            NavRow("Diagnostics", "Classic layout, app log, send feedback, version ${BuildConfig.VERSION_NAME}",
                onClick = { a.shell(ShellAction.Open(ShellPage.DIAGNOSTICS)) }, last = true)
        }
    }
}

/**
 * M5-U05 Connections (Connections.dc.html): the two server addresses (read only while connected, editable when signed
 * out), pairing with a PC code, and the glasses camera test.
 */
@Composable
internal fun ConnectionsPage(ui: AppUi, a: Actions) = Column(Modifier.fillMaxSize().background(Ground)) {
    PageHeader("Connections") { a.shell(ShellAction.Back) }
    Scroll {
        val connectedNow = connected(ui)
        SectionLabel("Servers")
        if (connectedNow) {
            val (state, tone) = ShellText.serverState(ui.connecting, ui.link == Link.OFFLINE, ui.connectError != null, ui.deviceId != null)
            val color = when (tone) { PillTone.GOOD -> Good; PillTone.WARN -> Warning; PillTone.NEUTRAL -> Muted }
            Group {
                if (ui.signedIn != null) ServerRow("SCMTIPS address", ui.signedIn.coreBaseUrl, "Signed in", Good)
                ServerRow("SCMTips Field server", ui.pairing?.apiBaseUrl ?: ui.signIn.fieldUrl, state, color, last = true)
            }
            Text("Sign out to change the servers.", fontSize = 13.sp, color = Muted, modifier = Modifier.padding(start = 4.dp))
        } else {
            var core by rememberSaveable(ui.signIn.coreUrl) { mutableStateOf(ui.signIn.coreUrl) }
            var field by rememberSaveable(ui.signIn.fieldUrl) { mutableStateOf(ui.signIn.fieldUrl) }
            CardBox {
                OutlinedTextField(core, { core = it.trim() }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("SCMTIPS address") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
                OutlinedTextField(field, { field = it.trim() }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("SCMTips Field server address") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
                PrimaryButton("Save", { a.setServers(core, field) }, Modifier.padding(top = 6.dp), height = 52.dp,
                    enabled = core != ui.signIn.coreUrl || field != ui.signIn.fieldUrl)
            }
        }
        SectionLabel("Pair with a PC")
        CardBox {
            Text("For the local test stack: scan the code START FIELD TEST shows on the PC " +
                "(scripts\\dev\\run-field-stack.cmd in the SCMTips-Field folder).", fontSize = 14.sp, color = Ink2)
            if (ui.signedIn == null && ui.pairing != null) Text("Paired with ${ui.pairing.siteName}.", fontSize = 14.sp, color = Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(top = 6.dp)) {
                PrimaryButton("Scan code", a.scanPairingCode, Modifier.weight(1f), bg = Ink, height = 52.dp, enabled = !ui.connecting && !ui.signIn.busy)
                if (ui.signedIn == null && ui.pairing != null && !ui.connecting) SecondaryButton("Try again", a.retryConnect, Modifier.weight(1f))
            }
        }
        SectionLabel("Glasses camera")
        CameraTestCard(ui.probe, a)
    }
}

@Composable
private fun ServerRow(label: String, url: String, state: String, color: Color, last: Boolean = false) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp)) {
        Row(Modifier.fillMaxWidth()) {
            Text(label, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Ink, modifier = Modifier.weight(1f))
            Text(state, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = color)
        }
        Text(url, fontSize = 15.sp, color = Ink2, fontFamily = FontFamily.Monospace)
    }
    if (!last) RowLine()
}

/** M5-U05 Diagnostics: the classic layout switch, the app log, send feedback, the version. */
@Composable
internal fun DiagnosticsPage(ui: AppUi, a: Actions) = Column(Modifier.fillMaxSize().background(Ground)) {
    var showLog by remember { mutableStateOf(false) }
    PageHeader("Diagnostics") { a.shell(ShellAction.Back) }
    Scroll {
        Group {
            ToggleRow("Classic layout", "The old three tabs, until the new layout passes testing", ui.shell.classic,
                { a.shell(ShellAction.Classic(!ui.shell.classic)) })
            NavRow("App log", "${ui.log.size} lines on this phone", action = if (showLog) "Hide" else "Show", onClick = { showLog = !showLog })
            NavRow("Send feedback", "With the app log", onClick = a.sendFeedback)
            NavRow("Version", BuildConfig.VERSION_NAME, onClick = null, last = true)
        }
        if (showLog) {
            CardBox {
                if (ui.log.isEmpty()) Text("Nothing yet.", color = Muted)
                ui.log.takeLast(60).forEach { Text(it, fontSize = 12.sp, fontFamily = FontFamily.Monospace, color = Ink) }
            }
        }
    }
}
