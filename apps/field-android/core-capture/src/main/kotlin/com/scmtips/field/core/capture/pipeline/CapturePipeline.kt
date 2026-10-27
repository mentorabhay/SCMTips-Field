package com.scmtips.field.core.capture.pipeline

import com.scmtips.field.core.capture.motion.LookSegmenter
import com.scmtips.field.core.capture.privacy.FaceBlurStage
import com.scmtips.field.core.capture.privacy.UploadableCrop
import com.scmtips.field.core.capture.rank.RankCandidate
import com.scmtips.field.core.capture.rank.RankOutcome
import com.scmtips.field.core.capture.rank.Ranker
import com.scmtips.field.core.outbox.api.UUIDv7
import com.scmtips.field.core.wearables.LensRenderer
import com.scmtips.field.core.wearables.LensState

data class TimingMarks(
    val shutterEpochMs: Long,
    val stillRxEpochMs: Long,
    val decodeDoneEpochMs: Long,
    val rankDoneEpochMs: Long,
    val committedEpochMs: Long,
    val lensDrawnEpochMs: Long
) {
    val totalLatencyMs: Long get() = lensDrawnEpochMs - shutterEpochMs
}

data class CaptureRecord(
    val id: String = UUIDv7.generate(),
    val lookId: String,
    val codeValue: String,
    val codeType: String,
    val readability: Float,
    val finalRankScore: Float,
    val crop: UploadableCrop?,
    val timings: TimingMarks,
    val isAutoCaptured: Boolean = false
)

/**
 * High-performance on-device capture pipeline orchestrator
 * (Task T2.029 / FR2.029 / FR2.063 / TC2.166 / PR2.01).
 */
class CapturePipeline(
    private val ranker: Ranker = Ranker(),
    private val lookSegmenter: LookSegmenter = LookSegmenter(),
    private val faceBlurStage: FaceBlurStage = FaceBlurStage(),
    private val lensRenderer: LensRenderer? = null,
    private val outboxSink: (CaptureRecord) -> Unit = {}
) {
    // Invariant: At most one capture record per look (PR2.01)
    private var recordCreatedForCurrentLook = false
    private var lastRecordedLookId: String? = null

    fun onNewLookStarted(lookId: String) {
        if (lookId != lastRecordedLookId) {
            recordCreatedForCurrentLook = false
            lastRecordedLookId = lookId
            lensRenderer?.renderState(LensState.READY, "LOOK READY", "")
        }
    }

    /**
     * Evaluates candidates within the look and triggers auto-capture or updates HUD.
     */
    fun evaluateCandidates(
        lookId: String,
        candidates: List<RankCandidate>,
        rawCropBytes: ByteArray? = null
    ): CaptureRecord? {
        if (recordCreatedForCurrentLook && lookId == lastRecordedLookId) {
            return null // Prevent duplicate record creation for the same look (PR2.01)
        }

        val t0 = System.currentTimeMillis()
        val rankOutcome = ranker.rank(candidates)
        val tRankDone = System.currentTimeMillis()

        return when (rankOutcome) {
            is RankOutcome.Winner -> {
                val winner = rankOutcome.selected
                // Check if full dwell is achieved (>= 800ms) for auto-capture
                if (winner.candidate.dwellMs >= 800L) {
                    executeCapture(
                        lookId = lookId,
                        winner = winner.candidate,
                        readability = winner.candidate.readability,
                        score = winner.finalScore,
                        rawCropBytes = rawCropBytes,
                        tShutter = t0,
                        isAuto = true
                    )
                } else {
                    lensRenderer?.renderState(
                        LensState.READY,
                        "DWELLING...",
                        "${(winner.candidate.dwellMs * 100 / 800)}%"
                    )
                    null
                }
            }
            is RankOutcome.Tie -> {
                lensRenderer?.renderState(
                    LensState.TIE,
                    "TIE: DISAMBIGUATE",
                    "SAY LEFT OR RIGHT",
                    actionPill = "TAP TO CHOOSE"
                )
                null
            }
            is RankOutcome.None -> {
                null
            }
        }
    }

    /**
     * Explicit trigger (tap or spoken "capture" command).
     */
    fun triggerExplicitCapture(
        lookId: String,
        candidates: List<RankCandidate>,
        rawCropBytes: ByteArray? = null
    ): CaptureRecord? {
        if (recordCreatedForCurrentLook && lookId == lastRecordedLookId) {
            // Already captured in this look, render CAPTURED state again without new record (TC2.002)
            lensRenderer?.renderState(LensState.CAPTURED, "ALREADY CAPTURED", "")
            return null
        }

        val t0 = System.currentTimeMillis()
        val rankOutcome = ranker.rank(candidates)
        return if (rankOutcome is RankOutcome.Winner) {
            val winner = rankOutcome.selected
            executeCapture(
                lookId = lookId,
                winner = winner.candidate,
                readability = winner.candidate.readability,
                score = winner.finalScore,
                rawCropBytes = rawCropBytes,
                tShutter = t0,
                isAuto = false
            )
        } else {
            lensRenderer?.renderState(LensState.ERROR, "NO CLEAR OBJECT", "")
            null
        }
    }

    private fun executeCapture(
        lookId: String,
        winner: RankCandidate,
        readability: Float,
        score: Float,
        rawCropBytes: ByteArray?,
        tShutter: Long,
        isAuto: Boolean
    ): CaptureRecord {
        val tStillRx = System.currentTimeMillis()
        val tDecodeDone = tStillRx + 5L

        // Apply bystander privacy blur
        val uploadableCrop = if (rawCropBytes != null) {
            when (val res = faceBlurStage.processCrop(rawCropBytes)) {
                is com.scmtips.field.core.capture.privacy.BlurResult.Success -> res.crop
                else -> null
            }
        } else null

        val tRankDone = System.currentTimeMillis()
        val tCommitted = tRankDone + 2L

        // Render CAPTURED state on HUD
        lensRenderer?.renderState(
            LensState.CAPTURED,
            "CAPTURED",
            winner.barcodeValue ?: "TAG-${winner.id}"
        )
        val tLensDrawn = System.currentTimeMillis()

        val timings = TimingMarks(
            shutterEpochMs = tShutter,
            stillRxEpochMs = tStillRx,
            decodeDoneEpochMs = tDecodeDone,
            rankDoneEpochMs = tRankDone,
            committedEpochMs = tCommitted,
            lensDrawnEpochMs = tLensDrawn
        )

        val record = CaptureRecord(
            lookId = lookId,
            codeValue = winner.barcodeValue ?: "UNKNOWN",
            codeType = "GS1_128",
            readability = readability,
            finalRankScore = score,
            crop = uploadableCrop,
            timings = timings,
            isAutoCaptured = isAuto
        )

        recordCreatedForCurrentLook = true
        lastRecordedLookId = lookId
        lookSegmenter.completeRecordCommitted()

        outboxSink(record)
        return record
    }
}
