package com.scmtips.field.feature.towerAudit

import com.scmtips.field.feature.towerAudit.lens.SectorChecklistRenderer
import com.scmtips.field.feature.towerAudit.lens.SectorChecklistState
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.MessageDigest

class TowerAuditTest {

    private fun state(missing: List<String>, climbing: Boolean = false) = SectorChecklistState(
        sectorName = "Sector A", levelName = "L3", capturedCount = 5, expectedCount = 8,
        missingClasses = missing, isHarnessConfirmed = true, loneWorkerTimerMinutes = 14, isClimbing = climbing,
    )

    /** TC4.113 / FR4.015 / FR4.068: stationary checklist shows sector, level, counts, max 4 missing classes, >= 24 sp, within 400 ms. */
    @Test
    fun tc4_113_sectorChecklistShowsCountsAndAtMostFourMissing() {
        val out = SectorChecklistRenderer().renderChecklist(state(listOf("RRU", "TMA", "Antenna", "Combiner", "Diplexer", "Cable")))
        assertTrue(out.rendered)
        assertEquals("Sector A • L3", out.title)
        assertEquals("5 of 8", out.counterText)
        assertEquals("Missing: RRU, TMA, Antenna, Combiner", out.missingText)
        assertTrue(out.minTextSizeSp >= 24)
        assertTrue(out.isHighContrast)
        assertTrue("render took ${out.renderNanos} ns", out.renderNanos <= SectorChecklistRenderer.MAX_UPDATE_BUDGET_MS * 1_000_000)
    }

    /** FR4.015 / FR4.039: the checklist is not rendered while climbing. */
    @Test
    fun fr4_015_checklistHeldWhileClimbing() {
        val out = SectorChecklistRenderer().renderChecklist(state(listOf("RRU"), climbing = true))
        assertFalse(out.rendered)
        assertEquals("", out.counterText)
    }

    /** FR4.015: nothing missing reads as complete. */
    @Test
    fun fr4_015_noMissingClasses() {
        assertEquals("All expected items captured", SectorChecklistRenderer().renderChecklist(state(emptyList())).missingText)
    }

    private val invertingBlur = FaceBlur { bytes -> ByteArray(bytes.size) { i -> (bytes[i].toInt() xor 0xFF).toByte() } }

    /** TC4.118 / FR4.020: no evidence before consent is recorded. */
    @Test
    fun tc4_118_noEvidenceBeforeConsent() {
        val m = EvidenceManager(invertingBlur)
        try {
            m.processEvidenceCrop("cap-1", byteArrayOf(1, 2, 3), faceDetectedInFrame = true)
            throw AssertionError("evidence produced without consent")
        } catch (_: ConsentMissingException) {
        }
    }

    /** TC4.118 / FR4.020: with consent and a face in frame, the queued crop is the blurred one and its hash is real. */
    @Test
    fun tc4_118_faceInFrameCropIsBlurredAndHashedAfterConsent() {
        val m = EvidenceManager(invertingBlur)
        m.setConsent("consent-f1-2026-11")
        val raw = byteArrayOf(10, 20, 30, 40)
        val r = m.processEvidenceCrop("cap-1", raw, faceDetectedInFrame = true) as EvidenceResult.Ready
        val expected = invertingBlur.blur(raw)!!
        assertArrayEquals(expected, r.record.bytes)
        assertTrue(r.record.blurApplied)
        assertEquals("queued", r.record.uploadState)
        val hex = MessageDigest.getInstance("SHA-256").digest(expected).joinToString("") { "%02x".format(it) }
        assertEquals(hex, r.record.sha256Hash)
        assertEquals("sha256:$hex", r.record.cropRef)
        assertEquals("consent-f1-2026-11", r.record.consentRef)
    }

    /** FR4.020: if blur fails the evidence is withheld, never sent unblurred. */
    @Test
    fun fr4_020_blurFailureWithholdsEvidence() {
        val m = EvidenceManager({ null }, "consent")
        assertEquals(EvidenceResult.Withheld("face_blur_failed"), m.processEvidenceCrop("c", byteArrayOf(1), true))
        val noFace = m.processEvidenceCrop("c", byteArrayOf(1), false) as EvidenceResult.Ready
        assertFalse(noFace.record.blurApplied)
    }

    /** TC4.119 / FR4.021: typed serial without photo is blocked with MSG4.16; with photo it saves with verify_status=queued. */
    @Test
    fun tc4_119_manualEntryNeedsPhotoThenQueuesVerification() {
        val m = ManualEntryManager()
        val blocked = m.submitTypedSerial("21a7k0093", "RRU", null)
        assertEquals(ManualEntryResult.Blocked("MSG4.16", "Take a photo of the nameplate to save a typed serial."), blocked)
        val ok = m.submitTypedSerial("21a7k0093", "RRU", "sha256:abc") as ManualEntryResult.Success
        assertEquals("queued", ok.verifyStatus)
        assertEquals("21A7K0093", ok.serialNo)
        assertEquals("sha256:abc", ok.photoRef)
        assertTrue(ok.photoAttached)
    }

    /** TC4.120 / FR4.022: unknown equipment is a tower_only finding with class, serial, position and photo. */
    @Test
    fun tc4_120_unknownEquipmentIsTowerOnlyFindingWithEvidence() {
        val f = ManualEntryManager().recordUnknownEquipment("TMA-99812", "TMA", "sha256:ph", "IN01-TWR-0042-T01-SA-L03-P02")
        assertEquals("tower_only", f.findingClass)
        assertEquals("TMA", f.equipmentClass)
        assertEquals("TMA-99812", f.serialNo)
        assertEquals("sha256:ph", f.photoRef)
        assertEquals("IN01-TWR-0042-T01-SA-L03-P02", f.locationRef)
        try {
            ManualEntryManager().recordUnknownEquipment("TMA-99812", "TMA", "", "loc")
            throw AssertionError("tower_only finding accepted without photo")
        } catch (_: IllegalArgumentException) {
        }
    }

    /** TC4.121 / FR4.023: mark missing with not_found / removed_by_other / inaccessible -> erp_only; other reasons rejected. */
    @Test
    fun tc4_121_markMissingCreatesErpOnlyWithReason() {
        val m = ManualEntryManager()
        for (reason in listOf("not_found", "removed_by_other", "inaccessible")) {
            val f = m.markMissing("RRU-1", "RRU", reason, "SC-L2")
            assertEquals("erp_only", f.findingClass)
            assertEquals(reason, f.reason)
            assertEquals("RRU-1", f.expectedSerial)
            assertNull(f.serialNo)
        }
        try {
            m.markMissing("RRU-1", "RRU", "lost", "SC-L2")
            throw AssertionError("invalid reason accepted")
        } catch (_: IllegalArgumentException) {
        }
    }

    /** FR4.020: the controller prepares evidence only with consent and marks the matching expected line captured. */
    @Test
    fun fr4_020_controllerEvidenceOnlyWithConsentAndLineMatched() {
        val ev = EvidenceManager(invertingBlur)
        val controller = TowerAuditController(ev)
        val line = AuditTaskLineItem(1, "21A7K0093", "RRU", "A", 30.0)
        val ui = TowerAuditUiState("t1", "IN01", "A", 30.0, listOf(line), deviceToken = "x")
        val noConsent = controller.processCapture(ui, listOf("SN: 21A7K0093"), "RRU", byteArrayOf(1, 2))
        assertNotNull(noConsent)
        assertNull(noConsent!!.evidence)
        assertEquals("captured", line.status)
        assertEquals(noConsent.captureId, line.captureId)
        ev.setConsent("c1")
        val withConsent = controller.processCapture(ui, listOf("SN: 21A7K0093"), "RRU", byteArrayOf(1, 2), faceDetected = true)
        assertTrue(withConsent!!.evidence is EvidenceResult.Ready)
        assertNull(controller.processCapture(ui, emptyList(), "RRU", byteArrayOf(1)))
    }
}
