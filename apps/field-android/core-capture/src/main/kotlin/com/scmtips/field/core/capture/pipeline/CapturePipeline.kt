package com.scmtips.field.core.capture.pipeline

import com.scmtips.field.core.capture.codes.Gs1BarcodeParser
import com.scmtips.field.core.capture.motion.LookSegmenter
import com.scmtips.field.core.capture.privacy.BlurResult
import com.scmtips.field.core.capture.privacy.FaceBlurStage
import com.scmtips.field.core.capture.privacy.PixelCrop
import com.scmtips.field.core.capture.privacy.UploadableCrop
import com.scmtips.field.core.capture.rank.RankCandidate
import com.scmtips.field.core.capture.rank.RankOutcome
import com.scmtips.field.core.capture.rank.Ranker
import com.scmtips.field.core.capture.rank.ScoredCandidate
import com.scmtips.field.core.outbox.api.UUIDv7
import com.scmtips.field.core.wearables.LensRenderer
import com.scmtips.field.core.wearables.LensState

/** Times measured before ranking, by the frame source and decoder (epoch ms). */
data class FrameMarks(val shutterEpochMs: Long, val stillRxEpochMs: Long, val decodeDoneEpochMs: Long)

/**
 * capture.timings (API2 ms marks). Every value is a clock reading taken where the step happened.
 * lensDrawnEpochMs is null in the record handed to the outbox, because the lens is drawn only
 * after the record is committed; the pipeline reports it through onLensDrawn.
 */
data class TimingMarks(
    val shutterEpochMs: Long,
    val stillRxEpochMs: Long,
    val decodeDoneEpochMs: Long,
    val rankDoneEpochMs: Long,
    val committedEpochMs: Long,
    val lensDrawnEpochMs: Long? = null
) {
    val totalLatencyMs: Long? get() = lensDrawnEpochMs?.minus(shutterEpochMs)
}

data class CaptureRecord(
    val id: String = UUIDv7.generate(),
    val lookId: String,
    val codeValue: String?,
    val codeType: String?,
    val readability: Float,
    val finalRankScore: Float,
    val rankDetail: Map<String, Any>,
    val crop: UploadableCrop?,
    /** "evidence_withheld" when face detection failed and the crop was withheld (FR2.022). */
    val evidenceStatus: String?,
    val timings: TimingMarks,
    val isAutoCaptured: Boolean = false
)

enum class TieSide { LEFT, RIGHT }

/**
 * On-device capture orchestrator (Task T2.029 / FR2.029 / FR2.025 / FR2.026 / FR2.065).
 *
 * - At most one record per look (FR2.029, PR2.01); a repeated trigger re-shows Captured (TC2.002).
 * - Triggers: full dwell (800 ms) on a clear winner, the capture command, or a tap (TC2.166).
 * - A tie creates no record and shows the tie state; it is resolved by "left"/"right" (FR2.026).
 * - A winner whose code is already captured for the task creates no record and shows the
 *   duplicate state (FR2.025, TC2.010).
 * - While walking-quiet is active, lens prompts other than errors and the captured mark are
 *   suppressed, and no tie-dependent record is made (FR2.065, TC2.156).
 * - Crops pass through FaceBlurStage; a withheld crop yields a record with crop = null and
 *   evidenceStatus "evidence_withheld" (FR2.022).
 */
class CapturePipeline(
    private val ranker: Ranker = Ranker(),
    private val lookSegmenter: LookSegmenter = LookSegmenter(),
    private val faceBlurStage: FaceBlurStage? = null,
    private val lensRenderer: LensRenderer? = null,
    private val outboxSink: (CaptureRecord) -> Unit = {},
    private val onLensDrawn: (CaptureRecord) -> Unit = {},
    private val isWalkingQuiet: () -> Boolean = { false },
    private val clock: () -> Long = System::currentTimeMillis
) {
    companion object {
        const val FULL_DWELL_MS = 800L
        private const val RECENT_LOOKS = 256
    }

    private val recordedLooks = LinkedHashSet<String>()

    private fun alreadyRecorded(lookId: String) = lookId in recordedLooks

    private fun markRecorded(lookId: String) {
        recordedLooks.add(lookId)
        while (recordedLooks.size > RECENT_LOOKS) recordedLooks.remove(recordedLooks.first())
    }

    private fun render(state: LensState, line1: String, line2: String = "", pill: String? = null) {
        if (isWalkingQuiet() && state != LensState.ERROR && state != LensState.CAPTURED) return
        lensRenderer?.renderState(state, line1, line2, pill)
    }

    fun onNewLookStarted(lookId: String) {
        if (!alreadyRecorded(lookId)) render(LensState.READY, "LOOK READY")
    }

    /** Per-frame evaluation: auto-captures on full dwell of a clear winner. */
    fun evaluateCandidates(
        lookId: String,
        candidates: List<RankCandidate>,
        crop: PixelCrop? = null,
        marks: FrameMarks? = null
    ): CaptureRecord? {
        if (alreadyRecorded(lookId)) return null
        val start = clock()
        return when (val outcome = ranker.rank(candidates)) {
            is RankOutcome.Winner -> {
                val w = outcome.selected
                when {
                    w.candidate.isAlreadyCaptured -> { render(LensState.DUPLICATE, "ALREADY CAPTURED"); null }
                    w.candidate.dwellMs >= FULL_DWELL_MS ->
                        executeCapture(lookId, w, crop, marks ?: FrameMarks(start, start, start), isAuto = true)
                    else -> {
                        render(LensState.READY, "DWELLING...", "${w.candidate.dwellMs * 100 / FULL_DWELL_MS}%")
                        null
                    }
                }
            }
            is RankOutcome.Tie -> { render(LensState.TIE, "LEFT OR RIGHT?", "SAY LEFT OR RIGHT", "TAP TO CHOOSE"); null }
            RankOutcome.None -> null
        }
    }

    /** Capture command or tap. */
    fun triggerExplicitCapture(
        lookId: String,
        candidates: List<RankCandidate>,
        crop: PixelCrop? = null,
        marks: FrameMarks? = null
    ): CaptureRecord? {
        if (alreadyRecorded(lookId)) {
            render(LensState.CAPTURED, "ALREADY CAPTURED")
            return null
        }
        val start = clock()
        return when (val outcome = ranker.rank(candidates)) {
            is RankOutcome.Winner ->
                if (outcome.selected.candidate.isAlreadyCaptured) {
                    render(LensState.DUPLICATE, "ALREADY CAPTURED"); null
                } else {
                    executeCapture(lookId, outcome.selected, crop, marks ?: FrameMarks(start, start, start), isAuto = false)
                }
            is RankOutcome.Tie -> { render(LensState.TIE, "LEFT OR RIGHT?", "SAY LEFT OR RIGHT", "TAP TO CHOOSE"); null }
            RankOutcome.None -> { render(LensState.ERROR, "NO CLEAR OBJECT"); null }
        }
    }

    /** "left" / "right" after a tie (FR2.026). No record while walking-quiet is active (FR2.065). */
    fun resolveTie(
        lookId: String,
        side: TieSide,
        candidates: List<RankCandidate>,
        crop: PixelCrop? = null,
        marks: FrameMarks? = null
    ): CaptureRecord? {
        if (alreadyRecorded(lookId) || isWalkingQuiet()) return null
        val start = clock()
        val tie = ranker.rank(candidates) as? RankOutcome.Tie ?: return null
        val chosen = if (side == TieSide.LEFT) tie.left else tie.right
        if (chosen.candidate.isAlreadyCaptured) {
            render(LensState.DUPLICATE, "ALREADY CAPTURED")
            return null
        }
        return executeCapture(lookId, chosen, crop, marks ?: FrameMarks(start, start, start), isAuto = false)
    }

    private fun codeTypeOf(c: RankCandidate): String? =
        c.codeType ?: c.barcodeValue?.let { if (Gs1BarcodeParser.validateSscc(it)) "sscc" else null }

    private fun executeCapture(
        lookId: String,
        winner: ScoredCandidate,
        crop: PixelCrop?,
        marks: FrameMarks,
        isAuto: Boolean
    ): CaptureRecord {
        val rankDone = clock()
        var evidenceStatus: String? = null
        val uploadable = if (crop != null && faceBlurStage != null) {
            when (val res = faceBlurStage.processCrop(crop)) {
                is BlurResult.Success -> res.crop
                is BlurResult.Withheld -> { evidenceStatus = res.evidenceStatus; null }
            }
        } else {
            if (crop != null) evidenceStatus = "evidence_withheld" // no blur stage: never upload raw pixels
            null
        }
        val draft = CaptureRecord(
            lookId = lookId,
            codeValue = winner.candidate.barcodeValue,
            codeType = codeTypeOf(winner.candidate),
            readability = winner.candidate.readability,
            finalRankScore = winner.finalScore,
            rankDetail = winner.rankDetail,
            crop = uploadable,
            evidenceStatus = evidenceStatus,
            timings = TimingMarks(marks.shutterEpochMs, marks.stillRxEpochMs, marks.decodeDoneEpochMs, rankDone, committedEpochMs = 0L),
            isAutoCaptured = isAuto
        )
        markRecorded(lookId)
        // committed = the moment the record is handed to the outbox's atomic commit (OutboxWriter)
        val committed = draft.copy(timings = draft.timings.copy(committedEpochMs = clock()))
        outboxSink(committed)
        lookSegmenter.completeRecordCommitted()

        render(LensState.CAPTURED, "CAPTURED", winner.candidate.barcodeValue ?: "")
        val final = committed.copy(timings = committed.timings.copy(lensDrawnEpochMs = clock()))
        onLensDrawn(final)
        return final
    }
}
