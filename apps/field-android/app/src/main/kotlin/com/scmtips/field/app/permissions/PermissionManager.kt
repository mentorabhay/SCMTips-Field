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
    BLUETOOTH_SCAN(
        "android.permission.BLUETOOTH_SCAN",
        "Find Glasses",
        "Required to find your glasses nearby when pairing."
    ),
    NOTIFICATIONS(
        "android.permission.POST_NOTIFICATIONS",
        "Session Notifications",
        "Required to maintain background capture sessions and display active outbox queue depth."
    )
}

enum class PermissionStatus {
    NOT_REQUESTED,
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
        /** MSG2.05 */
        const val MSG2_05 = "Camera and microphone access is off, so capture cannot start. Open Settings, then Permissions, to turn it on."
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
                _permissionStates.value[perm] == PermissionStatus.PERMANENTLY_DENIED -> PermissionStatus.PERMANENTLY_DENIED
                shouldShowRationale(perm.manifestName) -> PermissionStatus.RATIONALE_REQUIRED
                else -> PermissionStatus.NOT_REQUESTED
            }
        }
        _permissionStates.value = updated
    }

    fun markPermanentlyDenied(perm: FieldPermission) {
        val current = _permissionStates.value.toMutableMap()
        current[perm] = PermissionStatus.PERMANENTLY_DENIED
        _permissionStates.value = current
    }

    /** MSG2.05 when a capture-critical permission is permanently denied, else null. */
    fun blockingMessage(): String? {
        val states = _permissionStates.value
        val critical = listOf(FieldPermission.CAMERA, FieldPermission.RECORD_AUDIO)
        return if (critical.any { states[it] == PermissionStatus.PERMANENTLY_DENIED }) MSG2_05 else null
    }

    fun isAllCriticalGranted(): Boolean {
        val states = _permissionStates.value
        return states[FieldPermission.CAMERA] == PermissionStatus.GRANTED &&
                states[FieldPermission.RECORD_AUDIO] == PermissionStatus.GRANTED
    }
}
