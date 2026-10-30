package com.scmtips.field.feature.towerAudit

import java.security.MessageDigest

/**
 * Photo evidence record produced on the device. It is queued for upload by the outbox; this class
 * never claims an upload happened.
 */
data class CaptureEvidenceRecord(
    val captureId: String,
    /** Content address of the (blurred) crop bytes: "sha256:<hex>". */
    val cropRef: String,
    val fileSizeBytes: Long,
    val sha256Hash: String,
    val blurApplied: Boolean,
    val consentRef: String,
    val uploadState: String = "queued",
    val bytes: ByteArray,
)

class ConsentMissingException(message: String) : IllegalStateException(message)

/** Face blur seam: returns the blurred crop, or null when the crop must be withheld. */
fun interface FaceBlur {
    fun blur(crop: ByteArray): ByteArray?
}

sealed class EvidenceResult {
    data class Ready(val record: CaptureEvidenceRecord) : EvidenceResult()
    data class Withheld(val reason: String) : EvidenceResult()
}

/**
 * Tower audit photo evidence (T4.034 / FR4.020 / TC4.118).
 *
 * - Nothing is produced for upload before consent is recorded (P10 rule): [ConsentMissingException].
 * - When a face is in frame the crop passes through on-device [FaceBlur] first; if blur cannot be
 *   applied the evidence is withheld, never sent unblurred.
 * - The hash is the real SHA-256 of the bytes that would be uploaded.
 */
class EvidenceManager(
    private val faceBlur: FaceBlur,
    private var activeConsentRef: String? = null,
) {
    fun setConsent(consentRef: String) {
        activeConsentRef = consentRef
    }

    fun hasConsent(): Boolean = !activeConsentRef.isNullOrBlank()

    fun processEvidenceCrop(captureId: String, rawCropBytes: ByteArray, faceDetectedInFrame: Boolean): EvidenceResult {
        val consent = activeConsentRef
        if (consent.isNullOrBlank()) {
            throw ConsentMissingException("Photo evidence blocked: consent not recorded (P10 rule).")
        }
        val bytes = if (faceDetectedInFrame) {
            faceBlur.blur(rawCropBytes) ?: return EvidenceResult.Withheld("face_blur_failed")
        } else {
            rawCropBytes
        }
        val hex = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        return EvidenceResult.Ready(
            CaptureEvidenceRecord(
                captureId = captureId,
                cropRef = "sha256:$hex",
                fileSizeBytes = bytes.size.toLong(),
                sha256Hash = hex,
                blurApplied = faceDetectedInFrame,
                consentRef = consent,
                bytes = bytes,
            )
        )
    }
}
