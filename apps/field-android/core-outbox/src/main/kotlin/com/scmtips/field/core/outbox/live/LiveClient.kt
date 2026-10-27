package com.scmtips.field.core.outbox.live

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.Collections
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Lens tick marks mapped from live server events (Task T2.044 / FR2.052).
 */
enum class LensTickMark {
    RECEIVED,
    VERIFIED,
    MISMATCH,
    POSTED,
    FAILED
}

data class LiveTick(
    val eventId: String,
    val tickMark: LensTickMark,
    val captureId: String?,
    val taskId: String?,
    val detail: String? = null,
    val timestamp: Long = System.currentTimeMillis()
)

enum class LiveTransportMode {
    WEBSOCKET,
    SSE_FALLBACK
}

/**
 * Live client connecting to WebSocket or SSE fallback with auto-reconnect,
 * event deduplication, and last_event_id resume (Task T2.044 / FR2.052, TC2.144, TC2.145).
 */
class LiveClient(
    val deviceId: String,
    val baseUrl: String = "https://api.field.scmtips.internal",
    private val httpClient: OkHttpClient = OkHttpClient(),
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.IO)
) {
    private val _ticks = MutableSharedFlow<LiveTick>(extraBufferCapacity = 64)
    val ticks: SharedFlow<LiveTick> = _ticks.asSharedFlow()

    private var activeTransportMode = LiveTransportMode.WEBSOCKET
    private val failedUpgradeCount = AtomicInteger(0)
    private var lastEventId: String? = null
    private val processedEventIds = Collections.synchronizedSet(LinkedHashSet<String>())
    private val isRunning = AtomicBoolean(false)
    private var connectionJob: Job? = null
    private var reconnectAttempt = 0

    fun getTransportMode(): LiveTransportMode = activeTransportMode
    fun getLastEventId(): String? = lastEventId

    fun start() {
        if (isRunning.compareAndSet(false, true)) {
            reconnectAttempt = 0
            connect()
        }
    }

    fun stop() {
        isRunning.set(false)
        connectionJob?.cancel()
        connectionJob = null
    }

    private fun connect() {
        if (!isRunning.get()) return

        connectionJob = scope.launch {
            if (activeTransportMode == LiveTransportMode.WEBSOCKET) {
                connectWebSocket()
            } else {
                connectSse()
            }
        }
    }

    private fun connectWebSocket() {
        val wsUrl = buildString {
            val base = baseUrl.replace("http://", "ws://").replace("https://", "wss://")
            append("$base/v1/devices/$deviceId/live")
            lastEventId?.let { append("?last_event_id=$it") }
        }

        val request = Request.Builder().url(wsUrl).build()

        httpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                // Connection opened successfully, reset failed upgrades and backoff
                failedUpgradeCount.set(0)
                reconnectAttempt = 0
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleIncomingMessage(text)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                val failures = failedUpgradeCount.incrementAndGet()
                if (failures >= 2) {
                    // Fall back to SSE after 2 failed upgrades (TC2.145)
                    activeTransportMode = LiveTransportMode.SSE_FALLBACK
                }
                scheduleReconnect()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                scheduleReconnect()
            }
        })
    }

    private suspend fun connectSse() {
        val sseUrl = buildString {
            append("$baseUrl/v1/devices/$deviceId/events")
            lastEventId?.let { append("?last_event_id=$it") }
        }

        val request = Request.Builder()
            .url(sseUrl)
            .header("Accept", "text/event-stream")
            .build()

        try {
            httpClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    scheduleReconnect()
                    return
                }

                val reader = response.body?.byteStream()?.bufferedReader() ?: return
                var currentEventId: String? = null
                var currentData: String? = null

                while (isRunning.get()) {
                    val line = reader.readLine() ?: break
                    if (line.startsWith("id:")) {
                        currentEventId = line.substring(3).trim()
                    } else if (line.startsWith("data:")) {
                        currentData = line.substring(5).trim()
                    } else if (line.isEmpty() && currentEventId != null && currentData != null) {
                        handleEvent(currentEventId, currentData)
                        currentEventId = null
                        currentData = null
                    }
                }
            }
        } catch (e: Exception) {
            scheduleReconnect()
        }
    }

    fun handleIncomingMessage(rawJson: String) {
        val eventId = extractJsonString(rawJson, "event_id") ?: extractJsonString(rawJson, "id") ?: return
        val tickType = extractJsonString(rawJson, "tick") ?: extractJsonString(rawJson, "type") ?: "received"
        val captureId = extractJsonString(rawJson, "capture_id")
        val taskId = extractJsonString(rawJson, "task_id")
        val detail = extractJsonString(rawJson, "detail")

        handleEvent(eventId, tickType, captureId, taskId, detail)
    }

    fun handleEvent(
        eventId: String,
        tickType: String,
        captureId: String? = null,
        taskId: String? = null,
        detail: String? = null
    ) {
        // Deduplicate by event_id (FR2.052, TC2.144)
        if (!processedEventIds.add(eventId)) {
            // Already processed this event, drop duplicate
            return
        }

        // Cap cache size at 1000 items
        if (processedEventIds.size > 1000) {
            val iterator = processedEventIds.iterator()
            if (iterator.hasNext()) {
                iterator.next()
                iterator.remove()
            }
        }

        lastEventId = eventId

        val mark = mapToLensMark(tickType)
        val tick = LiveTick(
            eventId = eventId,
            tickMark = mark,
            captureId = captureId,
            taskId = taskId,
            detail = detail
        )
        _ticks.tryEmit(tick)
    }

    private fun mapToLensMark(tickType: String): LensTickMark = when (tickType.lowercase()) {
        "received", "capture.created" -> LensTickMark.RECEIVED
        "verified", "capture.verified" -> LensTickMark.VERIFIED
        "mismatch", "capture.mismatch" -> LensTickMark.MISMATCH
        "posted", "erp.posted" -> LensTickMark.POSTED
        "failed", "error", "capture.failed" -> LensTickMark.FAILED
        else -> LensTickMark.RECEIVED
    }

    fun scheduleReconnect() {
        if (!isRunning.get()) return

        // Backoff ladder: 1, 2, 4, 8, 16, 30s capped at 30s
        val delaySec = minOf(1L shl reconnectAttempt, 30L)
        reconnectAttempt++

        scope.launch {
            delay(delaySec * 1000L)
            connect()
        }
    }

    private fun extractJsonString(json: String, key: String): String? {
        val pattern = """"$key"\s*:\s*"([^"]+)"""".toRegex()
        return pattern.find(json)?.groupValues?.get(1)
    }
}
