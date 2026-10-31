package com.scmtips.field.app.navigation

import org.junit.Assert.assertEquals
import org.junit.Test
import java.net.URLClassLoader

/**
 * Owner crash 2026-10-31 (vivo I2304, Android 16): NullPointerException on Screen.getTitle() in TabBar
 * right after pairing. On a cold start the first class touched is Screen.Today (the default tab); its
 * static init runs Screen's, whose companion built listOf(Today, Scan, Me) while Today was unassigned.
 * A test JVM has usually loaded Screen another way already, so this test loads it fresh, Today first.
 */
class ScreenInitTest {
    private fun freshLoader(): ClassLoader = URLClassLoader(
        arrayOf(
            Screen::class.java.protectionDomain.codeSource.location,
            Unit::class.java.protectionDomain.codeSource.location, // kotlin stdlib (lazy, listOf)
        ),
        null, // bootstrap only: java.* (getPlatformClassLoader is not in the Android test classpath)
    )

    private fun tabTitlesAfterTouching(first: String): List<String?> {
        val loader = freshLoader()
        Class.forName("com.scmtips.field.app.navigation.Screen\$$first", true, loader)
        val screen = Class.forName("com.scmtips.field.app.navigation.Screen", true, loader)
        val companion = screen.getField("Companion").get(null)
        val tabs = companion.javaClass.getMethod("getTabs").invoke(companion) as List<*>
        return tabs.map { t -> t?.let { screen.getMethod("getTitle").invoke(it) as String } }
    }

    @Test
    fun tabsHaveNoHolesWhicheverScreenIsTouchedFirst() {
        for (first in listOf("Today", "Scan", "Me", "Connect", "Job")) {
            assertEquals("first touched: $first", listOf("Today", "Scan", "Me"), tabTitlesAfterTouching(first))
        }
    }

    @Test
    fun everyScreenIsListedOnce() {
        assertEquals(listOf("connect", "today", "scan", "me", "job"), Screen.allScreens.map { it.route })
    }
}
