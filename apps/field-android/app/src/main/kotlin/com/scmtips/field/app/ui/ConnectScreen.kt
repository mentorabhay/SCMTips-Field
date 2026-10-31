package com.scmtips.field.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.jobs.Tone
import com.scmtips.field.app.ui.theme.Divider
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Primary
import com.scmtips.field.feature.decisions.api.SignInMethod

/**
 * Connect once (M4 F2): sign in with SCMTIPS (e-mail + password in demo mode, or a pairing code made on
 * the web), or, as before, scan the QR code the office PC shows. The phone remembers it afterwards.
 */
@Composable
fun ConnectScreen(ui: AppUi, a: Actions) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Connect this phone", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink, lineHeight = 32.sp)
        Text("Do this once. After that the phone remembers you.", color = Muted, fontSize = 15.sp)
        if (ui.signedIn != null) SignedInWaiting(ui, a) else SignInCard(ui, a)
        Box(Modifier.fillMaxWidth().height(1.dp).background(Divider))
        Text("Or connect with the office PC's code", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = Muted)
        StepCard(1, "On the office PC, double-click START FIELD TEST.", "In the SCMTips-Field folder: scripts\\dev\\run-field-stack.cmd")
        StepCard(2, "Wait for the code.", "A square code opens on the PC screen after about a minute.")
        StepCard(3, "Scan it with this phone.", "Hold the phone 20 to 30 cm from the screen.")
        if (ui.signedIn == null) {
            when {
                ui.connecting -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator(Modifier.size(24.dp), color = Primary, strokeWidth = 3.dp)
                    Text("Connecting to ${ui.pairing?.siteName ?: "the PC"}…", color = Ink)
                }
                ui.connectError != null -> Notice(ui.connectError, Tone.BAD)
            }
        }
        SecondaryButton("Scan the code", a.scanPairingCode, enabled = !ui.connecting && !ui.signIn.busy)
        if (ui.pairing != null && !ui.connecting && ui.signedIn == null) SecondaryButton("Try again", a.retryConnect)
    }
}

/** E-mail + password, or a pairing code; the two server addresses (dev defaults, kept once typed). */
@Composable
private fun SignInCard(ui: AppUi, a: Actions) {
    var withCode by rememberSaveable { mutableStateOf(false) }
    var email by rememberSaveable(ui.signIn.email) { mutableStateOf(ui.signIn.email) }
    var password by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var core by rememberSaveable(ui.signIn.coreUrl) { mutableStateOf(ui.signIn.coreUrl) }
    var field by rememberSaveable(ui.signIn.fieldUrl) { mutableStateOf(ui.signIn.fieldUrl) }
    var showServers by rememberSaveable { mutableStateOf(false) }
    CardBox {
        Text("Sign in with SCMTIPS", fontWeight = FontWeight.Bold, color = Ink, fontSize = 18.sp)
        Text(if (withCode) "Make a pairing code in SCMTIPS on the web (your profile → devices) and type it here."
        else "Approvers see their decisions; operators and auditors see their work.", color = Muted, fontSize = 14.sp)
        if (withCode) {
            OutlinedTextField(code, { code = it.trim().take(64) }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Pairing code") })
        } else {
            OutlinedTextField(email, { email = it.take(254) }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Work e-mail") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email))
            OutlinedTextField(password, { password = it.take(256) }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Password") },
                visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
        }
        TextButton(onClick = { withCode = !withCode }) {
            Text(if (withCode) "Sign in with e-mail and password" else "I have a pairing code", color = Primary, fontWeight = FontWeight.Bold)
        }
        if (showServers) {
            OutlinedTextField(core, { core = it.trim() }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("SCMTIPS address") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
            OutlinedTextField(field, { field = it.trim() }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("SCMTips Field server address") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
        } else {
            TextButton(onClick = { showServers = true }) { Text("Servers: $core · $field", color = Muted, fontSize = 13.sp) }
        }
        ui.signIn.error?.let { Notice(it, Tone.BAD) }
        if (ui.signIn.busy) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                CircularProgressIndicator(Modifier.size(24.dp), color = Primary, strokeWidth = 3.dp)
                Text("Signing in…", color = Ink)
            }
        }
        PrimaryButton(
            "Sign in",
            {
                val method = if (withCode) SignInMethod.PairingCode(code) else SignInMethod.Password(email, password)
                a.signIn(method, core, field)
            },
            enabled = !ui.signIn.busy && (if (withCode) code.isNotBlank() else email.isNotBlank() && password.isNotEmpty()),
        )
    }
}

/** Signed in as an operator; the phone is still being registered with the field server. */
@Composable
private fun SignedInWaiting(ui: AppUi, a: Actions) {
    CardBox {
        Text("Signed in as ${ui.signedIn?.name ?: ""}", fontWeight = FontWeight.Bold, color = Ink, fontSize = 18.sp)
        when {
            ui.connecting -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                CircularProgressIndicator(Modifier.size(24.dp), color = Primary, strokeWidth = 3.dp)
                Text("Connecting to the SCMTips Field server…", color = Ink)
            }
            ui.connectError != null -> Notice(ui.connectError, Tone.BAD)
        }
        if (!ui.connecting) {
            PrimaryButton("Try again", a.retryConnect, height = 52.dp)
            SecondaryButton("Sign out", a.unpair)
        }
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
