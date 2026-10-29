package com.scmtips.field.core.wearables

import com.scmtips.field.core.wearables.lens.RayBanLensRenderer
import com.scmtips.field.core.wearables.mock.MockWearablesKit
import com.scmtips.field.core.wearables.testing.FakeLensRenderer
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/**
 * JVM UI / State Machine unit tests for Ray-Ban Lens Renderer and Mock Wearables Kit
 * (Task T2.014 / SCR2.07 / FR2.013 / TC2.113 / F-07).
 */
class LensRendererTest {

    private val renderer = FakeLensRenderer()

    @Test
    fun testAllSevenLensStatesRenderSuccessfully() {
        val states = listOf(
            LensState.READY,
            LensState.MOVING,
            LensState.TIE,
            LensState.CAPTURED,
            LensState.DUPLICATE,
            LensState.OFFLINE_QUEUED,
            LensState.ERROR
        )

        for (state in states) {
            val drawCall = renderer.renderState(
                state = state,
                line1 = "State ${state.name}",
                line2 = "Test subtext",
                actionPill = "OK"
            )

            assertEquals(state, drawCall.state)
            assertEquals("State ${state.name}".take(18), drawCall.line1)
            assertEquals("Test subtext", drawCall.line2)
            assertEquals("OK", drawCall.actionPill)
            assertTrue(drawCall.timestampMs > 0L)
        }

        assertEquals(7, renderer.getDrawCalls().size)
    }

    @Test
    fun testLineAndPillTruncationTo18Characters() {
        val longLine1 = "This is a very long string exceeding eighteen characters"
        val longLine2 = "Another line that definitely contains way more than 18 chars"
        val longPill = "Supercalifragilisticexpialidocious"

        val call = renderer.renderState(
            state = LensState.CAPTURED,
            line1 = longLine1,
            line2 = longLine2,
            actionPill = longPill
        )

        assertEquals(18, call.line1.length, "Line 1 must be truncated to exactly 18 chars")
        assertEquals(longLine1.take(18), call.line1)

        assertEquals(18, call.line2.length, "Line 2 must be truncated to exactly 18 chars")
        assertEquals(longLine2.take(18), call.line2)

        assertNotNull(call.actionPill)
        assertEquals(18, call.actionPill!!.length, "Pill must be truncated to exactly 18 chars")
        assertEquals(longPill.take(18), call.actionPill)
    }

    @Test
    fun testFakeLensRendererRecordingAndClear() {
        renderer.clear()
        assertEquals(0, renderer.getDrawCalls().size)

        renderer.renderState(LensState.READY, "Line A")
        renderer.renderState(LensState.MOVING, "Line B")

        assertEquals(2, renderer.getDrawCalls().size)
        assertEquals(LensState.MOVING, renderer.getLastDrawCall()?.state)

        renderer.clear()
        assertEquals(0, renderer.getDrawCalls().size)
    }

    @Test
    fun testMockWearablesKitSimulation() = runBlocking {
        val kit = MockWearablesKit()
        assertEquals(ConnectionState.Disconnected, kit.connectionState.value)

        kit.connect("00:11:22:33:44:55", "Meta Ray-Ban Display")
        val state = kit.connectionState.value
        assertTrue(state is ConnectionState.Connected)
        val connected = state as ConnectionState.Connected
        assertTrue(connected.displayCapability)
        assertEquals(95, connected.batteryPct)
        assertTrue(kit.isDisplayAvailable())

        // Still capture simulation
        val photo = kit.stillCapture.capturePhoto()
        assertEquals(3024, photo.width)
        assertEquals(4032, photo.height)
        assertNotNull(photo.traceparent)

        // Audio cues simulation
        kit.audioOut.playEarcon(EarconCue.CAPTURED)
        kit.audioOut.playSpeech("Scanned 12 items")
        assertEquals(listOf(EarconCue.CAPTURED), kit.playedEarcons)
        assertEquals(listOf("Scanned 12 items"), kit.playedSpeeches)

        // Preview stream simulation
        kit.previewStream.startStream()
        assertTrue(kit.previewStream.isStreaming())
        kit.emitSyntheticFrame(504, 896)
        val frame = kit.previewStream.frames.first()
        assertEquals(504, frame.width)
        assertEquals(896, frame.height)

        kit.disconnect()
        assertEquals(ConnectionState.Disconnected, kit.connectionState.value)
        assertFalse(kit.previewStream.isStreaming())
    }
}
