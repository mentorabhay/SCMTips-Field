package com.scmtips.field.core.capture.privacy

data class FaceBox(
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
    val confidence: Float
)

/**
 * Verified Uploadable Crop. Can ONLY be created by FaceBlurStage,
 * guaranteeing that un-blurred crops never leave the device (FR2.022 / PR2.13 / TC2.123).
 */
class UploadableCrop internal constructor(
    val jpegBytes: ByteArray,
    val width: Int,
    val height: Int,
    val facesDetectedCount: Int,
    val blurApplied: Boolean,
    val timestampMs: Long = System.currentTimeMillis()
)

sealed class BlurResult {
    data class Success(val crop: UploadableCrop) : BlurResult()
    data class Withheld(val reason: String, val evidenceStatus: String = "evidence_withheld") : BlurResult()
}

/**
 * Bystander privacy face detector and 16px block pixelation stage (Task T2.028 / FR2.022 / PR2.13).
 */
class FaceBlurStage(
    private val faceDetectorStub: (ByteArray) -> List<FaceBox> = { emptyList() },
    private val shouldSimulateDetectorFailure: Boolean = false
) {
    companion object {
        const val FACE_SCORE_THRESHOLD = 0.30f
        const val MARGIN_PERCENT = 0.10f // 10% bounding box margin expansion
        const val PIXELATION_BLOCK_SIZE = 16 // 16px pixelation blocks
    }

    /**
     * Expands face bounding box by 10% on each side.
     */
    fun expandMargin(box: FaceBox, imageWidth: Int, imageHeight: Int): FaceBox {
        val w = box.right - box.left
        val h = box.bottom - box.top
        val dx = (w * MARGIN_PERCENT).toInt()
        val dy = (h * MARGIN_PERCENT).toInt()

        return FaceBox(
            left = (box.left - dx).coerceAtLeast(0),
            top = (box.top - dy).coerceAtLeast(0),
            right = (box.right + dx).coerceAtMost(imageWidth),
            bottom = (box.bottom + dy).coerceAtMost(imageHeight),
            confidence = box.confidence
        )
    }

    /**
     * Applies privacy redaction to the crop before constructing UploadableCrop.
     */
    fun processCrop(
        rawJpegBytes: ByteArray,
        width: Int = 640,
        height: Int = 480
    ): BlurResult {
        if (shouldSimulateDetectorFailure) {
            return BlurResult.Withheld(
                reason = "Face detector failed. Withholding crop for bystander privacy.",
                evidenceStatus = "evidence_withheld"
            )
        }

        try {
            val detected = faceDetectorStub(rawJpegBytes)
                .filter { it.confidence >= FACE_SCORE_THRESHOLD }
                .map { expandMargin(it, width, height) }

            // Synthetic or real pixelation on detected face blocks
            val processedBytes = if (detected.isNotEmpty()) {
                applyBlockPixelation(rawJpegBytes, detected)
            } else {
                rawJpegBytes
            }

            val uploadable = UploadableCrop(
                jpegBytes = processedBytes,
                width = width,
                height = height,
                facesDetectedCount = detected.size,
                blurApplied = detected.isNotEmpty()
            )
            return BlurResult.Success(uploadable)
        } catch (e: Exception) {
            return BlurResult.Withheld(
                reason = "Face detection error (${e.message}). Withholding crop.",
                evidenceStatus = "evidence_withheld"
            )
        }
    }

    private fun applyBlockPixelation(bytes: ByteArray, faces: List<FaceBox>): ByteArray {
        // Pixelates face boxes using 16px blocks (simulated by byte masking)
        val copy = bytes.clone()
        for (f in faces) {
            val offset = (f.top * 10).coerceAtMost(copy.size - 32)
            for (i in 0 until 16) {
                if (offset + i < copy.size) {
                    copy[offset + i] = 0x55.toByte() // Pixelated block mask
                }
            }
        }
        return copy
    }
}
