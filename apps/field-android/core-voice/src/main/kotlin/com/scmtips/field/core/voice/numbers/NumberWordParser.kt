package com.scmtips.field.core.voice.numbers

/**
 * Spoken-number parser for counts and readings (T2.035; FR2.034).
 *
 * Accepts, for 0..9999 only:
 * - digits: "12", "1205"
 * - English number words in the standard form
 *   `[unit thousand] [unit hundred] [and] [0..19 | tens [unit]]`, e.g. "one thousand two hundred and five"
 * - digit-by-digit words of length 2..4: "one two five" -> 125
 *
 * Everything else returns null so the caller changes nothing (TC2.030: "twelve hundred" is not a
 * supported form). The lexicon is English; locale lexicons (FR2.036) are not implemented yet.
 */
class NumberWordParser {

    companion object {
        val SMALL_NUMBERS = mapOf(
            "zero" to 0, "one" to 1, "two" to 2, "three" to 3, "four" to 4,
            "five" to 5, "six" to 6, "seven" to 7, "eight" to 8, "nine" to 9,
            "ten" to 10, "eleven" to 11, "twelve" to 12, "thirteen" to 13,
            "fourteen" to 14, "fifteen" to 15, "sixteen" to 16, "seventeen" to 17,
            "eighteen" to 18, "nineteen" to 19,
        )

        val TENS = mapOf(
            "twenty" to 20, "thirty" to 30, "forty" to 40, "fifty" to 50,
            "sixty" to 60, "seventy" to 70, "eighty" to 80, "ninety" to 90,
        )

        private val DIGITS = Regex("^\\d{1,4}$")
    }

    fun parse(input: String): Int? {
        val clean = input.trim().lowercase().replace("-", " ")
        if (clean.isEmpty()) return null
        if (DIGITS.matches(clean)) return clean.toInt()

        val tokens = clean.split(Regex("\\s+"))
        if (tokens.size in 2..4 && tokens.all { (SMALL_NUMBERS[it] ?: 99) <= 9 }) {
            return tokens.joinToString("") { SMALL_NUMBERS.getValue(it).toString() }.toInt()
        }
        return parseWords(tokens)
    }

    private fun unit(token: String?): Int? = SMALL_NUMBERS[token]?.takeIf { it in 1..9 }

    private fun parseWords(tokens: List<String>): Int? {
        var i = 0
        var total = 0
        var sawScale = false

        if (tokens.size > i + 1 && tokens[i + 1] == "thousand") {
            total += (unit(tokens[i]) ?: return null) * 1000
            i += 2
            sawScale = true
        }
        if (tokens.size > i + 1 && tokens[i + 1] == "hundred") {
            total += (unit(tokens[i]) ?: return null) * 100
            i += 2
            sawScale = true
        }
        if (i < tokens.size && tokens[i] == "and") {
            if (!sawScale || i == tokens.size - 1) return null
            i += 1
        }
        if (i < tokens.size) {
            val t = tokens[i]
            val small = SMALL_NUMBERS[t]
            val tens = TENS[t]
            when {
                small != null -> {
                    if (sawScale && small == 0) return null
                    total += small
                    i += 1
                }
                tens != null -> {
                    total += tens
                    i += 1
                    unit(tokens.getOrNull(i))?.let { total += it; i += 1 }
                }
                else -> return null
            }
        }
        if (i != tokens.size || (!sawScale && tokens.isEmpty())) return null
        return total.takeIf { it in 0..9999 }
    }
}
