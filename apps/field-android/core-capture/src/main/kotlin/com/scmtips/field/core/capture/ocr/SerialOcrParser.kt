package com.scmtips.field.core.capture.ocr

import java.util.regex.Pattern

/** One line of recognised text with the recogniser's own confidence in [0, 1]. */
data class OcrLine(val text: String, val confidence: Float)

data class SerialCandidate(
    val rawText: String,
    val normalisedSerial: String,
    /** The OCR engine's confidence for the line the token came from. */
    val confidence: Float,
    val isPatternMatch: Boolean
)

/**
 * On-device OCR parser for nameplate and tag serial numbers (Task T2.023 / FR2.019 / TC2.121).
 *
 * Only tokens that match the task_line serial pattern (default `^[A-Z0-9-]{6,24}$`) are accepted.
 * When several tokens match, a token containing a digit is preferred over a letters-only word
 * (nameplate labels such as SERIAL or MODEL also match the default pattern), then the higher
 * OCR confidence, then the earlier position.
 */
object SerialOcrParser {

    val DEFAULT_PATTERN: Pattern = Pattern.compile("^[A-Z0-9-]{6,24}$")

    /** Normalises confusable characters (O/0, I/1, l/1) when the target pattern expects digits. */
    fun normaliseConfusable(token: String, isDigitsOnly: Boolean): String =
        if (isDigitsOnly) {
            token.replace('O', '0').replace('o', '0').replace('I', '1').replace('l', '1')
        } else {
            token
        }

    fun extractSerial(
        lines: List<OcrLine>,
        pattern: Pattern = DEFAULT_PATTERN,
        isDigitsOnly: Boolean = false
    ): SerialCandidate? {
        var best: SerialCandidate? = null
        var bestHasDigit = false
        for (line in lines) {
            for (rawToken in line.text.split(Regex("\\s+"))) {
                val token = rawToken.trim().trim(',', ';', ':', '.', '(', ')', '[', ']')
                if (token.isEmpty()) continue
                val clean = normaliseConfusable(token, isDigitsOnly)
                if (!pattern.matcher(clean).matches()) continue
                val hasDigit = clean.any { it.isDigit() }
                val better = best == null ||
                    (hasDigit && !bestHasDigit) ||
                    (hasDigit == bestHasDigit && line.confidence > best.confidence)
                if (better) {
                    best = SerialCandidate(token, clean, line.confidence.coerceIn(0f, 1f), isPatternMatch = true)
                    bestHasDigit = hasDigit
                }
            }
        }
        return best
    }
}
