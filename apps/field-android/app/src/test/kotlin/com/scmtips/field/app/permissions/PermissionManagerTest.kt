package com.scmtips.field.app.permissions

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** PermissionManager state logic for FR2.006 (MSG2.05 on permanent denial). UI flows are not covered. */
class PermissionManagerTest {

    @Test
    fun fr2_006_requestsTheSpecPermissions() {
        assertEquals(
            setOf(
                "android.permission.CAMERA", "android.permission.RECORD_AUDIO", "android.permission.BLUETOOTH_CONNECT",
                "android.permission.BLUETOOTH_SCAN", "android.permission.POST_NOTIFICATIONS",
            ),
            FieldPermission.values().map { it.manifestName }.toSet(),
        )
    }

    @Test
    fun fr2_006_permanentDenialOfCameraOrMicShowsMsg2_05AndSurvivesRefresh() {
        val granted = mutableSetOf("android.permission.CAMERA")
        val pm = PermissionManager(checkPermissionGranted = { it in granted }, shouldShowRationale = { it == "android.permission.BLUETOOTH_CONNECT" })
        assertEquals(PermissionStatus.GRANTED, pm.permissionStates.value[FieldPermission.CAMERA])
        assertEquals(PermissionStatus.RATIONALE_REQUIRED, pm.permissionStates.value[FieldPermission.BLUETOOTH])
        assertEquals(PermissionStatus.NOT_REQUESTED, pm.permissionStates.value[FieldPermission.RECORD_AUDIO])
        assertNull(pm.blockingMessage())
        assertFalse(pm.isAllCriticalGranted())

        pm.markPermanentlyDenied(FieldPermission.RECORD_AUDIO)
        pm.refreshStatuses()
        assertEquals(PermissionStatus.PERMANENTLY_DENIED, pm.permissionStates.value[FieldPermission.RECORD_AUDIO])
        assertEquals(PermissionManager.MSG2_05, pm.blockingMessage())

        granted += "android.permission.RECORD_AUDIO" // user enabled it in Settings
        pm.refreshStatuses()
        assertNull(pm.blockingMessage())
        assertTrue(pm.isAllCriticalGranted())
    }
}
