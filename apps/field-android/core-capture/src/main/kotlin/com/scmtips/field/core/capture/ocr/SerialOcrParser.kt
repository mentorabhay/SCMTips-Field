package com.scmtips.field.core.capture.ocr

import java.util.regex.Pattern

data class SerialCandidate(
    val rawText: String,
    val normalisedSerial: String,
    val confidence: Float,
    val isPatternMatch: Boolean
)

/**
 * On-device OCR parser for nameplate serial numbers (Task T2.023 / FR2.019 / TC2.121).
 */
object SerialOcrParser {

    val DEFAULT_PATTERN = Pattern.compile("^[A-Z0-9-]{6,24}$")

    /**
     * Normalises confusable characters (O/0, I/1) if the target pattern expects digits.
     */
    fun normaliseConfusable(token: String, isDigitsOnly: Boolean): String {
        return if (isDigitsOnly) {
            token.replace('O', '0')
                .replace('o', '0')
                .replace('I', '1')
                .replace('l', '1')
        } else {
            token
        }
    }

    /**
     * Extracts serial candidate matching pattern from raw OCR text blocks.
     */
    fun extractSerial(
        rawOcrLines: List<String>,
        pattern: Pattern = DEFAULT_PATTERN,
        isDigitsOnly: Boolean = false
    ): SerialCandidate? {
        for (line in rawOcrLines) {
            val tokens = line.split("\\s+".toRegex())
            for (rawToken in tokens) {
                val clean = normaliseConfusable(rawToken.trim(), isDigitsOnly)
                if (pattern.matcher(clean).matches()) {
                    return SerialCandidate(
                        rawText = rawToken,
                        normalisedSerial = clean,
                        confidence = 0.92f,
                        isPatternMatch = true
                    )
                }
            }
        }
        return null
    }
}
