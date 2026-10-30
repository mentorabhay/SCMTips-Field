package com.scmtips.field.app.device

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import com.scmtips.field.app.slice.Speaker
import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.Locale
import kotlin.coroutines.resume

/**
 * Barcode reading on the phone from a glasses photo (ML Kit, bundled model: works offline).
 * Code 128 / GS1-128 / QR / DataMatrix / EAN cover SAMPLE labels and real cartons.
 */
class BarcodeReader {
    private val scanner = BarcodeScanning.getClient(
        BarcodeScannerOptions.Builder().setBarcodeFormats(
            Barcode.FORMAT_CODE_128, Barcode.FORMAT_QR_CODE, Barcode.FORMAT_DATA_MATRIX,
            Barcode.FORMAT_EAN_13, Barcode.FORMAT_CODE_39,
        ).build(),
    )

    suspend fun read(bitmap: Bitmap): List<String> = suspendCancellableCoroutine { cont ->
        scanner.process(InputImage.fromBitmap(bitmap, 0))
            .addOnSuccessListener { codes -> cont.resume(codes.mapNotNull { it.rawValue }.distinct()) }
            .addOnFailureListener { cont.resume(emptyList()) }
    }
}

/**
 * Speech and earcons out. With the glasses connected as the phone's Bluetooth audio device, media
 * audio plays through their open-ear speakers (Gen 2 has no display, so this is the only prompt path).
 */
class TtsSpeaker(context: Context, private val onSaid: (String) -> Unit) : Speaker {
    private var ready = false
    private val pending = mutableListOf<String>()
    private val tts: TextToSpeech = TextToSpeech(context.applicationContext) { status ->
        ready = status == TextToSpeech.SUCCESS
        if (ready) {
            tts.language = Locale.US
            pending.forEach { speakNow(it) }
        }
        pending.clear()
    }
    private val tones = ToneGenerator(AudioManager.STREAM_MUSIC, 80)

    override fun say(text: String) {
        onSaid(text)
        if (ready) speakNow(text) else pending += text
    }

    override fun earcon(cue: EarconCue) {
        val tone = when (cue) {
            EarconCue.CAPTURED, EarconCue.READY -> ToneGenerator.TONE_PROP_ACK
            EarconCue.CONFIRM_PROMPT -> ToneGenerator.TONE_PROP_PROMPT
            EarconCue.DUPLICATE, EarconCue.OFFLINE_QUEUED -> ToneGenerator.TONE_PROP_BEEP2
            EarconCue.ERROR -> ToneGenerator.TONE_PROP_NACK
        }
        tones.startTone(tone, cue.durationMs)
    }

    private fun speakNow(text: String) {
        tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "u${text.hashCode()}")
    }

    fun shutdown() {
        tts.shutdown()
        tones.release()
    }
}

/**
 * Fallback when glasses speech is unavailable: Android's recogniser on the phone microphone, started
 * by holding the on-screen talk button. Returns the best hypothesis and its confidence; when the engine
 * gives none it is reported as exactly the 0.80 floor, the same rule as glasses speech (DatGlasses).
 */
class PhoneSpeech(context: Context, private val onResult: (String, Float) -> Unit, private val onError: (String) -> Unit) {
    private val recognizer: SpeechRecognizer? =
        if (SpeechRecognizer.isRecognitionAvailable(context)) SpeechRecognizer.createSpeechRecognizer(context) else null

    init {
        recognizer?.setRecognitionListener(object : RecognitionListener {
            override fun onResults(results: Bundle) {
                val texts = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
                val scores = results.getFloatArray(SpeechRecognizer.CONFIDENCE_SCORES)
                val text = texts.firstOrNull() ?: return onError("no speech recognised")
                val conf = scores?.firstOrNull()?.takeIf { it >= 0f } ?: 0.80f
                onResult(text, conf)
            }
            override fun onError(error: Int) = onError("speech error $error")
            override fun onReadyForSpeech(params: Bundle?) = Unit
            override fun onBeginningOfSpeech() = Unit
            override fun onRmsChanged(rmsdB: Float) = Unit
            override fun onBufferReceived(buffer: ByteArray?) = Unit
            override fun onEndOfSpeech() = Unit
            override fun onPartialResults(partialResults: Bundle?) = Unit
            override fun onEvent(eventType: Int, params: Bundle?) = Unit
        })
    }

    val available: Boolean get() = recognizer != null

    fun start() {
        val r = recognizer ?: return onError("no speech recogniser on this phone")
        r.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US")
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
        })
    }

    fun stop() = recognizer?.stopListening()

    fun destroy() = recognizer?.destroy()
}
