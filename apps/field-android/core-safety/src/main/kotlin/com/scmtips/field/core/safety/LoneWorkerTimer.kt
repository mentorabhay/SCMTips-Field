package com.scmtips.field.core.safety

/**
 * On-device lone-worker timer (T4.045 / FR4.043 / FR4.044 / TC4.138).
 *
 * - Interval default 20 min, tenant range 10..60 min; grace 5 min.
 * - Restarted by voice "check in" or a tap ([onCheckIn]).
 * - Warning window starts 2 min before expiry. The warning (MSG4.09) is emitted once, at the first
 *   evaluation in the window when the technician is not climbing; while CLIMBING or UNKNOWN it is
 *   deferred. Nothing is shown to the technician while climbing, overdue or escalated included.
 * - Escalation is due at last check-in + interval + grace, whatever happened in between
 *   ("escalation time unchanged" by deferral). Escalation itself is sent server-side (FR4.044);
 *   [LoneWorkerStatus.isEscalated] tells the caller it is due.
 */
enum class LoneWorkerWarningState {
    NORMAL,
    WARNING_DUE,
    WARNING_DEFERRED_CLIMBING,
    WARNING_EMITTED,
    OVERDUE,
    ESCALATED,
}

data class LoneWorkerStatus(
    val state: LoneWorkerWarningState,
    val remainingSeconds: Long,
    val elapsedSeconds: Long,
    /** True when something should be shown/spoken to the technician now. */
    val isWarningActive: Boolean,
    val isEscalated: Boolean,
    val message: String? = null,
    val escalatesAtMs: Long = 0L,
)

class LoneWorkerTimer(
    val intervalMinutes: Int = 20,
    val graceMinutes: Int = 5,
    private val warningLeadMinutes: Int = 2,
) {
    init {
        require(intervalMinutes in 10..60) { "lone-worker interval must be 10..60 min, got $intervalMinutes" }
        require(graceMinutes >= 0) { "grace must be >= 0" }
    }

    val intervalSeconds: Long = intervalMinutes * 60L
    val graceSeconds: Long = graceMinutes * 60L
    val warningLeadSeconds: Long = warningLeadMinutes * 60L

    var lastCheckInMs: Long = 0L
        private set
    private var warningEmitted: Boolean = false

    val nextDueMs: Long
        get() = lastCheckInMs + intervalSeconds * 1000L

    val escalatesAtMs: Long
        get() = lastCheckInMs + (intervalSeconds + graceSeconds) * 1000L

    fun start(startTimeMs: Long) = onCheckIn(startTimeMs)

    fun onCheckIn(checkInTimeMs: Long) {
        lastCheckInMs = checkInTimeMs
        warningEmitted = false
    }

    fun evaluate(currentTimeMs: Long, currentState: ClimbState): LoneWorkerStatus {
        val elapsedMs = maxOf(0L, currentTimeMs - lastCheckInMs)
        val elapsedSeconds = elapsedMs / 1000L
        val remainingSeconds = maxOf(0L, intervalSeconds - elapsedSeconds)
        val climbing = currentState.isClimbingOrFailSafe

        fun status(state: LoneWorkerWarningState, active: Boolean, escalated: Boolean, msg: String?) =
            LoneWorkerStatus(state, remainingSeconds, elapsedSeconds, active, escalated, msg, escalatesAtMs)

        return when {
            currentTimeMs >= escalatesAtMs ->
                status(LoneWorkerWarningState.ESCALATED, !climbing, true, if (climbing) null else MSG_ESCALATED)
            currentTimeMs >= nextDueMs ->
                status(LoneWorkerWarningState.OVERDUE, !climbing, false, if (climbing) null else MSG_OVERDUE)
            currentTimeMs >= nextDueMs - warningLeadSeconds * 1000L -> when {
                climbing -> status(LoneWorkerWarningState.WARNING_DEFERRED_CLIMBING, false, false, null)
                !warningEmitted -> {
                    warningEmitted = true
                    status(LoneWorkerWarningState.WARNING_EMITTED, true, false, MSG_CHECK_IN_DUE)
                }
                else -> status(LoneWorkerWarningState.WARNING_DUE, false, false, null)
            }
            else -> status(LoneWorkerWarningState.NORMAL, false, false, null)
        }
    }

    companion object {
        /** MSG4.09 */
        const val MSG_CHECK_IN_DUE = "Check in due in 2 min. Say check in."
        const val MSG_OVERDUE = "Check in now. Say check in."
        const val MSG_ESCALATED = "Your supervisor has been alerted. Say check in."
    }
}
