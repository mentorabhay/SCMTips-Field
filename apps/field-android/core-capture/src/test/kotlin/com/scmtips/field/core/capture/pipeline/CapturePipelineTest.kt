package com.scmtips.field.core.capture.pipeline

import com.scmtips.field.core.capture.privacy.CropEncoder
import com.scmtips.field.core.capture.privacy.FaceBlurStage
import com.scmtips.field.core.capture.privacy.FaceBox
import com.scmtips.field.core.capture.privacy.FaceDetector
import com.scmtips.field.core.capture.privacy.PixelCrop
import com.scmtips.field.core.capture.rank.RankCandidate
import com.scmtips.field.core.capture.rank.Ranker
import com.scmtips.field.core.wearables.DrawCall
import com.scmtips.field.core.wearables.LensRenderer
import com.scmtips.field.core.wearables.LensState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

/** Capture triggers and per-look record contract of the production CapturePipeline (FR2.029, FR2.025, FR2.026, FR2.065, FR2.022). */
class CapturePipelineTest {

    private class RecordingLens : LensRenderer {
        val calls = mutableListOf<DrawCall>()
        override fun renderState(state: LensState, line1: String, line2: String, actionPill: String?): DrawCall =
            DrawCall(state, line1, line2, actionPill, 0L).also { calls.add(it) }
        val states get() = calls.map { it.state }
    }

    private val ranker = Ranker() // 504 x 896
    private val sscc = "003012345678901232"

    private fun winner(dwell: Long, dup: Boolean = false) =
        RankCandidate("W", ranker.centerX, ranker.centerY, 60f, 40f, 0.93f, 1f, dwell, isAlreadyCaptured = dup, barcodeValue = sscc)

    private fun tiePair() = listOf(
        RankCandidate("L", ranker.centerX - 30f, ranker.centerY, 40f, 40f, 0.9f, 1f, 800L, barcodeValue = "LEFT-CODE"),
        RankCandidate("R", ranker.centerX + 30f, ranker.centerY, 40f, 40f, 0.9f, 1f, 800L, barcodeValue = "RIGHT-CODE")
    )

    private class Fixture(quiet: Boolean = false, blur: FaceBlurStage? = null) {
        val lens = RecordingLens()
        val sink = mutableListOf<CaptureRecord>()
        val drawn = mutableListOf<CaptureRecord>()
        var now = 1_000L
        val pipeline = CapturePipeline(
            faceBlurStage = blur, lensRenderer = lens, outboxSink = { sink.add(it) }, onLensDrawn = { drawn.add(it) },
            isWalkingQuiet = { quiet }, clock = { now++ }
        )
    }

    @Test
    fun tc2_001_autoCaptureThenCaptureCommandYieldsOneRecord_fr2_029() {
        val f = Fixture()
        assertNotNull(f.pipeline.evaluateCandidates("L1", listOf(winner(3000L))))
        assertNull(f.pipeline.triggerExplicitCapture("L1", listOf(winner(3000L))))
        assertEquals(1, f.sink.size)
        assertEquals(sscc, f.sink.single().codeValue)
        assertEquals("sscc", f.sink.single().codeType)
    }

    @Test
    fun tc2_002_secondCaptureCommandShowsCapturedAgainWithoutRecord_fr2_029() {
        val f = Fixture()
        f.pipeline.triggerExplicitCapture("L2", listOf(winner(0L)))
        f.lens.calls.clear()
        assertNull(f.pipeline.triggerExplicitCapture("L2", listOf(winner(0L))))
        assertEquals(1, f.sink.size)
        assertEquals(listOf(LensState.CAPTURED), f.lens.states)
    }

    @Test
    fun tc2_166_eachTriggerCreatesOneRecordForItsLook_fr2_029() {
        val f = Fixture()
        assertNull("no auto capture below full dwell", f.pipeline.evaluateCandidates("A", listOf(winner(700L))))
        val auto = f.pipeline.evaluateCandidates("A", listOf(winner(800L)))!!
        assertTrue(auto.isAutoCaptured)
        val command = f.pipeline.triggerExplicitCapture("B", listOf(winner(300L)))!!
        val tap = f.pipeline.triggerExplicitCapture("C", listOf(winner(0L)))!!
        assertEquals(listOf("A", "B", "C"), f.sink.map { it.lookId })
        assertEquals(false, command.isAutoCaptured)
        assertEquals(3, (f.sink.map { it.id } + tap.id).toSet().size)
        f.sink.forEach { assertEquals(7, UUID.fromString(it.id).version()) }
    }

    @Test
    fun tc2_003_tieMakesNoRecordLeftResolvesThenCaptureMakesNoSecond_fr2_026() {
        val f = Fixture()
        assertNull(f.pipeline.evaluateCandidates("L3", tiePair()))
        assertNull(f.pipeline.triggerExplicitCapture("L3", tiePair()))
        assertEquals(0, f.sink.size)
        assertTrue(LensState.TIE in f.lens.states)
        val chosen = f.pipeline.resolveTie("L3", TieSide.LEFT, tiePair())!!
        assertEquals("LEFT-CODE", chosen.codeValue)
        assertNull(f.pipeline.triggerExplicitCapture("L3", tiePair()))
        assertNull(f.pipeline.resolveTie("L3", TieSide.RIGHT, tiePair()))
        assertEquals(1, f.sink.size)
    }

    @Test
    fun tc2_010_duplicateWinnerShowsDuplicateAndMakesNoRecord_fr2_025() {
        val f = Fixture()
        assertNull(f.pipeline.evaluateCandidates("D", listOf(winner(3000L, dup = true))))
        assertNull(f.pipeline.triggerExplicitCapture("D", listOf(winner(3000L, dup = true))))
        assertEquals(0, f.sink.size)
        assertEquals(listOf(LensState.DUPLICATE, LensState.DUPLICATE), f.lens.states)
    }

    @Test
    fun tc2_156_walkingQuietNoTiePromptNoTieRecordErrorStillShown_fr2_065() {
        val f = Fixture(quiet = true)
        assertNull(f.pipeline.evaluateCandidates("Q", tiePair()))
        assertNull(f.pipeline.resolveTie("Q", TieSide.LEFT, tiePair()))
        assertNull(f.pipeline.evaluateCandidates("Q2", listOf(winner(3000L, dup = true))))
        assertEquals(0, f.sink.size)
        assertTrue("no tie or duplicate prompt", f.lens.calls.isEmpty())
        assertNull(f.pipeline.triggerExplicitCapture("Q3", emptyList()))
        assertEquals(listOf(LensState.ERROR), f.lens.states)
    }

    @Test
    fun fr2_022_failedFaceDetectionWithholdsCropButKeepsTheCode() {
        val enc = CropEncoder { ByteArray(it.argb.size) }
        val failing = FaceBlurStage(FaceDetector { throw RuntimeException("detector down") }, enc)
        val f = Fixture(blur = failing)
        val rec = f.pipeline.triggerExplicitCapture("E", listOf(winner(0L)), crop = PixelCrop(8, 8, IntArray(64)))!!
        assertNull(rec.crop)
        assertEquals("evidence_withheld", rec.evidenceStatus)
        assertEquals(sscc, rec.codeValue)

        val ok = Fixture(blur = FaceBlurStage(FaceDetector { listOf(FaceBox(0, 0, 4, 4, 0.9f)) }, enc))
        val rec2 = ok.pipeline.triggerExplicitCapture("E2", listOf(winner(0L)), crop = PixelCrop(8, 8, IntArray(64)))!!
        assertTrue(rec2.crop!!.blurApplied)
        assertEquals(1, rec2.crop!!.facesBlurred)

        val noStage = Fixture(blur = null)
        val rec3 = noStage.pipeline.triggerExplicitCapture("E3", listOf(winner(0L)), crop = PixelCrop(8, 8, IntArray(64)))!!
        assertNull("raw pixels never bypass the blur stage", rec3.crop)
    }

    @Test
    fun fr2_029_timingMarksAreOrderedClockReadingsAndLensFollowsCommit() {
        val f = Fixture()
        val marks = FrameMarks(shutterEpochMs = 900L, stillRxEpochMs = 950L, decodeDoneEpochMs = 990L)
        val rec = f.pipeline.triggerExplicitCapture("T", listOf(winner(0L)), marks = marks)!!
        val committed = f.sink.single().timings
        assertNull("lens is drawn after the commit", committed.lensDrawnEpochMs)
        val t = rec.timings
        val seq = listOf(t.shutterEpochMs, t.stillRxEpochMs, t.decodeDoneEpochMs, t.rankDoneEpochMs, t.committedEpochMs, t.lensDrawnEpochMs!!)
        assertEquals(seq.sorted(), seq)
        assertTrue(t.rankDoneEpochMs < t.committedEpochMs && t.committedEpochMs < t.lensDrawnEpochMs!!)
        assertEquals(rec, f.drawn.single())
        assertEquals(LensState.CAPTURED, f.lens.states.last())
        assertEquals(setOf("centre", "task", "read", "cov", "dwell", "size", "dup"), rec.rankDetail.keys)
    }
}
