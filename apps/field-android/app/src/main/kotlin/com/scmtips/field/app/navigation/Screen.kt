package com.scmtips.field.app.navigation

/**
 * The phone app's places (design Main.dc.html): connect once, then three tabs (Today, Scan, Me), and the
 * one job runner drawn over them while a job is open. The crash report screen replaces all of them after
 * a crash (MainActivity).
 *
 * M5-U (A-07): these are the places of the "Classic layout" (Settings › Diagnostics), kept unchanged. The redesign's
 * places are in com.scmtips.field.app.shell: [com.scmtips.field.app.shell.FirstRunStep] (the first-run graph),
 * [com.scmtips.field.app.shell.Tab] (Home · Activity · Scan · Inbox · Profile), [com.scmtips.field.app.shell.ShellPage]
 * (Settings › Connections / Diagnostics) and [com.scmtips.field.app.shell.Home] (the four role homes); the open job,
 * check, review and evidence screens are drawn full screen over both layouts.
 */
sealed class Screen(val route: String, val title: String) {
    object Connect : Screen("connect", "Connect")
    object Today : Screen("today", "Today")
    object Scan : Screen("scan", "Scan")
    object Me : Screen("me", "Me")
    object Job : Screen("job", "Job")

    companion object {
        // Lazy on purpose (owner crash 2026-10-31, NPE in TabBar): touching Screen.Today first runs
        // Screen's static init while Today.INSTANCE is still unassigned, so an eager list held null.
        val tabs: List<Screen> by lazy { listOf(Today, Scan, Me) }
        val allScreens: List<Screen> by lazy { listOf(Connect, Today, Scan, Me, Job) }
    }
}
