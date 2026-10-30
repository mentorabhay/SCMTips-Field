package com.scmtips.field.feature.towerAudit

import com.scmtips.field.core.ocr.NameplateOcrResult
import com.scmtips.field.core.ocr.NameplateReader
import java.util.UUID

data class AuditTaskLineItem(
    val lineNo: Int,
    val serialNo: String,
    val equipmentClass: String,
    val sectorCode: String,
    val levelHeightM: Double,
    var status: String = "pending", // pending, captured, missing, mismatch
    var captureId: String? = null
)

data class TowerAuditUiState(
    val taskId: String,
    val siteCode: String,
    val activeSector: String,
    val activeLevelHeight: Double,
    val taskLines: List<AuditTaskLineItem>,
    val deviceToken: String,
    val isOnline: Boolean = true
)

/**
 * Tower Audit Feature Controller and Navigation (Task T4.030 / FR4.014, FR4.017).
 * Connects sector/level navigation with Phase 2 capture pipeline, device tokens,
 * and nameplate OCR extraction.
 */
class TowerAuditController(
    private val evidenceManager: EvidenceManager,
    private val ocrReader: NameplateReader = NameplateReader(),
) {

    /**
     * Filters expected items for the currently selected sector and level.
     */
    fun getSectorItems(state: TowerAuditUiState, sector: String): List<AuditTaskLineItem> {
        return state.taskLines.filter { it.sectorCode.equals(sector, ignoreCase = true) }
    }

    /**
     * Processes a captured nameplate frame from the capture pipeline: OCR, evidence (only with
     * consent, blurred when a face is in frame), and matching against the expected task lines.
     * Returns null when OCR finds no serial candidate.
     */
    fun processCapture(
        state: TowerAuditUiState,
        candidateOcrLines: List<String>,
        equipmentClass: String,
        cropBytes: ByteArray,
        faceDetected: Boolean = false,
    ): TowerCaptureResult? {
        val ocrResult = ocrReader.readNameplate(
            candidateLines = candidateOcrLines,
            equipmentClass = equipmentClass,
        ) ?: return null

        val captureId = UUID.randomUUID().toString()
        val evidence = if (evidenceManager.hasConsent()) {
            evidenceManager.processEvidenceCrop(captureId, cropBytes, faceDetected)
        } else {
            null
        }

        val matchedLine = state.taskLines.firstOrNull { it.serialNo.equals(ocrResult.serialNo, ignoreCase = true) }
        if (matchedLine != null) {
            matchedLine.status = "captured"
            matchedLine.captureId = captureId
        }
        return TowerCaptureResult(captureId, ocrResult, evidence, matchedLine)
    }
}

data class TowerCaptureResult(
    val captureId: String,
    val ocr: NameplateOcrResult,
    /** Null when no consent is recorded: nothing is prepared for upload (FR4.020). */
    val evidence: EvidenceResult?,
    val matchedLine: AuditTaskLineItem?,
)
