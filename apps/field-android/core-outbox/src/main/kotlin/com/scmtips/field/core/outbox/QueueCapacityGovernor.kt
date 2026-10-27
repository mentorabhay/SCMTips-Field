package com.scmtips.field.core.outbox

import com.scmtips.field.core.outbox.db.OutboxDao

/**
 * Enforces bounded offline outbox capacity limits (Task T2.043 / FR2.042, PR2.18, TC2.137).
 * Capped at 2,000 items or 200 MB.
 */
class QueueCapacityGovernor(
    private val outboxDao: OutboxDao? = null,
    val maxItems: Int = MAX_OUTBOX_ITEMS,
    val maxSizeBytes: Long = MAX_OUTBOX_BYTES
) {
    companion object {
        const val MAX_OUTBOX_ITEMS = 2000
        const val MAX_OUTBOX_BYTES = 200 * 1024 * 1024L // 200 MB (209,715,200 bytes)
        const val WARN_ITEMS_THRESHOLD = 1800 // 90%
        const val WARN_BYTES_THRESHOLD = (200 * 1024 * 1024L * 9) / 10 // 180 MB

        fun formatWarningMsg(pendingCount: Int): String =
            "Outbox almost full: $pendingCount of 2,000 waiting. Move to signal soon so they can send."

        const val REFUSAL_MSG =
            "Outbox full. New captures are paused until waiting items send. Move to an area with signal."
    }

    sealed class CapacityStatus {
        data object Normal : CapacityStatus()
        data class Warning(val message: String, val currentItems: Int, val currentBytes: Long) : CapacityStatus()
        data class Refused(val message: String, val currentItems: Int, val currentBytes: Long) : CapacityStatus()
    }

    /**
     * Checks whether an incoming capture with estimated bytes can be admitted.
     * Returns null if admitted, or error message (MSG2.13) if refused.
     */
    suspend fun checkAdmission(
        newItemsCount: Int = 1,
        newSizeBytes: Long = 0L,
        currentItemsOverride: Int? = null,
        currentBytesOverride: Long? = null
    ): String? {
        val currentItems = currentItemsOverride ?: (outboxDao?.getPendingCount() ?: 0)
        val currentBytes = currentBytesOverride ?: (outboxDao?.getTotalCropSizeBytes() ?: 0L)

        if ((currentItems + newItemsCount > maxItems) || (currentBytes + newSizeBytes > maxSizeBytes)) {
            // Refuse admission without altering existing queued items (FR2.042, PR2.18)
            return REFUSAL_MSG
        }
        return null
    }

    /**
     * Evaluates current queue status for warnings or alerts.
     */
    suspend fun evaluateStatus(
        currentItemsOverride: Int? = null,
        currentBytesOverride: Long? = null
    ): CapacityStatus {
        val currentItems = currentItemsOverride ?: (outboxDao?.getPendingCount() ?: 0)
        val currentBytes = currentBytesOverride ?: (outboxDao?.getTotalCropSizeBytes() ?: 0L)

        return when {
            currentItems >= maxItems || currentBytes >= maxSizeBytes -> {
                CapacityStatus.Refused(REFUSAL_MSG, currentItems, currentBytes)
            }
            currentItems >= WARN_ITEMS_THRESHOLD || currentBytes >= WARN_BYTES_THRESHOLD -> {
                CapacityStatus.Warning(formatWarningMsg(currentItems), currentItems, currentBytes)
            }
            else -> CapacityStatus.Normal
        }
    }
}
