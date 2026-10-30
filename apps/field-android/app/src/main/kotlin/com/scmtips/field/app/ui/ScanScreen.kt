package com.scmtips.field.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Ink2
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Primary
import com.scmtips.field.app.ui.theme.ScanAreaBg
import com.scmtips.field.app.ui.theme.ScanHint

/** Scan anything: a bin, a box or a serial; the app says what it is and which of your jobs it starts. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ScanScreen(ui: AppUi, a: Actions) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(start = 20.dp, end = 20.dp, top = 24.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Scan anything", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink, lineHeight = 32.sp)
        Text("A bin, a box, a pallet or a serial number. The app tells you what it is and what you can do.", color = Muted, fontSize = 15.sp)
        ScanArea(ui.scanner.howTo, 220.dp, a.scan)
        ManualCode(a)
        ui.scanResult?.let { r ->
            CardBox {
                Text(r.kind, fontSize = 13.sp, color = Muted)
                Text(r.code, fontSize = 22.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace, color = Ink)
                Text(r.about, fontSize = 15.sp, color = Ink2)
                FlowRow(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    r.actions.forEach { (label, taskId) -> SmallButton(label, { a.openTask(taskId) }) }
                }
            }
        }
    }
}

/** The dark scan area of the design; tapping it starts the chosen scanner. */
@Composable
fun ScanArea(howTo: String, height: Dp, onScan: () -> Unit) {
    Column(
        Modifier.fillMaxWidth().height(height).background(ScanAreaBg, Corner).clickable(role = Role.Button, onClick = onScan)
            .semantics { contentDescription = "Scan. $howTo" },
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterVertically),
    ) {
        BarcodeGlyph()
        Text(howTo, color = Color.White, textAlign = TextAlign.Center, modifier = Modifier.widthIn(max = 260.dp))
        Text("Tap here to scan", color = ScanHint, fontSize = 13.sp)
    }
}

/** When a label cannot be scanned: type the code. While the field has focus, keys are not a handheld scan. */
@Composable
fun ManualCode(a: Actions) {
    var open by remember { mutableStateOf(false) }
    var text by remember { mutableStateOf("") }
    if (!open) {
        TextButton(onClick = { open = true }, modifier = Modifier.heightIn(min = 48.dp)) {
            Text("Type the code instead", color = Primary, fontWeight = FontWeight.Bold)
        }
        return
    }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(
            value = text, onValueChange = { text = it.take(80) }, singleLine = true, label = { Text("Code on the label") },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { if (text.isNotBlank()) { a.manualCode(text); text = "" } }),
            modifier = Modifier.weight(1f).onFocusChanged { a.manualEntryOpen(it.isFocused) },
        )
        SmallButton("Use", { if (text.isNotBlank()) { a.manualCode(text); text = "" } })
    }
}
