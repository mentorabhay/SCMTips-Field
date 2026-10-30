package com.scmtips.field.core.ocr

/** One recognised text line with the OCR engine's confidence in [0, 1] (ML Kit on Android). */
data class OcrTextLine(val text: String, val confidence: Float)

data class NameplateOcrResult(
    val rawText: String,
    val serialNo: String,
    val equipmentClass: String,
    /** OCR confidence of the line the serial came from (FR4.017). */
    val confidence: Float,
    /** Readability of the crop, computed by the capture pipeline (FR4.017). */
    val readability: Float,
    val isNormalised: Boolean,
    val substitutions: List<Substitution>,
    val matchesPattern: Boolean,
    val cropRef: String,
    val positionLatitude: Double? = null,
    val positionLongitude: Double? = null,
    val positionAltitude: Double? = null
) {
    /** capture.code_type for nameplate serials (FR4.017). */
    val codeType: String get() = "serial_text"
}

/**
 * On-device nameplate OCR reader (Task T4.032 / FR4.016, FR4.017).
 *
 * Takes the recognised lines of a ranked nameplate crop, normalises confusable characters per the
 * equipment-class serial pattern (SerialPatterns) and proposes the best serial:
 * pattern matches first, then the fewest substitutions, then the higher OCR confidence, then the
 * earlier token. When no token matches the pattern, the highest-confidence token of 5+ characters is
 * proposed with matchesPattern = false so verification routing can treat it as a pattern failure.
 * Confidence and readability are passed through from the OCR engine and the capture pipeline; this
 * class does not invent either.
 */
class NameplateReader {

    fun readNameplate(
        lines: List<OcrTextLine>,
        equipmentClass: String,
        readability: Float,
        cropRef: String,
        lat: Double? = null,
        lon: Double? = null,
        alt: Double? = null
    ): NameplateOcrResult? {
        var best: NameplateOcrResult? = null
        for (line in lines) {
            for (rawToken in line.text.split(Regex("\\s+|,|;|:"))) {
                val token = rawToken.trim()
                if (token.length < 5) continue
                val norm = SerialPatterns.normaliseSerial(token, equipmentClass)
                val candidate = NameplateOcrResult(
                    rawText = token,
                    serialNo = norm.normalisedSerial,
                    equipmentClass = norm.equipmentClass,
                    confidence = line.confidence.coerceIn(0f, 1f),
                    readability = readability.coerceIn(0f, 1f),
                    isNormalised = norm.isNormalised,
                    substitutions = norm.substitutions,
                    matchesPattern = norm.matchesPattern,
                    cropRef = cropRef,
                    positionLatitude = lat,
                    positionLongitude = lon,
                    positionAltitude = alt
                )
                if (best == null || better(candidate, best)) best = candidate
            }
        }
        return best
    }

    /**
     * Transitional overload for callers that do not yet pass engine confidence, readability and the
     * crop ref (feature-tower-audit). Both scores are reported as 0 (not measured), which routes the
     * capture to verification instead of claiming a confidence nobody measured; cropRef is empty.
     */
    @Deprecated("Pass OcrTextLine with the OCR engine confidence, the crop readability and the crop ref")
    fun readNameplate(candidateLines: List<String>, equipmentClass: String = "UNKNOWN"): NameplateOcrResult? =
        readNameplate(candidateLines.map { OcrTextLine(it, 0f) }, equipmentClass, readability = 0f, cropRef = "")

    private fun better(a: NameplateOcrResult, b: NameplateOcrResult): Boolean {
        if (a.matchesPattern != b.matchesPattern) return a.matchesPattern
        if (a.substitutions.size != b.substitutions.size) return a.substitutions.size < b.substitutions.size
        return a.confidence > b.confidence
    }
}
