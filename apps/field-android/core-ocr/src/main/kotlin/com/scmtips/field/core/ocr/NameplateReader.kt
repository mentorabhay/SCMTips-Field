package com.scmtips.field.core.ocr

import java.util.UUID

data class NameplateOcrResult(
    val rawText: String,
    val serialNo: String,
    val equipmentClass: String,
    val confidence: Float,
    val readability: Float,
    val isNormalised: Boolean,
    val substitutions: List<Substitution>,
    val matchesPattern: Boolean,
    val cropRef: String,
    val positionLatitude: Double? = null,
    val positionLongitude: Double? = null,
    val positionAltitude: Double? = null
)

/**
 * On-device nameplate OCR reader (Task T4.032 / FR4.016, FR4.017 / TC4.114).
 * Processes ranked crop tokens, applies confusable normalisation, scores against
 * class serial patterns, and returns candidate serial with evidence metadata.
 */
class NameplateReader {

    /**
     * Reads text candidate lines from a nameplate crop and returns the best serial match.
     */
    fun readNameplate(
        candidateLines: List<String>,
        equipmentClass: String = "UNKNOWN",
        cropRef: String = "crops/${UUID.randomUUID()}.jpg",
        lat: Double? = null,
        lon: Double? = null,
        alt: Double? = null
    ): NameplateOcrResult? {
        if (candidateLines.isEmpty()) {
            return null
        }

        var bestMatch: NameplateOcrResult? = null
        var highestScore = -1.0f

        for (line in candidateLines) {
            val tokens = line.split("\\s+|,|;|:".toRegex())
            for (rawToken in tokens) {
                val token = rawToken.trim()
                if (token.length < 5) continue

                val norm = SerialPatterns.normaliseSerial(token, equipmentClass)
                var score = 0.5f

                if (norm.matchesPattern) {
                    score += 0.45f
                }
                if (!norm.isNormalised) {
                    score += 0.05f
                }

                if (score > highestScore) {
                    highestScore = score
                    bestMatch = NameplateOcrResult(
                        rawText = token,
                        serialNo = norm.normalisedSerial,
                        equipmentClass = equipmentClass,
                        confidence = score.coerceIn(0.0f, 1.0f),
                        readability = 0.94f,
                        isNormalised = norm.isNormalised,
                        substitutions = norm.substitutions,
                        matchesPattern = norm.matchesPattern,
                        cropRef = cropRef,
                        positionLatitude = lat,
                        positionLongitude = lon,
                        positionAltitude = alt
                    )
                }
            }
        }

        return bestMatch
    }
}
