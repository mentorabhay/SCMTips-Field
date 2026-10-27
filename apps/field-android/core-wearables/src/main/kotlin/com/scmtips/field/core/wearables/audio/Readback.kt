package com.scmtips.field.core.wearables.audio

import com.scmtips.field.core.wearables.AudioOut
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Manages text-to-speech readbacks routed to smart glasses speakers (Task T2.016 / FR2.012 / TC2.112).
 * Flushes active speech instantly when the user taps or triggers Push-to-Talk.
 */
class GlassesReadbackManager(
    private val audioOut: AudioOut,
    private val speechRate: Float = 1.0f,
    private val volume: Float = 1.0f
) {
    private val _isSpeaking = MutableStateFlow(false)
    val isSpeaking: StateFlow<Boolean> = _isSpeaking.asStateFlow()

    private val _lastReadback = MutableStateFlow<String?>(null)
    val lastReadback: StateFlow<String?> = _lastReadback.asStateFlow()

    /**
     * Reads back an entered quantity or confirmation prompt (e.g., "Count 12. Say confirm.").
     * Enforces queue flush if another prompt was playing.
     */
    suspend fun readbackCount(count: Int, unit: String = "each") {
        val prompt = "Count $count. Say confirm."
        speak(prompt, flushQueue = true)
    }

    suspend fun readbackReading(value: Double, unit: String) {
        val prompt = "Reading $value $unit. Say confirm."
        speak(prompt, flushQueue = true)
    }

    suspend fun speak(text: String, flushQueue: Boolean = true) {
        _lastReadback.value = text
        _isSpeaking.value = true
        try {
            audioOut.playSpeech(text, flushQueue = flushQueue)
        } finally {
            _isSpeaking.value = false
        }
    }

    /**
     * Triggered on user Push-to-Talk button press or tap.
     * Instantly flushes speech queue so TTS never talks over the user (T2.016).
     */
    fun onPushToTalkStarted() {
        audioOut.stopAudio()
        _isSpeaking.value = false
    }
}
