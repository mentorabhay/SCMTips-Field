package com.scmtips.field.app.ui.shell

import androidx.compose.runtime.Composable
import com.scmtips.field.app.AppUi
import com.scmtips.field.app.BuildConfig
import com.scmtips.field.app.SignInView
import com.scmtips.field.app.shell.AccountPages
import com.scmtips.field.app.shell.FirstRunStep
import com.scmtips.field.app.shell.HomeMemory
import com.scmtips.field.app.shell.HomeRules
import com.scmtips.field.app.shell.ShellAction
import com.scmtips.field.app.shell.ShellPage
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
 * as the contract's §4 table says (M5-U06). The screens never navigate by themselves; every move is a ShellAction.
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
        FirstRunStep.SIGN_IN -> SignInScreen(
            state = signInState(ui),
            onSignIn = a.signIn,
            onForgot = { a.shell(ShellAction.Go(FirstRunStep.FORGOT)) },
            onCreateAccount = { core -> a.openUrl(AccountPages.signup(core, BuildConfig.DEFAULT_CORE_URL)) },
            onPcCode = { if (!ui.connecting && !ui.signIn.busy) a.scanPairingCode() },
            onBack = { a.shell(ShellAction.Back) },
            onServers = { a.shell(ShellAction.Open(ShellPage.CONNECTIONS)) },
        )
        FirstRunStep.FORGOT -> ForgotScreen(
            email = ui.signIn.email,
            onOpenReset = { a.openUrl(AccountPages.reset(ui.signIn.coreUrl, BuildConfig.DEFAULT_CORE_URL)) },
            onCreateAccount = { a.openUrl(AccountPages.signup(ui.signIn.coreUrl, BuildConfig.DEFAULT_CORE_URL)) },
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
