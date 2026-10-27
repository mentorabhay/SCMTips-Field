package com.scmtips.field.app.auth

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

interface SessionController {
    fun stopSession(reason: String)
}

interface OutboxController {
    fun setSyncBlocked(blocked: Boolean)
    fun purgeExpiredUnsentItems(cutoffEpochMs: Long): Int
}

/**
 * Device Revocation Lifecycle Handler (Task T2.006 / FR2.002 / Decision D2.05).
 */
class RevocationHandler(
    private val tokenManager: TokenManager,
    private val sessionController: SessionController,
    private val outboxController: OutboxController,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default)
) {
    companion object {
        const val MSG2_03 = "This device has been revoked by a supervisor. Active capture has stopped and outbox sync is blocked."
        const val ENCRYPTED_RETENTION_MS = 72 * 3600 * 1000L // 72 hours (D2.05)
    }

    private val _isRevoked = MutableStateFlow(false)
    val isRevoked: StateFlow<Boolean> = _isRevoked.asStateFlow()

    private val _revocationNotice = MutableStateFlow<String?>(null)
    val revocationNotice: StateFlow<String?> = _revocationNotice.asStateFlow()

    private var retentionTimerJob: Job? = null

    /**
     * Triggered on 401 FIELD-AUTH-401-REVOKED or live `device.revoked` SSE event.
     * Completes shutdown sequence within 5 seconds (TC2.102).
     */
    fun handleRevocation(source: String = "401_OR_LIVE_CHANNEL") {
        if (_isRevoked.value) return
        _isRevoked.value = true
        _revocationNotice.value = MSG2_03

        // 1. Immediately block outbox sync
        outboxController.setSyncBlocked(true)

        // 2. Stop capture session within 5s
        sessionController.stopSession("DEVICE_REVOKED: $source")

        // 3. Clear in-memory credentials and tokens
        tokenManager.revoke()

        // 4. Start 72-hour retention timer before local purge (D2.05)
        retentionTimerJob?.cancel()
        retentionTimerJob = scope.launch {
            delay(ENCRYPTED_RETENTION_MS)
            purgeUnsentOutboxItems()
        }
    }

    private fun purgeUnsentOutboxItems() {
        val cutoff = System.currentTimeMillis() - ENCRYPTED_RETENTION_MS
        val purgedCount = outboxController.purgeExpiredUnsentItems(cutoff)
        _revocationNotice.value = "$MSG2_03 [Purged $purgedCount items after 72h retention]"
    }
}
