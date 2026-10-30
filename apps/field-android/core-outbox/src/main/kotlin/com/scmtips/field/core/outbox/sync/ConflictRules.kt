package com.scmtips.field.core.outbox.sync

/**
 * Result of evaluating a server response against conflict rules (BR2.11; T2.042; FR2.041).
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
 * BR2.11 conflict rules as a pure function of the response and the item's retry state:
 * 2xx acked; 409 duplicate acked as duplicate with the server id; 422 quarantined; 410 rejected;
 * 401/403 pause everything until sign-in; 413 recompress once at quality 70 then quarantine;
 * 429/5xx/network retry with backoff 2, 4, 8, 16, 32 s then exponential from a 30 s base (FR2.045).
 * A 409 that is not a duplicate (no FIELD-*-409-DUPLICATE code and no duplicate_of) is quarantined,
 * so a real conflict is never silently acked.
 * The Room-entity overload lives in ConflictPolicy.kt.
 */
object ConflictPolicy {

    val RETRY_BACKOFF_SECONDS = listOf(2L, 4L, 8L, 16L, 32L)
    private const val WORKMANAGER_BASE_S = 30L
    private const val MAX_BACKOFF_S = 300L

    fun calculateRetryDelayMs(attempt: Int): Long {
        val a = attempt.coerceAtLeast(0)
        val seconds = if (a < RETRY_BACKOFF_SECONDS.size) {
            RETRY_BACKOFF_SECONDS[a]
        } else {
            val exponent = (a - RETRY_BACKOFF_SECONDS.size).coerceAtMost(4)
            (WORKMANAGER_BASE_S * (1L shl exponent)).coerceAtMost(MAX_BACKOFF_S)
        }
        return seconds * 1000L
    }

    fun evaluate(
        httpStatusCode: Int,
        responseBody: String?,
        attempts: Int,
        recompressed: Boolean,
        isNetworkError: Boolean = false,
    ): SyncDecision {
        if (isNetworkError) {
            return SyncDecision.Retry(calculateRetryDelayMs(attempts), "Network connectivity failure")
        }
        return when (httpStatusCode) {
            in 200..299 -> SyncDecision.Ack(serverId = parseField(responseBody, "id"), isDuplicate = false)
            409 -> {
                val dupOf = parseField(responseBody, "duplicate_of")
                val code = parseField(responseBody, "code")
                if (dupOf != null || code?.endsWith("-409-DUPLICATE") == true) {
                    SyncDecision.Ack(serverId = dupOf ?: parseField(responseBody, "id"), isDuplicate = true)
                } else {
                    SyncDecision.Quarantine("Conflict 409 ${code ?: "without code"}")
                }
            }
            422 -> SyncDecision.Quarantine("422 ${parseField(responseBody, "code") ?: "unprocessable"}: quarantined (key mismatch or invalid payload)")
            410 -> SyncDecision.Reject("410 task closed on server")
            401, 403 -> SyncDecision.PauseAll("Authentication revoked or expired ($httpStatusCode). Sign in again.")
            413 -> if (!recompressed) {
                SyncDecision.RecompressAndRetry
            } else {
                SyncDecision.Quarantine("413 payload too large even after quality 70 recompression")
            }
            429, in 500..599 -> {
                val delay = calculateRetryDelayMs(attempts)
                SyncDecision.Retry(delay, "Server error ($httpStatusCode): retrying in ${delay / 1000}s")
            }
            else -> SyncDecision.Quarantine("Unexpected HTTP $httpStatusCode")
        }
    }

    private fun parseField(body: String?, name: String): String? {
        if (body.isNullOrBlank()) return null
        return Regex(""""$name"\s*:\s*"([^"]+)"""").find(body)?.groupValues?.get(1)
    }
}
