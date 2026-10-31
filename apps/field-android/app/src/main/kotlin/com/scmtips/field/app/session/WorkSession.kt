package com.scmtips.field.app.session

import com.scmtips.field.app.jobs.Speaker
import com.scmtips.field.core.wearables.EarconCue

/** Where the session's words come from (M3 contract §5: through the glasses during a session). */
enum class MicSource(val label: String) {
    NONE("off"),

    /** The glasses' own transcriptions (Meta toolkit speech, experimental). */
    GLASSES("glasses (Meta toolkit speech)"),

    /** Android's recogniser with the glasses as the Bluetooth hands-free (SCO) microphone. */
    BLUETOOTH("glasses over Bluetooth"),

    /** Android's recogniser on the phone microphone (no glasses headset found). */
    PHONE("phone microphone"),
}

/** Which microphone a work session uses (pure, so the choice is unit-tested). */
object MicPlan {
    private val DAT_LIVE = setOf("ready", "STARTING", "STARTED", "STOPPING", "STOPPED")

    /**
     * The glasses' own speech when the operator left it on (Me → Glasses microphone) and the toolkit
     * accepted the capability; otherwise Android's recogniser (Bluetooth hands-free first, see
     * ContinuousSpeech). A refused or failing toolkit speech moves the session to the recogniser.
     */
    fun useGlassesSpeech(glassesSpeechOn: Boolean, datSpeech: String): Boolean = glassesSpeechOn && datSpeech in DAT_LIVE
}

enum class PauseReason(val text: String) {
    GLASSES_PAUSED("glasses paused (tap or taken off)"),
    GLASSES_GONE("glasses disconnected"),
    OPERATOR("paused on the phone"),
}

/** Everything Today and the notification show about the work session. */
data class SessionView(
    val active: Boolean = false,
    val paused: PauseReason? = null,
    val speaking: Boolean = false,
    val mic: MicSource = MicSource.NONE,
    val cameraOn: Boolean = false,
    /** "command" (grammar first) or "free" (the next words go to the assistant as they are). */
    val listenMode: String = "command",
    val heard: String? = null,
    val said: String? = null,
    val card: Pair<String, String>? = null,
    /** null until the first turn; false while the assistant cannot be reached (fixed phrases only). */
    val assistantOnline: Boolean? = null,
    /** Offered when the glasses connect and no session is open. */
    val offer: Boolean = false,
) {
    /** The microphone is open only now: in a session, not paused, not while the phone itself speaks. */
    val listening: Boolean get() = active && paused == null && !speaking && mic != MicSource.NONE

    val stateText: String
        get() = when {
            !active -> "Not started"
            paused != null -> "Paused · ${paused.text}"
            speaking -> "Speaking"
            mic == MicSource.NONE -> "No microphone"
            else -> "Listening · ${mic.label}"
        }
}

sealed interface SessionChange {
    data object Started : SessionChange
    data object Stopped : SessionChange
    data class Paused(val reason: PauseReason) : SessionChange
    data object Resumed : SessionChange
}

/**
 * The work session's state (owner decision A-03: the microphone listens only while a session is open).
 * Pure: the foreground service, the recogniser and the glasses only report into it and read [view].
 *
 * Pause rules: the glasses' DAT session PAUSED (capture-button tap, glasses taken off) pauses; STARTED
 * again resumes. A DAT session that stops after the glasses took part pauses as "disconnected"; it
 * resumes when the glasses start again. A pause by the operator is lifted only by the operator.
 */
class WorkSession(private val onChange: (SessionView) -> Unit = {}) {
    var view: SessionView = SessionView()
        private set(value) {
            val changed = value != field
            field = value
            if (changed) onChange(value)
        }
    private var glassesSeen = false

    fun start(mic: MicSource, glassesStarted: Boolean): SessionChange? {
        if (view.active) return null
        glassesSeen = glassesStarted
        view = view.copy(active = true, paused = null, mic = mic, listenMode = "command", offer = false, heard = null, said = null, card = null)
        return SessionChange.Started
    }

    fun stop(): SessionChange? {
        if (!view.active) return null
        glassesSeen = false
        view = SessionView(cameraOn = view.cameraOn)
        return SessionChange.Stopped
    }

    /** A DAT DeviceSessionState name: IDLE, STARTING, STARTED, PAUSED, STOPPING, STOPPED (or "none"). */
    fun onGlasses(state: String): SessionChange? {
        if (!view.active) {
            view = view.copy(offer = state == "STARTED")
            return null
        }
        return when (state) {
            "PAUSED" -> pause(PauseReason.GLASSES_PAUSED)
            "STARTED" -> {
                glassesSeen = true
                if (view.paused == PauseReason.GLASSES_PAUSED || view.paused == PauseReason.GLASSES_GONE) resume() else null
            }
            "STOPPED", "IDLE", "none" -> if (glassesSeen && view.paused == null) pause(PauseReason.GLASSES_GONE) else null
            else -> null
        }
    }

    fun pauseByOperator(): SessionChange? = if (view.active && view.paused == null) pause(PauseReason.OPERATOR) else null

    /** The operator resumes any pause (e.g. carry on with the phone microphone after the glasses went). */
    fun resumeByOperator(): SessionChange? = if (view.active && view.paused != null) resume() else null

    fun speaking(on: Boolean) {
        view = view.copy(speaking = on)
    }

    fun mic(m: MicSource) {
        view = view.copy(mic = m)
    }

    fun camera(on: Boolean) {
        view = view.copy(cameraOn = on)
    }

    fun listenMode(mode: String) {
        if (view.active) view = view.copy(listenMode = mode)
    }

    fun heard(text: String) {
        if (view.active) view = view.copy(heard = text)
    }

    fun said(text: String, card: Pair<String, String>? = view.card) {
        if (view.active) view = view.copy(said = text, card = card)
    }

    fun assistant(online: Boolean) {
        if (view.active) view = view.copy(assistantOnline = online)
    }

    fun dismissOffer() {
        view = view.copy(offer = false)
    }

    private fun pause(r: PauseReason): SessionChange {
        view = view.copy(paused = r)
        return SessionChange.Paused(r)
    }

    private fun resume(): SessionChange {
        view = view.copy(paused = null)
        return SessionChange.Resumed
    }
}

/**
 * When to start Android's recogniser again (it hears one utterance, then stops). After a result or the
 * normal "nothing heard" errors it restarts at once; after real errors it backs off 1, 2, 4 ... 15 s; a
 * missing permission stops it ([afterError] returns null). Error numbers are SpeechRecognizer.ERROR_*.
 */
class RestartBackoff(private val quickMs: Long = 250, private val firstMs: Long = 1_000, private val maxMs: Long = 15_000) {
    private var failures = 0

    fun afterResult(): Long {
        failures = 0
        return quickMs
    }

    fun afterError(code: Int): Long? = when (code) {
        ERROR_INSUFFICIENT_PERMISSIONS -> null
        ERROR_SPEECH_TIMEOUT, ERROR_NO_MATCH -> { failures = 0; quickMs }
        ERROR_RECOGNIZER_BUSY -> firstMs
        else -> {
            val d = (firstMs shl failures.coerceAtMost(4)).coerceAtMost(maxMs)
            failures += 1
            d
        }
    }

    companion object {
        const val ERROR_SPEECH_TIMEOUT = 6
        const val ERROR_NO_MATCH = 7
        const val ERROR_RECOGNIZER_BUSY = 8
        const val ERROR_INSUFFICIENT_PERMISSIONS = 9
    }
}

/**
 * Speech out for the session. While [holding] runs (the phone carries out an assistant reply's actions)
 * everything the job runner says is queued after the assistant's words instead of cutting them off.
 */
class TurnSpeaker(private val out: Speaker) : Speaker {
    private var hold = 0

    override fun say(text: String) {
        if (text.isBlank()) return
        if (hold > 0) out.queue(text) else out.say(text)
    }

    override fun queue(text: String) {
        if (text.isNotBlank()) out.queue(text)
    }

    override fun earcon(cue: EarconCue) = out.earcon(cue)

    suspend fun <T> holding(block: suspend () -> T): T {
        hold += 1
        try {
            return block()
        } finally {
            hold -= 1
        }
    }
}
