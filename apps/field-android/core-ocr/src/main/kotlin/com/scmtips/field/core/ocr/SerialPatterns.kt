package com.scmtips.field.core.ocr

import java.util.regex.Pattern

data class Substitution(
    val position: Int,
    val original: Char,
    val replacement: Char
)

data class NormalisationResult(
    val originalSerial: String,
    val normalisedSerial: String,
    val isNormalised: Boolean,
    val substitutions: List<Substitution>,
    val matchesPattern: Boolean,
    val equipmentClass: String,
    val pattern: String
)

/**
 * Shared serial pattern normalisation rules (Task T4.033 / FR4.016 / PR4.18).
 * Normalises confusable pairs: O/0, I/1, S/5, B/8, Z/2 per class regex, using the fewest
 * substitutions (up to MAX_SUBSTITUTIONS) that make the token match, and reports each one.
 */
object SerialPatterns {

    val LETTER_TO_DIGIT = mapOf(
        'O' to '0',
        'I' to '1',
        'S' to '5',
        'B' to '8',
        'Z' to '2'
    )

    val DIGIT_TO_LETTER = mapOf(
        '0' to 'O',
        '1' to 'I',
        '5' to 'S',
        '8' to 'B',
        '2' to 'Z'
    )

    val EQUIPMENT_PATTERNS = mapOf(
        "RRU" to "^([0-9]{2}[A-Z][0-9][A-Z][0-9]{4}|RRU-[A-Z0-9-]{4,16})$",
        "BBU" to "^BBU-[A-Z0-9-]{4,16}$",
        "TMA" to "^TMA-[A-Z0-9-]{4,16}$",
        "ANT_PANEL" to "^ANT-[A-Z0-9-]{4,16}$",
        "RECTIFIER" to "^REC-[A-Z0-9-]{4,16}$",
        "MICROWAVE" to "^MW-[A-Z0-9-]{4,16}$",
        "ROUTER" to "^RTR-[A-Z0-9-]{4,16}$",
        "CABINET" to "^CAB-[A-Z0-9-]{4,16}$",
        "UNKNOWN" to "^[A-Z0-9-]{6,24}$"
    )

    const val DEFAULT_PATTERN = "^[A-Z0-9-]{6,24}$"

    /** Upper bound on simultaneous confusable substitutions tried for one token. */
    const val MAX_SUBSTITUTIONS = 4

    private fun combinations(items: List<Int>, k: Int): Sequence<List<Int>> = sequence {
        val idx = IntArray(k) { it }
        while (true) {
            yield(idx.map { items[it] })
            var i = k - 1
            while (i >= 0 && idx[i] == items.size - k + i) i--
            if (i < 0) break
            idx[i]++
            for (j in i + 1 until k) idx[j] = idx[j - 1] + 1
        }
    }

    fun getPattern(equipmentClass: String?): String {
        return EQUIPMENT_PATTERNS[equipmentClass?.uppercase()] ?: DEFAULT_PATTERN
    }

    fun normaliseSerial(
        rawSerial: String,
        equipmentClass: String? = null,
        expectedPattern: String? = null
    ): NormalisationResult {
        val clean = rawSerial.trim().uppercase()
        val eqClass = equipmentClass?.uppercase() ?: "UNKNOWN"
        val patternStr = expectedPattern ?: getPattern(eqClass)
        val regex = Pattern.compile(patternStr)

        if (regex.matcher(clean).matches()) {
            return NormalisationResult(
                originalSerial = rawSerial,
                normalisedSerial = clean,
                isNormalised = false,
                substitutions = emptyList(),
                matchesPattern = true,
                equipmentClass = eqClass,
                pattern = patternStr
            )
        }

        // Try the fewest substitutions first (1, then 2, ...), leftmost positions first.
        val confusable = clean.indices.filter { LETTER_TO_DIGIT.containsKey(clean[it]) || DIGIT_TO_LETTER.containsKey(clean[it]) }
        for (k in 1..minOf(confusable.size, MAX_SUBSTITUTIONS)) {
            for (combo in combinations(confusable, k)) {
                val chars = clean.toCharArray()
                val subs = combo.map { i ->
                    val rep = LETTER_TO_DIGIT[clean[i]] ?: DIGIT_TO_LETTER.getValue(clean[i])
                    chars[i] = rep
                    Substitution(i, clean[i], rep)
                }
                val candidate = String(chars)
                if (regex.matcher(candidate).matches()) {
                    return NormalisationResult(
                        originalSerial = rawSerial,
                        normalisedSerial = candidate,
                        isNormalised = true,
                        substitutions = subs,
                        matchesPattern = true,
                        equipmentClass = eqClass,
                        pattern = patternStr
                    )
                }
            }
        }

        return NormalisationResult(
            originalSerial = rawSerial,
            normalisedSerial = clean,
            isNormalised = false,
            substitutions = emptyList(),
            matchesPattern = false,
            equipmentClass = eqClass,
            pattern = patternStr
        )
    }
}
