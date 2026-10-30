package com.scmtips.field.core.capture.codes

import java.time.LocalDate
import java.time.YearMonth

data class ParsedGs1(
    val rawCode: String,
    val sscc: String? = null,
    val gtin: String? = null,
    val batch: String? = null,
    /** AI 17 as an ISO date (yyyy-MM-dd); day 00 means the last day of the month (GS1 GenSpec 7.12). */
    val expiry: String? = null,
    val serial: String? = null,
    val isValid: Boolean = true,
    val validationError: String? = null
) {
    /** True when at least one supported GS1 AI was found. */
    val isGs1: Boolean get() = sscc != null || gtin != null || batch != null || expiry != null || serial != null
}

/**
 * GS1 Application Identifier parser and SSCC Mod-10 validator (Task T2.022 / FR2.017 / FR2.018).
 *
 * Accepts the three encodings a decoder can hand over:
 * - human-readable form with parentheses: `(01)09506000134352(17)271231(10)B-77(21)S1001`
 * - element string with FNC1 rendered as GS (U+001D) after variable-length fields, optionally
 *   prefixed by a symbology identifier (`]C1`, `]d2`, `]Q3`)
 * - a bare 18-digit SSCC
 * Supported AIs: 00 (SSCC, n18), 01 (GTIN, n14), 10 (batch, an..20), 17 (expiry, n6), 21 (serial, an..20).
 * Anything else (e.g. a plain QR payload) is returned with no AI fields and isValid = true.
 */
object Gs1BarcodeParser {

    const val MSG2_08 = "SSCC check digit invalid. Rescan barcode."
    const val ERR_BAD_EXPIRY = "GS1 AI 17 is not a valid date."
    const val ERR_BAD_LENGTH = "GS1 fixed-length field has the wrong length."

    private const val GS = '\u001D'
    private val FIXED = mapOf("00" to 18, "01" to 14, "17" to 6)
    private val VARIABLE = mapOf("10" to 20, "21" to 20)
    private val BRACKETED = Regex("""\((\d{2,4})\)([^(]*)""")

    /**
     * Standard GS1 Mod-10 check digit over the first 17 digits of an SSCC
     * (weights 3,1,3,1,... from the left, equivalently from the rightmost data digit).
     */
    fun calculateSsccMod10(ssccWithoutCheckDigit: String): Int {
        require(ssccWithoutCheckDigit.length == 17 && ssccWithoutCheckDigit.all { it in '0'..'9' }) {
            "Input must be exactly 17 digits"
        }
        var sum = 0
        for (i in 0 until 17) {
            val digit = ssccWithoutCheckDigit[i] - '0'
            sum += digit * if (i % 2 == 0) 3 else 1
        }
        val remainder = sum % 10
        return if (remainder == 0) 0 else 10 - remainder
    }

    /** Validates an 18-digit SSCC against its Mod-10 check digit (FR2.018). */
    fun validateSscc(sscc: String): Boolean {
        if (sscc.length != 18 || !sscc.all { it in '0'..'9' }) return false
        return calculateSsccMod10(sscc.take(17)) == sscc[17] - '0'
    }

    /**
     * Parses GS1 AIs from a decoded barcode payload.
     * @param currentYear used for the GS1 sliding-century rule on AI 17.
     */
    fun parse(raw: String, currentYear: Int = LocalDate.now().year): ParsedGs1 {
        var s = raw.trim()
        if (s.length >= 3 && s[0] == ']') s = s.substring(3)
        s = s.trimStart(GS)

        val fields: Map<String, String> = when {
            s.length == 18 && s.all { it in '0'..'9' } -> mapOf("00" to s)
            s.startsWith("(") -> parseBracketed(s)
            else -> parseElementString(s)
        } ?: return ParsedGs1(rawCode = raw, isValid = false, validationError = ERR_BAD_LENGTH)

        val sscc = fields["00"]
        if (sscc != null && !validateSscc(sscc)) {
            return ParsedGs1(rawCode = raw, sscc = sscc, isValid = false, validationError = MSG2_08)
        }
        val gtin = fields["01"]
        if (gtin != null && (gtin.length != 14 || !gtin.all { it in '0'..'9' })) {
            return ParsedGs1(rawCode = raw, isValid = false, validationError = ERR_BAD_LENGTH)
        }
        val expiryRaw = fields["17"]
        val expiry = expiryRaw?.let { yymmddToIso(it, currentYear) }
        if (expiryRaw != null && expiry == null) {
            return ParsedGs1(rawCode = raw, sscc = sscc, gtin = gtin, isValid = false, validationError = ERR_BAD_EXPIRY)
        }
        return ParsedGs1(
            rawCode = raw,
            sscc = sscc,
            gtin = gtin,
            batch = fields["10"],
            expiry = expiry,
            serial = fields["21"],
            isValid = true
        )
    }

    /** `(AI)value(AI)value...`; returns null when a fixed-length AI has the wrong length. */
    private fun parseBracketed(s: String): Map<String, String>? {
        val out = linkedMapOf<String, String>()
        for (m in BRACKETED.findAll(s)) {
            val ai = m.groupValues[1]
            val value = m.groupValues[2].trim(GS, ' ')
            val fixed = FIXED[ai]
            val maxVar = VARIABLE[ai]
            when {
                fixed != null -> if (value.length != fixed) return null else out[ai] = value
                maxVar != null -> out[ai] = value.take(maxVar)
            }
        }
        return out
    }

    /**
     * Element string: fixed-length AIs run straight on; variable-length AIs end at GS or the end.
     * Parsing stops at the first unsupported AI, because its length is unknown.
     * Returns null when a fixed-length field is truncated.
     */
    private fun parseElementString(s: String): Map<String, String>? {
        val out = linkedMapOf<String, String>()
        var i = 0
        while (i + 2 <= s.length) {
            val ai = s.substring(i, i + 2)
            val fixed = FIXED[ai]
            val maxVar = VARIABLE[ai]
            if (fixed != null) {
                val end = i + 2 + fixed
                if (end > s.length) return null
                out[ai] = s.substring(i + 2, end)
                i = end
                if (i < s.length && s[i] == GS) i++
            } else if (maxVar != null) {
                var end = s.indexOf(GS, i + 2)
                if (end < 0) end = s.length
                out[ai] = s.substring(i + 2, end).take(maxVar)
                i = if (end < s.length) end + 1 else end
            } else {
                break
            }
        }
        return out
    }

    /** YYMMDD to ISO date using the GS1 sliding window; DD = 00 means last day of month. */
    fun yymmddToIso(yymmdd: String, currentYear: Int): String? {
        if (yymmdd.length != 6 || !yymmdd.all { it in '0'..'9' }) return null
        val yy = yymmdd.substring(0, 2).toInt()
        val mm = yymmdd.substring(2, 4).toInt()
        val dd = yymmdd.substring(4, 6).toInt()
        if (mm !in 1..12) return null
        val currentCentury = currentYear / 100 * 100
        val diff = yy - currentYear % 100
        val year = when {
            diff in 51..99 -> currentCentury - 100 + yy
            diff in -99..-50 -> currentCentury + 100 + yy
            else -> currentCentury + yy
        }
        val ym = YearMonth.of(year, mm)
        val day = if (dd == 0) ym.lengthOfMonth() else dd
        if (day !in 1..ym.lengthOfMonth()) return null
        return ym.atDay(day).toString()
    }
}
