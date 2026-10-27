package com.scmtips.field.core.voice.numbers

/**
 * Natural language number word parser for warehouse voice count entry
 * (Task T2.035 / FR2.034 / FR2.036 / PR2.10 / TC2.132).
 *
 * Supports range [0, 9999] across:
 * - Direct digits ("12", "125")
 * - English number words ("twelve", "one hundred twenty five", "one thousand two hundred and five")
 * - Digit-by-digit sequences ("one two five" -> 125)
 */
class NumberWordParser {

    companion object {
        val SMALL_NUMBERS = mapOf(
            "zero" to 0, "one" to 1, "two" to 2, "three" to 3, "four" to 4,
            "five" to 5, "six" to 6, "seven" to 7, "eight" to 8, "nine" to 9,
            "ten" to 10, "eleven" to 11, "twelve" to 12, "thirteen" to 13,
            "fourteen" to 14, "fifteen" to 15, "sixteen" to 16, "seventeen" to 17,
            "eighteen" to 18, "nineteen" to 19,
            // Hindi fallback aliases
            "ek" to 1, "do" to 2, "teen" to 3, "char" to 4, "paanch" to 5
        )

        val TENS = mapOf(
            "twenty" to 20, "thirty" to 30, "forty" to 40, "fifty" to 50,
            "sixty" to 60, "seventy" to 70, "eighty" to 80, "ninety" to 90
        )
    }

    fun parse(input: String): Int? {
        val clean = input.trim().lowercase().replace("-", " ")
        if (clean.isEmpty()) return null

        // 1. Direct digit integer
        clean.toIntOrNull()?.let {
            return if (it in 0..9999) it else null
        }

        val tokens = clean.split("\\s+".toRegex()).filter { it != "and" }
        if (tokens.isEmpty()) return null

        // 2. Try digit-by-digit ("one two five" -> 125)
        if (tokens.all { it in SMALL_NUMBERS && SMALL_NUMBERS[it]!! in 0..9 }) {
            val digitStr = tokens.map { SMALL_NUMBERS[it]!! }.joinToString("")
            val value = digitStr.toIntOrNull()
            if (value != null && value in 0..9999) {
                return value
            }
        }

        // 3. Try standard composite English number ("one thousand two hundred and five")
        var total = 0
        var current = 0

        for (token in tokens) {
            when {
                token in SMALL_NUMBERS -> {
                    current += SMALL_NUMBERS[token]!!
                }
                token in TENS -> {
                    current += TENS[token]!!
                }
                token == "hundred" -> {
                    current = (if (current == 0) 1 else current) * 100
                }
                token == "thousand" -> {
                    total += (if (current == 0) 1 else current) * 1000
                    current = 0
                }
                else -> {
                    // Unknown token in number string
                    return null
                }
            }
        }

        total += current
        return if (total in 0..9999) total else null
    }
}
