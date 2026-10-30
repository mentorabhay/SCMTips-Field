package com.scmtips.field.core.wearables.mock

import com.scmtips.field.core.wearables.AudioOut
import com.scmtips.field.core.wearables.CapturedPhoto
import com.scmtips.field.core.wearables.ConnectionState
import com.scmtips.field.core.wearables.EarconCue
import com.scmtips.field.core.wearables.GlassesSession
import com.scmtips.field.core.wearables.LensRenderer
import com.scmtips.field.core.wearables.PreviewFrame
import com.scmtips.field.core.wearables.PreviewStream
import com.scmtips.field.core.wearables.StillCapture
import com.scmtips.field.core.wearables.testing.FakeLensRenderer
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.UUID

/**
 * Hand-written in-memory [GlassesSession] test double (rule 2.4). It is NOT Meta's Mock Device Kit
 * (com.meta.wearable:mwdat-mockdevice); TC2.117 needs that kit and stays open until it is wired.
 * Glasses report a display only when the model name contains "Display" (Ray-Ban Meta Gen 2 does not).
 * Lives in :core-wearables-testing so production modules cannot depend on it.
 */
class MockWearablesKit(
    val fakeRenderer: FakeLensRenderer = FakeLensRenderer()
) : GlassesSession {

    private val _connectionState = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    override val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()

    private val _frameFlow = MutableSharedFlow<PreviewFrame>(replay = 1)
    private var isStreamingActive = false

    override val previewStream: PreviewStream = object : PreviewStream {
        override val frames: Flow<PreviewFrame> = _frameFlow.asSharedFlow()
        override fun startStream() { isStreamingActive = true }
        override fun stopStream() { isStreamingActive = false }
        override fun isStreaming(): Boolean = isStreamingActive
    }

    override val stillCapture: StillCapture = object : StillCapture {
        override suspend fun capturePhoto(): CapturedPhoto {
            val traceId = UUID.randomUUID().toString().replace("-", "")
            val spanId = UUID.randomUUID().toString().replace("-", "").take(16)
            return CapturedPhoto(
                jpegBytes = ByteArray(1024) { 0xFF.toByte() }, // Synthetic 1KB JPEG
                width = 3024,
                height = 4032,
                timestampMs = System.currentTimeMillis(),
                traceparent = "00-$traceId-$spanId-01"
            )
        }
    }

    val playedEarcons = mutableListOf<EarconCue>()
    val playedSpeeches = mutableListOf<String>()
    /** Every speech request in order, never cleared by a queue flush. */
    val speechLog = mutableListOf<String>()
    var stopAudioCalls = 0
        private set
    /** Number of upcoming connect() calls that fail, to exercise reconnect backoff. */
    var failNextConnects = 0
    /** Address passed to every connect() call, in order. */
    val connectAddresses = mutableListOf<String>()

    override val audioOut: AudioOut = object : AudioOut {
        override suspend fun playEarcon(cue: EarconCue) {
            playedEarcons.add(cue)
        }

        override suspend fun playSpeech(text: String, flushQueue: Boolean) {
            if (flushQueue) playedSpeeches.clear()
            playedSpeeches.add(text)
            speechLog.add(text)
        }

        override fun stopAudio() {
            stopAudioCalls++
            playedSpeeches.clear()
        }
    }

    override val lensRenderer: LensRenderer = fakeRenderer

    override suspend fun connect(deviceAddress: String, model: String) {
        connectAddresses.add(deviceAddress)
        if (failNextConnects > 0) {
            failNextConnects--
            _connectionState.value = ConnectionState.Error("INJECTED_CONNECT_FAILURE")
            return
        }
        val hasDisplay = model.contains("Display", ignoreCase = true)
        _connectionState.value = ConnectionState.Connected(
            model = model,
            displayCapability = hasDisplay,
            batteryPct = 95
        )
    }

    override suspend fun disconnect() {
        _connectionState.value = ConnectionState.Disconnected
        isStreamingActive = false
    }

    override fun isDisplayAvailable(): Boolean {
        val current = _connectionState.value
        return current is ConnectionState.Connected && current.displayCapability
    }

    // --- Testing injection helpers ---

    suspend fun emitSyntheticFrame(width: Int = 504, height: Int = 896) {
        val frame = PreviewFrame(
            width = width,
            height = height,
            data = ByteArray(64) { 0x42 },
            timestampMs = System.currentTimeMillis()
        )
        _frameFlow.emit(frame)
    }

    fun injectDisconnect(reason: String = "INJECTED_TEST_DISCONNECT") {
        _connectionState.value = ConnectionState.Error(reason)
        isStreamingActive = false
    }

    fun injectBattery(batteryPct: Int) {
        val cur = _connectionState.value
        if (cur is ConnectionState.Connected) {
            _connectionState.value = cur.copy(batteryPct = batteryPct)
        }
    }
}
