package com.scmtips.field.app.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Shown instead of the app after a crash: the report can be copied or shared, then the app restarts. */
@Composable
fun CrashScreen(report: String, onDismiss: () -> Unit) {
    val context = LocalContext.current
    // Own background and safe-area padding: this screen is drawn outside the app theme, and edge-to-edge
    // on Android 15+ put it under the status bar as dark text on a dark window (owner report 2026-10-31).
    Column(
        Modifier.fillMaxSize().background(Color.White).safeDrawingPadding().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("SCMTips Field stopped last time", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold,
            color = Color(0xFF1C1E21))
        Text("Please copy or share this report and send it to Claude, then tap Start again.", color = Color(0xFF1C1E21))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                cm.setPrimaryClip(ClipData.newPlainText("SCMTips Field crash", report))
            }) { Text("Copy") }
            OutlinedButton(onClick = {
                val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, report)
                context.startActivity(Intent.createChooser(send, "Share crash report"))
            }) { Text("Share") }
            OutlinedButton(onClick = onDismiss) { Text("Start again") }
        }
        Text(
            report,
            Modifier.verticalScroll(rememberScrollState()),
            fontFamily = FontFamily.Monospace,
            fontSize = 11.sp,
            color = Color(0xFF1C1E21),
        )
    }
}
