package com.scmtips.field.core.wearables

import com.scmtips.field.core.wearables.lens.LensCopy
import com.scmtips.field.core.wearables.lens.RayBanLensRenderer
import com.scmtips.field.core.wearables.testing.FakeLensRenderer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** RayBanLensRenderer layout against SCR2.07 / FR2.013, observed through FakeLensRenderer. */
class LensRendererTest {
    private val renderer = FakeLensRenderer()

    @Test
    fun tc2_113_sevenStatesDrawScr2_07CopyWithinTwoLinesOf18() {
        val expected = mapOf(
            LensState.READY to ("Ready" to ""),
            LensState.MOVING to ("Hold still" to ""),
            LensState.TIE to ("Left or right?" to ""),
            LensState.CAPTURED to ("Captured" to ""),
            LensState.DUPLICATE to ("Already captured" to ""),
            LensState.OFFLINE_QUEUED to ("Saved offline" to ""),
            LensState.ERROR to ("Problem - see" to "phone"),
        )
        assertEquals(LensState.values().toSet(), expected.keys)
        for ((state, lines) in expected) renderer.renderState(state)
        val calls = renderer.getDrawCalls()
        assertEquals(7, calls.size)
        for (call in calls) {
            assertEquals(call.state.name, expected.getValue(call.state), call.line1 to call.line2)
            assertTrue(call.line1.length <= 18 && call.line2.length <= 18)
        }
    }

    @Test
    fun overlongTextIsWrappedThenTruncatedTo18() {
        val call = renderer.renderState(LensState.CAPTURED, "Pallet 0030123 accepted for line three")
        assertEquals("Pallet 0030123", call.line1)
        assertEquals("accepted for line ", call.line2)
        val noSpace = renderer.renderState(LensState.ERROR, "X".repeat(40), "", "Supercalifragilistic")
        assertEquals("X".repeat(18), noSpace.line1)
        assertEquals("", noSpace.line2)
        assertEquals("Supercalifragilist", noSpace.actionPill)
        val explicit = renderer.renderState(LensState.TIE, "A".repeat(20), "B".repeat(20))
        assertEquals("A".repeat(18) to "B".repeat(18), explicit.line1 to explicit.line2)
    }

    @Test
    fun everyScr2_07StateCopyFitsTheLens() {
        for ((state, text) in LensCopy.STATE_LINE) {
            val (a, b) = RayBanLensRenderer.wrap(text)
            assertTrue(state.name, a.length <= 18 && b.length <= 18)
            assertEquals(state.name, text, listOf(a, b).filter { it.isNotEmpty() }.joinToString(" "))
        }
    }

    @Test
    fun productionRendererHandsEveryDrawToTheSink() {
        val sunk = mutableListOf<DrawCall>()
        val r = RayBanLensRenderer { sunk += it }
        val call = r.renderState(LensState.READY)
        assertEquals(listOf(call), sunk)
    }
}
