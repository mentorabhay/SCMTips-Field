package com.scmtips.field.app.glasses

import android.app.Activity
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import com.meta.wearable.dat.camera.Camera
import com.meta.wearable.dat.camera.addCamera
import com.meta.wearable.dat.camera.types.PhotoData
import com.meta.wearable.dat.camera.types.StreamConfiguration
import com.meta.wearable.dat.camera.types.StreamState
import com.meta.wearable.dat.camera.types.VideoQuality
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.selectors.AutoDeviceSelector
import com.meta.wearable.dat.core.session.DeviceSession
import com.meta.wearable.dat.core.session.DeviceSessionState
import com.meta.wearable.dat.core.types.RegistrationState
import com.meta.wearable.dat.core.voiceinvocations.isVoiceInvocationsIntent
import com.meta.wearable.dat.core.voiceinvocations.startVoiceInvocationsStream
import com.meta.wearable.dat.core.voiceinvocations.types.actions.LaunchApp
import com.meta.wearable.dat.inputs.addInputs
import com.meta.wearable.dat.inputs.types.CapturePressType
import com.meta.wearable.dat.inputs.types.InputEvent
import com.meta.wearable.dat.speech.Speech
import com.meta.wearable.dat.speech.addSpeech
import com.scmtips.field.feature.decisions.flow.LaunchRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Ray-Ban Meta (Gen 2) through Meta's Wearables Device Access Toolkit 1.0.1.
 *
 * - Registration with the Meta AI app (Developer Mode: APPLICATION_ID 0), then one [DeviceSession].
 * - Camera (M3): a low-rate stream (HIGH = 720x1280, 2 fps) open only while [setStreaming] wants it
 *   (a work session, or a job scanning with the glasses). While [framesWanted], every uncompressed
 *   frame goes to [onFrame] (I420 bytes) for scan-by-looking on the phone. `capturePhoto()` opens the
 *   stream on demand when it is closed and closes it again afterwards.
 * - Inputs (experimental): a short press of the glasses capture button triggers [onCaptureButton].
 * - Speech (experimental): added when the session starts but started only by [setListening] (the work
 *   session); final transcriptions go to [onTranscript]. Nothing listens outside a session (A-03).
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
    private val onFrame: (i420: ByteArray, width: Int, height: Int) -> Unit = { _, _, _ -> },
) {
    private val _status = MutableStateFlow(GlassesStatus())
    val status: StateFlow<GlassesStatus> = _status.asStateFlow()
    private var session: DeviceSession? = null
    private var camera: Camera? = null
    private var cameraJobs = mutableListOf<Job>()
    private var speech: Speech? = null
    private val jobs = mutableListOf<Job>()
    private var monitoring = false
    private var streamWanted = false
    private var listenWanted = false

    /** Frames are handed to [onFrame] only while true (a work session that is not paused). */
    @Volatile var framesWanted: Boolean = false

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
                            DeviceSessionState.PAUSED -> Unit // the work session pauses on this state (WorkSession)
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
        if (streamWanted) openCamera(s)
        if (inputsAdded) {
            if (speech != null && listenWanted) startSpeech()
            return // PAUSED -> STARTED again: capabilities stay
        }
        inputsAdded = true
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
                onSuccess = { sp ->
                    speech = sp
                    update { it.copy(speech = "ready") }
                    jobs += scope.launch {
                        sp.transcriptions.collect { r ->
                            if (listenWanted && r != null && r.isFinal && r.text.isNotBlank()) {
                                // The toolkit reports -1 when it has no confidence for a result.
                                onTranscript(r.text, if (r.confidence < 0f) UNKNOWN_CONFIDENCE else r.confidence)
                            }
                        }
                    }
                    jobs += scope.launch { sp.state.collect { st -> if (speech != null) update { it.copy(speech = st.name) } } }
                    jobs += scope.launch { sp.errors.collect { e -> if (e != null) update { it.copy(speech = "error: ${e.description}") } } }
                    if (listenWanted) startSpeech()
                },
                onFailure = { e, _ -> update { it.copy(speech = "unavailable: ${e.description}") } },
            )
        }
    }

    private var inputsAdded = false

    /** The work session's microphone through the glasses' own speech capability (A-03: only in a session). */
    fun setListening(on: Boolean) {
        listenWanted = on
        val sp = speech ?: return
        if (on) startSpeech() else { sp.stop(); update { it.copy(speech = "ready") } }
    }

    private fun startSpeech() {
        speech?.start()?.onFailure { e, _ -> update { it.copy(speech = "refused: ${e.description}") } }
    }

    /** Opens (true) or closes (false) the camera stream; frames flow only while it is open. */
    fun setStreaming(on: Boolean) {
        if (streamWanted == on) return
        streamWanted = on
        val s = session ?: return
        if (on) { if (s.state.value == DeviceSessionState.STARTED) openCamera(s) } else closeCamera()
    }

    private fun openCamera(s: DeviceSession) {
        if (camera != null) return
        s.addCamera(StreamConfiguration(videoQuality = VideoQuality.HIGH, frameRate = 2)).fold(
            onSuccess = { cam ->
                camera = cam
                cameraJobs += scope.launch { cam.stream.state.collect { st -> update { it.copy(camera = st.name) } } }
                cameraJobs += scope.launch { cam.stream.errorStream.collect { e -> fail("stream", e.description) } }
                cameraJobs += scope.launch {
                    cam.stream.videoStream.collect { f ->
                        if (!framesWanted || f.isCompressed || f.isCodecConfig) return@collect
                        val b = f.buffer.duplicate()
                        val bytes = ByteArray(b.remaining()).also { b.get(it) }
                        onFrame(bytes, f.width, f.height)
                    }
                }
                cam.stream.start().onFailure { e, _ -> fail("stream.start", e.description) }
            },
            onFailure = { e, _ -> fail("addCamera", e.description) },
        )
    }

    private fun closeCamera() {
        val cam = camera ?: return
        camera = null
        cameraJobs.forEach { it.cancel() }
        cameraJobs.clear()
        runCatching { cam.stream.stop() }
        runCatching { cam.close() }
        update { it.copy(camera = "off") }
    }

    /** Takes a photo with the glasses camera; opens the stream for it when it is closed (up to 8 s). */
    suspend fun capturePhoto(): Bitmap? {
        val s = session ?: return null.also { fail("capture", "glasses not connected") }
        val opened = camera == null
        if (opened) openCamera(s)
        val cam = camera ?: return null.also { fail("capture", "camera not ready") }
        val streaming = withTimeoutOrNull(8_000) { cam.stream.state.first { it == StreamState.STREAMING } }
        if (streaming == null) {
            if (opened && !streamWanted) closeCamera()
            return null.also { fail("capture", "camera stream did not start") }
        }
        try {
            return capture(cam)
        } finally {
            if (opened && !streamWanted) closeCamera()
        }
    }

    private suspend fun capture(cam: Camera): Bitmap? {
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

    /**
     * App launches said to Meta AI on the glasses ("Hey Meta, start SCMTips Field"; M4, ported from the
     * core's wearable app). Collecting starts the toolkit's voice-invocation stream; it closes with the
     * collector. "Hey Meta" itself is Meta's: the app never hears or intercepts it. UNVERIFIED on the
     * owner's glasses; a stream the toolkit refuses ends the flow and is reported in [status].
     */
    val launches: Flow<LaunchRequest> = flow {
        val stream = Wearables.startVoiceInvocationsStream(AutoDeviceSelector())
        try {
            emitAll(
                stream.invocations.filterIsInstance<LaunchApp>().map { launch ->
                    LaunchRequest(
                        success = { msg -> launch.responseHandle.sendSuccess(msg) },
                        failure = { msg -> launch.responseHandle.sendFailure(msg) },
                    )
                },
            )
        } finally {
            stream.close()
        }
    }

    fun disconnect() {
        session?.stop()
        release()
    }

    private fun release() {
        jobs.forEach { it.cancel() }
        jobs.clear()
        cameraJobs.forEach { it.cancel() }
        cameraJobs.clear()
        camera = null
        speech = null
        inputsAdded = false
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

        /** True when the launcher intent came from a voice invocation on the glasses. */
        fun isVoiceLaunch(intent: android.content.Intent): Boolean = runCatching { isVoiceInvocationsIntent(intent) }.getOrDefault(false)

        /**
         * Used only when the glasses report no confidence (-1): exactly the 0.80 floor, never above, so
         * such a result can be accepted but never outranks a scored one. Posting still needs the spoken
         * post + confirm pair and the server's checks (BRIEF §1.3).
         */
        const val UNKNOWN_CONFIDENCE = 0.80f
    }
}
