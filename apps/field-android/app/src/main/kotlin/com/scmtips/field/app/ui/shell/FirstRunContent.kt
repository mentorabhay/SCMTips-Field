package com.scmtips.field.app.ui.shell

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.SignInView
import com.scmtips.field.app.shell.FirstRunStep
import com.scmtips.field.app.shell.HomeMemory
import com.scmtips.field.app.shell.HomeRules
import com.scmtips.field.app.shell.ShellAction
import com.scmtips.field.app.shell.ShellPage
import com.scmtips.field.app.signin.AccountEvent
import com.scmtips.field.app.signin.DemoOffer
import com.scmtips.field.app.ui.Actions
import com.scmtips.field.app.ui.firstrun.ForgotScreen
import com.scmtips.field.app.ui.firstrun.GlassesSetupScreen
import com.scmtips.field.app.ui.firstrun.PermissionsScreen
import com.scmtips.field.app.ui.firstrun.SignInScreen
import com.scmtips.field.app.ui.firstrun.SitePickScreen
import com.scmtips.field.app.ui.firstrun.WelcomeScreen
import com.scmtips.field.app.ui.theme.LocalReduceMotion

/**
 * THE FIRST-RUN SEAM (docs/design/M5_UI_CONTRACT.md §1): one of builder B's screens per [step], its callbacks bound
 * as the contract's §4 table says (M5-U06). The screens never navigate by themselves; every move is a ShellAction, and
 * inside sign-in and reset an AccountEvent (M5-L, signin/AccountFlow.kt): nothing here opens the browser.
 */
@Composable
fun FirstRunContent(step: FirstRunStep, ui: AppUi, a: Actions) {
    val still = LocalReduceMotion.current
    when (step) {
        FirstRunStep.WELCOME -> WelcomeScreen(
            reduceMotion = still,
            onGetStarted = { a.shell(ShellAction.Welcomed) },
            onJudgeDetails = { a.shell(ShellAction.Welcomed) }, // the SAMPLE note on Sign in carries the judge accounts
        )
        FirstRunStep.SIGN_IN -> {
            // M5-L: Back walks the sign-in stages first (after ShellRoot's handler, so this one wins), then the shell's.
            BackHandler(enabled = ui.account.stage.parent != null) { a.account(AccountEvent.Back) }
            SignInScreen(
                state = signInState(ui),
                flow = ui.account,
                demo = DemoOffer.shown(ui.signIn.coreUrl, ui.account.demoOff),
                onEvent = a.account,
                // The console QR, a bare code, or the field-api PC pairing QR (the old "I have a code from my PC").
                onScan = { if (!ui.connecting && !ui.signIn.busy) a.scanSignInCode() },
                onBack = { a.shell(ShellAction.Back) },
                onServers = { a.shell(ShellAction.Open(ShellPage.CONNECTIONS)) },
            )
        }
        FirstRunStep.FORGOT -> ForgotScreen(
            flow = ui.account,
            onEvent = a.account,
            onOpenMail = a.openMailApp,
            onBack = { a.shell(ShellAction.Back) },
            reduceMotion = still,
        )
        FirstRunStep.PERMISSIONS -> PermissionsScreen(
            reduceMotion = still,
            onAllow = a.requestPermission,
            onDone = { a.shell(ShellAction.Go(FirstRunStep.GLASSES)) },
        )
        FirstRunStep.GLASSES -> GlassesSetupScreen(
            advice = ui.glassesAdvice,
            reduceMotion = still,
            onSetUp = a.glassesSetUp,
            onTestPhoto = a.testCamera,
            onSkip = { a.shell(ShellAction.Go(FirstRunStep.SITE)) },
            onContinue = { a.shell(ShellAction.Go(FirstRunStep.SITE)) },
            probe = ui.probe,
        )
        FirstRunStep.SITE -> {
            val caps = capabilities(ui)
            val who = whoOf(ui)
            SitePickScreen(
                personName = ui.signedIn?.name ?: ui.person.name,
                sites = ui.sites,
                currentSiteId = ui.pairing?.siteId,
                homes = HomeRules.choices(caps),
                selected = HomeMemory.current(ui.shell.savedHome, who, caps),
                onSite = a.chooseSite,
                onHome = { h -> a.shell(ShellAction.PickHome(h, who)) },
                onContinue = { a.shell(ShellAction.FinishSetup) },
                pairedSiteName = ui.pairing?.siteName?.takeIf { ui.sites.isEmpty() },
                listAnswered = !ui.connecting,
            )
        }
    }
}

/**
 * The sign-in screen's state: the form's own, plus a PC-code pairing's failure (connectError while signed out), which
 * the interim screen showed under the card; and busy while that pairing is connecting.
 */
private fun signInState(ui: AppUi): SignInView {
    val pairingError = ui.connectError?.takeIf { ui.signedIn == null }
    return ui.signIn.copy(error = ui.signIn.error ?: pairingError, busy = ui.signIn.busy || ui.connecting)
}
