package com.scmtips.field.app.ui.firstrun

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.signin.AccountEvent
import com.scmtips.field.app.signin.AccountText
import com.scmtips.field.app.signin.AccountView
import com.scmtips.field.app.signin.ResetStage
import com.scmtips.field.app.ui.homes.GradientButton
import com.scmtips.field.app.ui.homes.HomeCard
import com.scmtips.field.app.ui.homes.LinkButton
import com.scmtips.field.app.ui.homes.QuietButton
import com.scmtips.field.app.ui.theme.BrandStart
import com.scmtips.field.app.ui.theme.Danger
import com.scmtips.field.app.ui.theme.Ground
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.feature.decisions.api.Consents
import com.scmtips.field.feature.decisions.api.InviteState

// M5-L in-app invite and reset (docs/design/M5_SIGNIN_CONTRACT.md §5, §7). Drawn only: every rule is in
// signin/AccountFlow.kt and feature-decisions' CoreAccountApi.kt (AcceptRules, PasswordPolicy), JVM-tested.

/** "I have an invite": paste the invite link or its code (the e-mail's link opens the invite by itself). */
@Composable
internal fun ColumnScope.InviteEnterStage(busy: Boolean, onEvent: (AccountEvent) -> Unit) {
    var text by rememberSaveable { mutableStateOf("") }
    OutlinedTextField(
        text, { text = it.take(2048) }, Modifier.fillMaxWidth(), enabled = !busy, minLines = 2, maxLines = 4,
        label = { Text("Invite link or code") }, placeholder = { Text("https://app.scmtips.com/invite/…") }, colors = fieldColors(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
    )
    GradientButton("Continue", { onEvent(AccountEvent.Pasted(text)) }, enabled = !busy && text.isNotBlank())
    Text("Tip: open the invite e-mail on this phone and tap the link; SCMTips Field opens at this screen with the invite filled in.",
        color = Muted, fontSize = 14.sp, lineHeight = 20.sp)
}

/** The invite (GET /v1/invites/{token}): organisation and role, then name, password and the two consents. */
@Composable
internal fun ColumnScope.InviteStage(flow: AccountView, busy: Boolean, onEvent: (AccountEvent) -> Unit) {
    val invite = flow.invite
    if (invite == null) {
        Text(if (flow.busy) "Reading the invite…" else "No invite is open.", color = Muted, fontSize = 15.sp,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        if (!flow.busy) QuietButton("Paste an invite link", { onEvent(AccountEvent.Open(com.scmtips.field.app.signin.SignInStage.INVITE_ENTER)) })
        return
    }
    if (invite.state != InviteState.PENDING) {
        QuietButton("Back to sign in", { onEvent(AccountEvent.Back) })
        return
    }
    var name by rememberSaveable { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var show by rememberSaveable { mutableStateOf(false) }
    var terms by rememberSaveable { mutableStateOf(false) }
    var dpdp by rememberSaveable { mutableStateOf(false) }
    val existing = invite.accountExists
    Text("E-mail", color = Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    Text(invite.email, color = Ink, fontSize = 16.sp)
    invite.expiresAt?.take(10)?.let { Text("The invite works until $it.", color = Muted, fontSize = 14.sp) }
    if (existing) {
        Text("This address already has an account here: enter its password to join.", color = Muted, fontSize = 15.sp, lineHeight = 22.sp)
    } else {
        OutlinedTextField(
            name, { name = it.take(200) }, Modifier.fillMaxWidth(), singleLine = true, enabled = !busy, label = { Text("Your name") },
            colors = fieldColors(), keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
        )
    }
    Text(if (existing) "Password" else "Choose a password", color = Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    PasswordField(password, { password = it }, show, { show = !show }, if (existing) "Your password" else "At least 12 characters", !busy)
    flow.policy.forEach { Text(it, color = Danger, fontSize = 14.sp, lineHeight = 20.sp) }
    if (!existing) {
        Consent(Consents.TERMS_TEXT, terms, !busy) { terms = it }
        Consent(Consents.DPDP_TEXT, dpdp, !busy) { dpdp = it }
    }
    GradientButton(
        when {
            flow.busy -> "Joining…"
            existing -> "Sign in and join"
            else -> "Create account and join"
        },
        { onEvent(AccountEvent.Accept(name, password, terms, dpdp)) },
        enabled = !busy && password.isNotEmpty() && (existing || (name.isNotBlank() && terms && dpdp)),
    )
}

@Composable
private fun Consent(text: String, checked: Boolean, enabled: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).toggleable(checked, enabled = enabled, role = Role.Checkbox, onValueChange = onChange),
        verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Checkbox(checked = checked, onCheckedChange = null, enabled = enabled, colors = CheckboxDefaults.colors(checkedColor = BrandStart))
        Text(text, color = Ink, fontSize = 14.sp, lineHeight = 20.sp, modifier = Modifier.weight(1f))
    }
}

/**
 * 1.3 Forgot password, in the app (M5-L contract §5, §7): the e-mail → "Check your e-mail" with "Open my mail app"
 * (the phone's e-mail app, never a browser) → the e-mailed link opens the app here at "Set a new password" (twice,
 * the core's policy messages shown) → back to sign in with the e-mail filled. [onEvent] carries every move.
 */
@Composable
fun ForgotScreen(flow: AccountView, onEvent: (AccountEvent) -> Unit, onOpenMail: () -> Unit, onBack: () -> Unit, reduceMotion: Boolean = false) {
    Column(
        Modifier.fillMaxSize().background(Ground).verticalScroll(rememberScrollState()).padding(start = 20.dp, end = 20.dp, top = 52.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        BackLink(onBack, Ink, "Back to sign in")
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(if (flow.reset == ResetStage.SET) "Set a new password" else "Reset your password", color = Ink, fontSize = 28.sp, lineHeight = 34.sp,
                fontWeight = FontWeight.Bold, modifier = Modifier.semantics { heading() })
            Text(if (flow.reset == ResetStage.SET) ResetText.SET_INTRO else ResetText.INTRO, color = Muted, fontSize = 16.sp, lineHeight = 24.sp)
        }
        HomeCard(shape = RoundedCornerShape(20.dp), padding = PaddingValues(20.dp)) {
            when (flow.reset) {
                ResetStage.REQUEST -> ResetRequest(flow, onEvent)
                ResetStage.SENT -> ResetSent(flow, onEvent, onOpenMail, onBack, reduceMotion)
                ResetStage.SET -> ResetSet(flow, onEvent)
            }
            flow.error?.let {
                ProblemBox(it, null, demo = false, busy = flow.busy, onEvent = onEvent, onScan = {})
                if (flow.reset == ResetStage.SET && it == AccountText.RESET_INVALID) LinkButton("Ask for a new link", { onEvent(AccountEvent.Forgot) })
            }
        }
        if (flow.reset != ResetStage.SET) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                Text("No account yet?", color = Muted, fontSize = 14.sp)
                LinkButton("Create an account", { onBack(); onEvent(AccountEvent.Open(com.scmtips.field.app.signin.SignInStage.CREATE)) }, size = 14)
            }
        }
    }
}

@Composable
private fun ColumnScope.ResetRequest(flow: AccountView, onEvent: (AccountEvent) -> Unit) {
    var email by rememberSaveable(flow.email) { mutableStateOf(flow.email) }
    OutlinedTextField(
        email, { email = it.take(254) }, Modifier.fillMaxWidth(), singleLine = true, enabled = !flow.busy, label = { Text("Work e-mail") },
        colors = fieldColors(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Done),
    )
    GradientButton(if (flow.busy) "Sending…" else "E-mail me a reset link", { onEvent(AccountEvent.ResetEmail(email)) },
        enabled = !flow.busy && email.isNotBlank())
}

@Composable
private fun ColumnScope.ResetSent(flow: AccountView, onEvent: (AccountEvent) -> Unit, onOpenMail: () -> Unit, onBack: () -> Unit, reduceMotion: Boolean) {
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        EnvelopeArt(reduceMotion)
        Text("Check your e-mail", color = Ink, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Text(flow.notice ?: AccountText.RESET_ON_ITS_WAY, color = Muted, fontSize = 15.sp, lineHeight = 22.sp, textAlign = TextAlign.Center,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        GradientButton("Open my mail app", onOpenMail)
        QuietButton("Back to sign in", onBack)
        LinkButton("Send it again", { onEvent(AccountEvent.ResetEmail(flow.email)) }, enabled = !flow.busy)
    }
}

@Composable
private fun ColumnScope.ResetSet(flow: AccountView, onEvent: (AccountEvent) -> Unit) {
    var password by remember { mutableStateOf("") }
    var again by remember { mutableStateOf("") }
    var show by rememberSaveable { mutableStateOf(false) }
    Text("New password", color = Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    PasswordField(password, { password = it }, show, { show = !show }, "At least 12 characters", !flow.busy, description = "New password")
    Text("The new password again", color = Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    PasswordField(again, { again = it }, show, { show = !show }, "The same password", !flow.busy, description = "The new password again",
        onDone = { onEvent(AccountEvent.NewPassword(password, again)) })
    flow.policy.forEach { Text(it, color = Danger, fontSize = 14.sp, lineHeight = 20.sp, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
    GradientButton(if (flow.busy) "Saving…" else "Save the new password", { onEvent(AccountEvent.NewPassword(password, again)) },
        enabled = !flow.busy && password.isNotEmpty() && again.isNotEmpty())
}
