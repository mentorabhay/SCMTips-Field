package com.scmtips.field.core.ocr

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Nameplate serial proposal and evidence fields (FR4.016, FR4.017). TC4.114 accuracy needs the SAMPLE crop set and is not run here. */
class NameplateReaderTest {

    private val reader = NameplateReader()

    @Test
    fun fr4_016_patternMatchPreferredOverHigherConfidenceNoise() {
        val lines = listOf(OcrTextLine("ERICSSON RADIO 4415", 0.99f), OcrTextLine("S/N: 2IA7K0093", 0.81f))
        val r = reader.readNameplate(lines, "RRU", readability = 0.88f, cropRef = "crops/abc.jpg")!!
        assertEquals("21A7K0093", r.serialNo)
        assertTrue(r.matchesPattern)
        assertTrue(r.isNormalised)
    }

    @Test
    fun fr4_016_fewerSubstitutionsWinThenConfidence() {
        val lines = listOf(OcrTextLine("2IA7K0O93", 0.95f), OcrTextLine("31A7K0093", 0.60f), OcrTextLine("41A7K0093", 0.70f))
        assertEquals("41A7K0093", reader.readNameplate(lines, "RRU", 0.9f, "c")!!.serialNo)
    }

    @Test
    fun fr4_017_confidenceReadabilityCropRefAndPositionArePassedThrough() {
        val r = reader.readNameplate(listOf(OcrTextLine("BBU-77A1", 0.73f)), "BBU", readability = 0.66f,
            cropRef = "crops/0193.jpg", lat = 60.17, lon = 24.94, alt = 31.5)!!
        assertEquals(0.73f, r.confidence, 0f)
        assertEquals(0.66f, r.readability, 0f)
        assertEquals("crops/0193.jpg", r.cropRef)
        assertEquals("serial_text", r.codeType)
        assertEquals(60.17, r.positionLatitude!!, 0.0)
        assertEquals(31.5, r.positionAltitude!!, 0.0)
    }

    @Test
    fun fr4_016_noPatternMatchIsProposedAsFailedPatternOrNullWhenEmpty() {
        val r = reader.readNameplate(listOf(OcrTextLine("HELLO WORLDS", 0.9f)), "BBU", 0.9f, "c")!!
        assertFalse(r.matchesPattern)
        assertNull(reader.readNameplate(emptyList(), "BBU", 0.9f, "c"))
        assertNull(reader.readNameplate(listOf(OcrTextLine("ab cd", 0.9f)), "BBU", 0.9f, "c"))
    }
}
