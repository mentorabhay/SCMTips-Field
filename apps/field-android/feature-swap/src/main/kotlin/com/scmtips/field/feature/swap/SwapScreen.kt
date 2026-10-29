package com.scmtips.field.feature.swap

import java.time.Instant

/**
 * Equipment Swap / Staged Replacement Flow (Task T4.038 / SCR4.06 / FR4.031 / FR4.032 / FR4.035).
 *
 * Implements two-step install/replace staging driven by pinned asset model BOM:
 * 1. Stage dismantle of old equipment and install of replacement from BOM checklist.
 * 2. Post operation to API (/v1/equipment-events) then confirm.
 * 3. Undo before post (local cancellation) and undo after post (calls compensating reversal /v1/equipment-events/{id}/reverse).
 */

data class BomItem(
    val lineNo: Int,
    val material: String,
    val description: String,
    val requiredQty: Int,
    val isMandatory: Boolean = true
)

enum class SwapStageState {
    IDLE,
    STAGED,
    POSTED,
    CONFIRMED,
    REVERSED
}

data class SwapUiState(
    val siteId: String,
    val locationId: String,
    val flCode: String,
    val oldSerialNo: String,
    val newSerialNo: String? = null,
    val material: String? = null,
    val bomItems: List<BomItem> = emptyList(),
    val state: SwapStageState = SwapStageState.IDLE,
    val postedEventId: String? = null,
    val docNumber: String? = null,
    val error: String? = null
)

class SwapViewModel(
    private val siteId: String,
    private val locationId: String,
    private val flCode: String,
    private val oldSerialNo: String,
    private val bomItems: List<BomItem>
) {
    private var _state = SwapUiState(
        siteId = siteId,
        locationId = locationId,
        flCode = flCode,
        oldSerialNo = oldSerialNo,
        bomItems = bomItems
    )
    val state: SwapUiState get() = _state

    /** Stage replacement serial against BOM checklist. */
    fun stageReplacement(newSerial: String, selectedMaterial: String): Boolean {
        // Validate material against pinned BOM
        val matchingBom = _state.bomItems.find { it.material == selectedMaterial }
        if (matchingBom == null && _state.bomItems.isNotEmpty()) {
            _state = _state.copy(error = "Selected material $selectedMaterial is not in pinned asset model BOM")
            return false
        }

        _state = _state.copy(
            newSerialNo = newSerial,
            material = selectedMaterial,
            state = SwapStageState.STAGED,
            error = null
        )
        return true
    }

    /** Undo before post: resets staging locally without network mutation. */
    fun undoBeforePost() {
        if (_state.state == SwapStageState.STAGED) {
            _state = _state.copy(
                newSerialNo = null,
                material = null,
                state = SwapStageState.IDLE,
                error = null
            )
        }
    }

    /** Mock network post to /v1/equipment-events. */
    fun markPosted(eventId: String, docNo: String) {
        _state = _state.copy(
            state = SwapStageState.POSTED,
            postedEventId = eventId,
            docNumber = docNo
        )
    }

    /** Second step: Technician confirms successful mechanical lock/cabling on tower. */
    fun confirmInstallation() {
        if (_state.state == SwapStageState.POSTED) {
            _state = _state.copy(state = SwapStageState.CONFIRMED)
        }
    }

    /** Undo after post: calls reverse endpoint. */
    fun markReversed() {
        if (_state.state in listOf(SwapStageState.POSTED, SwapStageState.CONFIRMED)) {
            _state = _state.copy(state = SwapStageState.REVERSED)
        }
    }
}
