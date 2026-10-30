package com.scmtips.field.core.outbox.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/** TowerOutboxReplayCoordinator against FR4.059: per-tower replay in original sequence, towers independent. */
class TowerOrderingTest {
    private fun ev(t: String, seq: Int, st: TowerEventStatus = TowerEventStatus.PENDING) =
        TowerOutboxEvent("$t-$seq", t, seq, "INSTALL", "{}", st)

    @Test
    fun fr4_059_onlyTheLowestUncompletedSeqOfEachTowerIsEligible() {
        val c = TowerOutboxReplayCoordinator()
        val events = listOf(
            ev("T1", 2), ev("T1", 1, TowerEventStatus.COMPLETED), ev("T1", 3),
            ev("T2", 1, TowerEventStatus.UPLOADING), ev("T2", 2),
            ev("T3", 1, TowerEventStatus.FAILED), ev("T3", 2),
        )
        assertEquals(listOf("T1-2"), c.selectNextBatch(events).map { it.id })
    }

    @Test
    fun fr4_059_aHeldTowerDoesNotBlockOthersAndResumesInOrder() {
        val c = TowerOutboxReplayCoordinator()
        c.holdTower("T2", "erp conflict")
        val events = listOf(ev("T1", 1), ev("T2", 1), ev("T3", 1))
        assertEquals(listOf("T1-1", "T3-1"), c.selectNextBatch(events).map { it.id })
        c.releaseTower("T2")
        assertEquals(listOf("T1-1", "T2-1", "T3-1"), c.selectNextBatch(events).map { it.id })
    }

    /** Seeded random replays: whatever completes, each tower is delivered in strictly increasing seq. */
    @Test
    fun randomReplaysDeliverEachTowerInOriginalSequence() {
        val rnd = Random(4_059)
        repeat(300) {
            val towers = (1..rnd.nextInt(1, 5)).map { "T$it" }
            var events = towers.flatMap { t -> (1..rnd.nextInt(1, 10)).map { ev(t, it) } }.shuffled(rnd)
            val c = TowerOutboxReplayCoordinator()
            val delivered = mutableMapOf<String, MutableList<Int>>()
            var guard = 0
            while (events.any { it.status != TowerEventStatus.COMPLETED } && guard++ < 1_000) {
                if (rnd.nextInt(10) == 0) c.holdTower(towers.random(rnd), "x") else towers.forEach { c.releaseTower(it) }
                val batch = c.selectNextBatch(events)
                val done = batch.filter { rnd.nextBoolean() }.map { it.id }.toSet()
                events = events.map { if (it.id in done) it.copy(status = TowerEventStatus.COMPLETED) else it }
                batch.filter { it.id in done }.forEach { delivered.getOrPut(it.towerFl) { mutableListOf() } += it.seq }
            }
            for ((t, seqs) in delivered) assertEquals(t, (1..seqs.size).toList(), seqs)
            assertTrue(events.all { it.status == TowerEventStatus.COMPLETED })
        }
    }
}
