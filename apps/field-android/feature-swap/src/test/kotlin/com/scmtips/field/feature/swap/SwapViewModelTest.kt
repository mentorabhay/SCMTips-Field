package com.scmtips.field.feature.swap

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Install / replace staging view-model (FR4.031, FR4.032, FR4.035). ERP posting itself is server-side. */
class SwapViewModelTest {

    private val bom = listOf(
        BomItem(1, "RRU-4415", "RRU body", 1, isSerialised = true, balloonNo = 1),
        BomItem(2, "BOLT-M8", "Bolt kit", 4),
        BomItem(3, "PSU-48V", "Power supply", 1, isSerialised = true, balloonNo = 3)
    )

    private fun vm(old: String? = "S-OLD") = SwapViewModel("site", "loc", "FL-T01-S1", old, bom)

    @Test
    fun fr4_032_stagingRefusedUntilEverySerialisedBomItemCapturedNamesBalloon() {
        val v = vm()
        assertTrue(v.captureBomSerial(1, "RRU-SN-1"))
        assertFalse(v.stageReplacement("S-NEW", "RRU-4415", nextSeq = 10))
        assertEquals("Capture the serial for Power supply (balloon 3) before posting.", v.state.error)
        assertEquals("1 of 2 serialised parts captured", v.state.checklistText)
        assertFalse("non-serialised lines take no serial", v.captureBomSerial(2, "x"))
        assertTrue(v.captureBomSerial(3, "PSU-SN-9"))
        assertTrue(v.stageReplacement("S-NEW", "RRU-4415", nextSeq = 10))
        assertEquals(SwapStageState.STAGED, v.state.state)
    }

    @Test
    fun fr4_031_replaceStagesDismantleThenInstallConsecutiveSameQueue() {
        val v = vm()
        v.captureBomSerial(1, "a"); v.captureBomSerial(3, "b")
        v.stageReplacement("S-NEW", "RRU-4415", nextSeq = 41)
        val e = v.state.stagedEvents
        assertEquals(listOf(EquipmentOp.DISMANTLE, EquipmentOp.INSTALL), e.map { it.op })
        assertEquals(listOf("S-OLD", "S-NEW"), e.map { it.serialNo })
        assertEquals(listOf(41L, 42L), e.map { it.seq })
        assertEquals(1, e.map { it.queueKey }.toSet().size)
        assertEquals(setOf("FL-T01-S1"), e.map { it.flCode }.toSet())
    }

    @Test
    fun fr4_031_installWithoutOldSerialIsOneEvent() {
        val v = SwapViewModel("site", "loc", "FL", null, emptyList())
        assertTrue(v.stageReplacement("S-NEW", "ANY", nextSeq = 1))
        assertEquals(listOf(EquipmentOp.INSTALL), v.state.stagedEvents.map { it.op })
    }

    @Test
    fun fr4_032_materialMustBeInPinnedBom() {
        val v = vm()
        v.captureBomSerial(1, "a"); v.captureBomSerial(3, "b")
        assertFalse(v.stageReplacement("S-NEW", "NOT-IN-BOM", 1))
        assertEquals(SwapStageState.IDLE, v.state.state)
    }

    @Test
    fun fr4_035_undoBeforePostRemovesStagedEvents() {
        val v = vm()
        v.captureBomSerial(1, "a"); v.captureBomSerial(3, "b")
        v.stageReplacement("S-NEW", "RRU-4415", 1)
        assertTrue(v.undoBeforePost())
        assertEquals(SwapStageState.IDLE, v.state.state)
        assertTrue(v.state.stagedEvents.isEmpty())
        assertTrue(v.undoAfterPost().isEmpty())
    }

    @Test
    fun fr4_035_undoAfterPostCompensatesWithRefDocNoAndMsg4_19() {
        val v = vm()
        v.captureBomSerial(1, "a"); v.captureBomSerial(3, "b")
        v.stageReplacement("S-NEW", "RRU-4415", 1)
        assertFalse("confirm needs a post first", v.confirmInstallation())
        assertTrue(v.markPosted("evt-1", "4900001234"))
        assertFalse("cannot undo-before-post once posted", v.undoBeforePost())
        assertTrue(v.confirmInstallation())
        val ops = v.undoAfterPost()
        assertEquals(listOf(EquipmentOp.DISMANTLE to "S-NEW", EquipmentOp.INSTALL to "S-OLD"), ops.map { it.op to it.serialNo })
        assertTrue(ops.all { it.refDocNo == "4900001234" })
        assertEquals(SwapStageState.REVERSED, v.state.state)
        assertEquals("Reversal queued for 4900001234. The original stays in SAP marked reversed.", v.state.message)
    }
}
