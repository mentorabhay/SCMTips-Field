package com.scmtips.field.app.ui

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.ui.theme.CardBg
import com.scmtips.field.app.ui.theme.Divider
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Line
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Primary

/** Me and this phone: connection, scanner, glasses, language, audio-only, practice and feedback. */
@Composable
fun MeScreen(ui: AppUi, a: Actions) {
    var showLog by remember { mutableStateOf(false) }
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(start = 20.dp, end = 20.dp, top = 24.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Me and this phone", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink, lineHeight = 32.sp)
        Column(Modifier.fillMaxWidth().background(CardBg, Corner).border(1.dp, Line, Corner)) {
            val signed = ui.signedIn
            if (signed != null) {
                SettingRow("Signed in to SCMTIPS", listOfNotNull(signed.name, signed.email, ui.pairing?.siteName).joinToString(" · ") +
                    "\n" + listOfNotNull("decisions".takeIf { signed.approver }, "field work".takeIf { signed.fieldOperator }).ifEmpty { listOf("no app roles") }
                        .joinToString(" and ").replaceFirstChar { it.uppercase() }, "Sign out", a.unpair)
                if (ui.sites.size > 1) {
                    SettingRow("Site", "${ui.pairing?.siteName ?: "—"}${if (ui.sandbox) " · sandbox" else ""} · ${ui.sites.size} sites", "Change", a.nextSite)
                }
            } else {
                SettingRow("Connected to", "${ui.pairing?.siteName ?: "—"} · ${ui.person.name}", "Change", a.unpair)
            }
            SettingRow("Scanning with", ui.scanner.label, "Change", a.cycleScanner)
            SettingRow("Smart glasses", "Ray-Ban Meta Gen 2 · ${ui.glassesAdvice.text}", ui.glassesAdvice.button, a.glassesSetUp)
            SettingRow("Glasses microphone", if (ui.glassesSpeech) "On · the glasses listen during a work session" else "Off · a work session uses the phone's recogniser",
                if (ui.glassesSpeech) "Turn off" else "Turn on", a.toggleGlassesMic)
            SettingRow("Attention word", if (ui.attentionWord) "On · only what starts with “Field” is acted on, like “Field, next”"
                else "Off · everything said in a work session is heard", if (ui.attentionWord) "Turn off" else "Turn on", a.toggleAttentionWord)
            SettingRow("Language", "English · Hindi is coming", "Change", a.languageInfo)
            SettingRow("Audio-only mode", if (ui.audioOnly) "On · prompts are spoken, never shown" else "Off",
                if (ui.audioOnly) "Turn off" else "Turn on", a.toggleAudioOnly, last = true)
        }
        CameraTestCard(ui.probe, a)
        CardBox {
            Text("Talking to the glasses", fontWeight = FontWeight.Bold, color = Ink)
            Text("During a work session the glasses' microphone hears you; just speak (or start with “Field” when the attention word is on). " +
                "“Hey Meta” is Meta's own wake word: the glasses hand it to Meta AI before this app hears anything, so it cannot be used for " +
                "SCMTips Field commands. Where Meta AI supports it, “Hey Meta, start SCMTips Field” opens this app at your decisions.", color = Muted, fontSize = 14.sp)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Tile("Practice task", "Nothing goes to SAP", a.startPractice, Modifier.weight(1f))
            Tile("Send feedback", "Tell us what is hard", a.sendFeedback, Modifier.weight(1f))
        }
        TextButton(onClick = { showLog = !showLog }, modifier = Modifier.heightIn(min = 48.dp)) {
            Text(if (showLog) "Hide activity log" else "Show activity log", color = Primary, fontWeight = FontWeight.Bold)
        }
        if (showLog) {
            CardBox {
                if (ui.log.isEmpty()) Text("Nothing yet.", color = Muted)
                ui.log.takeLast(60).forEach { Text(it, fontSize = 12.sp, fontFamily = FontFamily.Monospace, color = Ink) }
            }
        }
    }
}

@Composable
private fun SettingRow(label: String, value: String, button: String?, onClick: () -> Unit, last: Boolean = false) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f)) {
            Text(label, fontWeight = FontWeight.Bold, color = Ink)
            Text(value, fontSize = 14.sp, color = Muted)
        }
        button?.let { SmallButton(it, onClick) }
    }
    if (!last) Box(Modifier.fillMaxWidth().height(1.dp).background(Divider))
}

@Composable
private fun Tile(title: String, sub: String, onClick: () -> Unit, modifier: Modifier) {
    Column(
        modifier.heightIn(min = 64.dp).background(CardBg, Corner).border(1.dp, Line, Corner)
            .clickable(role = Role.Button, onClick = onClick).padding(14.dp),
    ) {
        Text(title, fontWeight = FontWeight.Bold, color = Ink)
        Text(sub, fontSize = 14.sp, color = Muted)
    }
}
