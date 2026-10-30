package com.scmtips.field.core.voice.numbers

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** NumberWordParser against the spoken-number rules of FR2.034. */
class NumberWordParserTest {
    private val parser = NumberWordParser()

    /** Independent oracle: the standard English form, with "and" after hundred or thousand. */
    private fun toWords(n: Int, withAnd: Boolean): String {
        val units = listOf("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
            "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
        val tens = listOf("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
        if (n < 20) return units[n]
        val parts = mutableListOf<String>()
        if (n >= 1000) parts += listOf(units[n / 1000], "thousand")
        if (n % 1000 >= 100) parts += listOf(units[(n % 1000) / 100], "hundred")
        val rest = n % 100
        if (rest > 0) {
            if (parts.isNotEmpty() && withAnd) parts += "and"
            if (rest < 20) parts += units[rest] else {
                parts += tens[rest / 10]
                if (rest % 10 > 0) parts += units[rest % 10]
            }
        }
        return parts.joinToString(" ")
    }

    @Test
    fun tc2_028_wordsWithHundredAndThousand() {
        assertEquals(1205, parser.parse("one thousand two hundred and five"))
    }

    @Test
    fun tc2_029_digitByDigit() {
        assertEquals(125, parser.parse("one two five"))
        assertEquals(9031, parser.parse("nine zero three one"))
    }

    @Test
    fun tc2_030_twelveHundredIsNotASupportedForm() {
        assertNull(parser.parse("twelve hundred"))
    }

    /** FR2.034: every n in 0..9999 round-trips as digits and as words, with and without "and". */
    @Test
    fun fr2_034_exhaustiveRoundTripDigitsAndWords() {
        for (n in 0..9999) {
            assertEquals("digits $n", n, parser.parse(n.toString()))
            val w = toWords(n, withAnd = true)
            assertEquals("words '$w'", n, parser.parse(w))
            val w2 = toWords(n, withAnd = false)
            assertEquals("words '$w2'", n, parser.parse(w2))
        }
    }

    @Test
    fun fr2_034_outOfRangeAndMalformedInputsAreNull() {
        listOf(
            "10000", "-1", "12.5", "", "   ", "ten thousand", "one hundred thousand", "twenty twenty",
            "five twenty", "and five", "one thousand and", "hundred", "thousand", "twenty zero",
            "one hundred zero", "dozen", "do", "one two three four five", "count twelve",
        ).forEach { assertNull("'$it' must not parse", parser.parse(it)) }
    }

    @Test
    fun hyphenatedTensAreAccepted() {
        assertEquals(42, parser.parse("forty-two"))
        assertEquals(9999, parser.parse("nine thousand nine hundred and ninety-nine"))
    }
}
