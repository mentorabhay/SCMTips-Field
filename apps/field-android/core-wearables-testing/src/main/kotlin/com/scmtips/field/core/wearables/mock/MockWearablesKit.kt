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
 * Mock Device Kit implementation simulating Meta smart glasses for CI and unit testing
 * (Task T2.017 / TC2.117 / FR2.015).
 * Isolated inside :core-wearables-testing to preserve architectural firewall (Rule 2.2 / Finding F-07).
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

    override val audioOut: AudioOut = object : AudioOut {
        override suspend fun playEarcon(cue: EarconCue) {
            playedEarcons.add(cue)
        }

        override suspend fun playSpeech(text: String, flushQueue: Boolean) {
            if (flushQueue) playedSpeeches.clear()
            playedSpeeches.add(text)
        }

        override fun stopAudio() {
            // Stop active playback
        }
    }

    override val lensRenderer: LensRenderer = fakeRenderer

    override suspend fun connect(deviceAddress: String, model: String) {
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
    }

    fun injectBattery(batteryPct: Int) {
        val cur = _connectionState.value
        if (cur is ConnectionState.Connected) {
            _connectionState.value = cur.copy(batteryPct = batteryPct)
        }
    }
}
