package com.scmtips.field.core.outbox

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** QueueCapacityGovernor against FR2.042 / BR2.12 (2,000 items or 200 MB; warn at 90 %, refuse at 100 %). */
class OutboxCapacityTest {
    private val g = QueueCapacityGovernor()
    private val mb = 1024L * 1024L

    @Test
    fun tc2_052_1999ItemsAdmitOneMore() = runBlocking {
        assertNull(g.checkAdmission(1, 1024, currentItemsOverride = 1_999, currentBytesOverride = 100 * mb))
    }

    @Test
    fun tc2_053_2000ItemsRefuseWithMsg2_13() = runBlocking {
        assertEquals(
            "Outbox full. New captures are paused until waiting items send. Move to an area with signal.",
            g.checkAdmission(1, 1024, currentItemsOverride = 2_000, currentBytesOverride = 100 * mb),
        )
        assertTrue(g.evaluateStatus(2_000, 0) is QueueCapacityGovernor.CapacityStatus.Refused)
    }

    @Test
    fun tc2_054_1800ItemsWarnWithMsg2_12() = runBlocking {
        val s = g.evaluateStatus(1_812, 0)
        assertEquals(
            "Outbox almost full: 1,812 of 2,000 waiting. Move to signal soon so they can send.",
            (s as QueueCapacityGovernor.CapacityStatus.Warning).message,
        )
        assertTrue(g.evaluateStatus(1_800, 0) is QueueCapacityGovernor.CapacityStatus.Warning)
        assertEquals(QueueCapacityGovernor.CapacityStatus.Normal, g.evaluateStatus(1_799, 0))
    }

    @Test
    fun fr2_042_byteCapAppliesIndependently() = runBlocking {
        assertNull(g.checkAdmission(1, mb, 10, 199 * mb))
        assertEquals(QueueCapacityGovernor.REFUSAL_MSG, g.checkAdmission(1, mb + 1, 10, 199 * mb))
        assertTrue(g.evaluateStatus(10, 180 * mb) is QueueCapacityGovernor.CapacityStatus.Warning)
    }

    @Test
    fun configuredMaxItemsMovesBothThresholds() = runBlocking {
        val small = QueueCapacityGovernor(maxItems = 1_000)
        assertEquals(QueueCapacityGovernor.REFUSAL_MSG, small.checkAdmission(1, 0, 1_000, 0))
        val w = small.evaluateStatus(900, 0) as QueueCapacityGovernor.CapacityStatus.Warning
        assertEquals("Outbox almost full: 900 of 1,000 waiting. Move to signal soon so they can send.", w.message)
    }

    @Test
    fun statsSourceIsUsedWhenNoOverride() = runBlocking {
        val g2 = QueueCapacityGovernor(object : OutboxStats {
            override suspend fun pendingCount() = 2_000
            override suspend fun totalCropBytes() = 0L
        })
        assertEquals(QueueCapacityGovernor.REFUSAL_MSG, g2.checkAdmission())
    }
}
