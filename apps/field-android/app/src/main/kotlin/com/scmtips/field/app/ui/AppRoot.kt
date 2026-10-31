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
import com.scmtips.field.app.jobs.JobAction
import com.scmtips.field.app.jobs.JobType
import com.scmtips.field.app.navigation.Screen
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
)

@Composable
fun AppRoot(ui: AppUi, a: Actions) {
    Box(Modifier.fillMaxSize().background(Background).safeDrawingPadding()) {
        val job = ui.job
        when {
            ui.pairing == null || ui.deviceId == null -> ConnectScreen(ui, a)
            job != null -> Column(Modifier.fillMaxSize()) {
                if (ui.work.active) SessionStrip(ui.work, a)
                Box(Modifier.weight(1f)) { JobScreen(job, ui.audioOnly, a) }
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
