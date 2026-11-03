package com.scmtips.field.app.device

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.Bundle
import android.speech.tts.UtteranceProgressListener
import android.util.Base64
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import com.scmtips.field.app.jobs.Speaker
import com.scmtips.field.app.session.MicSource
import com.scmtips.field.app.session.RestartBackoff
import com.scmtips.field.core.wearables.EarconCue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.ByteArrayOutputStream
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger
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

    suspend fun read(bitmap: Bitmap): List<String> = read(InputImage.fromBitmap(bitmap, 0))

    /** One glasses video frame, already converted to NV21 (scan by looking, M3 contract §5). */
    suspend fun readNv21(nv21: ByteArray, width: Int, height: Int): List<String> =
        read(InputImage.fromByteArray(nv21, width, height, 0, InputImage.IMAGE_FORMAT_NV21))

    private suspend fun read(image: InputImage): List<String> = suspendCancellableCoroutine { cont ->
        scanner.process(image)
            .addOnSuccessListener { codes -> cont.resume(codes.mapNotNull { it.rawValue }.distinct()) }
            .addOnFailureListener { cont.resume(emptyList()) }
    }

    companion object {
        /** The assistant takes at most 1 MB of JPEG (contract §4): scaled to 1280 px, quality lowered until it fits. */
        fun jpegBase64(bitmap: Bitmap, maxBytes: Int = 1_000_000): String? {
            val longest = maxOf(bitmap.width, bitmap.height)
            val scaled = if (longest > 1280) {
                val f = 1280f / longest
                Bitmap.createScaledBitmap(bitmap, (bitmap.width * f).toInt().coerceAtLeast(1), (bitmap.height * f).toInt().coerceAtLeast(1), true)
            } else bitmap
            for (q in listOf(80, 65, 50, 35)) {
                val out = ByteArrayOutputStream()
                scaled.compress(Bitmap.CompressFormat.JPEG, q, out)
                if (out.size() <= maxBytes) return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
            }
            return null
        }
    }
}

/**
 * Speech and earcons out. With the glasses connected as the phone's Bluetooth audio device, media
 * audio plays through their open-ear speakers (Gen 2 has no display, so this is the only prompt path).
 */
class TtsSpeaker(
    context: Context,
    private val onSaid: (String) -> Unit,
    /** True while an utterance is playing (the session microphone is held meanwhile: no self-hearing). */
    private val onSpeaking: (Boolean) -> Unit = {},
) : Speaker {
    private var ready = false
    private val pending = mutableListOf<Pair<String, Int>>()
    private val playing = AtomicInteger(0)
    private val seq = AtomicInteger(0)
    private val tts: TextToSpeech = TextToSpeech(context.applicationContext) { status ->
        ready = status == TextToSpeech.SUCCESS
        if (ready) {
            tts.language = Locale.US
            tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) = onSpeaking(true)
                override fun onDone(utteranceId: String?) = finished()
                @Deprecated("Deprecated in Java")
                override fun onError(utteranceId: String?) = finished()
                override fun onStop(utteranceId: String?, interrupted: Boolean) = finished()
            })
            pending.forEach { (t, mode) -> speakNow(t, mode) }
        }
        pending.clear()
    }

    /**
     * During a work session that hears through the glasses' Bluetooth hands-free link, prompts are
     * played as voice-communication audio so they go out on that same link (glasses speakers).
     */
    fun useCallAudio(on: Boolean) {
        val usage = if (on) AudioAttributes.USAGE_VOICE_COMMUNICATION else AudioAttributes.USAGE_ASSISTANT
        tts.setAudioAttributes(AudioAttributes.Builder().setUsage(usage).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
    }

    private fun finished() {
        if (playing.decrementAndGet() <= 0) {
            playing.set(0)
            onSpeaking(false)
        }
    }
    private val tones = ToneGenerator(AudioManager.STREAM_MUSIC, 80)

    override fun say(text: String) {
        onSaid(text)
        if (ready) speakNow(text, TextToSpeech.QUEUE_FLUSH) else pending += text to TextToSpeech.QUEUE_FLUSH
    }

    override fun queue(text: String) {
        onSaid(text)
        if (ready) speakNow(text, TextToSpeech.QUEUE_ADD) else pending += text to TextToSpeech.QUEUE_ADD
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

    private fun speakNow(text: String, mode: Int) {
        if (mode == TextToSpeech.QUEUE_FLUSH) playing.set(0)
        playing.incrementAndGet()
        if (tts.speak(text, mode, null, "u${seq.incrementAndGet()}") != TextToSpeech.SUCCESS) finished()
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
                val conf = com.scmtips.field.app.session.SpokenText.confidence(scores) // 0 or none = the floor (4 Nov test)
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

/**
 * The work session's microphone when the glasses' own speech is not used: Android's recogniser, started
 * again after every result or error ([RestartBackoff]), with the glasses as the Bluetooth hands-free
 * (SCO) input when the phone offers one (Android 12+: AudioManager.setCommunicationDevice); else the
 * phone microphone. [hold] stops listening while the phone speaks or the session is paused, without
 * dropping the Bluetooth link. Runs only between [start] and [stop] (owner decision A-03).
 * Must be called on the main thread (SpeechRecognizer's rule).
 */
class ContinuousSpeech(
    private val context: Context,
    private val scope: CoroutineScope,
    private val onResult: (String, Float) -> Unit,
    private val onNote: (String) -> Unit,
) {
    private val audio = context.getSystemService(AudioManager::class.java)
    private var recognizer: SpeechRecognizer? = null
    private val backoff = RestartBackoff()
    private var wanted = false
    private var held = false
    private var listening = false
    private var restart: Job? = null
    var source: MicSource = MicSource.NONE
        private set

    /** Opens the microphone path; returns where the words will come from. */
    fun start(preferBluetooth: Boolean): MicSource {
        if (wanted) return source
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            onNote("no speech recogniser on this phone")
            return MicSource.NONE
        }
        wanted = true
        source = if (preferBluetooth && routeToBluetooth()) MicSource.BLUETOOTH else MicSource.PHONE
        recognizer = SpeechRecognizer.createSpeechRecognizer(context).also { it.setRecognitionListener(listener) }
        listenAfter(0)
        return source
    }

    fun stop() {
        wanted = false
        restart?.cancel()
        recognizer?.cancel()
        recognizer?.destroy()
        recognizer = null
        listening = false
        if (source == MicSource.BLUETOOTH && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) audio?.clearCommunicationDevice()
        source = MicSource.NONE
    }

    /** True: stop listening for now (the phone speaks, or the session is paused). False: listen again. */
    fun hold(on: Boolean) {
        if (held == on) return
        held = on
        if (on) {
            restart?.cancel()
            if (listening) recognizer?.cancel()
            listening = false
        } else listenAfter(150)
    }

    private fun routeToBluetooth(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return false
        val am = audio ?: return false
        val sco = am.availableCommunicationDevices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO } ?: return false
        return am.setCommunicationDevice(sco)
    }

    private fun listenAfter(ms: Long) {
        restart?.cancel()
        if (!wanted || held) return
        restart = scope.launch {
            delay(ms)
            val r = recognizer ?: return@launch
            if (!wanted || held || listening) return@launch
            listening = true
            r.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US")
                putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
            })
        }
    }

    private val listener = object : RecognitionListener {
        override fun onResults(results: Bundle) {
            listening = false
            val texts = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
            val scores = results.getFloatArray(SpeechRecognizer.CONFIDENCE_SCORES)
            texts.firstOrNull()?.takeIf { it.isNotBlank() }?.let { onResult(it, com.scmtips.field.app.session.SpokenText.confidence(scores)) }
            listenAfter(backoff.afterResult())
        }

        override fun onError(error: Int) {
            listening = false
            val wait = backoff.afterError(error)
            if (wait == null) {
                onNote("microphone permission missing: the session cannot listen")
                stop()
            } else {
                if (error != RestartBackoff.ERROR_NO_MATCH && error != RestartBackoff.ERROR_SPEECH_TIMEOUT) onNote("speech error $error, again in ${wait} ms")
                listenAfter(wait)
            }
        }

        override fun onReadyForSpeech(params: Bundle?) = Unit
        override fun onBeginningOfSpeech() = Unit
        override fun onRmsChanged(rmsdB: Float) = Unit
        override fun onBufferReceived(buffer: ByteArray?) = Unit
        override fun onEndOfSpeech() = Unit
        override fun onPartialResults(partialResults: Bundle?) = Unit
        override fun onEvent(eventType: Int, params: Bundle?) = Unit
    }
}
