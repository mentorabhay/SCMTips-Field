package com.scmtips.field.feature.towerAudit

import java.util.UUID

sealed class ManualEntryResult {
    data class Success(
        val captureId: String,
        val serialNo: String,
        val equipmentClass: String,
        val photoRef: String,
        val verifyStatus: String,
        val photoAttached: Boolean,
    ) : ManualEntryResult()
    data class Blocked(val messageCode: String, val messageText: String) : ManualEntryResult()
}

data class TowerFinding(
    val id: String = UUID.randomUUID().toString(),
    val findingClass: String, // "matched", "serial_mismatch", "tower_only", "erp_only", "misplaced"
    val equipmentClass: String?,
    val serialNo: String?,
    val expectedSerial: String?,
    val reason: String?, // "not_found", "removed_by_other", "inaccessible"
    val photoRef: String?,
    val locationRef: String?,
    val status: String = "open"
)

/**
 * Manual Entry, Unknown Class Picker, and Missing Reasons Engine (Task T4.037 / FR4.021, FR4.022, FR4.023 / TC4.119, TC4.120, TC4.121).
 */
class ManualEntryManager {

    companion object {
        const val MSG4_16 = "Take a photo of the nameplate to save a typed serial."
    }

    /**
     * FR4.021 / TC4.119: Saves a manually typed serial number.
     * Requires a photo of the nameplate; otherwise blocks with MSG4.16.
     * Sets verify_status = "queued".
     */
    fun submitTypedSerial(
        typedSerial: String,
        equipmentClass: String,
        photoCropRef: String?
    ): ManualEntryResult {
        require(typedSerial.isNotBlank()) { "typed serial is blank" }
        if (photoCropRef.isNullOrBlank()) {
            return ManualEntryResult.Blocked(
                messageCode = "MSG4.16",
                messageText = MSG4_16
            )
        }

        val captureId = UUID.randomUUID().toString()
        return ManualEntryResult.Success(
            captureId = captureId,
            serialNo = typedSerial.trim().uppercase(),
            equipmentClass = equipmentClass,
            photoRef = photoCropRef,
            verifyStatus = "queued",
            photoAttached = true
        )
    }

    /**
     * FR4.022 / TC4.120: Records unknown equipment found on tower as tower_only finding.
     */
    fun recordUnknownEquipment(
        serialNo: String,
        equipmentClass: String,
        photoRef: String,
        locationRef: String
    ): TowerFinding {
        // FR4.022: class, serial, position and photo evidence are all required.
        require(serialNo.isNotBlank()) { "serial is required" }
        require(equipmentClass.isNotBlank()) { "equipment class is required" }
        require(photoRef.isNotBlank()) { "photo evidence is required" }
        require(locationRef.isNotBlank()) { "position is required" }
        return TowerFinding(
            findingClass = "tower_only",
            equipmentClass = equipmentClass,
            serialNo = serialNo,
            expectedSerial = null,
            reason = null,
            photoRef = photoRef,
            locationRef = locationRef
        )
    }

    /**
     * FR4.023 / TC4.121: Marks an expected item as missing with mandatory reason code.
     * Reason must be one of: not_found, removed_by_other, inaccessible.
     */
    fun markMissing(
        expectedSerial: String,
        equipmentClass: String,
        reason: String,
        locationRef: String
    ): TowerFinding {
        val allowedReasons = setOf("not_found", "removed_by_other", "inaccessible")
        if (reason !in allowedReasons) {
            throw IllegalArgumentException("Invalid missing reason '$reason'. Must be one of: $allowedReasons")
        }

        return TowerFinding(
            findingClass = "erp_only",
            equipmentClass = equipmentClass,
            serialNo = null,
            expectedSerial = expectedSerial,
            reason = reason,
            photoRef = null,
            locationRef = locationRef
        )
    }
}
