package com.scmtips.field.core.safety

/**
 * Prompt Gate for Hands-Free and Distraction-Free Climbing Safety (Task T4.040 / FR4.039 / PR4.04 / TC4.134).
 *
 * Rule: Emits NO lens, audio, or haptic prompt while state is CLIMBING or UNKNOWN.
 * Holds prompts until stationary for at least 3.0 seconds, then releases at most the 3 newest prompts.
 */
data class SafetyPrompt(
    val id: String,
    val type: String, // "audio", "lens", "haptic", "task"
    val text: String,
    val enqueuedAtMs: Long,
    val isSafetyCritical: Boolean = false,
)

data class PromptReleaseResult(
    val releasedPrompts: List<SafetyPrompt>,
    val droppedCount: Int,
    val message: String? = null, // MSG4.25 if older prompts were dropped
)

class PromptGate {
    private val heldPrompts = mutableListOf<SafetyPrompt>()
    private var stationaryStartMs: Long? = null

    /**
     * Submit a prompt to the gate.
     * Returns true if prompt was held, false if dropped or rejected.
     */
    fun enqueuePrompt(prompt: SafetyPrompt, currentState: ClimbState, currentTimeMs: Long): Boolean {
        // Enqueue to held buffer
        heldPrompts.add(prompt)
        return true
    }

    /**
     * Periodic tick called at sensor update rate.
     * Evaluates state and stationary duration, releasing up to 3 newest prompts after 3.0s stationary.
     */
    fun evaluate(
        currentState: ClimbState,
        isHarnessConfirmed: Boolean,
        isOnStructure: Boolean,
        currentTimeMs: Long,
    ): PromptReleaseResult {
        // 1. While CLIMBING or UNKNOWN: hold prompts, reset stationary timer
        if (currentState.isClimbingOrFailSafe) {
            stationaryStartMs = null
            return PromptReleaseResult(emptyList(), 0, null)
        }

        // 2. Track stationary start
        if (stationaryStartMs == null) {
            stationaryStartMs = currentTimeMs
            return PromptReleaseResult(emptyList(), 0, null)
        }

        val stationaryDurationMs = currentTimeMs - (stationaryStartMs ?: currentTimeMs)

        // 3. Must be stationary for at least 3.0 seconds (3000 ms) before releasing
        if (stationaryDurationMs < 3000L) {
            return PromptReleaseResult(emptyList(), 0, null)
        }

        if (heldPrompts.isEmpty()) {
            return PromptReleaseResult(emptyList(), 0, null)
        }

        // 4. On structure: task prompts require harness confirmation
        val eligiblePrompts = heldPrompts.filter { prompt ->
            if (isOnStructure && prompt.type == "task" && !isHarnessConfirmed) {
                false
            } else {
                true
            }
        }

        if (eligiblePrompts.isEmpty()) {
            return PromptReleaseResult(emptyList(), 0, null)
        }

        // 5. Release at most 3 newest eligible prompts
        val sortedEligible = eligiblePrompts.sortedBy { it.enqueuedAtMs }
        val toRelease = sortedEligible.takeLast(3)
        val droppedCount = heldPrompts.size - toRelease.size

        val msg = if (droppedCount > 0) {
            "$droppedCount earlier prompts dropped while climbing [MSG4.25]"
        } else {
            null
        }

        heldPrompts.clear()

        return PromptReleaseResult(
            releasedPrompts = toRelease,
            droppedCount = droppedCount,
            message = msg,
        )
    }

    val heldCount: Int
        get() = heldPrompts.size

    fun clear() {
        heldPrompts.clear()
        stationaryStartMs = null
    }
}
