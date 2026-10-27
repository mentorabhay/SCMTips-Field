package com.scmtips.field.core.outbox.sync

import com.scmtips.field.core.outbox.db.OutboxItemEntity
import com.scmtips.field.core.outbox.db.OutboxStatus

/**
 * Result of evaluating a server response against conflict rules (Rule BR2.11 / Task T2.042 / FR2.041).
 */
sealed class SyncDecision {
    data class Ack(val serverId: String? = null, val isDuplicate: Boolean = false) : SyncDecision()
    data class Quarantine(val reason: String) : SyncDecision()
    data class Reject(val reason: String) : SyncDecision()
    data class PauseAll(val reason: String) : SyncDecision()
    data object RecompressAndRetry : SyncDecision()
    data class Retry(val delayMs: Long, val reason: String) : SyncDecision()
}

/**
 * Evaluates HTTP status codes and payloads per BR2.11.
 */
object ConflictPolicy {

    // Initial backoff ladder per FR2.045: 2, 4, 8, 16, 32 s
    val RETRY_BACKOFF_SECONDS = listOf(2L, 4L, 8L, 16L, 32L)

    fun calculateRetryDelayMs(attempt: Int): Long {
        val index = attempt.coerceAtMost(RETRY_BACKOFF_SECONDS.size - 1)
        val seconds = if (attempt < RETRY_BACKOFF_SECONDS.size) {
            RETRY_BACKOFF_SECONDS[index]
        } else {
            // WorkManager exponential with 30s base: 30 * 2^(attempt - 5) capped at 300s
            val exponent = (attempt - RETRY_BACKOFF_SECONDS.size).coerceAtMost(4)
            (30L * (1L shl exponent)).coerceAtMost(300L)
        }
        return seconds * 1000L
    }

    /**
     * Resolves server HTTP response into an actionable SyncDecision according to BR2.11.
     */
    fun evaluate(
        httpStatusCode: Int,
        responseBody: String?,
        item: OutboxItemEntity,
        isNetworkError: Boolean = false
    ): SyncDecision {
        if (isNetworkError) {
            val delay = calculateRetryDelayMs(item.attempts)
            return SyncDecision.Retry(delay, "Network connectivity failure")
        }

        return when (httpStatusCode) {
            in 200..299 -> {
                // Successfully posted and acked
                SyncDecision.Ack(serverId = parseServerId(responseBody), isDuplicate = false)
            }
            409 -> {
                // BR2.11: 409 duplicate is acked as duplicate with server id
                val dupId = parseDuplicateOf(responseBody) ?: parseServerId(responseBody)
                SyncDecision.Ack(serverId = dupId, isDuplicate = true)
            }
            422 -> {
                // BR2.11: 422 key mismatch quarantined and alerted
                SyncDecision.Quarantine("FIELD-IDEM-422: Idempotency key mismatch or payload conflict")
            }
            410 -> {
                // BR2.11: 410 task closed rejected and shown
                SyncDecision.Reject("FIELD-TASK-410: Target task has been closed on server")
            }
            401, 403 -> {
                // BR2.11: 401/403 pause all items until sign-in
                SyncDecision.PauseAll("Authentication revoked or expired ($httpStatusCode). Re-login required.")
            }
            413 -> {
                // BR2.11: 413 recompress once at quality 70 then quarantine
                if (!item.recompressed) {
                    SyncDecision.RecompressAndRetry
                } else {
                    SyncDecision.Quarantine("Payload too large (413) even after quality 70 recompression")
                }
            }
            429, in 500..599 -> {
                // Transient server error: retry with backoff ladder
                val delay = calculateRetryDelayMs(item.attempts)
                SyncDecision.Retry(delay, "Server error ($httpStatusCode): retrying in ${delay / 1000}s")
            }
            else -> {
                // Other client 4xx errors
                SyncDecision.Quarantine("Unexpected client error HTTP $httpStatusCode")
            }
        }
    }

    private fun parseServerId(body: String?): String? {
        if (body.isNullOrBlank()) return null
        val match = """"id"\s*:\s*"([^"]+)"""".toRegex().find(body)
        return match?.groupValues?.get(1)
    }

    private fun parseDuplicateOf(body: String?): String? {
        if (body.isNullOrBlank()) return null
        val match = """"duplicate_of"\s*:\s*"([^"]+)"""".toRegex().find(body)
        return match?.groupValues?.get(1)
    }
}
