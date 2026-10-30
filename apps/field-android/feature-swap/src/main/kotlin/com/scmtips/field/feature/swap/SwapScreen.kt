package com.scmtips.field.feature.swap

/**
 * Equipment install / replace staging (Task T4.038 / SCR4.06 / FR4.031 / FR4.032 / FR4.035).
 *
 * View-model only (no Compose UI exists yet):
 * - The capture checklist comes from the pinned asset-model BOM; staging is refused until every
 *   serialised BOM item has a captured serial, with MSG4.12 naming the first missing part (FR4.032).
 * - A replace stages a dismantle of the old serial followed by an install of the new serial at the
 *   same position, as two events with consecutive sequence numbers in one tower queue (FR4.031).
 * - Undo before post removes the staged events; undo after post produces a compensating operation
 *   linked by ref_doc_no and MSG4.19 (FR4.035). The network calls are made by the caller.
 */

data class BomItem(
    val lineNo: Int,
    val material: String,
    val description: String,
    val requiredQty: Int,
    val isMandatory: Boolean = true,
    val isSerialised: Boolean = false,
    val balloonNo: Int? = null
)

enum class SwapStageState { IDLE, STAGED, POSTED, CONFIRMED, REVERSED }

enum class EquipmentOp { DISMANTLE, INSTALL }

data class StagedEquipmentEvent(
    val op: EquipmentOp,
    val serialNo: String,
    val flCode: String,
    val queueKey: String,
    val seq: Long,
    val material: String? = null
)

data class CompensatingOperation(val op: EquipmentOp, val serialNo: String, val flCode: String, val refDocNo: String)

data class SwapUiState(
    val siteId: String,
    val locationId: String,
    val flCode: String,
    val oldSerialNo: String?,
    val newSerialNo: String? = null,
    val material: String? = null,
    val bomItems: List<BomItem> = emptyList(),
    val capturedSerials: Map<Int, String> = emptyMap(),
    val stagedEvents: List<StagedEquipmentEvent> = emptyList(),
    val state: SwapStageState = SwapStageState.IDLE,
    val postedEventId: String? = null,
    val docNumber: String? = null,
    val error: String? = null,
    val message: String? = null
) {
    val serialisedTotal: Int get() = bomItems.count { it.isSerialised }
    val serialisedCaptured: Int get() = bomItems.count { it.isSerialised && capturedSerials.containsKey(it.lineNo) }

    /** SCR4.06 progress text, e.g. "2 of 3 serialised parts captured". */
    val checklistText: String get() = "$serialisedCaptured of $serialisedTotal serialised parts captured"
}

class SwapViewModel(
    siteId: String,
    locationId: String,
    flCode: String,
    oldSerialNo: String?,
    bomItems: List<BomItem>
) {
    private var _state = SwapUiState(
        siteId = siteId,
        locationId = locationId,
        flCode = flCode,
        oldSerialNo = oldSerialNo,
        bomItems = bomItems
    )
    val state: SwapUiState get() = _state

    /** Records the captured serial of a serialised BOM line. */
    fun captureBomSerial(lineNo: Int, serial: String): Boolean {
        val item = _state.bomItems.find { it.lineNo == lineNo }
        if (item == null || !item.isSerialised || serial.isBlank()) return false
        _state = _state.copy(capturedSerials = _state.capturedSerials + (lineNo to serial.trim()))
        return true
    }

    /**
     * Stages the install (or replace, when an old serial is present) of [newSerial].
     * @param nextSeq the next free sequence number of the tower queue.
     */
    fun stageReplacement(newSerial: String, selectedMaterial: String, nextSeq: Long): Boolean {
        if (_state.state != SwapStageState.IDLE) {
            _state = _state.copy(error = "Already ${_state.state.name.lowercase()}")
            return false
        }
        if (_state.bomItems.isNotEmpty() && _state.bomItems.none { it.material == selectedMaterial }) {
            _state = _state.copy(error = "Selected material $selectedMaterial is not in pinned asset model BOM")
            return false
        }
        val missing = _state.bomItems.firstOrNull { it.isSerialised && !_state.capturedSerials.containsKey(it.lineNo) }
        if (missing != null) {
            val balloon = missing.balloonNo?.toString() ?: missing.lineNo.toString()
            _state = _state.copy(error = "Capture the serial for ${missing.description} (balloon $balloon) before posting.")
            return false
        }
        val queueKey = "EQUIP:${_state.flCode}"
        val events = buildList {
            var seq = nextSeq
            _state.oldSerialNo?.let { add(StagedEquipmentEvent(EquipmentOp.DISMANTLE, it, _state.flCode, queueKey, seq++)) }
            add(StagedEquipmentEvent(EquipmentOp.INSTALL, newSerial, _state.flCode, queueKey, seq, selectedMaterial))
        }
        _state = _state.copy(
            newSerialNo = newSerial,
            material = selectedMaterial,
            stagedEvents = events,
            state = SwapStageState.STAGED,
            error = null
        )
        return true
    }

    /** Undo before post: removes the staged events; nothing is sent. */
    fun undoBeforePost(): Boolean {
        if (_state.state != SwapStageState.STAGED) return false
        _state = _state.copy(newSerialNo = null, material = null, stagedEvents = emptyList(), state = SwapStageState.IDLE, error = null)
        return true
    }

    /** Records the server's acceptance of the staged events (POST /v1/equipment-events). */
    fun markPosted(eventId: String, docNo: String): Boolean {
        if (_state.state != SwapStageState.STAGED) return false
        _state = _state.copy(state = SwapStageState.POSTED, postedEventId = eventId, docNumber = docNo)
        return true
    }

    /** Technician confirms the mechanical installation after posting. */
    fun confirmInstallation(): Boolean {
        if (_state.state != SwapStageState.POSTED) return false
        _state = _state.copy(state = SwapStageState.CONFIRMED)
        return true
    }

    /**
     * Undo after post: returns the compensating operations to send (reverse order of the staged
     * events, each linked to the posted document by ref_doc_no) and shows MSG4.19.
     */
    fun undoAfterPost(): List<CompensatingOperation> {
        val doc = _state.docNumber
        if (_state.state !in setOf(SwapStageState.POSTED, SwapStageState.CONFIRMED) || doc == null) return emptyList()
        val ops = _state.stagedEvents.reversed().map {
            val inverse = if (it.op == EquipmentOp.INSTALL) EquipmentOp.DISMANTLE else EquipmentOp.INSTALL
            CompensatingOperation(inverse, it.serialNo, it.flCode, refDocNo = doc)
        }
        _state = _state.copy(
            state = SwapStageState.REVERSED,
            message = "Reversal queued for $doc. The original stays in SAP marked reversed."
        )
        return ops
    }
}
