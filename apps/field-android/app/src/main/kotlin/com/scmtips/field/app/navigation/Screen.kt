package com.scmtips.field.app.navigation

sealed class Screen(val route: String, val title: String) {
    object SignIn : Screen("sign-in", "Sign In")
    object Permissions : Screen("permissions", "Permissions")
    object Consent : Screen("consent", "Site Consent")
    object Pair : Screen("pair", "Pair Glasses")
    object Tasks : Screen("tasks", "Tasks")
    object Session : Screen("session", "Capture Session")
    object Outbox : Screen("outbox", "Outbox Queue")
    object Settings : Screen("settings", "Settings")

    companion object {
        val allScreens = listOf(
            SignIn,
            Permissions,
            Consent,
            Pair,
            Tasks,
            Session,
            Outbox,
            Settings
        )
    }
}
