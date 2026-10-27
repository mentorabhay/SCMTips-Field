package com.scmtips.field.app.permissions

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class FieldPermission(val manifestName: String, val rationaleTitle: String, val rationaleDescription: String) {
    CAMERA(
        "android.permission.CAMERA",
        "Camera Access",
        "Required to scan bin barcodes, materials, and equipment labels when glasses are not connected."
    ),
    RECORD_AUDIO(
        "android.permission.RECORD_AUDIO",
        "Microphone Access",
        "Required for push-to-talk voice count entries and spoken confirmation turns."
    ),
    BLUETOOTH(
        "android.permission.BLUETOOTH_CONNECT",
        "Glasses Connectivity",
        "Required to pair and stream HUD preview to Meta Ray-Ban glasses."
    ),
    NOTIFICATIONS(
        "android.permission.POST_NOTIFICATIONS",
        "Session Notifications",
        "Required to maintain background capture sessions and display active outbox queue depth."
    )
}

enum class PermissionStatus {
    GRANTED,
    RATIONALE_REQUIRED,
    PERMANENTLY_DENIED
}

/**
 * Manages just-in-time permission flows, rationale modals, and reduced mode fallbacks (Task T2.008 / FR2.006 / TC2.106).
 */
class PermissionManager(
    private val checkPermissionGranted: (String) -> Boolean = { false },
    private val shouldShowRationale: (String) -> Boolean = { false }
) {
    companion object {
        const val MSG2_05 = "Permission permanently denied. Open App Settings to enable full glasses and voice features, or continue in reduced manual mode."
    }

    private val _permissionStates = MutableStateFlow<Map<FieldPermission, PermissionStatus>>(emptyMap())
    val permissionStates: StateFlow<Map<FieldPermission, PermissionStatus>> = _permissionStates.asStateFlow()

    init {
        refreshStatuses()
    }

    fun refreshStatuses() {
        val updated = FieldPermission.values().associateWith { perm ->
            when {
                checkPermissionGranted(perm.manifestName) -> PermissionStatus.GRANTED
                shouldShowRationale(perm.manifestName) -> PermissionStatus.RATIONALE_REQUIRED
                else -> PermissionStatus.RATIONALE_REQUIRED
            }
        }
        _permissionStates.value = updated
    }

    fun markPermanentlyDenied(perm: FieldPermission) {
        val current = _permissionStates.value.toMutableMap()
        current[perm] = PermissionStatus.PERMANENTLY_DENIED
        _permissionStates.value = current
    }

    fun canRunReducedMode(): Boolean {
        // App can run in reduced manual mode even if Camera or Mic is missing
        return true
    }

    fun isAllCriticalGranted(): Boolean {
        val states = _permissionStates.value
        return states[FieldPermission.CAMERA] == PermissionStatus.GRANTED &&
                states[FieldPermission.RECORD_AUDIO] == PermissionStatus.GRANTED
    }
}
