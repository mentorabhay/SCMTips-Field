package com.scmtips.field.core.outbox.sync

import com.scmtips.field.core.outbox.db.OutboxItemEntity

/** Applies the BR2.11 rules in ConflictRules.kt to a Room outbox item. */
fun ConflictPolicy.evaluate(
    httpStatusCode: Int,
    responseBody: String?,
    item: OutboxItemEntity,
    isNetworkError: Boolean = false,
): SyncDecision = evaluate(
    httpStatusCode = httpStatusCode,
    responseBody = responseBody,
    attempts = item.attempts,
    recompressed = item.recompressed,
    isNetworkError = isNetworkError,
)
