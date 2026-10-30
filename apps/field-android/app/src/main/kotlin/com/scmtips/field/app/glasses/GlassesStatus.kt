package com.scmtips.field.app.glasses

/**
 * What the app knows about the glasses (filled from Meta DAT 1.0.1 state flows by [DatGlasses]).
 * The values are the DAT enum names (RegistrationState, DeviceSessionState, StreamState), kept as
 * strings so this class and [GlassesHelp] stay pure Kotlin and JVM-tested.
 */
data class GlassesStatus(
    val registration: String = "not initialised",
    val devices: Int = 0,
    val session: String = "none",
    val camera: String = "off",
    val speech: String = "off",
    val inputs: String = "off",
    val lastError: String? = null,
) {
    val ready: Boolean get() = session == "STARTED" && camera == "STREAMING"
}

/** Plain-English glasses status for the Me tab, with the one thing to do next. */
data class GlassesAdvice(val text: String, val button: String?, val action: Action, val ready: Boolean) {
    enum class Action { NONE, REGISTER, CONNECT }
}

object GlassesHelp {
    fun advise(s: GlassesStatus, toolkitError: String?): GlassesAdvice {
        val err = s.lastError.orEmpty()
        return when {
            toolkitError != null -> GlassesAdvice(
                "The glasses toolkit did not start ($toolkitError). Use the phone camera.", null, GlassesAdvice.Action.NONE, false)
            s.ready -> GlassesAdvice(
                "Ready · speaks prompts, no display" + speechNote(s), null, GlassesAdvice.Action.NONE, true)
            s.registration == "REGISTERING" -> GlassesAdvice(
                "Finish in the Meta AI app: approve SCMTips Field, then come back.", "Set up", GlassesAdvice.Action.REGISTER, false)
            s.registration != "REGISTERED" -> GlassesAdvice(
                "Not linked yet. Tap Set up: the Meta AI app opens. Approve SCMTips Field there.", "Set up", GlassesAdvice.Action.REGISTER, false)
            err.contains("eligible", ignoreCase = true) || err.contains("NO_ELIGIBLE_DEVICE") || s.devices == 0 -> GlassesAdvice(
                "Linked, but not awake: take them out of the case, put them on, wait for the chime.", "Connect", GlassesAdvice.Action.CONNECT, false)
            err.contains("thermal", ignoreCase = true) -> GlassesAdvice(
                "The glasses are too warm. Take them off for a few minutes, then tap Connect.", "Connect", GlassesAdvice.Action.CONNECT, false)
            err.contains("battery", ignoreCase = true) -> GlassesAdvice(
                "The glasses battery is too low. Charge them in the case.", "Connect", GlassesAdvice.Action.CONNECT, false)
            err.contains("update", ignoreCase = true) -> GlassesAdvice(
                "The glasses need an update. Open the Meta AI app and update them.", "Connect", GlassesAdvice.Action.CONNECT, false)
            err.contains("disconnected", ignoreCase = true) -> GlassesAdvice(
                "The glasses disconnected. Check Bluetooth, then tap Connect.", "Connect", GlassesAdvice.Action.CONNECT, false)
            s.session == "STARTED" -> GlassesAdvice(
                "Connected · camera is starting. Allow camera access in Meta AI if it asks.", "Connect", GlassesAdvice.Action.CONNECT, false)
            s.session == "STARTING" -> GlassesAdvice("Connecting…", null, GlassesAdvice.Action.NONE, false)
            else -> GlassesAdvice(
                "Linked. Put them on and tap Connect.", "Connect", GlassesAdvice.Action.CONNECT, false)
        }
    }

    private fun speechNote(s: GlassesStatus): String = when {
        s.speech == "STARTED" || s.speech == "LISTENING" -> " · listening"
        s.speech.startsWith("unavailable") || s.speech.startsWith("refused") -> " · use Hold to talk on the phone"
        else -> ""
    }
}
