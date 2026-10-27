package com.scmtips.field.core.voice

import com.scmtips.field.core.voice.grammar.VoiceIntent

data class StagedPostingRequest(
    val taskId: String,
    val captureId: String?,
    val lineId: String?,
    val quantity: Double,
    val unit: String = "each",
    val isDamaged: Boolean = false,
    val isReversal: Boolean = false,
    val stagedAtEpochMs: Long = System.currentTimeMillis()
)

sealed class ConfirmGateState {
    object Idle : ConfirmGateState()
    data class Staged(val request: StagedPostingRequest, val prompt: String) : ConfirmGateState()
    data class Sent(val request: StagedPostingRequest) : ConfirmGateState()
    data class Cancelled(val reason: String) : ConfirmGateState()
}

/**
 * Mandatory Confirmation Gate and Correction Engine
 * (Task T2.036 / FR2.033 / FR2.037 / PR2.11 / TC2.130 / TC2.133 / TC2.134).
 *
 * Invariant:
 * Zero postings occur without affirmative "confirm" within 10 seconds.
 * ERP documents are NEVER deleted; undo after posting raises reversal requests.
 */
class ConfirmGate(
    private val confirmTimeoutMs: Long = 10_000L,
    private val onPostingDispatched: (StagedPostingRequest) -> Unit = {}
) {
    private var currentState: ConfirmGateState = ConfirmGateState.Idle
    private var stagedCountLine: Double? = null
    private var activeDamagedCondition: Boolean = false
    private var lastCommittedPosting: StagedPostingRequest? = null
    private var isLastCaptureActive: Boolean = true

    fun getState(): ConfirmGateState = currentState

    fun getStagedCount(): Double? = stagedCountLine
    fun isDamaged(): Boolean = activeDamagedCondition
    fun isLastCaptureActive(): Boolean = isLastCaptureActive

    /**
     * Records a spoken count or reading before posting.
     */
    fun recordCount(quantity: Double) {
        stagedCountLine = quantity
    }

    /**
     * Spoken "post" command: stages request and enters confirmation gate.
     */
    fun handlePostCommand(taskId: String, captureId: String? = null, currentEpochMs: Long = System.currentTimeMillis()): ConfirmGateState {
        val qty = stagedCountLine ?: 1.0
        val request = StagedPostingRequest(
            taskId = taskId,
            captureId = captureId,
            lineId = "line-01",
            quantity = qty,
            isDamaged = activeDamagedCondition,
            stagedAtEpochMs = currentEpochMs
        )
        val prompt = "Posting count ${qty.toInt()}. Say confirm."
        currentState = ConfirmGateState.Staged(request, prompt)
        return currentState
    }

    /**
     * Handles user speech intent within the confirmation gate.
     */
    fun handleIntent(
        intent: VoiceIntent,
        currentEpochMs: Long = System.currentTimeMillis()
    ): ConfirmGateState {
        val staged = currentState as? ConfirmGateState.Staged

        if (staged != null) {
            val elapsed = currentEpochMs - staged.request.stagedAtEpochMs
            if (elapsed > confirmTimeoutMs) {
                // Timeout expired (> 10s) -> automatically cleared and cancelled (FR2.033)
                currentState = ConfirmGateState.Cancelled("CONFIRM_TIMEOUT_EXPIRED")
                return currentState
            }

            when (intent) {
                VoiceIntent.CONFIRM -> {
                    // Confirmed within 10s: dispatch posting request
                    val committed = staged.request
                    currentState = ConfirmGateState.Sent(committed)
                    lastCommittedPosting = committed
                    stagedCountLine = null
                    onPostingDispatched(committed)
                    return currentState
                }
                VoiceIntent.CANCEL -> {
                    currentState = ConfirmGateState.Cancelled("USER_CANCELLED")
                    return currentState
                }
                else -> {
                    // Any other intent clears the staged post (FR2.033)
                    currentState = ConfirmGateState.Cancelled("SUPERSEDED_BY_ANOTHER_INTENT")
                }
            }
        }

        // Handle correction commands outside active staging (FR2.037)
        when (intent) {
            VoiceIntent.UNDO -> {
                if (stagedCountLine != null) {
                    // Undo before posting: removes staged line
                    stagedCountLine = null
                    currentState = ConfirmGateState.Cancelled("UNDO_BEFORE_POST")
                } else if (lastCommittedPosting != null) {
                    // Undo after posting: raises a reversal post request (never deletes ERP doc)
                    val original = lastCommittedPosting!!
                    val reversal = original.copy(
                        isReversal = true,
                        stagedAtEpochMs = currentEpochMs
                    )
                    currentState = ConfirmGateState.Staged(reversal, "Reversing posted document. Say confirm.")
                }
            }
            VoiceIntent.WRONG_ONE -> {
                // Supersedes and invalidates the last capture
                isLastCaptureActive = false
                stagedCountLine = null
                currentState = ConfirmGateState.Cancelled("WRONG_ONE_SUPERSEDED")
            }
            VoiceIntent.MARK_DAMAGED -> {
                activeDamagedCondition = true
            }
            VoiceIntent.CONDITION_GOOD -> {
                activeDamagedCondition = false
            }
            else -> {}
        }

        return currentState
    }
}
