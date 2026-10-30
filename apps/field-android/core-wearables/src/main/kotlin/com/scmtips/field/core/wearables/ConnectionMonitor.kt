package com.scmtips.field.core.wearables

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

interface DisconnectRecoveryListener {
    fun onLookInProgressDiscarded()
    fun onPreviewResumed()
}

/**
 * Handles Bluetooth / Wi-Fi disconnects and reconnects with capped backoff
 * (Task T2.013 / FR2.015 / TC2.116).
 *
 * Backoff schedule: 1s, 2s, 4s, 8s, 16s, 30s (cap 30s). Reconnects to the stored address without a
 * new pairing, discards the look in progress, and restarts the preview stream once connected.
 */
class ConnectionMonitor(
    private val glassesSession: GlassesSession,
    private val recoveryListener: DisconnectRecoveryListener? = null,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default),
    private val sleep: suspend (Long) -> Unit = { delay(it) },
) {
    companion object {
        val BACKOFF_SCHEDULE_MS = listOf(
            1_000L,
            2_000L,
            4_000L,
            8_000L,
            16_000L,
            30_000L
        )
    }

    private var reconnectJob: Job? = null
    private var reconnectAttempt = 0
    private var lastTargetAddress: String? = null
    private var lastModel: String = "Ray-Ban Display"

    private val _reconnectCount = MutableStateFlow(0)
    val reconnectCount: StateFlow<Int> = _reconnectCount.asStateFlow()

    fun onConnected(address: String, model: String) {
        lastTargetAddress = address
        lastModel = model
        reconnectAttempt = 0
        reconnectJob?.cancel()
    }

    /**
     * Triggered on unexpected glasses disconnect.
     * Discards the look in progress; outbox records remain intact.
     */
    fun onDisconnected(reason: String = "BT_LINK_LOSS") {
        // Discard any look/capture in progress (FR2.015)
        recoveryListener?.onLookInProgressDiscarded()

        val targetAddress = lastTargetAddress ?: return
        startReconnectLoop(targetAddress, lastModel)
    }

    private fun startReconnectLoop(address: String, model: String) {
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            while (true) {
                val delayMs = if (reconnectAttempt < BACKOFF_SCHEDULE_MS.size) {
                    BACKOFF_SCHEDULE_MS[reconnectAttempt]
                } else {
                    BACKOFF_SCHEDULE_MS.last()
                }

                sleep(delayMs)
                reconnectAttempt++

                try {
                    glassesSession.connect(address, model)
                    if (glassesSession.connectionState.value !is ConnectionState.Connected) {
                        throw IllegalStateException("not connected after reconnect attempt")
                    }
                    // Reconnected with the stored pairing; resume the preview (FR2.015)
                    glassesSession.previewStream.startStream()
                    _reconnectCount.value = _reconnectCount.value + 1
                    reconnectAttempt = 0
                    recoveryListener?.onPreviewResumed()
                    break
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    // Retry with next backoff
                }
            }
        }
    }

    fun stopMonitoring() {
        reconnectJob?.cancel()
    }

    fun getNextDelayMs(attempt: Int): Long {
        return if (attempt < BACKOFF_SCHEDULE_MS.size) {
            BACKOFF_SCHEDULE_MS[attempt]
        } else {
            BACKOFF_SCHEDULE_MS.last()
        }
    }
}
