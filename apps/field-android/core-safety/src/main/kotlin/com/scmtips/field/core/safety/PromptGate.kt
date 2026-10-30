package com.scmtips.field.core.safety

/**
 * Prompt gate for climb safety (T4.040 / FR4.039 / TC4.134).
 *
 * Every lens, audio and haptic prompt passes through this gate.
 * - While the state is CLIMBING or UNKNOWN nothing is released; prompts are held.
 * - Held prompts are released only after the technician has been stationary (any non-climbing
 *   state) for at least 3.0 s; then at most the 3 newest are released and older ones dropped.
 *   The release carries MSG4.25 "{n} messages held while climbing." when any prompt was held
 *   through a climb.
 * - On structure with the harness unconfirmed, task prompts are never released (PR4.04). They stay
 *   held and the result asks the caller to show the harness check instead (TC4.012).
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
    /** MSG4.25, set when the released batch had been held through a climb. */
    val message: String? = null,
    /** True when task prompts are waiting only for harness confirmation on structure. */
    val harnessCheckRequested: Boolean = false,
)

class PromptGate(
    private val stationaryHoldMs: Long = 3000L,
    private val maxRelease: Int = 3,
) {
    private val heldPrompts = mutableListOf<SafetyPrompt>()
    private var stationaryStartMs: Long? = null
    private var heldThroughClimb = 0

    /** Hold a prompt; it is only ever delivered through [evaluate]. */
    fun enqueuePrompt(prompt: SafetyPrompt, currentState: ClimbState, currentTimeMs: Long): Boolean {
        heldPrompts.add(prompt)
        if (currentState.isClimbingOrFailSafe) stationaryStartMs = null
        return true
    }

    /** Periodic tick at the sensor update rate. */
    fun evaluate(
        currentState: ClimbState,
        isHarnessConfirmed: Boolean,
        isOnStructure: Boolean,
        currentTimeMs: Long,
    ): PromptReleaseResult {
        if (currentState.isClimbingOrFailSafe) {
            stationaryStartMs = null
            heldThroughClimb = heldPrompts.size
            return EMPTY
        }
        val start = stationaryStartMs ?: currentTimeMs.also { stationaryStartMs = it }
        if (currentTimeMs - start < stationaryHoldMs || heldPrompts.isEmpty()) return EMPTY

        val blockTasks = isOnStructure && !isHarnessConfirmed
        val (waiting, eligible) = heldPrompts.partition { blockTasks && it.type == "task" }
        if (eligible.isEmpty()) {
            return PromptReleaseResult(emptyList(), 0, null, harnessCheckRequested = waiting.isNotEmpty())
        }
        val toRelease = eligible.sortedBy { it.enqueuedAtMs }.takeLast(maxRelease)
        val dropped = eligible.size - toRelease.size
        val msg = if (heldThroughClimb > 0) "$heldThroughClimb messages held while climbing." else null
        heldPrompts.clear()
        heldPrompts.addAll(waiting)
        heldThroughClimb = 0
        return PromptReleaseResult(toRelease, dropped, msg, harnessCheckRequested = waiting.isNotEmpty())
    }

    val heldCount: Int
        get() = heldPrompts.size

    fun clear() {
        heldPrompts.clear()
        stationaryStartMs = null
        heldThroughClimb = 0
    }

    private companion object {
        val EMPTY = PromptReleaseResult(emptyList(), 0, null)
    }
}
