package com.scmtips.field.app.ui.firstrun

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.SignInView
import com.scmtips.field.app.signin.AccountEvent
import com.scmtips.field.app.signin.AccountView
import com.scmtips.field.app.signin.CodeEntry
import com.scmtips.field.app.signin.ResendTimer
import com.scmtips.field.app.signin.SignInProblem
import com.scmtips.field.app.signin.SignInStage
import com.scmtips.field.app.signin.SignInWay
import com.scmtips.field.app.ui.MinTouch
import com.scmtips.field.app.ui.homes.ArtInk
import com.scmtips.field.app.ui.homes.FieldLine
import com.scmtips.field.app.ui.homes.Glyph
import com.scmtips.field.app.ui.homes.GlyphKind
import com.scmtips.field.app.ui.homes.GradientButton
import com.scmtips.field.app.ui.homes.HomeCard
import com.scmtips.field.app.ui.homes.LinkButton
import com.scmtips.field.app.ui.homes.QuietButton
import com.scmtips.field.app.ui.theme.AccentInk
import com.scmtips.field.app.ui.theme.AccentTint
import com.scmtips.field.app.ui.theme.Border
import com.scmtips.field.app.ui.theme.BrandStart
import com.scmtips.field.app.ui.theme.Danger
import com.scmtips.field.app.ui.theme.DangerBg
import com.scmtips.field.app.ui.theme.Ground
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Night
import com.scmtips.field.app.ui.theme.NightMuted
import com.scmtips.field.app.ui.theme.Surface
import com.scmtips.field.app.ui.theme.WarnBg
import com.scmtips.field.app.ui.theme.WarnInk
import kotlinx.coroutines.delay

/**
 * 1.2 Sign in (SignIn.dc.html, M5-L contract §7): the five ways in on one card ("Continue with e-mail", "Scan a code
 * from your computer", "I have an invite", "Try the SAMPLE demo" when [demo], and "Forgot password?"), then the
 * e-mail stage ("Use my password" / "E-mail me a code"), the password, the 6-box code, the invite and the "Create
 * account" sheet. Every move is an [AccountEvent] (rules: signin/AccountFlow.kt); the browser is never opened. The
 * server addresses are not on this screen (Settings › Connections); [onServers] adds a small "Servers" link.
 */
@Composable
fun SignInScreen(
    state: SignInView,
    flow: AccountView,
    demo: Boolean,
    onEvent: (AccountEvent) -> Unit,
    onScan: () -> Unit,
    onBack: () -> Unit,
    onServers: (() -> Unit)? = null,
) {
    val busy = state.busy || flow.busy
    val stage = flow.stage
    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().background(Ground).verticalScroll(rememberScrollState())) {
            Header(stage, flow, onBack = { if (stage.parent == null || stage == SignInStage.CREATE) onBack() else onEvent(AccountEvent.Back) },
                backLabel = if (stage.parent == null || stage == SignInStage.CREATE) "Back to welcome" else "Back")
            HomeCard(Modifier.padding(horizontal = 16.dp).offset(y = (-14).dp), shape = RoundedCornerShape(20.dp),
                padding = PaddingValues(horizontal = 20.dp, vertical = 24.dp)) {
                when (stage) {
                    SignInStage.CHOOSE, SignInStage.CREATE -> ChooseStage(demo, busy, onEvent, onScan)
                    SignInStage.EMAIL -> EmailStage(flow, busy, onEvent)
                    SignInStage.PASSWORD -> PasswordStage(flow, busy, onEvent)
                    SignInStage.CODE -> CodeStage(flow, busy, onEvent)
                    SignInStage.INVITE_ENTER -> InviteEnterStage(busy, onEvent)
                    SignInStage.INVITE -> InviteStage(flow, busy, onEvent)
                }
                flow.notice?.takeIf { stage != SignInStage.CODE }?.let { InfoLine(it) }
                (flow.error ?: state.error)?.let { ProblemBox(it, if (flow.error == null) state.problem else null, demo, busy, onEvent, onScan) }
                if (state.busy) Text("Signing in…", color = Muted, fontSize = 15.sp, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
            }
            if (stage == SignInStage.CHOOSE || stage == SignInStage.CREATE) {
                Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp), horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("New to SCMTIPS?", color = Muted, fontSize = 15.sp)
                        LinkButton("Create an account", { onEvent(AccountEvent.Open(SignInStage.CREATE)) })
                    }
                    onServers?.let { LinkButton("Servers", it, color = Muted, size = 13) }
                }
            }
            SampleNote(Modifier.padding(start = 16.dp, end = 16.dp, top = 20.dp, bottom = 28.dp))
        }
        if (stage == SignInStage.CREATE) CreateAccountSheet(demo, onEvent, onClose = { onEvent(AccountEvent.Back) })
    }
}

@Composable
private fun Header(stage: SignInStage, flow: AccountView, onBack: () -> Unit, backLabel: String) {
    val (title, sub) = when (stage) {
        SignInStage.CHOOSE, SignInStage.CREATE -> "Sign in" to "Use your SCMTIPS work account. Your role decides what you see next."
        SignInStage.EMAIL -> "Continue with e-mail" to "Use your password, or get a 6-digit code by e-mail."
        SignInStage.PASSWORD -> "Enter your password" to flow.email.trim()
        SignInStage.CODE -> "Check your e-mail" to (flow.notice ?: "Enter the 6-digit code we e-mailed you.")
        SignInStage.INVITE_ENTER -> "I have an invite" to "Your administrator's invite e-mail has a link. Paste it here, or open the link on this phone."
        SignInStage.INVITE -> "Join your team" to (flow.invite?.let { com.scmtips.field.app.signin.AccountText.invited(it) } ?: "Reading the invite…")
    }
    Column(Modifier.fillMaxWidth().background(Night).padding(start = 24.dp, end = 24.dp, top = 52.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        BackLink(onBack, NightMuted, backLabel)
        Text("SCMTIPS FIELD", color = ArtInk.Lilac, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp)
        Text(title, color = Color.White, fontSize = 30.sp, lineHeight = 36.sp, fontWeight = FontWeight.Bold, modifier = Modifier.semantics { heading() })
        if (sub.isNotBlank()) Text(sub, color = NightMuted, fontSize = 15.sp, lineHeight = 22.sp,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
    }
}

/** The five ways in (SignInWay.shown) and "Forgot password?". */
@Composable
private fun ColumnScope.ChooseStage(demo: Boolean, busy: Boolean, onEvent: (AccountEvent) -> Unit, onScan: () -> Unit) {
    SignInWay.shown(demo).forEach { way ->
        val go: () -> Unit = when (way) {
            SignInWay.EMAIL -> { { onEvent(AccountEvent.Open(SignInStage.EMAIL)) } }
            SignInWay.SCAN -> onScan
            SignInWay.INVITE -> { { onEvent(AccountEvent.Open(SignInStage.INVITE_ENTER)) } }
            SignInWay.DEMO -> { { onEvent(AccountEvent.Demo) } }
        }
        if (way == SignInWay.EMAIL) GradientButton(way.label, go, enabled = !busy)
        else WayRow(way, go, enabled = !busy)
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
        LinkButton("Forgot password?", { onEvent(AccountEvent.Forgot) }, enabled = !busy, size = 15)
    }
}

@Composable
private fun WayRow(way: SignInWay, onClick: () -> Unit, enabled: Boolean) {
    val glyph = when (way) {
        SignInWay.SCAN -> GlyphKind.CAMERA
        SignInWay.INVITE -> GlyphKind.LAYERS
        SignInWay.DEMO -> GlyphKind.BOX
        SignInWay.EMAIL -> GlyphKind.INFO
    }
    Row(
        Modifier.fillMaxWidth().heightIn(min = 60.dp).border(1.dp, FieldLine, RoundedCornerShape(14.dp))
            .background(if (way == SignInWay.DEMO) WarnBg else Surface, RoundedCornerShape(14.dp))
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick).padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(36.dp).background(if (way == SignInWay.DEMO) Color(0xFFFED7AA) else AccentTint, RoundedCornerShape(10.dp)),
            contentAlignment = Alignment.Center) { Glyph(glyph, if (way == SignInWay.DEMO) Color(0xFF9A3412) else AccentInk, size = 20.dp) }
        Column(Modifier.weight(1f)) {
            Text(way.label, color = Ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
            Text(way.sub, color = Muted, fontSize = 13.sp, lineHeight = 18.sp)
        }
    }
}

@Composable
private fun EmailStage(flow: AccountView, busy: Boolean, onEvent: (AccountEvent) -> Unit) {
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    OutlinedTextField(
        flow.email, { onEvent(AccountEvent.Email(it)) }, Modifier.fillMaxWidth().focusRequester(focus), singleLine = true, enabled = !busy,
        label = { Text("Work e-mail") }, colors = fieldColors(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
        keyboardActions = KeyboardActions(onNext = { onEvent(AccountEvent.UsePassword) }),
    )
    GradientButton("Use my password", { onEvent(AccountEvent.UsePassword) }, enabled = !busy, modifier = Modifier.padding(top = 4.dp))
    QuietButton(if (flow.busy) "Sending…" else "E-mail me a code", { onEvent(AccountEvent.SendCode(System.currentTimeMillis())) }, enabled = !busy)
    Text("A code works for 10 minutes and only once. No password needed.", color = Muted, fontSize = 14.sp, lineHeight = 20.sp)
}

@Composable
private fun PasswordStage(flow: AccountView, busy: Boolean, onEvent: (AccountEvent) -> Unit) {
    var password by remember { mutableStateOf("") }
    var show by rememberSaveable { mutableStateOf(false) }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    val canSubmit = SignInRules.canSubmit(flow.email, password, busy)
    val submit = { if (canSubmit) onEvent(AccountEvent.Password(password)) }
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text("Password", color = Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        LinkButton("Forgot password?", { onEvent(AccountEvent.Forgot) }, size = 14, enabled = !busy)
    }
    PasswordField(password, { password = it }, show, { show = !show }, "Your password", !busy, Modifier.focusRequester(focus), onDone = submit)
    Text(SignInRules.KEEP_NOTE, color = Muted, fontSize = 14.sp, lineHeight = 20.sp)
    GradientButton(if (busy) "Signing in…" else "Sign in", submit, enabled = canSubmit, modifier = Modifier.padding(top = 4.dp))
    LinkButton("E-mail me a code instead", { onEvent(AccountEvent.SendCode(System.currentTimeMillis())) }, enabled = !busy, color = Muted)
}

/** The 6 boxes: one hidden text field under them, so typing, paste and the keyboard's suggestion all work. */
@Composable
private fun CodeStage(flow: AccountView, busy: Boolean, onEvent: (AccountEvent) -> Unit) {
    var code by rememberSaveable { mutableStateOf("") }
    var now by remember { mutableStateOf(System.currentTimeMillis()) }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    LaunchedEffect(flow.codeRefused) { if (flow.codeRefused) { code = ""; onEvent(AccountEvent.Code("")) } }
    LaunchedEffect(flow.codeSentAtMs) {
        while (true) {
            now = System.currentTimeMillis()
            if (ResendTimer.canResend(flow.codeSentAtMs, now)) break
            delay(1_000)
        }
    }
    flow.notice?.let { InfoLine(it) }
    Text("Code from the e-mail", color = Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    BasicTextField(
        value = code,
        onValueChange = { typed -> val c = CodeEntry.clean(typed); if (c != code) { code = c; onEvent(AccountEvent.Code(c)) } },
        enabled = !busy, singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
        modifier = Modifier.fillMaxWidth().focusRequester(focus).semantics { contentDescription = "6-digit code from the e-mail, ${code.length} of 6 entered" },
        decorationBox = { inner ->
            Box {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val at = CodeEntry.focus(code)
                    CodeEntry.boxes(code).forEachIndexed { i, ch ->
                        val on = i == at && code.length < CodeEntry.LENGTH
                        Box(
                            Modifier.weight(1f).height(56.dp).background(Surface, RoundedCornerShape(12.dp))
                                .border(if (on) 2.dp else 1.dp, if (on) BrandStart else FieldLine, RoundedCornerShape(12.dp)),
                            contentAlignment = Alignment.Center,
                        ) { Text(ch?.toString() ?: "", color = Ink, fontSize = 24.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center) }
                    }
                }
                Box(Modifier.size(1.dp).alpha(0f)) { inner() }
            }
        },
    )
    Text(if (busy) "Checking the code…" else "The app signs in as soon as all 6 digits are in. You can paste the code.",
        color = Muted, fontSize = 14.sp, lineHeight = 20.sp)
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
        LinkButton(ResendTimer.label(flow.codeSentAtMs, now), { onEvent(AccountEvent.SendCode(System.currentTimeMillis())) },
            enabled = !busy && ResendTimer.canResend(flow.codeSentAtMs, now), size = 14)
        LinkButton("Use my password", { onEvent(AccountEvent.UsePassword) }, enabled = !busy, color = Muted, size = 14)
    }
}

/** "Create account" without an invite (contract §7): accounts come from an organisation; the demo and the invite. */
@Composable
private fun CreateAccountSheet(demo: Boolean, onEvent: (AccountEvent) -> Unit, onClose: () -> Unit) {
    Box(Modifier.fillMaxSize().background(Color(0x99000000)).clickable(onClickLabel = "Close", role = Role.Button, onClick = onClose)) {
        Column(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth().background(Surface, RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp))
                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = {})
                .padding(start = 20.dp, end = 20.dp, top = 12.dp, bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(Modifier.align(Alignment.CenterHorizontally).size(width = 40.dp, height = 4.dp).background(Border, RoundedCornerShape(2.dp)))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Create an account", color = Ink, fontSize = 22.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f).semantics { heading() })
                TextButton(onClick = onClose, modifier = Modifier.heightIn(min = MinTouch).semantics { contentDescription = "Close" }) {
                    Glyph(GlyphKind.CLOSE, Muted, size = 20.dp)
                }
            }
            Text(CreateText.BODY, color = Ink, fontSize = 16.sp, lineHeight = 24.sp)
            Text(CreateText.ASK, color = Muted, fontSize = 15.sp, lineHeight = 22.sp)
            GradientButton("I have an invite", { onEvent(AccountEvent.Open(SignInStage.INVITE_ENTER)) })
            if (demo) QuietButton("Try the SAMPLE demo", { onEvent(AccountEvent.Demo) })
        }
    }
}

/** A neutral sign-in or account message, with the way on it offers (the demo for no Field role, the scan for SSO). */
@Composable
internal fun ProblemBox(text: String, problem: SignInProblem?, demo: Boolean, busy: Boolean, onEvent: (AccountEvent) -> Unit, onScan: () -> Unit) {
    Column(Modifier.fillMaxWidth().background(DangerBg, RoundedCornerShape(12.dp)).padding(horizontal = 14.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(text, color = Danger, fontSize = 15.sp, lineHeight = 21.sp, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        if (problem?.offersDemo == true && demo) QuietButton("Try the SAMPLE demo", { onEvent(AccountEvent.Demo) }, enabled = !busy)
        if (problem?.offersScan == true) QuietButton("Scan a code from your computer", onScan, enabled = !busy)
    }
}

@Composable
internal fun InfoLine(text: String) {
    Text(text, color = AccentInk, fontSize = 15.sp, lineHeight = 21.sp,
        modifier = Modifier.fillMaxWidth().background(AccentTint, RoundedCornerShape(12.dp)).padding(horizontal = 14.dp, vertical = 10.dp)
            .semantics { liveRegion = LiveRegionMode.Polite })
}

@Composable
internal fun PasswordField(
    value: String, onChange: (String) -> Unit, show: Boolean, onToggle: () -> Unit, placeholder: String, enabled: Boolean,
    modifier: Modifier = Modifier, description: String = "Password", onDone: () -> Unit = {},
) {
    OutlinedTextField(
        value, { onChange(it.take(1024)) }, modifier.fillMaxWidth().semantics { contentDescription = description },
        singleLine = true, enabled = enabled, placeholder = { Text(placeholder) }, colors = fieldColors(),
        visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { onDone() }),
        trailingIcon = {
            TextButton(onClick = onToggle, modifier = Modifier.heightIn(min = MinTouch)
                .semantics { contentDescription = if (show) "Hide password" else "Show password" }) {
                Text(if (show) "Hide" else "Show", color = AccentInk, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            }
        },
    )
}

@Composable
internal fun BackLink(onBack: () -> Unit, color: Color, description: String) {
    TextButton(onClick = onBack, modifier = Modifier.heightIn(min = MinTouch).semantics { contentDescription = description },
        contentPadding = PaddingValues(horizontal = 0.dp)) {
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
internal fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = BrandStart, unfocusedBorderColor = FieldLine, focusedLabelColor = AccentInk,
    focusedContainerColor = Surface, unfocusedContainerColor = Surface, cursorColor = BrandStart, disabledBorderColor = Border,
)
