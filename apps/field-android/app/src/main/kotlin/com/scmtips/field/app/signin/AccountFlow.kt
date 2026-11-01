package com.scmtips.field.app.signin

import com.scmtips.field.feature.decisions.api.AcceptReply
import com.scmtips.field.feature.decisions.api.AcceptRules
import com.scmtips.field.feature.decisions.api.InviteAcceptance
import com.scmtips.field.feature.decisions.api.InviteReply
import com.scmtips.field.feature.decisions.api.InviteState
import com.scmtips.field.feature.decisions.api.MailReply
import com.scmtips.field.feature.decisions.api.PasswordPolicy
import com.scmtips.field.feature.decisions.api.PublicInvite
import com.scmtips.field.feature.decisions.api.ResetReply
import com.scmtips.field.feature.decisions.api.SignInMethod

/**
 * The in-app account flow of M5-L (docs/design/M5_SIGNIN_CONTRACT.md §7): the sign-in screen's stages, the in-app
 * invite and the in-app password reset. Pure: [AccountFlow.reduce] takes an [AccountEvent] (a tap, an App Link, or
 * the answer of a call) and gives the next [AccountView] plus the [AccountEffect]s FieldController runs (calls to the
 * core, a sign-in, a first-run step). The browser is never part of it.
 */

/** Where the sign-in screen is (first-run step SIGN_IN). [parent] is where Back goes; null: the shell's Back. */
enum class SignInStage(val parent: SignInStage?) {
    /** The five ways in. */
    CHOOSE(null),
    /** "Continue with e-mail": the e-mail field, then "Use my password" or "E-mail me a code". */
    EMAIL(CHOOSE),
    PASSWORD(EMAIL),
    /** The 6 boxes of the e-mailed code. */
    CODE(EMAIL),
    /** "I have an invite": paste a link or code. */
    INVITE_ENTER(CHOOSE),
    /** The invite: organisation and role, name, password, consents. */
    INVITE(CHOOSE),
    /** "Create account" without an invite: accounts come from an organisation. */
    CREATE(CHOOSE),
}

/** Where the reset is (first-run step FORGOT). */
enum class ResetStage { REQUEST, SENT, SET }

/** The flow's state (AppUi.account). No password or code is ever kept here: AppUi is drawn and logged freely. */
data class AccountView(
    val stage: SignInStage = SignInStage.CHOOSE,
    val reset: ResetStage = ResetStage.REQUEST,
    /** The e-mail typed on any of the screens (one field, filled everywhere). */
    val email: String = "",
    /** When the last code e-mail was asked for (the resend timer), null before. */
    val codeSentAtMs: Long? = null,
    /** True once the last code tried was refused: the boxes are cleared and that code is not sent again. */
    val codeRefused: Boolean = false,
    val inviteToken: String? = null,
    val invite: PublicInvite? = null,
    /** The token of the reset link that opened "Set a new password" (it goes only to the core's confirm). */
    val resetToken: String? = null,
    val busy: Boolean = false,
    /** A neutral line the screen shows in its info box (a code is on its way, the password was changed). */
    val notice: String? = null,
    val error: String? = null,
    /** The password-policy messages of the last set-password or invite answer (shown under the password field). */
    val policy: List<String> = emptyList(),
    /** SCMTIPS addresses that answered 403 demo_off: the demo button is hidden for them. */
    val demoOff: Set<String> = emptySet(),
) {
    override fun toString(): String =
        "AccountView(stage=$stage, reset=$reset, email=$email, busy=$busy, invite=${invite?.organisation}, resetLink=${resetToken != null})"
}

sealed interface AccountEvent {
    data class Open(val stage: SignInStage) : AccountEvent
    data object Back : AccountEvent
    data class Email(val email: String) : AccountEvent
    data object UsePassword : AccountEvent
    class Password(val password: String) : AccountEvent {
        override fun toString(): String = "Password(<redacted>)"
    }
    /** "E-mail me a code", and "Resend code" (refused before the 30 s are over). */
    data class SendCode(val nowMs: Long) : AccountEvent
    /** The boxes changed (typed or pasted): a full code that was not just refused signs in by itself. */
    class Code(val code: String) : AccountEvent {
        override fun toString(): String = "Code(<redacted>)"
    }
    data object Demo : AccountEvent
    data class Pasted(val text: String) : AccountEvent
    data class Scanned(val text: String) : AccountEvent
    /** An App Link opened the app; [signedIn]: a sign-in or pairing is already on this phone. */
    data class Link(val link: AppLink, val signedIn: Boolean) : AccountEvent
    class Accept(val name: String, val password: String, val terms: Boolean, val dpdp: Boolean) : AccountEvent {
        override fun toString(): String = "Accept(name=$name, password=<redacted>, terms=$terms, dpdp=$dpdp)"
    }
    data object Forgot : AccountEvent
    data class ResetEmail(val email: String) : AccountEvent
    class NewPassword(val password: String, val again: String) : AccountEvent {
        override fun toString(): String = "NewPassword(<redacted>)"
    }

    // --- answers (FieldController, after an effect) ---
    data class CodeSent(val reply: MailReply, val atMs: Long) : AccountEvent
    data class InviteRead(val token: String, val reply: InviteReply) : AccountEvent
    class InviteAccepted(val reply: AcceptReply, val email: String, val password: String) : AccountEvent {
        override fun toString(): String = "InviteAccepted($reply, email=$email, password=<redacted>)"
    }
    data class ResetSent(val reply: MailReply) : AccountEvent
    data class ResetDone(val reply: ResetReply) : AccountEvent
    /**
     * A sign-in was refused at [coreUrl]: 403 demo_off hides the demo button for that address ([demoOff]); a refused
     * e-mail code marks the code as refused, so the screen clears the boxes and the same code is not sent again.
     */
    data class SignInFailed(val coreUrl: String, val demoOff: Boolean, val method: SignInMethod?) : AccountEvent
}

sealed interface AccountEffect {
    /** FieldController.signIn at the SCMTIPS address the screen is set to. */
    data class SignIn(val method: SignInMethod) : AccountEffect
    data class RequestCode(val email: String) : AccountEffect
    data class LoadInvite(val token: String) : AccountEffect {
        override fun toString(): String = "LoadInvite(<redacted>)"
    }
    class AcceptInvite(val token: String, val acceptance: InviteAcceptance, val email: String) : AccountEffect {
        override fun toString(): String = "AcceptInvite($acceptance, email=$email)"
    }
    data class RequestReset(val email: String) : AccountEffect
    class ConfirmReset(val token: String, val password: String) : AccountEffect {
        override fun toString(): String = "ConfirmReset(<redacted>)"
    }
    /** Show this first-run step (ShellAction.Go). */
    data class Show(val step: com.scmtips.field.app.shell.FirstRunStep) : AccountEffect
    /** The field-api PC pairing QR (FieldController.pair), as "I have a code from my PC" did. */
    data class PcPairing(val text: String) : AccountEffect
}

data class AccountStep(val view: AccountView, val effects: List<AccountEffect> = emptyList())

object AccountText {
    const val CODE_ON_ITS_WAY = "If that e-mail has an account, a code is on its way. It works for 10 minutes."
    const val RESET_ON_ITS_WAY = "If that e-mail has an account, a reset link is on its way. It works for 30 minutes and only once. " +
        "Open the link on this phone and SCMTips Field opens at \"Set a new password\"."
    const val ENTER_EMAIL = "Enter your work e-mail address."
    const val NO_CODE_ROUTE = "This SCMTIPS server cannot e-mail sign-in codes. Use your password, or scan a code from your computer."
    const val NO_RESET_ROUTE = "This SCMTIPS server cannot e-mail reset links. Ask your SCMTIPS administrator to reset your password."
    const val NOT_A_CODE = "That is not a SCMTIPS sign-in code. On your computer, open SCMTIPS Field and choose \"Sign in your phone\"."
    const val NOT_AN_INVITE = "Paste the whole invite link from the e-mail, or its 43-character code."
    const val INVITE_INVALID = "This invite is not valid. Check that you copied the whole link from the e-mail."
    const val RESET_INVALID = "This reset link is not valid or has expired. Ask for a new one."
    const val RESET_SSO = "Your organisation signs in with single sign-on, so SCMTIPS keeps no password to reset. " +
        "Sign in on your computer and scan its sign-in code."
    const val PASSWORD_CHANGED = "Your password was changed. Sign in with the new one."
    const val SIGNED_IN_ALREADY = "This phone is already signed in. Sign out in Profile first, then open the link again."

    fun inviteClosed(state: InviteState): String? = when (state) {
        InviteState.PENDING -> null
        InviteState.ACCEPTED -> "This invite was already used. Sign in with the account it created."
        InviteState.REVOKED -> "This invite was revoked. Ask your administrator for a new one."
        InviteState.EXPIRED -> "This invite has expired. Ask your administrator to send it again."
    }

    fun joined(organisation: String) = "You joined $organisation. Signing you in…"

    /** "You are invited to <org> as Approver, Procurement." */
    fun invited(i: PublicInvite): String =
        "You are invited to ${i.organisation}" + (i.roleNames.takeIf { it.isNotEmpty() }?.joinToString(", ", prefix = " as ") ?: "") + "."
}

object AccountFlow {
    private fun validEmail(e: String) = e.trim().let { it.contains('@') && it.length in 3..254 }

    fun reduce(v: AccountView, e: AccountEvent): AccountStep = when (e) {
        is AccountEvent.Open -> AccountStep(
            if (e.stage == SignInStage.INVITE_ENTER) v.copy(stage = e.stage, error = null, notice = null, policy = emptyList(), invite = null, inviteToken = null)
            else v.copy(stage = e.stage, error = null, notice = null, policy = emptyList()),
        )
        AccountEvent.Back -> back(v)?.let { AccountStep(it) } ?: AccountStep(v)
        is AccountEvent.Email -> AccountStep(v.copy(email = e.email.take(254), error = null))
        AccountEvent.UsePassword ->
            if (validEmail(v.email)) AccountStep(v.copy(stage = SignInStage.PASSWORD, error = null, notice = null))
            else AccountStep(v.copy(error = AccountText.ENTER_EMAIL))
        is AccountEvent.Password -> AccountStep(v.copy(error = null, notice = null), listOf(AccountEffect.SignIn(SignInMethod.Password(v.email.trim(), e.password))))
        is AccountEvent.SendCode -> when {
            !validEmail(v.email) -> AccountStep(v.copy(error = AccountText.ENTER_EMAIL))
            v.busy -> AccountStep(v)
            v.stage == SignInStage.CODE && !ResendTimer.canResend(v.codeSentAtMs, e.nowMs) -> AccountStep(v)
            else -> AccountStep(v.copy(busy = true, error = null), listOf(AccountEffect.RequestCode(v.email.trim())))
        }
        is AccountEvent.CodeSent -> when (val r = e.reply) {
            MailReply.Accepted -> AccountStep(v.copy(busy = false, stage = SignInStage.CODE, codeSentAtMs = e.atMs, codeRefused = false,
                notice = AccountText.CODE_ON_ITS_WAY, error = null))
            MailReply.NotAvailable -> AccountStep(v.copy(busy = false, error = AccountText.NO_CODE_ROUTE))
            is MailReply.Offline -> AccountStep(v.copy(busy = false, error = r.message))
        }
        is AccountEvent.Code -> {
            val code = CodeEntry.clean(e.code)
            when {
                code.length < CodeEntry.LENGTH -> AccountStep(if (v.codeRefused) v.copy(codeRefused = false) else v)
                !CodeEntry.shouldSubmit(code, null, v.busy) || v.codeRefused -> AccountStep(v)
                else -> AccountStep(v.copy(error = null), listOf(AccountEffect.SignIn(SignInMethod.EmailCode(v.email.trim(), code))))
            }
        }
        AccountEvent.Demo -> AccountStep(v.copy(error = null), listOf(AccountEffect.SignIn(SignInMethod.Demo)))
        is AccountEvent.SignInFailed -> AccountStep(v.copy(
            demoOff = if (e.demoOff) v.demoOff + e.coreUrl else v.demoOff,
            codeRefused = v.codeRefused || e.method is SignInMethod.EmailCode,
        ))
        is AccountEvent.Pasted -> when (val link = SignInLinks.pasted(e.text)) {
            null -> AccountStep(v.copy(error = AccountText.NOT_AN_INVITE))
            else -> open(v, link)
        }
        is AccountEvent.Scanned -> when (val s = SignInLinks.scanned(e.text)) {
            is SignInLinks.Scanned.Link -> open(v, s.link)
            is SignInLinks.Scanned.PcPairing -> AccountStep(v.copy(error = null), listOf(AccountEffect.PcPairing(s.text)))
            is SignInLinks.Scanned.Code -> AccountStep(v.copy(stage = SignInStage.CHOOSE, error = null),
                listOf(AccountEffect.SignIn(SignInMethod.PairingCode(s.code))))
            SignInLinks.Scanned.NotACode -> AccountStep(v.copy(error = AccountText.NOT_A_CODE))
        }
        is AccountEvent.Link -> if (e.signedIn) AccountStep(v.copy(error = AccountText.SIGNED_IN_ALREADY)) else open(v, e.link)
        is AccountEvent.InviteRead -> when {
            e.token != v.inviteToken -> AccountStep(v) // an answer for an invite no longer on the screen
            else -> when (val r = e.reply) {
                is InviteReply.Found -> AccountStep(v.copy(busy = false, invite = r.invite, error = AccountText.inviteClosed(r.invite.state),
                    email = r.invite.email.ifBlank { v.email }))
                InviteReply.Invalid -> AccountStep(v.copy(busy = false, invite = null, error = AccountText.INVITE_INVALID))
                is InviteReply.Failed -> AccountStep(v.copy(busy = false, error = r.message))
            }
        }
        is AccountEvent.Accept -> {
            val invite = v.invite
            val token = v.inviteToken
            if (invite == null || token == null || invite.state != InviteState.PENDING || v.busy) AccountStep(v)
            else {
                val a = InviteAcceptance(invite.accountExists, e.name, e.password, e.terms, e.dpdp)
                when (val why = AcceptRules.problem(a)) {
                    null -> AccountStep(v.copy(busy = true, error = null, policy = emptyList()), listOf(AccountEffect.AcceptInvite(token, a, invite.email)))
                    else -> AccountStep(v.copy(error = why))
                }
            }
        }
        is AccountEvent.InviteAccepted -> when (val r = e.reply) {
            is AcceptReply.Accepted -> AccountStep(
                // The sign-in that follows shows its answer on the password stage (the e-mail filled), not on a used invite.
                v.copy(busy = false, error = null, policy = emptyList(), email = e.email, notice = AccountText.joined(v.invite?.organisation ?: "SCMTIPS"),
                    inviteToken = null, invite = null, stage = SignInStage.PASSWORD),
                listOf(AccountEffect.SignIn(SignInMethod.Password(e.email, e.password))),
            )
            is AcceptReply.Policy -> AccountStep(v.copy(busy = false, policy = r.messages, error = null))
            is AcceptReply.Failed -> AccountStep(v.copy(busy = false, error = r.message))
        }
        AccountEvent.Forgot -> AccountStep(v.copy(reset = ResetStage.REQUEST, resetToken = null, error = null, notice = null, policy = emptyList()),
            listOf(AccountEffect.Show(com.scmtips.field.app.shell.FirstRunStep.FORGOT)))
        is AccountEvent.ResetEmail -> {
            val email = e.email.trim().take(254)
            when {
                !validEmail(email) -> AccountStep(v.copy(email = email, error = AccountText.ENTER_EMAIL))
                v.busy -> AccountStep(v)
                else -> AccountStep(v.copy(email = email, busy = true, error = null), listOf(AccountEffect.RequestReset(email)))
            }
        }
        is AccountEvent.ResetSent -> when (val r = e.reply) {
            MailReply.Accepted -> AccountStep(v.copy(busy = false, reset = ResetStage.SENT, notice = AccountText.RESET_ON_ITS_WAY, error = null))
            MailReply.NotAvailable -> AccountStep(v.copy(busy = false, error = AccountText.NO_RESET_ROUTE))
            is MailReply.Offline -> AccountStep(v.copy(busy = false, error = r.message))
        }
        is AccountEvent.NewPassword -> {
            val token = v.resetToken
            val local = PasswordPolicy.local(e.password, e.again)
            when {
                token == null -> AccountStep(v.copy(error = AccountText.RESET_INVALID))
                v.busy -> AccountStep(v)
                local.isNotEmpty() -> AccountStep(v.copy(policy = local, error = null))
                else -> AccountStep(v.copy(busy = true, policy = emptyList(), error = null), listOf(AccountEffect.ConfirmReset(token, e.password)))
            }
        }
        is AccountEvent.ResetDone -> when (val r = e.reply) {
            ResetReply.Done -> AccountStep(
                v.copy(busy = false, reset = ResetStage.REQUEST, resetToken = null, policy = emptyList(), error = null,
                    stage = if (validEmail(v.email)) SignInStage.PASSWORD else SignInStage.EMAIL, notice = AccountText.PASSWORD_CHANGED),
                listOf(AccountEffect.Show(com.scmtips.field.app.shell.FirstRunStep.SIGN_IN)),
            )
            ResetReply.Sso -> AccountStep(v.copy(busy = false, error = AccountText.RESET_SSO))
            ResetReply.InvalidLink -> AccountStep(v.copy(busy = false, error = AccountText.RESET_INVALID))
            is ResetReply.Policy -> AccountStep(v.copy(busy = false, policy = r.messages))
            is ResetReply.Failed -> AccountStep(v.copy(busy = false, error = r.message))
        }
    }

    /** Back inside the sign-in screen: to the stage's parent; null when the shell's Back should run. */
    fun back(v: AccountView): AccountView? =
        v.stage.parent?.let { v.copy(stage = it, error = null, notice = null, policy = emptyList(), busy = false) }

    private fun open(v: AccountView, link: AppLink): AccountStep = when (link) {
        is AppLink.Pair -> AccountStep(v.copy(stage = SignInStage.CHOOSE, error = null),
            listOf(AccountEffect.Show(com.scmtips.field.app.shell.FirstRunStep.SIGN_IN), AccountEffect.SignIn(SignInMethod.PairingCode(link.code))))
        is AppLink.Invite -> AccountStep(
            v.copy(stage = SignInStage.INVITE, inviteToken = link.token, invite = null, busy = true, error = null, notice = null, policy = emptyList()),
            listOf(AccountEffect.Show(com.scmtips.field.app.shell.FirstRunStep.SIGN_IN), AccountEffect.LoadInvite(link.token)),
        )
        is AppLink.Reset -> AccountStep(
            v.copy(reset = ResetStage.SET, resetToken = link.token, busy = false, error = null, notice = null, policy = emptyList()),
            listOf(AccountEffect.Show(com.scmtips.field.app.shell.FirstRunStep.FORGOT)),
        )
    }
}
