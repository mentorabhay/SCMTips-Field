package com.scmtips.field.app.ui.shell

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.BuildConfig
import com.scmtips.field.app.jobs.Tone
import com.scmtips.field.app.shell.AccountPages
import com.scmtips.field.app.shell.FirstRunStep
import com.scmtips.field.app.shell.HomeMemory
import com.scmtips.field.app.shell.HomeRules
import com.scmtips.field.app.shell.PermissionStep
import com.scmtips.field.app.shell.ShellAction
import com.scmtips.field.app.shell.ShellPage
import com.scmtips.field.app.ui.Actions
import com.scmtips.field.app.ui.CameraTestCard
import com.scmtips.field.app.ui.CardBox
import com.scmtips.field.app.ui.CardShape
import com.scmtips.field.app.ui.GradientButton
import com.scmtips.field.app.ui.MinTouch
import com.scmtips.field.app.ui.Notice
import com.scmtips.field.app.ui.SecondaryButton
import com.scmtips.field.app.ui.SignInCard
import com.scmtips.field.app.ui.SmallButton
import com.scmtips.field.app.ui.theme.AccentInk
import com.scmtips.field.app.ui.theme.AccentTint
import com.scmtips.field.app.ui.theme.BrandGradientDiagonal
import com.scmtips.field.app.ui.theme.BrandStart
import com.scmtips.field.app.ui.theme.Border
import com.scmtips.field.app.ui.theme.Ink
import com.scmtips.field.app.ui.theme.Muted
import com.scmtips.field.app.ui.theme.Night
import com.scmtips.field.app.ui.theme.NightMuted
import com.scmtips.field.app.ui.theme.NightRaised
import com.scmtips.field.app.ui.theme.Surface
import com.scmtips.field.app.ui.theme.WarnBg
import com.scmtips.field.app.ui.theme.WarnInk

/**
 * THE FIRST-RUN SEAM (docs/design/M5_UI_CONTRACT.md §1): one screen per [step]. To use builder B's screens, replace
 * one `Interim…(...)` call per branch with B's screen and bind its callbacks as the contract's §4 table says.
 */
@Composable
fun FirstRunContent(step: FirstRunStep, ui: AppUi, a: Actions) {
    when (step) {
        FirstRunStep.WELCOME -> InterimWelcome(onGetStarted = { a.shell(ShellAction.Welcomed) })
        FirstRunStep.SIGN_IN -> InterimSignIn(ui, a)
        FirstRunStep.FORGOT -> InterimForgot(
            email = ui.signIn.email,
            onOpenReset = { a.openUrl(AccountPages.reset(ui.signIn.coreUrl, BuildConfig.DEFAULT_CORE_URL)) },
            onCreateAccount = { a.openUrl(AccountPages.signup(ui.signIn.coreUrl, BuildConfig.DEFAULT_CORE_URL)) },
            onBack = { a.shell(ShellAction.Back) },
        )
        FirstRunStep.PERMISSIONS -> InterimPermissions(onAllow = a.requestPermission, onDone = { a.shell(ShellAction.Go(FirstRunStep.GLASSES)) })
        FirstRunStep.GLASSES -> InterimGlasses(ui, a, onNext = { a.shell(ShellAction.Go(FirstRunStep.SITE)) })
        FirstRunStep.SITE -> InterimSitePick(ui, a)
    }
}

// INTERIM first-run screens (builder A, until builder B's ui/firstrun/* are merged). Plain, but every path works.

@Composable
private fun Page(dark: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier.fillMaxSize().background(if (dark) Night else com.scmtips.field.app.ui.theme.Ground)
            .verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp), content = content,
    )
}

@Composable
private fun BrandMark() {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(Modifier.size(36.dp).background(BrandGradientDiagonal, RoundedCornerShape(10.dp)))
        Text("SCMTips Field", color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.Bold)
    }
}

/** INTERIM Welcome (Main.dc.html): look, hear, confirm. */
@Composable
internal fun InterimWelcome(onGetStarted: () -> Unit) = Page(dark = true) {
    BrandMark()
    Spacer(Modifier.height(24.dp))
    listOf(
        "Look" to "One look with your glasses counts the delivery and reads every label.",
        "Hear" to "The glasses tell you what they found: count, damage, pack size, expiry.",
        "Confirm" to "You say the numbers and \"confirm\". Every posting gets an evidence page.",
    ).forEach { (t, b) ->
        Column(Modifier.fillMaxWidth().background(NightRaised, CardShape).padding(18.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(t, color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Text(b, color = NightMuted, fontSize = 16.sp, lineHeight = 23.sp)
        }
    }
    Spacer(Modifier.height(12.dp))
    GradientButton("Get started", onGetStarted)
    TextButton(onClick = onGetStarted, modifier = Modifier.fillMaxWidth().heightIn(min = MinTouch)) {
        Text("For judges: SAMPLE sign-in details", color = NightMuted, fontSize = 15.sp)
    }
}

/** INTERIM Sign in (SignIn.dc.html): the existing sign-in card plus forgot, create account and the PC code. */
@Composable
internal fun InterimSignIn(ui: AppUi, a: Actions) = Page {
    Text("SCMTIPS FIELD", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = AccentInk)
    Text("Sign in", fontSize = 30.sp, fontWeight = FontWeight.Bold, color = Ink, lineHeight = 36.sp)
    Text("Use your SCMTIPS work account. Your role decides what you see next.", color = Muted, fontSize = 15.sp)
    SignInCard(ui, a)
    TextButton(onClick = { a.shell(ShellAction.Go(FirstRunStep.FORGOT)) }, modifier = Modifier.heightIn(min = MinTouch)) {
        Text("Forgot password?", color = AccentInk, fontWeight = FontWeight.SemiBold)
    }
    TextButton(onClick = { a.openUrl(AccountPages.signup(ui.signIn.coreUrl, BuildConfig.DEFAULT_CORE_URL)) }, modifier = Modifier.heightIn(min = MinTouch)) {
        Text("New to SCMTIPS? Create an account", color = AccentInk, fontWeight = FontWeight.SemiBold)
    }
    ui.connectError?.takeIf { ui.signedIn == null }?.let { Notice(it, Tone.BAD) }
    SecondaryButton("I have a code from my PC", a.scanPairingCode, enabled = !ui.connecting && !ui.signIn.busy)
    TextButton(onClick = { a.shell(ShellAction.Open(ShellPage.CONNECTIONS)) }, modifier = Modifier.heightIn(min = MinTouch)) {
        Text("Servers and connections", color = Muted)
    }
    Text("SAMPLE data only. Judges: use the judge01 to judge05 accounts from the submission notes.", color = WarnInk, fontSize = 14.sp,
        modifier = Modifier.fillMaxWidth().background(WarnBg, CardShape).padding(14.dp))
}

/** INTERIM Forgot password: the SCMTIPS reset page opens in the browser; SCMTips Field never sees the password. */
@Composable
internal fun InterimForgot(email: String, onOpenReset: () -> Unit, onCreateAccount: () -> Unit, onBack: () -> Unit) = Page {
    TextButton(onClick = onBack, modifier = Modifier.heightIn(min = MinTouch)) { Text("Back", color = Ink) }
    Text("Reset your password", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink, lineHeight = 34.sp)
    Text("SCMTIPS sends a reset link to your work e-mail${if (email.isNotBlank()) " ($email)" else ""}. The SCMTIPS page opens " +
        "in your browser; SCMTips Field never sees your password.", color = Muted, fontSize = 16.sp, lineHeight = 24.sp)
    GradientButton("Open the SCMTIPS reset page", onOpenReset)
    SecondaryButton("Back to sign in", onBack)
    TextButton(onClick = onCreateAccount, modifier = Modifier.heightIn(min = MinTouch)) {
        Text("No account yet? Create one on SCMTIPS", color = AccentInk, fontWeight = FontWeight.SemiBold)
    }
}

/** INTERIM Permissions: the four permissions with why; "Allow" asks Android, Continue moves on either way. */
@Composable
internal fun InterimPermissions(onAllow: (PermissionStep) -> Unit, onDone: () -> Unit) = Page {
    Text("Set up · permissions", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Muted)
    Text("What the app needs", fontSize = 26.sp, fontWeight = FontWeight.Bold, color = Ink)
    PermissionStep.entries.forEach { p ->
        CardBox {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.weight(1f)) {
                    Text(p.title, fontWeight = FontWeight.Bold, color = Ink, fontSize = 17.sp)
                    Text(p.why, color = Muted, fontSize = 14.sp)
                }
                SmallButton("Allow", { onAllow(p) })
            }
        }
    }
    GradientButton("Continue", onDone)
}

/** INTERIM Glasses (optional): set up or connect through the Meta AI app, a test photo, or skip. */
@Composable
internal fun InterimGlasses(ui: AppUi, a: Actions, onNext: () -> Unit) = Page {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text("Set up · optional", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Muted, modifier = Modifier.weight(1f))
        TextButton(onClick = onNext, modifier = Modifier.heightIn(min = MinTouch)) { Text("Skip", color = Muted, fontWeight = FontWeight.SemiBold) }
    }
    Text("Connect your glasses", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink)
    Text("Hands free: the glasses see, speak and listen. Without them, the phone camera does the same work.", color = Muted, fontSize = 16.sp)
    CardBox {
        Text("Ray-Ban Meta Gen 2", fontWeight = FontWeight.Bold, color = Ink)
        Text(ui.glassesAdvice.text, color = Muted, fontSize = 14.sp)
        ui.glassesAdvice.button?.let { SecondaryButton(it, a.glassesSetUp, Modifier.padding(top = 6.dp)) }
    }
    CameraTestCard(ui.probe, a)
    GradientButton(if (ui.glassesAdvice.ready) "Glasses ready · Continue" else "Continue", onNext)
}

/** INTERIM Site and role: the sites field-api lists and the four homes (can act / view only). */
@Composable
internal fun InterimSitePick(ui: AppUi, a: Actions) = Page {
    val caps = capabilities(ui)
    val who = whoOf(ui)
    val current = HomeMemory.current(ui.shell.savedHome, who, caps)
    Text("Signed in as ${ui.signedIn?.name ?: ui.person.name}", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Muted)
    Text("Where are you working?", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Ink)
    when {
        ui.sites.isNotEmpty() -> ui.sites.forEach { s ->
            Choice(s.name, if (s.mode == com.scmtips.field.app.assistant.SiteModes.SANDBOX) "Sandbox · nothing reaches SAP" else "Site", s.id == ui.pairing?.siteId) { a.chooseSite(s.id) }
        }
        ui.pairing != null -> Choice(ui.pairing.siteName, "From your PC's code", true) {}
        ui.connecting -> Text("Asking the SCMTips Field server for your sites…", color = Muted)
        else -> Text(ui.connectError ?: "No field site is linked to this account; approvals still work.", color = Muted)
    }
    Text("What are you doing now?", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Ink, modifier = Modifier.padding(top = 8.dp))
    Text("You can switch any time at the top of Home.", color = Muted, fontSize = 14.sp)
    HomeRules.choices(caps).forEach { c ->
        Choice(c.home.menuLabel, c.badge, c.home == current) { a.shell(ShellAction.PickHome(c.home, who)) }
    }
    GradientButton("Continue", { a.shell(ShellAction.FinishSetup) })
}

@Composable
private fun Choice(title: String, sub: String, on: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).background(if (on) AccentTint else Surface, CardShape)
            .border(if (on) 2.dp else 1.dp, if (on) BrandStart else Border, CardShape)
            .clickable(role = Role.RadioButton, onClick = onClick).semantics { selected = on }.padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, fontWeight = FontWeight.SemiBold, color = Ink, fontSize = 16.sp)
            Text(sub, color = Muted, fontSize = 14.sp)
        }
        Box(Modifier.size(22.dp).border(2.dp, if (on) BrandStart else Border, CircleShape), contentAlignment = Alignment.Center) {
            if (on) Box(Modifier.size(12.dp).background(BrandStart, CircleShape))
        }
    }
}
