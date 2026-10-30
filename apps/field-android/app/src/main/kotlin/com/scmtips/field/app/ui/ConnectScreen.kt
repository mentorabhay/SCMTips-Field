package com.scmtips.field.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.jobs.Tone
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Primary

/** Connect once: three numbered steps, then the phone remembers the site (design: Journey step 1). */
@Composable
fun ConnectScreen(ui: AppUi, a: Actions) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Connect this phone", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink, lineHeight = 32.sp)
        Text("Do this once. After that the phone remembers your site.", color = Muted, fontSize = 15.sp)
        StepCard(1, "On the office PC, double-click START FIELD TEST.", "In the SCMTips-Field folder: scripts\\dev\\run-field-stack.cmd")
        StepCard(2, "Wait for the code.", "A square code opens on the PC screen after about a minute.")
        StepCard(3, "Scan it with this phone.", "Hold the phone 20 to 30 cm from the screen.")
        when {
            ui.connecting -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                CircularProgressIndicator(Modifier.size(24.dp), color = Primary, strokeWidth = 3.dp)
                Text("Connecting to ${ui.pairing?.siteName ?: "the PC"}…", color = Ink)
            }
            ui.connectError != null -> Notice(ui.connectError, Tone.BAD)
        }
        PrimaryButton("Scan the code", a.scanPairingCode, enabled = !ui.connecting)
        if (ui.pairing != null && !ui.connecting) SecondaryButton("Try again", a.retryConnect)
    }
}

@Composable
private fun StepCard(n: Int, title: String, detail: String) {
    CardBox {
        Row(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.Top) {
            Box(Modifier.size(32.dp).background(Primary, CircleShape), contentAlignment = Alignment.Center) {
                Text("$n", color = Color.White, fontWeight = FontWeight.Bold)
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(title, fontWeight = FontWeight.Bold, color = Ink, fontSize = 17.sp)
                Text(detail, color = Muted, fontSize = 14.sp)
            }
        }
    }
}
