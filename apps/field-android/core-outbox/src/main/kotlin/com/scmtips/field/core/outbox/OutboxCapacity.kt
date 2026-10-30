package com.scmtips.field.core.outbox

import java.text.NumberFormat
import java.util.Locale

/** Current outbox occupancy, supplied by the Room DAO in production (see QueueCapacityGovernor.kt). */
interface OutboxStats {
    suspend fun pendingCount(): Int
    suspend fun totalCropBytes(): Long
}

/**
 * Bounded outbox (T2.043; FR2.042; BR2.12): at most [maxItems] items or [maxSizeBytes]; warn at 90%
 * (MSG2.12) and refuse new captures at 100% (MSG2.13). Admission never alters or drops queued items.
 * [maxItems] follows the effective max_outbox_items config (default 2,000); the 90% warning and the
 * MSG2.12 text follow it.
 */
class QueueCapacityGovernor(
    private val stats: OutboxStats? = null,
    val maxItems: Int = MAX_OUTBOX_ITEMS,
    val maxSizeBytes: Long = MAX_OUTBOX_BYTES,
) {
    companion object {
        const val MAX_OUTBOX_ITEMS = 2000
        const val MAX_OUTBOX_BYTES = 200 * 1024 * 1024L

        /** MSG2.12, e.g. "Outbox almost full: 1,812 of 2,000 waiting. Move to signal soon so they can send." */
        fun formatWarningMsg(pendingCount: Int, maxItems: Int = MAX_OUTBOX_ITEMS): String {
            val f = NumberFormat.getIntegerInstance(Locale.US)
            return "Outbox almost full: ${f.format(pendingCount)} of ${f.format(maxItems)} waiting. Move to signal soon so they can send."
        }

        /** MSG2.13 */
        const val REFUSAL_MSG =
            "Outbox full. New captures are paused until waiting items send. Move to an area with signal."
    }

    val warnItems: Int get() = (maxItems * 9 + 9) / 10
    val warnBytes: Long get() = maxSizeBytes * 9 / 10

    sealed class CapacityStatus {
        data object Normal : CapacityStatus()
        data class Warning(val message: String, val currentItems: Int, val currentBytes: Long) : CapacityStatus()
        data class Refused(val message: String, val currentItems: Int, val currentBytes: Long) : CapacityStatus()
    }

    /** Returns null when [newItemsCount] items of [newSizeBytes] fit, otherwise MSG2.13. */
    suspend fun checkAdmission(
        newItemsCount: Int = 1,
        newSizeBytes: Long = 0L,
        currentItemsOverride: Int? = null,
        currentBytesOverride: Long? = null,
    ): String? {
        val items = currentItemsOverride ?: (stats?.pendingCount() ?: 0)
        val bytes = currentBytesOverride ?: (stats?.totalCropBytes() ?: 0L)
        return if (items + newItemsCount > maxItems || bytes + newSizeBytes > maxSizeBytes) REFUSAL_MSG else null
    }

    suspend fun evaluateStatus(
        currentItemsOverride: Int? = null,
        currentBytesOverride: Long? = null,
    ): CapacityStatus {
        val items = currentItemsOverride ?: (stats?.pendingCount() ?: 0)
        val bytes = currentBytesOverride ?: (stats?.totalCropBytes() ?: 0L)
        return when {
            items >= maxItems || bytes >= maxSizeBytes -> CapacityStatus.Refused(REFUSAL_MSG, items, bytes)
            items >= warnItems || bytes >= warnBytes ->
                CapacityStatus.Warning(formatWarningMsg(items, maxItems), items, bytes)
            else -> CapacityStatus.Normal
        }
    }
}
