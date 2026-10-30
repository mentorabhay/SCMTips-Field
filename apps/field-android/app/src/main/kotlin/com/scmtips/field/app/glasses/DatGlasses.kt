package com.scmtips.field.app.glasses

import android.app.Activity
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import com.meta.wearable.dat.camera.Camera
import com.meta.wearable.dat.camera.addCamera
import com.meta.wearable.dat.camera.types.PhotoData
import com.meta.wearable.dat.camera.types.StreamConfiguration
import com.meta.wearable.dat.camera.types.VideoQuality
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.selectors.AutoDeviceSelector
import com.meta.wearable.dat.core.session.DeviceSession
import com.meta.wearable.dat.core.session.DeviceSessionState
import com.meta.wearable.dat.core.types.RegistrationState
import com.meta.wearable.dat.inputs.addInputs
import com.meta.wearable.dat.inputs.types.CapturePressType
import com.meta.wearable.dat.inputs.types.InputEvent
import com.meta.wearable.dat.speech.addSpeech
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Ray-Ban Meta (Gen 2) through Meta's Wearables Device Access Toolkit 1.0.1.
 *
 * - Registration with the Meta AI app (Developer Mode: APPLICATION_ID 0), then one [DeviceSession].
 * - Camera: a low-rate stream (HIGH = 720x1280, 2 fps) kept open so `capturePhoto()` is fast; photos
 *   go to the phone for barcode reading (glasses capture -> phone perception).
 * - Inputs (experimental): a short press of the glasses capture button triggers [onCaptureButton].
 * - Speech (experimental): final transcriptions from the glasses microphones go to [onTranscript].
 * Experimental capabilities may be refused for an app without Developer Center approval; the phone
 * buttons and the phone microphone are the fallback, and the status says which path is live.
 *
 * Every SDK call follows the documented contract: capabilities only after STARTED, collectors before
 * start(), errors surfaced from the session/stream/capability flows (see plugins/mwdat-android skills).
 */
class DatGlasses(
    private val scope: CoroutineScope,
    private val onCaptureButton: () -> Unit,
    private val onTranscript: (text: String, confidence: Float) -> Unit,
) {
    private val _status = MutableStateFlow(GlassesStatus())
    val status: StateFlow<GlassesStatus> = _status.asStateFlow()
    private var session: DeviceSession? = null
    private var camera: Camera? = null
    private val jobs = mutableListOf<Job>()
    private var monitoring = false

    fun startMonitoring() {
        if (monitoring) return
        monitoring = true
        scope.launch { Wearables.registrationState.collect { s -> update { it.copy(registration = s.name) } } }
        scope.launch { Wearables.devices.collect { d -> update { it.copy(devices = d.size) } } }
    }

    fun register(activity: Activity) = Wearables.startRegistration(activity)

    val isRegistered: Boolean get() = Wearables.registrationState.value == RegistrationState.REGISTERED

    /** Opens the session and, once STARTED, the camera stream plus inputs and speech. Idempotent. */
    fun connect(withSpeech: Boolean) {
        if (session != null) return
        Wearables.createSession(AutoDeviceSelector()).fold(
            onSuccess = { s ->
                session = s
                jobs += scope.launch { s.errors.collect { e -> fail("session", e.description) } }
                jobs += scope.launch {
                    s.state.collect { st ->
                        update { it.copy(session = st.name) }
                        when (st) {
                            DeviceSessionState.STARTED -> onStarted(s, withSpeech)
                            DeviceSessionState.STOPPED -> release()
                            else -> Unit
                        }
                    }
                }
                s.start()
            },
            onFailure = { e, _ -> fail("createSession", e.description) },
        )
    }

    private fun onStarted(s: DeviceSession, withSpeech: Boolean) {
        if (camera == null) {
            s.addCamera(StreamConfiguration(videoQuality = VideoQuality.HIGH, frameRate = 2)).fold(
                onSuccess = { cam ->
                    camera = cam
                    jobs += scope.launch { cam.stream.state.collect { st -> update { it.copy(camera = st.name) } } }
                    jobs += scope.launch { cam.stream.errorStream.collect { e -> fail("stream", e.description) } }
                    // Frames are not used: the stream is kept open only so capturePhoto() is available.
                    jobs += scope.launch { cam.stream.videoStream.collect { } }
                    cam.stream.start().onFailure { e, _ -> fail("stream.start", e.description) }
                },
                onFailure = { e, _ -> fail("addCamera", e.description) },
            )
        }
        s.addInputs().fold(
            onSuccess = { inputs ->
                update { it.copy(inputs = "on") }
                jobs += scope.launch {
                    inputs.events.collect { ev ->
                        if (ev is InputEvent.Capture && ev.pressType == CapturePressType.SHORT_PRESS) onCaptureButton()
                    }
                }
                jobs += scope.launch { inputs.errors.collect { e -> if (e != null) update { it.copy(inputs = "refused: ${e.description}") } } }
            },
            onFailure = { e, _ -> update { it.copy(inputs = "unavailable: ${e.description}") } },
        )
        if (withSpeech) {
            s.addSpeech().fold(
                onSuccess = { speech ->
                    jobs += scope.launch {
                        speech.transcriptions.collect { r ->
                            if (r != null && r.isFinal && r.text.isNotBlank()) {
                                // The toolkit reports -1 when it has no confidence for a result.
                                onTranscript(r.text, if (r.confidence < 0f) UNKNOWN_CONFIDENCE else r.confidence)
                            }
                        }
                    }
                    jobs += scope.launch { speech.state.collect { st -> update { it.copy(speech = st.name) } } }
                    jobs += scope.launch { speech.errors.collect { e -> if (e != null) update { it.copy(speech = "error: ${e.description}") } } }
                    speech.start().onFailure { e, _ -> update { it.copy(speech = "refused: ${e.description}") } }
                },
                onFailure = { e, _ -> update { it.copy(speech = "unavailable: ${e.description}") } },
            )
        }
    }

    /** Takes a photo with the glasses camera (stream must be STREAMING). */
    suspend fun capturePhoto(): Bitmap? {
        val cam = camera ?: return null.also { fail("capture", "camera not ready") }
        var out: Bitmap? = null
        cam.stream.capturePhoto()
            .onSuccess { data ->
                out = when (data) {
                    is PhotoData.Bitmap -> data.bitmap
                    is PhotoData.HEIC -> {
                        val buf = data.data.duplicate()
                        val bytes = ByteArray(buf.remaining()).also { buf.get(it) }
                        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    }
                }
            }
            .onFailure { e, _ -> fail("capturePhoto", e.description) }
        return out
    }

    fun disconnect() {
        session?.stop()
        release()
    }

    private fun release() {
        jobs.forEach { it.cancel() }
        jobs.clear()
        camera = null
        session = null
        update { it.copy(camera = "off", speech = "off", inputs = "off") }
    }

    private fun fail(where: String, what: String) {
        Log.w(TAG, "$where: $what")
        update { it.copy(lastError = "$where: $what") }
    }

    private inline fun update(f: (GlassesStatus) -> GlassesStatus) {
        _status.value = f(_status.value)
    }

    companion object {
        private const val TAG = "DatGlasses"

        /**
         * Used only when the glasses report no confidence (-1): exactly the 0.80 floor, never above, so
         * such a result can be accepted but never outranks a scored one. Posting still needs the spoken
         * post + confirm pair and the server's checks (BRIEF §1.3).
         */
        const val UNKNOWN_CONFIDENCE = 0.80f
    }
}
