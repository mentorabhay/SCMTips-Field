package com.scmtips.field.core.capture.codes

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/** GS1 parsing and SSCC validation against the production Gs1BarcodeParser (FR2.017, FR2.018). */
class Gs1BarcodeParserTest {

    @Test
    fun tc2_034_publishedSsccIsValid_fr2_018() {
        assertTrue(Gs1BarcodeParser.validateSscc("003012345678901232"))
        assertEquals(2, Gs1BarcodeParser.calculateSsccMod10("00301234567890123"))
    }

    @Test
    fun tc2_035_wrongCheckDigitRejectedWithMsg2_08_fr2_018() {
        assertFalse(Gs1BarcodeParser.validateSscc("003012345678901238"))
        val parsed = Gs1BarcodeParser.parse("(00)003012345678901238")
        assertFalse(parsed.isValid)
        assertEquals(Gs1BarcodeParser.MSG2_08, parsed.validationError)
    }

    @Test
    fun tc2_036_wrongLengthOrNonDigitRejected_fr2_018() {
        assertFalse(Gs1BarcodeParser.validateSscc("00301234567890123"))
        assertFalse(Gs1BarcodeParser.validateSscc("0030123456789012320"))
        assertFalse(Gs1BarcodeParser.validateSscc("00301234567890123A"))
        assertFalse(Gs1BarcodeParser.validateSscc(""))
    }

    /** Seeded sweep: for each 17-digit prefix exactly one of the ten check digits is accepted. */
    @Test
    fun fr2_018_exactlyOneCheckDigitAcceptedPerPrefix() {
        val random = Random(20261112)
        repeat(2000) {
            val prefix = (0 until 17).map { random.nextInt(10) }.joinToString("")
            // reference: weights 3,1,... from the left over 17 digits (GS1 GenSpec 7.9.1)
            val sum = prefix.mapIndexed { i, ch -> (ch - '0') * if (i % 2 == 0) 3 else 1 }.sum()
            val expected = (10 - sum % 10) % 10
            val accepted = (0..9).filter { Gs1BarcodeParser.validateSscc(prefix + it) }
            assertEquals("prefix $prefix", listOf(expected), accepted)
        }
    }

    @Test
    fun tc2_119_ssccFromGs1_128ElementStringAndBareCode_fr2_017() {
        val elementString = Gs1BarcodeParser.parse("]C100003012345678901232")
        assertTrue(elementString.isValid)
        assertEquals("003012345678901232", elementString.sscc)
        val bare = Gs1BarcodeParser.parse("003012345678901232")
        assertEquals("003012345678901232", bare.sscc)
        val bad = Gs1BarcodeParser.parse("00003012345678901238")
        assertFalse(bad.isValid)
        assertEquals(Gs1BarcodeParser.MSG2_08, bad.validationError)
    }

    @Test
    fun tc2_120_dataMatrixAisParsed_fr2_017() {
        val p = Gs1BarcodeParser.parse("(01)09506000134352(17)271231(10)B-77(21)S1001", currentYear = 2026)
        assertTrue(p.isValid)
        assertEquals("09506000134352", p.gtin)
        assertEquals("2027-12-31", p.expiry)
        assertEquals("B-77", p.batch)
        assertEquals("S1001", p.serial)
    }

    @Test
    fun tc2_120_elementStringWithGroupSeparator_fr2_017() {
        val gs = '\u001D'
        val p = Gs1BarcodeParser.parse("]d2010950600013435217271231" + "10B-77" + gs + "21S1001", currentYear = 2026)
        assertTrue(p.isValid)
        assertEquals("09506000134352", p.gtin)
        assertEquals("2027-12-31", p.expiry)
        assertEquals("B-77", p.batch)
        assertEquals("S1001", p.serial)
    }

    @Test
    fun fr2_017_expiryDayZeroAndCenturyWindow() {
        assertEquals("2028-02-29", Gs1BarcodeParser.yymmddToIso("280200", 2026))
        assertEquals("1980-01-15", Gs1BarcodeParser.yymmddToIso("800115", 2026)) // 54 years ahead -> past century
        assertEquals("2075-01-15", Gs1BarcodeParser.yymmddToIso("750115", 2026)) // 49 years ahead -> this century
        assertNull(Gs1BarcodeParser.yymmddToIso("271331", 2026))
        val p = Gs1BarcodeParser.parse("(17)271399")
        assertFalse(p.isValid)
        assertEquals(Gs1BarcodeParser.ERR_BAD_EXPIRY, p.validationError)
    }

    @Test
    fun fr2_017_qrPayloadWithoutAisIsNotGs1() {
        val p = Gs1BarcodeParser.parse("https://example.invalid/asset/42")
        assertTrue(p.isValid)
        assertFalse(p.isGs1)
    }

    @Test
    fun fr2_017_truncatedFixedLengthFieldIsInvalid() {
        assertFalse(Gs1BarcodeParser.parse("0109506000").isValid)
        assertFalse(Gs1BarcodeParser.parse("(01)0950600013435").isValid)
    }
}
