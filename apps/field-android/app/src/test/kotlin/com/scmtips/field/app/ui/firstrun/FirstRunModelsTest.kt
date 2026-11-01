package com.scmtips.field.app.ui.firstrun

import com.scmtips.field.app.glasses.GlassesAdvice
import com.scmtips.field.app.glasses.GlassesHelp
import com.scmtips.field.app.glasses.GlassesStatus
import com.scmtips.field.app.look.CameraProbe
import com.scmtips.field.app.shell.Home
import com.scmtips.field.app.shell.HomeChoice
import com.scmtips.field.app.shell.PermissionStep
import com.scmtips.field.app.signin.SiteRef
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The first-run screens' pure rules (M5-U02): welcome cards, permission plan, glasses steps, site pick, sign-in. */
class FirstRunModelsTest {
    @Test
    fun m5U02_welcome_threeCardsInOrder_nextStopsOnTheLast_andDotsAreLabelled() {
        assertEquals(listOf("Look", "Hear", "Confirm"), WelcomeCard.entries.map { it.title })
        assertEquals(1, WelcomeCard.next(0)); assertEquals(2, WelcomeCard.next(1)); assertNull(WelcomeCard.next(2))
        assertEquals("Card 2 of 3: Hear", WelcomeCard.dotLabel(1))
        assertTrue(WelcomeCard.CONFIRM.body.contains("evidence page"))
    }

    @Test
    fun m5U02_permissions_onlyThisAndroidsSteps_minusGranted_oneAtATime() {
        assertEquals(PermissionStep.entries, PermissionPlan.steps(35))
        // Android 10 (API 29, the app's minSdk): nearby devices and notifications are granted at install
        assertEquals(listOf(PermissionStep.CAMERA, PermissionStep.MICROPHONE), PermissionPlan.steps(29))
        assertEquals(listOf(PermissionStep.MICROPHONE, PermissionStep.NEARBY), PermissionPlan.steps(32, setOf("android.permission.CAMERA")))
        val s = PermissionPlan.steps(35)
        assertEquals(1, PermissionPlan.after(s, 0)); assertNull(PermissionPlan.after(s, 3)); assertNull(PermissionPlan.after(emptyList(), 0))
        assertEquals("Set up · 2 of 4", PermissionPlan.progress(1, 4))
        assertEquals("Allow", PermissionPlan.allowLabel(0, 4)); assertEquals("Allow and continue", PermissionPlan.allowLabel(3, 4))
        assertTrue(PermissionStep.MICROPHONE.why.contains("only while a work session is open"))
    }

    private fun model(s: GlassesStatus, awake: Boolean = false, probe: CameraProbe? = null, toolkit: String? = null) =
        GlassesSetupModel.from(GlassesHelp.advise(s, toolkit), awake, probe)

    @Test
    fun m5U02_glasses_stepsFollowTheRealToolkitState() {
        val fresh = model(GlassesStatus())
        assertEquals(listOf(StepMark.CURRENT, StepMark.LATER, StepMark.LATER), fresh.rows.map { it.mark })
        assertEquals(GlassesCta.AWAKE, fresh.cta)

        val notApproved = model(GlassesStatus(), awake = true)
        assertEquals(GlassesCta.SET_UP, notApproved.cta)
        assertTrue(notApproved.status.contains("Meta AI"))

        val registered = model(GlassesStatus(registration = "REGISTERED", devices = 1), awake = true)
        assertEquals(listOf(StepMark.DONE, StepMark.DONE, StepMark.CURRENT), registered.rows.map { it.mark })
        assertEquals(GlassesCta.CONNECT, registered.cta)

        val ready = model(GlassesStatus(registration = "REGISTERED", devices = 1, session = "STARTED"))
        assertEquals(StepMark.DONE, ready.rows[0].mark) // connected glasses are awake without the person saying so
        assertEquals(GlassesCta.TEST_PHOTO, ready.cta)

        val photo = model(GlassesStatus(registration = "REGISTERED", devices = 1, session = "STARTED"),
            probe = CameraProbe(width = 1280, height = 960, delayMs = 1200))
        assertEquals(GlassesCta.CONTINUE, photo.cta)
        assertTrue(photo.rows.all { it.mark == StepMark.DONE })
        assertEquals("1280 × 960 px from the glasses in 1.2 s", photo.photo)

        val busy = model(GlassesStatus(registration = "REGISTERED", devices = 1, session = "STARTED"), probe = CameraProbe(busy = true))
        assertTrue(busy.busy); assertEquals(GlassesCta.TEST_PHOTO, busy.cta)
    }

    @Test
    fun m5U02_glasses_aToolkitThatDidNotStart_isSaid_andOnlySkipLeads_on() {
        val down = model(GlassesStatus(), awake = true, toolkit = "no DAT")
        assertTrue(down.toolkitDown)
        assertEquals(GlassesCta.WAIT, down.cta)
        assertTrue(down.status.startsWith(GlassesSetupModel.TOOLKIT_DOWN_PREFIX))
        val pausedNotDown = GlassesSetupModel.from(GlassesAdvice("Connecting…", null, GlassesAdvice.Action.NONE, false), awake = true)
        assertFalse(pausedNotDown.toolkitDown)
        assertEquals(GlassesCta.WAIT, pausedNotDown.cta)
    }

    @Test
    fun m5U02_site_sandboxIsMarked_selectionAndContinueFollowTheList() {
        val sites = listOf(SiteRef("s1", "DC Milan", "production"), SiteRef("s2", "Home (sandbox)", "sandbox"))
        val o = SitePick.options(sites, "s2")
        assertEquals(listOf(false, true), o.map { it.sandbox })
        assertEquals(listOf(false, true), o.map { it.selected })
        assertTrue(o[1].sub.startsWith("Sandbox"))
        assertTrue(SitePick.canContinue(sites, "s1", null))
        assertFalse(SitePick.canContinue(sites, "gone", null))
        assertTrue(SitePick.canContinue(emptyList(), null, "PC site")) // a PC pairing has its site
        assertFalse(SitePick.canContinue(emptyList(), null, null))
    }

    @Test
    fun m5U02_site_roleNoteCountsTheHomesTheAccountCanActIn() {
        val two = listOf(HomeChoice(Home.WAREHOUSE, true), HomeChoice(Home.TOWER, false), HomeChoice(Home.APPROVALS, true), HomeChoice(Home.SCAN, false))
        assertTrue(SitePick.roleNote(two).startsWith("Your account can act in 2 of these"))
        assertTrue(SitePick.roleNote(two.map { it.copy(canAct = true) }).startsWith("Your account can act in all"))
        assertTrue(SitePick.roleNote(two.map { it.copy(canAct = false) }).startsWith("Your account can only view"))
        assertEquals("Is this unit really new?", HomeBlurb.of(Home.SCAN))
        assertEquals(4, Home.entries.map(HomeBlurb::of).toSet().size)
    }

    @Test
    fun m5U02_signIn_needsBothFields_andNotWhileBusy_forgotSaysWhatHappensNext() {
        assertTrue(SignInRules.canSubmit("judge01", "x", busy = false))
        assertFalse(SignInRules.canSubmit(" ", "x", busy = false))
        assertFalse(SignInRules.canSubmit("a@b.example", "", busy = false))
        assertFalse(SignInRules.canSubmit("a@b.example", "x", busy = true))
        assertEquals("a@b.example", SignInRules.cleanEmail("  a@b.example "))
        assertTrue(SignInRules.SAMPLE_NOTE.startsWith("SAMPLE"))
        assertTrue(ForgotText.afterOpen(" tester01@x.example ").contains("tester01@x.example"))
        assertFalse(ForgotText.afterOpen("").contains("exists"))
        assertTrue(ForgotText.INTRO.contains("never sees your password"))
    }
}
