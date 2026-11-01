package com.scmtips.field.app.shell

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** M5-U01 / M5-U05: first-run gating, the shell's back stack, the SCMTIPS pages, the status pill, reduce motion. */
class ShellNavTest {
    private val fresh = ShellView()

    @Test
    fun m5_u01_firstRunShowsOnlyWhenNotSignedInAndNotPaired() {
        assertEquals(FirstRunStep.WELCOME, FirstRun.step(fresh, connected = false))
        val seen = ShellNav.reduce(fresh, ShellAction.Welcomed, connected = false)
        assertTrue(seen.welcomeSeen)
        assertEquals(FirstRunStep.SIGN_IN, FirstRun.step(seen, connected = false))
        assertEquals(FirstRunStep.SIGN_IN, FirstRun.step(seen.copy(step = null), connected = false)) // welcome is remembered
        assertEquals(FirstRunStep.FORGOT, FirstRun.step(ShellNav.reduce(seen, ShellAction.Go(FirstRunStep.FORGOT), false), connected = false))
        // signed in (or paired): the setup steps, then the home
        assertEquals(FirstRunStep.PERMISSIONS, FirstRun.step(seen, connected = true))
        val glasses = ShellNav.reduce(seen, ShellAction.Go(FirstRunStep.GLASSES), connected = true)
        assertEquals(FirstRunStep.GLASSES, FirstRun.step(glasses, connected = true))
        val done = ShellNav.reduce(glasses, ShellAction.FinishSetup, connected = true)
        assertNull(FirstRun.step(done, connected = true))
        assertEquals(Tab.HOME, done.tab)
        // a post-sign-in step is never drawn while signed out
        assertEquals(FirstRunStep.SIGN_IN, FirstRun.step(glasses, connected = false))
        // signed out after setup: sign in again (setup was reset by signedOut), welcome not shown again
        val out = ShellNav.signedOut(done.copy(classic = true, savedHome = "x"))
        assertEquals(FirstRunStep.SIGN_IN, FirstRun.step(out, connected = false))
        assertFalse(out.setupDone)
        assertNull(out.savedHome)
        assertTrue(out.classic)
    }

    @Test
    fun m5_u01_anInstallConnectedBeforeTheRedesignSkipsFirstRun() {
        assertTrue(FirstRun.initialFlag(stored = null, connectedAtStart = true))
        assertFalse(FirstRun.initialFlag(stored = null, connectedAtStart = false))
        assertFalse(FirstRun.initialFlag(stored = false, connectedAtStart = true))
        assertTrue(FirstRun.initialFlag(stored = true, connectedAtStart = false))
    }

    @Test
    fun m5_u01_backWalksPagesTabsAndTheFirstRunGraph() {
        val home = fresh.copy(welcomeSeen = true, setupDone = true)
        assertNull(ShellNav.back(home, connected = true)) // Home: the system's Back
        val diag = ShellNav.reduce(home, ShellAction.Open(ShellPage.DIAGNOSTICS), connected = true)
        assertEquals(Tab.PROFILE, diag.tab)
        val settings = ShellNav.back(diag, connected = true)!!
        assertEquals(ShellPage.SETTINGS, settings.page)
        val profile = ShellNav.back(settings, connected = true)!!
        assertNull(profile.page)
        assertEquals(Tab.PROFILE, profile.tab)
        assertEquals(Tab.HOME, ShellNav.back(profile, connected = true)!!.tab)
        // first run
        val forgot = fresh.copy(welcomeSeen = true, step = FirstRunStep.FORGOT)
        assertEquals(FirstRunStep.SIGN_IN, ShellNav.back(forgot, connected = false)!!.step)
        assertEquals(FirstRunStep.WELCOME, ShellNav.back(forgot.copy(step = FirstRunStep.SIGN_IN), connected = false)!!.step)
        assertNull(ShellNav.back(fresh, connected = false))
        assertNull(ShellNav.back(home.copy(setupDone = false), connected = true)) // Permissions: no way back to sign-in
        assertEquals(FirstRunStep.GLASSES, ShellNav.back(home.copy(setupDone = false, step = FirstRunStep.SITE), connected = true)!!.step)
        // signed out, Connections over the sign-in screen
        val conn = ShellNav.reduce(forgot.copy(step = FirstRunStep.SIGN_IN), ShellAction.Open(ShellPage.CONNECTIONS), connected = false)
        assertEquals(ShellPage.CONNECTIONS, ShellNav.signedOutPage(conn, connected = false))
        assertNull(ShellNav.signedOutPage(conn, connected = true))
        assertNull(ShellNav.back(conn, connected = false)!!.page)
        // Back as an action changes nothing where the system's Back should run
        assertEquals(home, ShellNav.reduce(home, ShellAction.Back, connected = true))
    }

    @Test
    fun m5_u01_pickingAHomeRemembersItAndOpensHome() {
        val s = ShellNav.reduce(fresh.copy(tab = Tab.PROFILE, page = ShellPage.SETTINGS), ShellAction.PickHome(Home.APPROVALS, "a@b.c"), true)
        assertEquals(Tab.HOME, s.tab)
        assertNull(s.page)
        assertEquals(Home.APPROVALS, HomeMemory.decode(s.savedHome, "a@b.c"))
        assertTrue(ShellNav.reduce(s, ShellAction.Classic(true), true).classic)
    }

    @Test
    fun m5_u01_forgotAndCreateAccountOpenTheScmtipsPages() {
        val default = "https://api.scmtips.com"
        assertEquals("https://app.scmtips.com/reset", AccountPages.reset(default, default))
        assertEquals("https://app.scmtips.com/signup", AccountPages.signup("https://api.scmtips.com/", default))
        assertEquals("https://app.scmtips.com/signup", AccountPages.signup("http://127.0.0.1:8011", "http://127.0.0.1:8011"))
        assertEquals("https://app.scmtips.com/reset", AccountPages.reset(null, default))
        assertEquals("https://app.scmtips.com/reset", AccountPages.reset("not a url", default))
        assertEquals("https://app.acme.example/reset", AccountPages.reset("https://api.acme.example", default))
        assertEquals("https://app.acme.example:8443/signup", AccountPages.signup("https://api.acme.example:8443/v1", default))
        assertEquals("http://192.168.1.20:8011/signup", AccountPages.signup("http://192.168.1.20:8011", default))
        assertEquals("https://scmtips.acme.example/reset", AccountPages.reset("https://scmtips.acme.example/", default))
    }

    @Test
    fun m5_u01_theStatusPillReplacesTheChipRow() {
        assertEquals(StatusPill("Offline", PillTone.WARN, false), StatusPill.of(offline = true, connecting = true, glassesReady = true, sandbox = false))
        assertEquals("Connecting", StatusPill.of(false, connecting = true, glassesReady = true, sandbox = false).text)
        assertEquals(StatusPill("Glasses ready", PillTone.GOOD, true), StatusPill.of(false, false, glassesReady = true, sandbox = false))
        assertEquals(StatusPill("Phone camera · Sandbox", PillTone.NEUTRAL, false), StatusPill.of(false, false, false, sandbox = true))
    }

    @Test
    fun m5_u05_profileRolesGreetingAndRemoveAnimations() {
        assertEquals(listOf("Warehouse operator", "Approver"), ShellText.roleChips(approver = true, fieldOperator = true, signedIn = true))
        assertEquals(listOf("Field operator (PC pairing)"), ShellText.roleChips(approver = false, fieldOperator = true, signedIn = false))
        assertEquals(listOf("No app roles"), ShellText.roleChips(approver = false, fieldOperator = false, signedIn = true))
        assertEquals("Good morning", ShellText.greeting(8))
        assertEquals("Good afternoon", ShellText.greeting(13))
        assertEquals("Good evening", ShellText.greeting(22))
        assertTrue(ShellText.reduceMotion(0f))
        assertFalse(ShellText.reduceMotion(1f))
        assertFalse(ShellText.reduceMotion(0.5f))
    }

    @Test
    fun m5_u01_permissionStepsAreInThePrototypesOrder() {
        assertEquals(listOf("Camera", "Microphone", "Nearby devices", "Notifications"), PermissionStep.entries.map { it.title })
        assertEquals("android.permission.BLUETOOTH_CONNECT", PermissionStep.NEARBY.androidPermission)
        assertEquals(33, PermissionStep.NOTIFICATIONS.minSdk)
    }
}
