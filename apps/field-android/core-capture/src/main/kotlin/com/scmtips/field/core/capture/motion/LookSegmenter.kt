package com.scmtips.field.core.capture.motion

import com.scmtips.field.core.common.UUIDv7

sealed class LookState {
    object Idle : LookState()
    object Searching : LookState()
    data class LookActive(val lookId: String, val startEpochMs: Long, val speedDegPerSec: Float) : LookState()
    data class LookEnded(val lookId: String, val reason: String) : LookState()
}

/**
 * Head speed tracker and Look Segmentation engine (Task T2.021 / FR2.021 / FR2.029 / Decision D2.07).
 *
 * Invariant:
 * - Look starts after 150 ms below 8 deg/s.
 * - Look ends when head speed exceeds 25 deg/s or when a capture record is committed.
 * - Look ids are UUIDv7 (capture.look_id is uuid not null).
 */
class LookSegmenter {

    companion object {
        const val SPEED_THRESHOLD_STATIONARY = 8.0f // deg/s
        const val SPEED_THRESHOLD_BREAK = 25.0f // deg/s
        const val LOOK_START_DURATION_MS = 150L
    }

    private var currentLookId: String? = null
    private var belowThresholdSinceMs: Long? = null
    private var isLookActive = false

    fun processMotionSample(
        angularSpeedDegPerSec: Float,
        currentTimestampMs: Long = System.currentTimeMillis()
    ): LookState {
        // If speed exceeds break threshold (25 deg/s), end active look immediately
        if (angularSpeedDegPerSec > SPEED_THRESHOLD_BREAK) {
            belowThresholdSinceMs = null
            if (isLookActive && currentLookId != null) {
                val endedId = currentLookId!!
                isLookActive = false
                currentLookId = null
                return LookState.LookEnded(endedId, "MOTION_BREAK_EXCEEDED_25_DEG_S")
            }
            return LookState.Searching
        }

        // Check if head is stationary (below 8 deg/s)
        if (angularSpeedDegPerSec <= SPEED_THRESHOLD_STATIONARY) {
            if (belowThresholdSinceMs == null) {
                belowThresholdSinceMs = currentTimestampMs
            }

            val stationaryDuration = currentTimestampMs - belowThresholdSinceMs!!
            if (!isLookActive && stationaryDuration >= LOOK_START_DURATION_MS) {
                isLookActive = true
                currentLookId = UUIDv7.generate() // capture.look_id is a uuid column
                return LookState.LookActive(currentLookId!!, currentTimestampMs, angularSpeedDegPerSec)
            } else if (isLookActive && currentLookId != null) {
                return LookState.LookActive(currentLookId!!, currentTimestampMs, angularSpeedDegPerSec)
            }
        } else {
            // Speed between 8 and 25 deg/s: resets stationary look accumulator if not yet active
            if (!isLookActive) {
                belowThresholdSinceMs = null
            }
        }

        return if (isLookActive && currentLookId != null) {
            LookState.LookActive(currentLookId!!, currentTimestampMs, angularSpeedDegPerSec)
        } else {
            LookState.Searching
        }
    }

    fun completeRecordCommitted(): LookState? {
        if (isLookActive && currentLookId != null) {
            val endedId = currentLookId!!
            isLookActive = false
            currentLookId = null
            belowThresholdSinceMs = null
            return LookState.LookEnded(endedId, "RECORD_COMMITTED")
        }
        return null
    }

    fun getActiveLookId(): String? = currentLookId
    fun isLookActive(): Boolean = isLookActive
}
