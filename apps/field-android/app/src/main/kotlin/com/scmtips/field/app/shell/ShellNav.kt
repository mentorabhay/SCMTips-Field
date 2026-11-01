package com.scmtips.field.app.shell

/** The tab bar of the redesign: Home · Activity · Scan (centre, raised, gradient) · Inbox · Profile. */
enum class Tab(val title: String) {
    HOME("Home"), ACTIVITY("Activity"), SCAN("Scan"), INBOX("Inbox"), PROFILE("Profile"),
}

/** Full-screen pages under Profile (no tab bar); [parent] is where Back goes (null: back to the Profile tab). */
enum class ShellPage(val title: String, val parent: ShellPage?) {
    SETTINGS("Settings", null),
    CONNECTIONS("Connections", SETTINGS),
    DIAGNOSTICS("Diagnostics", SETTINGS),
}

/** The first-run graph: Welcome → Sign in (→ Forgot) → Permissions → Glasses (optional) → Site and role. */
enum class FirstRunStep(val beforeSignIn: Boolean) {
    WELCOME(true), SIGN_IN(true), FORGOT(true), PERMISSIONS(false), GLASSES(false), SITE(false),
}

/**
 * The first-run permission steps, in order (prototype Permissions.dc.html). [androidPermission] is the platform
 * name MainActivity asks for; [minSdk] the first Android version that has it (older ones grant it at install).
 * CAMERA is asked only when the merged manifest declares it (the phone camera app needs no permission otherwise).
 */
enum class PermissionStep(val title: String, val why: String, val androidPermission: String, val minSdk: Int) {
    CAMERA("Camera", "To read labels and count boxes when you use the phone instead of the glasses.", "android.permission.CAMERA", 1),
    MICROPHONE("Microphone", "So you can say \"look\", your numbers and \"confirm\". It listens only while a work session is open.",
        "android.permission.RECORD_AUDIO", 1),
    NEARBY("Nearby devices", "To connect your Ray-Ban Meta glasses through the Meta AI app.", "android.permission.BLUETOOTH_CONNECT", 31),
    NOTIFICATIONS("Notifications", "To tell you when a delivery arrives or a decision waits for you.", "android.permission.POST_NOTIFICATIONS", 33),
}

/**
 * The shell's own state (AppUi.shell). Remembered in SharedPreferences: [welcomeSeen], [setupDone], [savedHome],
 * [classic]. [reduceMotion] follows the system's "Remove animations" (ANIMATOR_DURATION_SCALE == 0).
 */
data class ShellView(
    val welcomeSeen: Boolean = false,
    val setupDone: Boolean = false,
    /** The first-run step asked for (Back / Next); null: derived by [FirstRun.step]. */
    val step: FirstRunStep? = null,
    val tab: Tab = Tab.HOME,
    val page: ShellPage? = null,
    /** HomeMemory.encode(who, home) of the last home picked in the switcher. */
    val savedHome: String? = null,
    /** Settings › Diagnostics › Classic layout: the old three tabs exactly as before (default off). */
    val classic: Boolean = false,
    val reduceMotion: Boolean = false,
)

/** Everything the new screens can ask the shell for (Actions.shell). */
sealed interface ShellAction {
    /** Welcome's "Get started" (and the judges' link): remembered, then Sign in. */
    data object Welcomed : ShellAction
    data class Go(val step: FirstRunStep) : ShellAction
    /** Site and role's "Continue": first run is over until the next sign-out. */
    data object FinishSetup : ShellAction
    data class SelectTab(val tab: Tab) : ShellAction
    data class Open(val page: ShellPage) : ShellAction
    data object Back : ShellAction
    /** The role switcher; [who] is HomeMemory.who of the signed-in account. */
    data class PickHome(val home: Home, val who: String?) : ShellAction
    data class Classic(val on: Boolean) : ShellAction
}

object FirstRun {
    /**
     * The first-run step to draw, or null for the role home. Not signed in and not paired: Welcome (until seen) or
     * Sign in (Forgot when asked). Connected but setup not finished: Permissions, Glasses, Site (as asked).
     */
    fun step(s: ShellView, connected: Boolean): FirstRunStep? {
        val asked = s.step
        return when {
            !connected -> asked?.takeIf { it.beforeSignIn } ?: if (s.welcomeSeen) FirstRunStep.SIGN_IN else FirstRunStep.WELCOME
            s.setupDone -> null
            asked != null && !asked.beforeSignIn -> asked
            else -> FirstRunStep.PERMISSIONS
        }
    }

    /**
     * An install from before the redesign that is already signed in or paired has done its setup and seen the
     * welcome: it opens at its home, not at Permissions. [stored] is the saved flag (null: never saved).
     */
    fun initialFlag(stored: Boolean?, connectedAtStart: Boolean): Boolean = stored ?: connectedAtStart

    fun next(step: FirstRunStep): FirstRunStep? = when (step) {
        FirstRunStep.WELCOME -> FirstRunStep.SIGN_IN
        FirstRunStep.SIGN_IN, FirstRunStep.FORGOT -> FirstRunStep.SIGN_IN // signing in moves on by itself
        FirstRunStep.PERMISSIONS -> FirstRunStep.GLASSES
        FirstRunStep.GLASSES -> FirstRunStep.SITE
        FirstRunStep.SITE -> null
    }

    /** Where Back goes inside first run; null: the system's Back (leave the app). */
    fun back(step: FirstRunStep): FirstRunStep? = when (step) {
        FirstRunStep.WELCOME, FirstRunStep.PERMISSIONS -> null
        FirstRunStep.SIGN_IN -> FirstRunStep.WELCOME
        FirstRunStep.FORGOT -> FirstRunStep.SIGN_IN
        FirstRunStep.GLASSES -> FirstRunStep.PERMISSIONS
        FirstRunStep.SITE -> FirstRunStep.GLASSES
    }
}

object ShellNav {
    /** [connected]: signed in or paired (Back walks the first-run graph only while it is shown). */
    fun reduce(s: ShellView, a: ShellAction, connected: Boolean): ShellView = when (a) {
        ShellAction.Welcomed -> s.copy(welcomeSeen = true, step = FirstRunStep.SIGN_IN)
        is ShellAction.Go -> s.copy(step = a.step, welcomeSeen = s.welcomeSeen || a.step != FirstRunStep.WELCOME)
        ShellAction.FinishSetup -> s.copy(setupDone = true, welcomeSeen = true, step = null, tab = Tab.HOME, page = null)
        is ShellAction.SelectTab -> s.copy(tab = a.tab, page = null)
        is ShellAction.Open -> if (connected) s.copy(page = a.page, tab = Tab.PROFILE) else s.copy(page = a.page)
        ShellAction.Back -> back(s, connected) ?: s
        is ShellAction.PickHome -> s.copy(savedHome = HomeMemory.encode(a.who, a.home), tab = Tab.HOME, page = null)
        is ShellAction.Classic -> s.copy(classic = a.on)
    }

    /**
     * Back inside the shell, or null when the system's Back should run (leave the app from Home or the first
     * screen). A page goes to its parent, then Profile; another tab goes Home; first run walks its graph back.
     */
    fun back(s: ShellView, connected: Boolean): ShellView? {
        // Signed out, Connections is opened from the sign-in screen: Back returns there.
        if (!connected && s.page != null) return s.copy(page = null)
        FirstRun.step(s, connected)?.let { step -> return FirstRun.back(step)?.let { s.copy(step = it) } }
        s.page?.let { p -> return s.copy(page = p.parent) }
        if (s.tab != Tab.HOME) return s.copy(tab = Tab.HOME)
        return null
    }

    /** Signed out, only Connections is drawn over the sign-in screen (servers, PC code); other pages wait for a sign-in. */
    fun signedOutPage(s: ShellView, connected: Boolean): ShellPage? = if (!connected && s.page == ShellPage.CONNECTIONS) s.page else null

    /** Sign out: the setup runs again at the next sign-in; the home choice is forgotten; welcome and layout stay. */
    fun signedOut(s: ShellView): ShellView = ShellView(welcomeSeen = s.welcomeSeen, classic = s.classic, reduceMotion = s.reduceMotion)
}

/**
 * Create account and forgot password open the SCMTIPS pages (A-07 decision): https://app.scmtips.com/signup and
 * /reset for the build's default core; for another SCMTIPS address the web app is derived from it: an "api." host
 * becomes "app." (https://api.acme.example → https://app.acme.example), any other address is used as it is.
 */
object AccountPages {
    const val WEB_APP = "https://app.scmtips.com"

    fun webApp(coreUrl: String?, defaultCoreUrl: String): String {
        val core = coreUrl?.trim()?.trimEnd('/')?.takeIf { it.startsWith("http://") || it.startsWith("https://") }
            ?: return WEB_APP
        if (core == defaultCoreUrl.trim().trimEnd('/')) return WEB_APP
        val scheme = core.substringBefore("://")
        val rest = core.substringAfter("://")
        val hostPort = rest.substringBefore('/')
        return if (hostPort.startsWith("api.")) "$scheme://app.${hostPort.removePrefix("api.")}" else "$scheme://$hostPort"
    }

    fun reset(coreUrl: String?, defaultCoreUrl: String): String = webApp(coreUrl, defaultCoreUrl) + "/reset"
    fun signup(coreUrl: String?, defaultCoreUrl: String): String = webApp(coreUrl, defaultCoreUrl) + "/signup"
}

/** The one status pill in the home header (it replaces Today's chip row). */
enum class PillTone { GOOD, NEUTRAL, WARN }

data class StatusPill(val text: String, val tone: PillTone, val live: Boolean) {
    companion object {
        /** Offline beats Connecting beats Glasses ready beats Phone camera; a sandbox site adds " · Sandbox". */
        fun of(offline: Boolean, connecting: Boolean, glassesReady: Boolean, sandbox: Boolean): StatusPill {
            val base = when {
                offline -> StatusPill("Offline", PillTone.WARN, live = false)
                connecting -> StatusPill("Connecting", PillTone.NEUTRAL, live = true)
                glassesReady -> StatusPill("Glasses ready", PillTone.GOOD, live = true)
                else -> StatusPill("Phone camera", PillTone.NEUTRAL, live = false)
            }
            return if (sandbox) base.copy(text = base.text + " · Sandbox") else base
        }
    }
}

/** Small words of the shell: greeting, role chips, motion. */
object ShellText {
    fun greeting(hour: Int): String = when (hour) {
        in 5..11 -> "Good morning"
        in 12..16 -> "Good afternoon"
        else -> "Good evening"
    }

    /** Profile's role chips, from the capabilities the app already has (a PC pairing is field work). */
    fun roleChips(approver: Boolean, fieldOperator: Boolean, signedIn: Boolean): List<String> = buildList {
        if (fieldOperator) add(if (signedIn) "Warehouse operator" else "Field operator (PC pairing)")
        if (approver) add("Approver")
        if (isEmpty()) add("No app roles")
    }

    /** Connections' state word for the field server, and its tone. */
    fun serverState(connecting: Boolean, offline: Boolean, error: Boolean, deviceKnown: Boolean): Pair<String, PillTone> = when {
        connecting -> "Connecting" to PillTone.NEUTRAL
        offline -> "Offline" to PillTone.WARN
        error -> "Problem" to PillTone.WARN
        deviceKnown -> "Connected" to PillTone.GOOD
        else -> "Not linked" to PillTone.NEUTRAL
    }

    /** Settings › Scanning with: every scanner the app has, glasses first (the prototype's two plus the handheld). */
    val scannerChoices: List<Pair<com.scmtips.field.app.jobs.ScannerKind, String>> = listOf(
        com.scmtips.field.app.jobs.ScannerKind.GLASSES to "Glasses",
        com.scmtips.field.app.jobs.ScannerKind.CAMERA to "Phone camera",
        com.scmtips.field.app.jobs.ScannerKind.HANDHELD to "Handheld",
    )

    /** Settings.Global.ANIMATOR_DURATION_SCALE == 0 is Android's "Remove animations". */
    fun reduceMotion(animatorDurationScale: Float): Boolean = animatorDurationScale == 0f
}
