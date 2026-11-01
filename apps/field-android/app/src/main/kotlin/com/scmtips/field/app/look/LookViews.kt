package com.scmtips.field.app.look

import com.scmtips.field.feature.decisions.flow.DecisionCard

/** Today's Claims card and the claims review screen (supervisors; hidden when the server says 403). */
data class ClaimsView(
    /** Null: not asked yet or not a supervisor (no card). */
    val waiting: Int? = null,
    val reviewing: Boolean = false,
    val state: String = "",
    val card: DecisionCard? = null,
    val listening: Boolean = false,
    val last: String? = null,
)

object ClaimsText {
    fun chip(n: Int?): String = when (n) {
        null -> "Claims: checking…"
        0 -> "No claims waiting"
        1 -> "1 draft claim waiting"
        else -> "$n draft claims waiting"
    }

    fun state(s: ClaimFlowState): String = when (s) {
        ClaimFlowState.Idle -> ""
        ClaimFlowState.Fetching -> "Getting the draft claims…"
        is ClaimFlowState.Presenting -> "Reading claim ${s.index + 1} of ${s.total}"
        ClaimFlowState.Listening -> "Listening · say approve, reject, next claim, or stop"
        is ClaimFlowState.Sending -> "Sending “${s.what}”"
        is ClaimFlowState.AwaitingConfirm -> "Say confirm within 10 seconds, or cancel"
        is ClaimFlowState.Finished -> when (s.outcome) {
            ClaimOutcome.DONE -> "Done · ${s.decided} decided"
            ClaimOutcome.NOTHING_WAITING -> "No claims waiting"
            ClaimOutcome.NOT_ALLOWED -> "Your role does not decide claims"
            ClaimOutcome.STOPPED -> "Stopped · ${s.decided} decided"
            ClaimOutcome.ABANDONED -> "Stopped · nothing heard"
        }
        is ClaimFlowState.Failed -> "Claims: ${s.text}"
    }
}

/**
 * Me → "Test glasses camera" (the owner's Gate 0 probe G0-5): one photo through the Meta toolkit, its
 * size as the toolkit delivered it and the delay from asking to having it. Nothing leaves the phone
 * unless the operator taps Upload.
 */
data class CameraProbe(
    val busy: Boolean = false,
    val width: Int? = null,
    val height: Int? = null,
    val delayMs: Long? = null,
    val preview: LookPhoto? = null,
    val message: String? = null,
    val uploadedCaptureId: String? = null,
    val needsConsent: Boolean = false,
) {
    val summary: String?
        get() = if (width == null || height == null || delayMs == null) null
        else "$width × $height px from the glasses in ${"%.1f".format(java.util.Locale.ROOT, delayMs / 1000.0)} s"
}
