package com.scmtips.field.app.session

import com.scmtips.field.app.auth.SessionController
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class ThermalStatus {
    NONE,
    LIGHT,
    MODERATE,
    SEVERE,
    CRITICAL,
    EMERGENCY,
    SHUTDOWN
}

enum class DetectionMode {
    CONTINUOUS,
    ON_DEMAND_ONLY,
    DISABLED
}

data class PowerGovernorState(
    val batteryPct: Int = 100,
    val thermalStatus: ThermalStatus = ThermalStatus.NONE,
    val targetFps: Int = 15,
    val detectionMode: DetectionMode = DetectionMode.CONTINUOUS,
    val isSessionTerminated: Boolean = false,
    val activeNotice: String? = null
)

data class TelemetryEvent(
    val eventType: String,
    val timestampMs: Long,
    val batteryPct: Int,
    val thermalStatus: ThermalStatus,
    val targetFps: Int,
    val detectionMode: DetectionMode,
    val note: String? = null
)

/**
 * Power and Thermal Governor applying Rule BR2.16 (Task T2.009 / FR2.007 / TC2.107 / TC2.108).
 */
class PowerGovernor(
    private val sessionController: SessionController? = null,
    private val telemetrySink: (TelemetryEvent) -> Unit = {}
) {
    companion object {
        const val MSG2_14 = "Phone is hot. Detection now runs only when you say capture or tap."
        const val MSG2_15 = "Battery low. Session ended. Saved captures will send when you reconnect and charge."
    }

    private val _state = MutableStateFlow(PowerGovernorState())
    val state: StateFlow<PowerGovernorState> = _state.asStateFlow()

    /**
     * Updates governor with current thermal status and battery percentage (0..100).
     * Applies ladder according to BR2.16.
     */
    fun evaluate(thermal: ThermalStatus, batteryPct: Int): PowerGovernorState {
        var targetFps = 15
        var detectionMode = DetectionMode.CONTINUOUS
        var terminateSession = false
        var notice: String? = null

        // Ladder Level 1: Thermal MODERATE or Battery < 20% -> 8 fps
        if (thermal == ThermalStatus.MODERATE || batteryPct < 20) {
            targetFps = 8
        }

        // Ladder Level 2: Thermal SEVERE -> detection only on capture command or tap
        if (thermal == ThermalStatus.SEVERE) {
            targetFps = 8
            detectionMode = DetectionMode.ON_DEMAND_ONLY
            notice = MSG2_14
        }

        // Ladder Level 3: Thermal CRITICAL, EMERGENCY, SHUTDOWN or Battery < 10% -> end session
        if (thermal >= ThermalStatus.CRITICAL || batteryPct < 10) {
            targetFps = 0
            detectionMode = DetectionMode.DISABLED
            terminateSession = true
            notice = if (batteryPct < 10) MSG2_15 else "Critical device temperature. Session ended safely."
        }

        val newState = PowerGovernorState(
            batteryPct = batteryPct,
            thermalStatus = thermal,
            targetFps = targetFps,
            detectionMode = detectionMode,
            isSessionTerminated = terminateSession,
            activeNotice = notice
        )
        _state.value = newState

        // Emit telemetry event for every state change
        val event = TelemetryEvent(
            eventType = "field.session.thermal_battery_step",
            timestampMs = System.currentTimeMillis(),
            batteryPct = batteryPct,
            thermalStatus = thermal,
            targetFps = targetFps,
            detectionMode = detectionMode,
            note = notice
        )
        telemetrySink(event)

        if (terminateSession) {
            sessionController?.stopSession(notice ?: "PowerGovernor: critical power/thermal state")
        }

        return newState
    }
}
