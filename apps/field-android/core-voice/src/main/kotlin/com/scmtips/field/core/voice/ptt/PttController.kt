package com.scmtips.field.core.voice.ptt

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Arrays

enum class PttTriggerSource {
    ON_SCREEN_TOUCH,
    VOLUME_DOWN_LONG_PRESS,
    BLUETOOTH_MEDIA_BUTTON
}

enum class PttState {
    IDLE,
    LISTENING,
    PROCESSING
}

/**
 * RAM-only audio ring buffer that is zeroed immediately after recognition (Task T2.032 / FR2.011 / FR2.035).
 * Guarantees zero persistent audio files on device storage.
 */
class SecureAudioRamBuffer(val capacityBytes: Int = 16000 * 2 * 10) { // 10 seconds of 16kHz 16-bit mono
    private val buffer = ByteArray(capacityBytes)
    private var writePos = 0

    @Synchronized
    fun write(pcmData: ByteArray, offset: Int = 0, length: Int = pcmData.size) {
        val toCopy = length.coerceAtMost(capacityBytes - writePos)
        System.arraycopy(pcmData, offset, buffer, writePos, toCopy)
        writePos += toCopy
    }

    @Synchronized
    fun getSnapshot(): ByteArray {
        val snapshot = ByteArray(writePos)
        System.arraycopy(buffer, 0, snapshot, 0, writePos)
        return snapshot
    }

    /**
     * Zeros the RAM buffer memory completely (FR2.035).
     */
    @Synchronized
    fun zeroAndReset() {
        Arrays.fill(buffer, 0.toByte())
        writePos = 0
    }

    fun bytesWritten(): Int = writePos

    /** True when every byte of the backing RAM buffer is zero (FR2.035 evidence for tests and diagnostics). */
    @Synchronized
    fun isZeroed(): Boolean = writePos == 0 && buffer.all { it == 0.toByte() }
}

/**
 * Push-to-talk controller (T2.032; FR2.011, FR2.035). Audio is recorded only while held.
 *
 * On release the captured PCM is handed to [onPttStopped] (the recogniser) and then zeroed: both the
 * ring buffer and the snapshot array are wiped when the callback returns, so the callback must finish
 * recognition (or copy what it needs) before returning. No audio is ever written to storage here.
 */
class PttController(
    val audioBuffer: SecureAudioRamBuffer = SecureAudioRamBuffer(),
    private val onPttStarted: (PttTriggerSource) -> Unit = {},
    private val onPttStopped: (ByteArray) -> Unit = {}
) {
    private val _state = MutableStateFlow(PttState.IDLE)
    val state: StateFlow<PttState> = _state.asStateFlow()

    private var activeSource: PttTriggerSource? = null

    fun startPtt(source: PttTriggerSource) {
        if (_state.value != PttState.IDLE) return
        activeSource = source
        _state.value = PttState.LISTENING
        audioBuffer.zeroAndReset()
        onPttStarted(source)
    }

    fun stopPtt() {
        if (_state.value != PttState.LISTENING) return
        _state.value = PttState.PROCESSING
        val audioSnapshot = audioBuffer.getSnapshot()
        
        // Zero the RAM buffer immediately after capturing snapshot for ASR (FR2.035)
        audioBuffer.zeroAndReset()

        try {
            onPttStopped(audioSnapshot)
        } finally {
            Arrays.fill(audioSnapshot, 0.toByte())
            _state.value = PttState.IDLE
        }
        activeSource = null
    }

    fun appendAudioChunk(pcmChunk: ByteArray) {
        if (_state.value == PttState.LISTENING) {
            audioBuffer.write(pcmChunk)
        }
    }

    fun isListening(): Boolean = _state.value == PttState.LISTENING
}
