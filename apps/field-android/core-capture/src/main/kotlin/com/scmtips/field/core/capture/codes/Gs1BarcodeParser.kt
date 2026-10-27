package com.scmtips.field.core.capture.codes

data class ParsedGs1(
    val rawCode: String,
    val sscc: String? = null,
    val gtin: String? = null,
    val batch: String? = null,
    val expiry: String? = null,
    val serial: String? = null,
    val isValid: Boolean = true,
    val validationError: String? = null
)

/**
 * GS1 Application Identifier parser and SSCC Mod-10 validator (Task T2.022 / FR2.017 / FR2.018 / PR2.12).
 */
object Gs1BarcodeParser {

    const val MSG2_08 = "SSCC check digit invalid. Rescan barcode."

    /**
     * Calculates the standard GS1 Mod-10 check digit for an 18-digit SSCC.
     * Weights: 3, 1, 3, 1, ... on the first 17 digits.
     */
    fun calculateSsccMod10(ssccWithoutCheckDigit: String): Int {
        require(ssccWithoutCheckDigit.length == 17) { "Input must be exactly 17 digits" }
        var sum = 0
        for (i in 0 until 17) {
            val digit = ssccWithoutCheckDigit[i].digitToInt()
            val weight = if (i % 2 == 0) 3 else 1
            sum += digit * weight
        }
        val remainder = sum % 10
        return if (remainder == 0) 0 else 10 - remainder
    }

    /**
     * Validates whether an 18-digit SSCC matches its Mod-10 check digit (FR2.018).
     */
    fun validateSscc(sscc: String): Boolean {
        if (sscc.length != 18 || !sscc.all { it.isDigit() }) {
            return false
        }
        val expectedCheck = calculateSsccMod10(sscc.take(17))
        val actualCheck = sscc[17].digitToInt()
        return expectedCheck == actualCheck
    }

    /**
     * Parses GS1 AI tokens from raw barcode string (AIs 00, 01, 10, 17, 21).
     */
    fun parse(raw: String): ParsedGs1 {
        var clean = raw.trim().replace("(", "").replace(")", "")
        var sscc: String? = null
        var gtin: String? = null
        var batch: String? = null
        var expiry: String? = null
        var serial: String? = null

        // Check if raw is an 18-digit SSCC
        if (clean.length == 18 && clean.all { it.isDigit() }) {
            sscc = clean
        } else if (clean.startsWith("00") && clean.length >= 20) {
            val candidate = clean.substring(2, 20)
            if (candidate.all { it.isDigit() }) {
                sscc = candidate
                clean = clean.substring(20)
            }
        }

        if (sscc != null && !validateSscc(sscc)) {
            return ParsedGs1(
                rawCode = raw,
                sscc = sscc,
                isValid = false,
                validationError = MSG2_08
            )
        }

        // Parse AI 01 (GTIN, 14 digits)
        if (clean.startsWith("01") && clean.length >= 16) {
            gtin = clean.substring(2, 16)
            clean = clean.substring(16)
        }

        // Parse AI 17 (Expiry, 6 digits YYMMDD)
        if (clean.startsWith("17") && clean.length >= 8) {
            expiry = clean.substring(2, 8)
            clean = clean.substring(8)
        }

        // Parse AI 10 (Batch, variable length)
        if (clean.startsWith("10") && clean.length > 2) {
            batch = clean.substring(2).take(20)
        }

        // Parse AI 21 (Serial, variable length)
        if (clean.startsWith("21") && clean.length > 2) {
            serial = clean.substring(2).take(20)
        }

        return ParsedGs1(
            rawCode = raw,
            sscc = sscc,
            gtin = gtin,
            batch = batch,
            expiry = expiry,
            serial = serial,
            isValid = true
        )
    }
}
