package com.scmtips.field.core.safety

/**
 * On-Device Lone-Worker Countdown Timer and Warning Deferral Engine (Task T4.045 / FR4.043 / FR4.044 / PR4.19 / TC4.138).
 *
 * Rules:
 * - Default interval: 20 minutes (1200 s).
 * - Grace period: 5 minutes (300 s).
 * - Restarted by voice 'check in' or physical tap.
 * - Warns 2 minutes (120 s) before expiry when STATIONARY.
 * - DEFERS warning while CLIMBING or UNKNOWN. Emits warning at first stationary window; escalation time unchanged (TC4.138).
 * - Escalation fires if total elapsed time exceeds interval + grace without check-in.
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
    val isWarningActive: Boolean,
    val isEscalated: Boolean,
    val message: String? = null,
)

class LoneWorkerTimer(
    val intervalMinutes: Int = 20,
    val graceMinutes: Int = 5,
    private val warningLeadMinutes: Int = 2,
) {
    val intervalSeconds: Long = intervalMinutes * 60L
    val graceSeconds: Long = graceMinutes * 60L
    val warningLeadSeconds: Long = warningLeadMinutes * 60L

    private var lastCheckInMs: Long = 0L
    private var warningEmitted: Boolean = false

    fun start(startTimeMs: Long) {
        lastCheckInMs = startTimeMs
        warningEmitted = false
    }

    fun onCheckIn(checkInTimeMs: Long) {
        lastCheckInMs = checkInTimeMs
        warningEmitted = false
    }

    fun evaluate(currentTimeMs: Long, currentState: ClimbState): LoneWorkerStatus {
        val elapsedMs = currentTimeMs - lastCheckInMs
        val elapsedSeconds = maxOf(0L, elapsedMs / 1000L)
        val remainingSeconds = maxOf(0L, intervalSeconds - elapsedSeconds)

        val isOverdue = elapsedSeconds > intervalSeconds
        val isEscalated = elapsedSeconds > (intervalSeconds + graceSeconds)

        val warningThresholdSeconds = intervalSeconds - warningLeadSeconds

        return when {
            isEscalated -> {
                LoneWorkerStatus(
                    state = LoneWorkerWarningState.ESCALATED,
                    remainingSeconds = 0L,
                    elapsedSeconds = elapsedSeconds,
                    isWarningActive = true,
                    isEscalated = true,
                    message = "Lone worker check-in overdue! Supervisor escalation active [MSG4.10]",
                )
            }
            isOverdue -> {
                LoneWorkerStatus(
                    state = LoneWorkerWarningState.OVERDUE,
                    remainingSeconds = 0L,
                    elapsedSeconds = elapsedSeconds,
                    isWarningActive = true,
                    isEscalated = false,
                    message = "Check-in grace period active. Please check in now.",
                )
            }
            elapsedSeconds >= warningThresholdSeconds -> {
                if (currentState.isClimbingOrFailSafe) {
                    // Defer while climbing!
                    LoneWorkerStatus(
                        state = LoneWorkerWarningState.WARNING_DEFERRED_CLIMBING,
                        remainingSeconds = remainingSeconds,
                        elapsedSeconds = elapsedSeconds,
                        isWarningActive = false,
                        isEscalated = false,
                        message = "Warning deferred while climbing",
                    )
                } else {
                    // Stationary or ground: deliver warning
                    warningEmitted = true
                    LoneWorkerStatus(
                        state = LoneWorkerWarningState.WARNING_EMITTED,
                        remainingSeconds = remainingSeconds,
                        elapsedSeconds = elapsedSeconds,
                        isWarningActive = true,
                        isEscalated = false,
                        message = "Lone worker check-in due in 2 minutes. Say 'check in' or tap to confirm [MSG4.09]",
                    )
                }
            }
            else -> {
                LoneWorkerStatus(
                    state = LoneWorkerWarningState.NORMAL,
                    remainingSeconds = remainingSeconds,
                    elapsedSeconds = elapsedSeconds,
                    isWarningActive = false,
                    isEscalated = false,
                    message = null,
                )
            }
        }
    }
}
