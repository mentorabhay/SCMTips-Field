package com.scmtips.field.core.capture.ocr

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.regex.Pattern

/** Serial token selection by the production SerialOcrParser (FR2.019). */
class SerialOcrParserTest {

    @Test
    fun tc2_121_patternTokenSelectedNonMatchingIgnored_fr2_019() {
        val lines = listOf(OcrLine("ACME Radio Systems", 0.97f), OcrLine("S/N: SN-4471-K2", 0.88f), OcrLine("230V~ 50Hz", 0.91f))
        val c = SerialOcrParser.extractSerial(lines)!!
        assertEquals("SN-4471-K2", c.normalisedSerial)
        assertEquals("confidence is the OCR line's, not a constant", 0.88f, c.confidence, 0f)
    }

    @Test
    fun fr2_019_noMatchingTokenReturnsNull() {
        assertNull(SerialOcrParser.extractSerial(listOf(OcrLine("made in finland", 0.9f), OcrLine("S/N", 0.9f))))
    }

    @Test
    fun fr2_019_digitTokenPreferredOverLabelWordThenConfidence() {
        val lines = listOf(OcrLine("SERIAL NUMBER", 0.99f), OcrLine("AB-1234-X", 0.70f), OcrLine("CD-9876-Y", 0.80f))
        assertEquals("CD-9876-Y", SerialOcrParser.extractSerial(lines)!!.normalisedSerial)
    }

    @Test
    fun fr2_019_taskLinePatternAndDigitConfusables() {
        val digits = Pattern.compile("^[0-9]{8}$")
        val c = SerialOcrParser.extractSerial(listOf(OcrLine("No. 12O45I78", 0.9f)), digits, isDigitsOnly = true)!!
        assertEquals("12045178", c.normalisedSerial)
        assertEquals("12O45I78", c.rawText)
        assertNull(SerialOcrParser.extractSerial(listOf(OcrLine("No. 12O45I78", 0.9f)), digits, isDigitsOnly = false))
    }
}
