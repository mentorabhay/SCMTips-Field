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
        val tabs: List<Screen> = listOf(Today, Scan, Me)
        val allScreens: List<Screen> = listOf(Connect, Today, Scan, Me, Job)
    }
}
