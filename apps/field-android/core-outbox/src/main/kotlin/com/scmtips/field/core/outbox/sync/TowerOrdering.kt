package com.scmtips.field.core.outbox.sync

/**
 * Per-Tower Outbox Replay Ordering & Partitioning Engine (Task T4.063 / PR4.12 / FR4.059).
 *
 * Implements:
 * - Room outbox partitioned by tower functional location (towerFl).
 * - Strictly monotonic FIFO execution per tower based on seq: an event is eligible only when every
 *   lower seq of the same tower is COMPLETED.
 * - Non-blocking multi-tower replay: a held or failed tower queue does NOT block
 *   independent progress on any other tower (PR4.12).
 */

enum class TowerEventStatus {
    PENDING,
    UPLOADING,
    COMPLETED,
    HELD,
    FAILED
}

data class TowerOutboxEvent(
    val id: String,
    val towerFl: String,
    val seq: Int,
    val operation: String,
    val payloadJson: String,
    val status: TowerEventStatus = TowerEventStatus.PENDING,
    val retryCount: Int = 0,
    val holdReason: String? = null
)

class TowerOutboxReplayCoordinator {
    private val heldTowers = mutableSetOf<String>()

    /**
     * Determine eligible events ready for upload dispatch across all towers.
     * Selects exactly the lowest un-processed seq for each non-held tower.
     */
    fun selectNextBatch(events: List<TowerOutboxEvent>): List<TowerOutboxEvent> {
        val eligible = mutableListOf<TowerOutboxEvent>()
        for ((towerFl, towerEvents) in events.groupBy { it.towerFl }) {
            // A held tower is skipped without blocking any other tower (FR4.059)
            if (heldTowers.contains(towerFl)) continue
            // Strict FIFO: only the lowest not-yet-completed seq may go. If that head is uploading,
            // held or failed, nothing later in the same tower is sent.
            val head = towerEvents
                .filter { it.status != TowerEventStatus.COMPLETED }
                .minByOrNull { it.seq } ?: continue
            if (head.status == TowerEventStatus.PENDING) eligible.add(head)
        }
        return eligible.sortedBy { it.towerFl }
    }

    /**
     * Mark a specific tower queue as held due to conflict or error.
     */
    fun holdTower(towerFl: String, reason: String) {
        heldTowers.add(towerFl)
    }

    /**
     * Check if a tower queue is held.
     */
    fun isTowerHeld(towerFl: String): Boolean = heldTowers.contains(towerFl)

    /**
     * Release hold on a tower queue once conflict is resolved.
     */
    fun releaseTower(towerFl: String) {
        heldTowers.remove(towerFl)
    }
}
