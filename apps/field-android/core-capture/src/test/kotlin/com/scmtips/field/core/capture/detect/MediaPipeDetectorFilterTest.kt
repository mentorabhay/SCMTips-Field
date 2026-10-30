package com.scmtips.field.core.capture.detect

import com.scmtips.field.core.wearables.PreviewFrame
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Post-filter of MediaPipeDetector only: allowed classes, score >= 0.50, best first, at most 10.
 * The model itself is not provided (UNVERIFIED), so detection quality (TC2.118) is not tested here.
 */
class MediaPipeDetectorFilterTest {

    private fun d(id: String, cls: String, score: Float) = DetectedObject(id, cls, score, BoundingBox(0f, 0f, 1f, 1f))

    @Test
    fun postFilterKeepsAllowedClassesAtOrAboveHalfBestFirstMaxTen() {
        val raw = listOf(d("a", "carton", 0.49f), d("b", "label", 0.50f), d("c", "person", 0.99f), d("e", "gauge", 0.9f)) +
            (0 until 12).map { d("t$it", "tag", 0.6f + it * 0.01f) }
        val detector = MediaPipeDetector(engine = { raw })
        val out = detector.detect(PreviewFrame(data = ByteArray(0)))
        assertEquals(10, out.size)
        assertEquals("e", out.first().id)
        assertEquals(out.sortedByDescending { it.confidence }, out)
        assert(out.none { it.category == "person" || it.id == "a" })
        assertEquals(listOf("b"), detector.filterAndSort(listOf(d("a", "carton", 0.49f), d("b", "label", 0.50f))).map { it.id })
    }
}
