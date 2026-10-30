package com.scmtips.field.core.voice

import com.scmtips.field.core.voice.grammar.ParsedUtterance
import com.scmtips.field.core.voice.grammar.VoiceIntent

data class StagedPostingRequest(
    val taskId: String,
    val captureId: String?,
    val lineId: String?,
    val quantity: Double,
    val unit: String = "each",
    val isDamaged: Boolean = false,
    val isReversal: Boolean = false,
    val stagedAtEpochMs: Long = System.currentTimeMillis(),
)

sealed class ConfirmGateState {
    object Idle : ConfirmGateState()
    data class Staged(val request: StagedPostingRequest, val prompt: String) : ConfirmGateState()
    data class Sent(val request: StagedPostingRequest) : ConfirmGateState()
    data class Cancelled(val reason: String, val message: String? = null) : ConfirmGateState()
}

/**
 * Mandatory confirmation gate and correction commands (T2.036; FR2.033, FR2.037; BR2.10, BR2.18).
 *
 * - `post` stages a request and reads it back (MSG2.11); only an accepted `confirm` within 10 s sends it.
 * - `cancel`, the 10 s timeout (MSG2.22) or any other accepted intent clears the stage.
 * - Utterances that were not accepted (below the 0.80 floor or out of grammar) change nothing (FR2.032).
 * - `undo` before posting removes the staged line; `undo` after posting stages a reversal request.
 *   ERP documents are never deleted.
 * - `wrong one` supersedes the last capture; `mark damaged` / `condition good` set its condition.
 */
class ConfirmGate(
    private val confirmTimeoutMs: Long = 10_000L,
    private val onPostingDispatched: (StagedPostingRequest) -> Unit = {},
) {
    companion object {
        const val MSG2_22 = "Post cancelled: no confirm within 10 seconds. Say post again when ready."

        /** MSG2.11 readback, e.g. "Post count 12 for line 3? Say confirm or cancel." */
        fun readback(quantity: Double, lineLabel: String?): String {
            val q = if (quantity % 1.0 == 0.0) quantity.toLong().toString() else quantity.toString()
            val forLine = if (lineLabel.isNullOrBlank()) "" else " for line $lineLabel"
            return "Post count $q$forLine? Say confirm or cancel."
        }
    }

    private var currentState: ConfirmGateState = ConfirmGateState.Idle
    private var stagedCountLine: Double? = null
    private var activeDamagedCondition: Boolean = false
    private var lastCommittedPosting: StagedPostingRequest? = null
    private var lastCaptureId: String? = null
    private var isLastCaptureActive: Boolean = true

    fun getState(): ConfirmGateState = currentState
    fun getStagedCount(): Double? = stagedCountLine
    fun isDamaged(): Boolean = activeDamagedCondition
    fun isLastCaptureActive(): Boolean = isLastCaptureActive
    fun lastCaptureId(): String? = lastCaptureId

    /** A new capture was committed: it becomes the target of wrong one / mark damaged. */
    fun onCaptureCommitted(captureId: String) {
        lastCaptureId = captureId
        isLastCaptureActive = true
        activeDamagedCondition = false
    }

    /** Records a spoken count or reading before posting. */
    fun recordCount(quantity: Double) {
        stagedCountLine = quantity
    }

    /**
     * Spoken `post`: stages the counted line and returns the readback prompt.
     * With nothing counted there is nothing to post and nothing is staged.
     */
    fun handlePostCommand(
        taskId: String,
        captureId: String? = lastCaptureId,
        currentEpochMs: Long = System.currentTimeMillis(),
        lineId: String? = null,
        lineLabel: String? = null,
    ): ConfirmGateState {
        val qty = stagedCountLine
        if (qty == null) {
            currentState = ConfirmGateState.Cancelled("NOTHING_STAGED")
            return currentState
        }
        val request = StagedPostingRequest(
            taskId = taskId,
            captureId = captureId,
            lineId = lineId,
            quantity = qty,
            isDamaged = activeDamagedCondition,
            stagedAtEpochMs = currentEpochMs,
        )
        currentState = ConfirmGateState.Staged(request, readback(qty, lineLabel))
        return currentState
    }

    /** Clears a stage whose 10 s window has passed. Call on a timer as well as on every utterance. */
    fun tick(currentEpochMs: Long): ConfirmGateState {
        val staged = currentState as? ConfirmGateState.Staged ?: return currentState
        if (currentEpochMs - staged.request.stagedAtEpochMs > confirmTimeoutMs) {
            currentState = ConfirmGateState.Cancelled("CONFIRM_TIMEOUT_EXPIRED", MSG2_22)
        }
        return currentState
    }

    /**
     * Entry point for recognised speech. Not-accepted utterances are inert (FR2.032); an accepted
     * `count n` records the count (and, like any other intent, clears a pending stage).
     */
    fun handleUtterance(
        utterance: ParsedUtterance,
        taskId: String,
        currentEpochMs: Long = System.currentTimeMillis(),
    ): ConfirmGateState {
        if (!utterance.isAccepted) return tick(currentEpochMs)
        return when (utterance.intent) {
            VoiceIntent.POST -> {
                tick(currentEpochMs)
                handlePostCommand(taskId, currentEpochMs = currentEpochMs)
            }
            VoiceIntent.COUNT, VoiceIntent.READING -> {
                handleIntent(utterance.intent, currentEpochMs)
                utterance.quantityOrValue?.let { recordCount(it) }
                currentState
            }
            else -> handleIntent(utterance.intent, currentEpochMs)
        }
    }

    /** Handles an accepted intent. UNKNOWN is never accepted and therefore changes nothing. */
    fun handleIntent(
        intent: VoiceIntent,
        currentEpochMs: Long = System.currentTimeMillis(),
    ): ConfirmGateState {
        if (intent == VoiceIntent.UNKNOWN) return tick(currentEpochMs)
        val staged = tick(currentEpochMs) as? ConfirmGateState.Staged

        if (staged != null) {
            when (intent) {
                VoiceIntent.CONFIRM -> {
                    val committed = staged.request
                    currentState = ConfirmGateState.Sent(committed)
                    // A sent reversal closes the undo chain; it is never reversed again by undo.
                    lastCommittedPosting = if (committed.isReversal) null else committed
                    stagedCountLine = null
                    onPostingDispatched(committed)
                    return currentState
                }
                VoiceIntent.CANCEL -> {
                    currentState = ConfirmGateState.Cancelled("USER_CANCELLED")
                    return currentState
                }
                else -> currentState = ConfirmGateState.Cancelled("SUPERSEDED_BY_ANOTHER_INTENT")
            }
        }

        when (intent) {
            VoiceIntent.UNDO -> {
                val committed = lastCommittedPosting
                if (stagedCountLine != null) {
                    stagedCountLine = null
                    currentState = ConfirmGateState.Cancelled("UNDO_BEFORE_POST")
                } else if (committed != null && staged == null) {
                    val reversal = committed.copy(isReversal = true, stagedAtEpochMs = currentEpochMs)
                    currentState = ConfirmGateState.Staged(
                        reversal,
                        "Reverse posted count ${readback(committed.quantity, null).removePrefix("Post count ")}",
                    )
                }
            }
            VoiceIntent.WRONG_ONE -> {
                isLastCaptureActive = false
                stagedCountLine = null
                currentState = ConfirmGateState.Cancelled("WRONG_ONE_SUPERSEDED")
            }
            VoiceIntent.MARK_DAMAGED -> activeDamagedCondition = true
            VoiceIntent.CONDITION_GOOD -> activeDamagedCondition = false
            else -> {}
        }
        return currentState
    }
}
