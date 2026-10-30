package com.scmtips.field.core.outbox

import com.scmtips.field.core.outbox.db.OutboxDao

/** Room-backed [OutboxStats] for [QueueCapacityGovernor] (logic in OutboxCapacity.kt). */
fun OutboxDao.capacityStats(): OutboxStats = object : OutboxStats {
    override suspend fun pendingCount(): Int = getPendingCount()
    override suspend fun totalCropBytes(): Long = getTotalCropSizeBytes()
}
