package com.scmtips.field.app.ui.firstrun

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.SignInView
import com.scmtips.field.app.ui.homes.AccentInk
import com.scmtips.field.app.ui.homes.ArtInk
import com.scmtips.field.app.ui.homes.BrandStart
import com.scmtips.field.app.ui.homes.Border
import com.scmtips.field.app.ui.homes.Danger
import com.scmtips.field.app.ui.homes.DangerBg
import com.scmtips.field.app.ui.homes.FieldLine
import com.scmtips.field.app.ui.homes.Glyph
import com.scmtips.field.app.ui.homes.GlyphKind
import com.scmtips.field.app.ui.homes.GradientButton
import com.scmtips.field.app.ui.homes.Ground
import com.scmtips.field.app.ui.homes.HomeCard
import com.scmtips.field.app.ui.homes.Ink
import com.scmtips.field.app.ui.homes.LinkButton
import com.scmtips.field.app.ui.homes.MinTouch
import com.scmtips.field.app.ui.homes.Muted
import com.scmtips.field.app.ui.homes.Night
import com.scmtips.field.app.ui.homes.NightMuted
import com.scmtips.field.app.ui.homes.QuietButton
import com.scmtips.field.app.ui.homes.Surface
import com.scmtips.field.app.ui.homes.WarnBg
import com.scmtips.field.app.ui.homes.WarnInk
import com.scmtips.field.feature.decisions.api.SignInMethod

/**
 * 1.2 Sign in (SignIn.dc.html): work e-mail, password with Show/Hide, Sign in with the existing [SignInView] busy and
 * error states, Forgot password?, Create an account (both open the SCMTIPS pages through the shell), "I have a code
 * from my PC" and the SAMPLE note for judges. The server addresses are not on this screen (Settings › Connections);
 * [onServers] adds a small "Servers" link for testers when given. The app keeps the phone signed in until Profile ›
 * Sign out, so "Keep me signed in" is said as a fact, not offered as a switch that would do nothing.
 */
@Composable
fun SignInScreen(
    state: SignInView,
    onSignIn: (SignInMethod, String, String) -> Unit,
    onForgot: () -> Unit,
    onCreateAccount: (String) -> Unit,
    onPcCode: () -> Unit,
    onBack: () -> Unit,
    onServers: (() -> Unit)? = null,
) {
    var email by rememberSaveable(state.email) { mutableStateOf(state.email) }
    var password by remember { mutableStateOf("") }
    var show by rememberSaveable { mutableStateOf(false) }
    val canSubmit = SignInRules.canSubmit(email, password, state.busy)
    val submit = { if (canSubmit) onSignIn(SignInMethod.Password(SignInRules.cleanEmail(email), password), state.coreUrl, state.fieldUrl) }
    Column(Modifier.fillMaxSize().background(Ground).verticalScroll(rememberScrollState())) {
        Column(Modifier.fillMaxWidth().background(Night).padding(start = 24.dp, end = 24.dp, top = 52.dp, bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)) {
            BackLink(onBack, NightMuted, "Back to welcome")
            Text("SCMTIPS FIELD", color = ArtInk.Lilac, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp)
            Text("Sign in", color = Color.White, fontSize = 30.sp, lineHeight = 36.sp, fontWeight = FontWeight.Bold, modifier = Modifier.semantics { heading() })
            Text("Use your SCMTIPS work account. Your role decides what you see next.", color = NightMuted, fontSize = 15.sp, lineHeight = 22.sp)
        }
        HomeCard(Modifier.padding(horizontal = 16.dp).offset(y = (-14).dp), shape = RoundedCornerShape(20.dp),
            padding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 24.dp)) {
            OutlinedTextField(
                email, { email = it.take(254) }, Modifier.fillMaxWidth(), singleLine = true, enabled = !state.busy,
                label = { Text("Work e-mail") }, colors = fieldColors(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
            )
            Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Password", color = Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                LinkButton("Forgot password?", onForgot, size = 14)
            }
            OutlinedTextField(
                password, { password = it.take(256) }, Modifier.fillMaxWidth().semantics { contentDescription = "Password" },
                singleLine = true, enabled = !state.busy,
                placeholder = { Text("Your password") }, colors = fieldColors(),
                visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                trailingIcon = {
                    TextButton(onClick = { show = !show }, modifier = Modifier.heightIn(min = MinTouch)
                        .semantics { contentDescription = if (show) "Hide password" else "Show password" }) {
                        Text(if (show) "Hide" else "Show", color = AccentInk, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                    }
                },
            )
            Text(SignInRules.KEEP_NOTE, color = Muted, fontSize = 14.sp, lineHeight = 20.sp)
            state.error?.let {
                Text(it, color = Danger, fontSize = 15.sp, lineHeight = 21.sp,
                    modifier = Modifier.fillMaxWidth().background(DangerBg, RoundedCornerShape(12.dp)).padding(horizontal = 14.dp, vertical = 10.dp)
                        .semantics { liveRegion = LiveRegionMode.Polite })
            }
            GradientButton(if (state.busy) "Signing in…" else "Sign in", submit, enabled = canSubmit, modifier = Modifier.padding(top = 4.dp))
        }
        Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("New to SCMTIPS?", color = Muted, fontSize = 15.sp)
                LinkButton("Create an account", { onCreateAccount(state.coreUrl) })
            }
            LinkButton("I have a code from my PC", onPcCode, color = Muted)
            onServers?.let { LinkButton("Servers", it, color = Muted, size = 13) }
        }
        SampleNote(Modifier.padding(start = 16.dp, end = 16.dp, top = 20.dp, bottom = 28.dp))
    }
}

/**
 * 1.3 Forgot password (Forgot.dc.html). SCMTIPS owns the reset: the button opens the SCMTIPS reset page (the shell's
 * onOpenReset), then the screen says to finish there; the app never claims an e-mail was sent.
 */
@Composable
fun ForgotScreen(email: String, onOpenReset: () -> Unit, onCreateAccount: () -> Unit, onBack: () -> Unit, reduceMotion: Boolean = false) {
    var opened by rememberSaveable { mutableStateOf(false) }
    Column(
        Modifier.fillMaxSize().background(Ground).verticalScroll(rememberScrollState()).padding(start = 20.dp, end = 20.dp, top = 52.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        BackLink(onBack, Ink, "Back to sign in")
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Reset your password", color = Ink, fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold, modifier = Modifier.semantics { heading() })
            Text(ForgotText.INTRO, color = Muted, fontSize = 16.sp, lineHeight = 24.sp)
        }
        HomeCard(shape = RoundedCornerShape(20.dp), padding = androidx.compose.foundation.layout.PaddingValues(20.dp)) {
            if (!opened) {
                email.trim().takeIf { it.isNotEmpty() }?.let {
                    Text("Work e-mail", color = Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    Text(it, color = Ink, fontSize = 16.sp, modifier = Modifier.fillMaxWidth().border(1.dp, FieldLine, RoundedCornerShape(12.dp))
                        .padding(horizontal = 14.dp, vertical = 15.dp))
                }
                GradientButton("Open the SCMTIPS reset page", { opened = true; onOpenReset() })
            } else {
                Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    EnvelopeArt(reduceMotion)
                    Text("Finish on the SCMTIPS page", color = Ink, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                    Text(ForgotText.afterOpen(email), color = Muted, fontSize = 15.sp, lineHeight = 22.sp,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                    QuietButton("Back to sign in", onBack)
                    LinkButton("Open the page again", onOpenReset)
                }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Text("No account yet?", color = Muted, fontSize = 14.sp)
            LinkButton("Create one on SCMTIPS", onCreateAccount, size = 14)
        }
    }
}

@Composable
internal fun BackLink(onBack: () -> Unit, color: Color, description: String) {
    TextButton(onClick = onBack, modifier = Modifier.heightIn(min = MinTouch).semantics { contentDescription = description },
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 0.dp)) {
        Glyph(GlyphKind.BACK, color, size = 18.dp)
        Text("Back", color = color, fontSize = 15.sp, modifier = Modifier.padding(start = 6.dp))
    }
}

@Composable
private fun SampleNote(modifier: Modifier) {
    Row(
        modifier.fillMaxWidth().background(WarnBg, RoundedCornerShape(14.dp)).border(1.dp, Color(0xFFFED7AA), RoundedCornerShape(14.dp))
            .padding(horizontal = 14.dp, vertical = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Glyph(GlyphKind.INFO, Color(0xFF9A3412), size = 20.dp)
        Text(SignInRules.SAMPLE_NOTE, color = WarnInk, fontSize = 14.sp, lineHeight = 20.sp, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = BrandStart, unfocusedBorderColor = FieldLine, focusedLabelColor = AccentInk,
    focusedContainerColor = Surface, unfocusedContainerColor = Surface, cursorColor = BrandStart, disabledBorderColor = Border,
)
