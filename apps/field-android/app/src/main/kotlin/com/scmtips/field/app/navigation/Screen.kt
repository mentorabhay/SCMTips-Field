package com.scmtips.field.app.navigation

/**
 * The phone app's places (design Main.dc.html): connect once, then three tabs (Today, Scan, Me), and the
 * one job runner drawn over them while a job is open. The crash report screen replaces all of them after
 * a crash (MainActivity).
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
