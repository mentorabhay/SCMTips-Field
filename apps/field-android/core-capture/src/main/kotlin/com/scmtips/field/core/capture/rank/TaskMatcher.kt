package com.scmtips.field.core.capture.rank

data class TaskExpectations(
    val taskId: String,
    val expectedCodes: Set<String> = emptySet(),
    val expectedGtins: Set<String> = emptySet(),
    val expectedMaterials: Set<String> = emptySet(),
    val expectedClasses: Set<String> = emptySet(),
    val fetchedAtMs: Long = System.currentTimeMillis()
)

/**
 * Task expectations matcher (Task T2.026 / FR2.028 / TC2.126).
 * Computes:
 * - 1.0 for exact code match
 * - 0.6 for material or GTIN match
 * - 0.3 for class match
 * - 0.0 otherwise
 */
class TaskMatcher(
    private var expectations: TaskExpectations = TaskExpectations("TASK-DEFAULT")
) {
    fun updateExpectations(newExpectations: TaskExpectations) {
        expectations = newExpectations
    }

    fun computeMatchScore(
        code: String?,
        gtin: String? = null,
        material: String? = null,
        objectClass: String? = null
    ): Float {
        // 1. Exact code match: 1.0 (FR2.028)
        if (code != null && code in expectations.expectedCodes) {
            return 1.0f
        }

        // 2. Material or GTIN match: 0.6
        if ((gtin != null && gtin in expectations.expectedGtins) ||
            (material != null && material in expectations.expectedMaterials)
        ) {
            return 0.6f
        }

        // 3. Class match: 0.3
        if (objectClass != null && objectClass in expectations.expectedClasses) {
            return 0.3f
        }

        // 4. Default: 0.0
        return 0.0f
    }
}
