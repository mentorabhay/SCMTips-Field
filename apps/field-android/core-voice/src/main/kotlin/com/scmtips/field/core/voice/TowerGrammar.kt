package com.scmtips.field.core.voice

data class VoiceParseResult(
    val phrase: String,
    val command: String,
    val confidence: Float,
    val isAccepted: Boolean,
    val feedbackMessage: String
)

/**
 * Voice Grammar Extension for Tower Work (Task T4.048 / FR4.041, FR4.043, FR4.068 / TC4.136, TC4.138).
 * Enforces the 0.80 confidence floor for tower operations:
 * - 'harness clipped'
 * - 'check in'
 * - 'mark missing'
 * - 'route'
 */
class TowerGrammar {

    companion object {
        const val CONFIDENCE_FLOOR = 0.80f

        val TOWER_COMMAND_MAP = mapOf(
            "harness clipped" to "CMD_HARNESS_CLIPPED",
            "check in" to "CMD_CHECK_IN",
            "mark missing" to "CMD_MARK_MISSING",
            "route" to "CMD_NAV_ROUTE"
        )
    }

    /**
     * Parses spoken tower phrase and applies the 0.80 confidence floor.
     */
    fun parseTowerPhrase(spokenText: String, confidence: Float): VoiceParseResult {
        val clean = spokenText.trim().lowercase()
        val command = TOWER_COMMAND_MAP[clean]

        if (command == null) {
            return VoiceParseResult(
                phrase = spokenText,
                command = "UNKNOWN",
                confidence = confidence,
                isAccepted = false,
                feedbackMessage = "Unrecognised tower voice command."
            )
        }

        if (confidence < CONFIDENCE_FLOOR) {
            return VoiceParseResult(
                phrase = clean,
                command = command,
                confidence = confidence,
                isAccepted = false,
                feedbackMessage = "Voice confidence too low (${"%.2f".format(confidence)} < 0.80). Please repeat clearly."
            )
        }

        val feedback = when (command) {
            "CMD_HARNESS_CLIPPED" -> "Harness spoken. Now tap touchpad or button within 10s to confirm."
            "CMD_CHECK_IN" -> "Lone-worker check-in confirmed. Timer restarted."
            "CMD_MARK_MISSING" -> "Mark missing selected. State reason or tap to choose."
            "CMD_NAV_ROUTE" -> "3D route guidance active."
            else -> "Command accepted."
        }

        return VoiceParseResult(
            phrase = clean,
            command = command,
            confidence = confidence,
            isAccepted = true,
            feedbackMessage = feedback
        )
    }
}
