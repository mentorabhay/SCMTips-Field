package com.scmtips.field.app.ui.firstrun

import com.scmtips.field.app.assistant.SiteModes
import com.scmtips.field.app.glasses.GlassesAdvice
import com.scmtips.field.app.look.CameraProbe
import com.scmtips.field.app.shell.Home
import com.scmtips.field.app.shell.HomeChoice
import com.scmtips.field.app.shell.PermissionStep
import com.scmtips.field.app.signin.SiteRef

// Pure models and rules of the first-run screens (M5-U02, prototype Main/SignIn/Forgot/Permissions/Glasses/Site
// .dc.html). The Compose screens next to this file only draw them; every rule here is JVM-tested (FirstRunModelsTest).

/** The three welcome cards (Main.dc.html), in order. */
enum class WelcomeCard(val title: String, val body: String, val art: String) {
    LOOK("Look", "One look with your glasses counts the delivery and reads every label.",
        "Glasses looking at three boxes, each gets a numbered outline"),
    HEAR("Hear", "The glasses tell you what they found: count, damage, pack size, expiry.",
        "Sound waves: the glasses speak the count"),
    CONFIRM("Confirm", "You say the numbers and \"confirm\". Every posting gets an evidence page.",
        "A ring counting down around a confirm tick"),
    ;

    companion object {
        /** The page after [page], or null on the last card ("Next" is hidden there; "Get started" stays). */
        fun next(page: Int): Int? = (page + 1).takeIf { it < entries.size }

        /** The page dot's spoken label, e.g. "Card 2 of 3: Hear". */
        fun dotLabel(page: Int): String = "Card ${page + 1} of ${entries.size}: ${entries[page].title}"
    }
}

/**
 * The permission steps the phone asks one at a time (Permissions.dc.html): the shell's [PermissionStep]s this
 * Android version has ([PermissionStep.minSdk]; older versions grant them at install), minus those already granted.
 * "Allow" asks the system (the shell's onAllow), "Not now" skips the step and never asks.
 */
object PermissionPlan {
    fun steps(sdkInt: Int, granted: Set<String> = emptySet()): List<PermissionStep> =
        PermissionStep.entries.filter { sdkInt >= it.minSdk && it.androidPermission !in granted }

    /** The index after [index] in [steps], or null when the plan is finished (then the shell's onDone). */
    fun after(steps: List<PermissionStep>, index: Int): Int? = (index + 1).takeIf { it < steps.size }

    /** "Set up · 2 of 4". */
    fun progress(index: Int, total: Int): String = "Set up · ${index + 1} of $total"

    fun allowLabel(index: Int, total: Int): String = if (index >= total - 1) "Allow and continue" else "Allow"
}

/** One of the three glasses steps (Glasses.dc.html) and how far it is. */
enum class StepMark { DONE, CURRENT, LATER }

data class GlassesStepRow(val title: String, val sub: String, val mark: StepMark)

/** What the glasses screen's main button does now. */
enum class GlassesCta(val label: String) {
    /** Step 1 is the person's own: they put the glasses on and say so (nothing is sent). */
    AWAKE("They are on"),
    SET_UP("Open Meta AI"),
    CONNECT("Connect the glasses"),
    TEST_PHOTO("Take a test photo"),
    CONTINUE("Glasses ready · Continue"),

    /** The toolkit is busy (connecting, paused): no button, the status line says what is happening. */
    WAIT("Waiting for the glasses…"),
}

/**
 * The glasses setup, from the app's real glasses state only ([GlassesAdvice] from GlassesHelp, the Me camera test's
 * [CameraProbe]) plus the person's own "They are on". Step 2 is done once the Meta AI app has approved SCMTips Field
 * (the advice no longer asks to set up); step 3 once a test photo arrived. The glasses are optional: Skip always works.
 */
data class GlassesSetupModel(
    val rows: List<GlassesStepRow>,
    val cta: GlassesCta,
    /** GlassesHelp's sentence, shown under the steps (the real state, e.g. "Finish in the Meta AI app…"). */
    val status: String,
    val busy: Boolean,
    /** The toolkit did not start: the phone camera does the work; Skip is the way on. */
    val toolkitDown: Boolean,
    /** "640 × 480 px from the glasses in 1.2 s" after a test photo. */
    val photo: String?,
) {
    companion object {
        val STEPS = listOf(
            "Wake the glasses" to "Put them on and tap the side.",
            "Approve in Meta AI" to "The Meta AI app opens; allow SCMTips Field.",
            "Test photo" to "One photo shows the camera works; nothing is uploaded.",
        )

        /** GlassesHelp.advise's first words when the Meta toolkit did not start (GlassesSetupModel test pins them). */
        const val TOOLKIT_DOWN_PREFIX = "The glasses toolkit did not start"

        fun from(advice: GlassesAdvice, awake: Boolean, probe: CameraProbe? = null): GlassesSetupModel {
            val toolkitDown = !advice.ready && advice.action == GlassesAdvice.Action.NONE && advice.text.startsWith(TOOLKIT_DOWN_PREFIX)
            val woke = awake || advice.ready
            val approved = advice.action != GlassesAdvice.Action.REGISTER && !toolkitDown
            val photo = probe?.summary
            val current = when {
                !woke -> 0
                !approved -> 1
                photo == null -> 2
                else -> 3
            }
            val rows = STEPS.mapIndexed { i, (t, s) ->
                GlassesStepRow(t, s, when {
                    i < current -> StepMark.DONE
                    i == current -> StepMark.CURRENT
                    else -> StepMark.LATER
                })
            }
            val busy = probe?.busy == true
            val cta = when {
                toolkitDown -> GlassesCta.WAIT
                current == 0 -> GlassesCta.AWAKE
                current == 1 -> GlassesCta.SET_UP
                current == 3 -> GlassesCta.CONTINUE
                advice.ready -> GlassesCta.TEST_PHOTO
                advice.action == GlassesAdvice.Action.CONNECT -> GlassesCta.CONNECT
                else -> GlassesCta.WAIT
            }
            return GlassesSetupModel(rows, cta, probe?.message ?: advice.text, busy, toolkitDown, photo)
        }
    }
}

/** One site row of "Where are you working?" (Site.dc.html). */
data class SiteOption(val id: String, val name: String, val sub: String, val sandbox: Boolean, val selected: Boolean)

object SitePick {
    /** field-api's sites in its order; a sandbox site says so (it is where the home test cases run). */
    fun options(sites: List<SiteRef>, currentSiteId: String?): List<SiteOption> = sites.map { s ->
        val sandbox = s.mode == SiteModes.SANDBOX
        SiteOption(s.id, s.name, if (sandbox) "Sandbox · test at home with real products" else "Live site · postings go to the ERP",
            sandbox, s.id == currentSiteId)
    }

    /**
     * A sign-in needs a chosen site; a PC pairing (no list) already has its site. [listAnswered]: field-api has
     * answered (or there was nothing to ask, e.g. an approver-only account): an empty list then lets the person on to
     * Home (approvals and the shell's "no field site linked" cards still work) instead of a Continue that never
     * enables. While the list is still being asked for, an empty list waits.
     */
    fun canContinue(sites: List<SiteRef>, currentSiteId: String?, pairedSiteName: String?, listAnswered: Boolean = false): Boolean =
        if (sites.isEmpty()) pairedSiteName != null || listAnswered else sites.any { it.id == currentSiteId }

    /** The line under "What are you doing now?": how many homes the account can act in. */
    fun roleNote(homes: List<HomeChoice>): String {
        val n = homes.count { it.canAct }
        val what = when (n) {
            0 -> "Your account can only view these homes."
            1 -> "Your account can act in one of these; the others are view only."
            homes.size -> "Your account can act in all of these."
            else -> "Your account can act in $n of these; the others are view only."
        }
        return "$what You can switch any time at the top of Home."
    }
}

/** The line under each home on "What are you doing now?" (Site.dc.html). */
object HomeBlurb {
    fun of(home: Home): String = when (home) {
        Home.WAREHOUSE -> "Receive, put away, pick, count"
        Home.TOWER -> "Check in, audit a sector, swap a unit"
        Home.APPROVALS -> "Decisions and claims waiting"
        Home.SCAN -> "Is this unit really new?"
    }
}

object SignInRules {
    /** As the M4 sign-in form: something typed in both fields (judge accounts may be names, not e-mails). */
    fun canSubmit(email: String, password: String, busy: Boolean): Boolean = !busy && email.isNotBlank() && password.isNotEmpty()

    fun cleanEmail(raw: String): String = raw.trim().take(254)

    const val SAMPLE_NOTE = "SAMPLE data only. Judges: use the judge01 to judge05 accounts from the submission notes."

    /** The app keeps the phone signed in until Profile › Sign out; the screen says so instead of a dead switch. */
    const val KEEP_NOTE = "You stay signed in on this phone until you sign out in Profile."
}

/** The "Create an account" sheet without an invite (M5-L contract §7). */
object CreateText {
    const val BODY = "SCMTIPS accounts belong to an organisation. Your administrator adds you, and SCMTIPS e-mails you an " +
        "invite: open it on this phone, or paste its link here."
    const val ASK = "No invite yet? Ask your SCMTIPS administrator for one. To look around first, try the SAMPLE demo."
}

/**
 * The A-07 words of the browser reset (the SCMTIPS page). M5-L draws [ResetText] instead; these stay, with their test,
 * until the owner retires them (rule 2.5: a test is never deleted to make room).
 */
object ForgotText {
    const val INTRO = "SCMTIPS sends a reset link to your work e-mail. The link opens the SCMTIPS page; " +
        "SCMTips Field never sees your password."

    /** After "Open the reset page": the app cannot know whether a mail went out, so it says what to do next. */
    fun afterOpen(email: String): String = email.trim().takeIf { it.isNotEmpty() }
        ?.let { "Finish on the SCMTIPS page. If an account exists for $it, SCMTIPS sends the reset link there." }
        ?: "Finish on the SCMTIPS page. SCMTIPS sends the reset link to your work e-mail."
}

/** M5-L: the reset happens in the app; the e-mailed link opens SCMTips Field at "Set a new password". */
object ResetText {
    const val INTRO = "Enter your work e-mail. If it has an account, SCMTIPS e-mails you a link that opens this app at " +
        "\"Set a new password\"."
    const val SET_INTRO = "Choose a new password for your SCMTIPS account: at least 12 characters, not used before."
}
