package com.scmtips.field.core.ocr

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Confusable-character normalisation per equipment-class pattern (FR4.016, T4.033). */
class SerialPatternsTest {

    @Test
    fun fr4_016_cleanSerialIsNotNormalised() {
        val r = SerialPatterns.normaliseSerial("21A7K0093", "RRU")
        assertTrue(r.matchesPattern)
        assertFalse(r.isNormalised)
        assertEquals(emptyList<Substitution>(), r.substitutions)
    }

    @Test
    fun fr4_016_singleConfusableReplacedAndReported() {
        val r = SerialPatterns.normaliseSerial("2IA7K0093", "RRU")
        assertEquals("21A7K0093", r.normalisedSerial)
        assertEquals(listOf(Substitution(1, 'I', '1')), r.substitutions)
    }

    @Test
    fun fr4_016_twoConfusablesNeedTwoSubstitutions() {
        val r = SerialPatterns.normaliseSerial("2IA7K0O93", "rru")
        assertTrue(r.matchesPattern)
        assertEquals("21A7K0093", r.normalisedSerial)
        assertEquals(listOf(Substitution(1, 'I', '1'), Substitution(6, 'O', '0')), r.substitutions)
    }

    @Test
    fun fr4_016_digitToLetterAndUnknownClassFallsBackToDefaultPattern() {
        assertEquals("BBU-A1B2", SerialPatterns.normaliseSerial("88U-A1B2", "BBU").normalisedSerial)
        assertEquals(SerialPatterns.DEFAULT_PATTERN, SerialPatterns.getPattern("SOMETHING-NEW"))
        val none = SerialPatterns.normaliseSerial("X", "RRU")
        assertFalse(none.matchesPattern)
        assertEquals("X", none.normalisedSerial)
    }
}
