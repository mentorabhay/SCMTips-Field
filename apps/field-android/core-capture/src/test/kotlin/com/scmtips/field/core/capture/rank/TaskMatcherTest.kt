package com.scmtips.field.core.capture.rank

import org.junit.Assert.assertEquals
import org.junit.Test

/** Task match values by the production TaskMatcher (FR2.028). */
class TaskMatcherTest {

    private val m = TaskMatcher(
        TaskExpectations(
            taskId = "T-SAMPLE-17",
            expectedCodes = setOf("003012345678901232"),
            expectedGtins = setOf("09506000134352"),
            expectedMaterials = setOf("MAT-100"),
            expectedClasses = setOf("carton"),
            fetchedAtMs = 0L
        )
    )

    @Test
    fun tc2_126_exactGtinClassNone_fr2_028() {
        assertEquals(1.0f, m.computeMatchScore("003012345678901232", objectClass = "carton"), 0f)
        assertEquals(0.6f, m.computeMatchScore("999", gtin = "09506000134352"), 0f)
        assertEquals(0.3f, m.computeMatchScore("999", objectClass = "carton"), 0f)
        assertEquals(0.0f, m.computeMatchScore("999", gtin = "1", material = "x", objectClass = "gauge"), 0f)
    }

    @Test
    fun fr2_028_materialMatchIs0_6AndExpectationsCanChange() {
        assertEquals(0.6f, m.computeMatchScore(null, material = "MAT-100"), 0f)
        m.updateExpectations(TaskExpectations("T-2", expectedCodes = setOf("X"), fetchedAtMs = 0L))
        assertEquals(0.0f, m.computeMatchScore("003012345678901232"), 0f)
        assertEquals(1.0f, m.computeMatchScore("X"), 0f)
    }
}
