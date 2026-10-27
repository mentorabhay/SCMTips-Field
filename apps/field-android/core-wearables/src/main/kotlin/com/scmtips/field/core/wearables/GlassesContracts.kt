package com.scmtips.field.core.wearables

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

/**
 * Connection states for paired smart glasses (Task T2.011 / FR2.009).
 */
sealed class ConnectionState {
    object Disconnected : ConnectionState()
    data class Connecting(val deviceAddress: String) : ConnectionState()
    data class Connected(
        val model: String,
        val displayCapability: Boolean,
        val batteryPct: Int = 100
    ) : ConnectionState()
    data class Reconnecting(val attempt: Int, val delayMs: Long) : ConnectionState()
    data class Error(val reason: String) : ConnectionState()
}

/**
 * Preview frame representation targeting 504x896 at 15 fps (T2.011 / FR2.010).
 */
data class PreviewFrame(
    val width: Int = 504,
    val height: Int = 896,
    val data: ByteArray,
    val timestampMs: Long = System.currentTimeMillis()
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (javaClass != other?.javaClass) return false
        other as PreviewFrame
        return timestampMs == other.timestampMs && data.contentEquals(other.data)
    }

    override fun hashCode(): Int = 31 * timestampMs.hashCode() + data.contentHashCode()
}

interface PreviewStream {
    val frames: Flow<PreviewFrame>
    fun startStream()
    fun stopStream()
    fun isStreaming(): Boolean
}

data class CapturedPhoto(
    val jpegBytes: ByteArray,
    val width: Int = 3024,
    val height: Int = 4032,
    val timestampMs: Long = System.currentTimeMillis(),
    val traceparent: String? = null
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (javaClass != other?.javaClass) return false
        other as CapturedPhoto
        return timestampMs == other.timestampMs && jpegBytes.contentEquals(other.jpegBytes)
    }

    override fun hashCode(): Int = 31 * timestampMs.hashCode() + jpegBytes.contentHashCode()
}

interface StillCapture {
    suspend fun capturePhoto(): CapturedPhoto
}

enum class EarconCue(val cueName: String, val frequencyHz: Int, val durationMs: Int) {
    READY("ready", 440, 100),
    CAPTURED("captured", 880, 150),
    DUPLICATE("duplicate", 330, 200),
    OFFLINE_QUEUED("offline_queued", 520, 150),
    ERROR("error", 220, 250),
    CONFIRM_PROMPT("confirm_prompt", 660, 120)
}

interface AudioOut {
    suspend fun playEarcon(cue: EarconCue)
    suspend fun playSpeech(text: String, flushQueue: Boolean = true)
    fun stopAudio()
}

/**
 * 7 lens states defined in SCR2.07 for Ray-Ban Display HUD (T2.014 / FR2.013).
 */
enum class LensState {
    READY,
    MOVING,
    TIE,
    CAPTURED,
    DUPLICATE,
    OFFLINE_QUEUED,
    ERROR
}

data class DrawCall(
    val state: LensState,
    val line1: String,
    val line2: String,
    val actionPill: String?,
    val timestampMs: Long = System.currentTimeMillis()
)

interface LensRenderer {
    fun renderState(
        state: LensState,
        line1: String,
        line2: String = "",
        actionPill: String? = null
    ): DrawCall
}

/**
 * Isolates Wearables Device Access Toolkit from other modules (Task T2.011 / FR2.009).
 */
interface GlassesSession {
    val connectionState: StateFlow<ConnectionState>
    val previewStream: PreviewStream
    val stillCapture: StillCapture
    val audioOut: AudioOut
    val lensRenderer: LensRenderer

    suspend fun connect(deviceAddress: String, model: String = "Ray-Ban Display")
    suspend fun disconnect()
    fun isDisplayAvailable(): Boolean
}
