package com.scmtips.field.core.capture.privacy

data class FaceBox(
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
    val confidence: Float
)

/** Decoded crop pixels, ARGB_8888, row-major. On Android this comes from a Bitmap. */
class PixelCrop(val width: Int, val height: Int, val argb: IntArray) {
    init {
        require(width > 0 && height > 0) { "crop must be non-empty" }
        require(argb.size == width * height) { "argb has ${argb.size} pixels, expected ${width * height}" }
    }

    fun pixel(x: Int, y: Int): Int = argb[y * width + x]
    fun copy(): PixelCrop = PixelCrop(width, height, argb.copyOf())
}

/** Face detector on the device (ML Kit on Android). Throwing means detection failed. */
fun interface FaceDetector {
    fun detect(crop: PixelCrop): List<FaceBox>
}

/** JPEG encoder on the device (Bitmap.compress on Android, which writes no EXIF). */
fun interface CropEncoder {
    fun encodeJpeg(crop: PixelCrop): ByteArray
}

/**
 * Verified uploadable crop. Can only be created by FaceBlurStage, so crops that did not pass the
 * blur stage cannot reach the upload path (FR2.022 / PR2.13 / TC2.123).
 *
 * blurApplied is true for every crop the stage produced (capture.blur_applied; the server rejects
 * false with FIELD-CAP-422-BLUR-MISSING); facesBlurred is the number of faces pixelated
 * (capture.faces_blurred, 0 when none were found).
 */
class UploadableCrop internal constructor(
    val jpegBytes: ByteArray,
    val width: Int,
    val height: Int,
    val facesBlurred: Int,
    val blurApplied: Boolean,
    val timestampMs: Long
)

sealed class BlurResult {
    data class Success(val crop: UploadableCrop) : BlurResult()
    data class Withheld(val reason: String, val evidenceStatus: String = "evidence_withheld") : BlurResult()
}

/**
 * Bystander privacy stage (Task T2.028 / FR2.022): face detection at score >= 0.30, each face box
 * expanded by 10% on every side, pixelated with 16 px blocks (each block filled with its mean
 * colour) before JPEG encoding. If the detector fails the crop is withheld (evidence_withheld).
 * Crops larger than 640 x 640 px are withheld (FR2.066 / TC2.110: crops are at most 640 x 640).
 */
class FaceBlurStage(
    private val detector: FaceDetector,
    private val encoder: CropEncoder,
    private val clock: () -> Long = System::currentTimeMillis
) {
    companion object {
        const val FACE_SCORE_THRESHOLD = 0.30f
        const val MARGIN_PERCENT = 0.10f
        const val PIXELATION_BLOCK_SIZE = 16
        const val MAX_CROP_DIMENSION = 640
    }

    /** Expands a face box by 10% of its size on each side, clamped to the image. */
    fun expandMargin(box: FaceBox, imageWidth: Int, imageHeight: Int): FaceBox {
        val dx = ((box.right - box.left) * MARGIN_PERCENT).toInt()
        val dy = ((box.bottom - box.top) * MARGIN_PERCENT).toInt()
        return FaceBox(
            left = (box.left - dx).coerceAtLeast(0),
            top = (box.top - dy).coerceAtLeast(0),
            right = (box.right + dx).coerceAtMost(imageWidth),
            bottom = (box.bottom + dy).coerceAtMost(imageHeight),
            confidence = box.confidence
        )
    }

    fun processCrop(crop: PixelCrop): BlurResult {
        if (crop.width > MAX_CROP_DIMENSION || crop.height > MAX_CROP_DIMENSION) {
            return BlurResult.Withheld("Crop ${crop.width}x${crop.height} exceeds 640x640.")
        }
        val faces = try {
            detector.detect(crop)
        } catch (e: Exception) {
            return BlurResult.Withheld("Face detection failed. Crop withheld for bystander privacy.")
        }
        val boxes = faces.filter { it.confidence >= FACE_SCORE_THRESHOLD }
            .map { expandMargin(it, crop.width, crop.height) }
            .filter { it.right > it.left && it.bottom > it.top }
        val redacted = crop.copy()
        for (b in boxes) pixelate(redacted, b)
        val bytes = try {
            encoder.encodeJpeg(redacted)
        } catch (e: Exception) {
            return BlurResult.Withheld("Crop encoding failed. Crop withheld.")
        }
        return BlurResult.Success(
            UploadableCrop(
                jpegBytes = bytes,
                width = crop.width,
                height = crop.height,
                facesBlurred = boxes.size,
                blurApplied = true,
                timestampMs = clock()
            )
        )
    }

    /** Fills each 16 x 16 block of the box (aligned to the box origin) with the block's mean colour. */
    private fun pixelate(img: PixelCrop, box: FaceBox) {
        val bs = PIXELATION_BLOCK_SIZE
        var by = box.top
        while (by < box.bottom) {
            val yEnd = minOf(by + bs, box.bottom)
            var bx = box.left
            while (bx < box.right) {
                val xEnd = minOf(bx + bs, box.right)
                var a = 0L; var r = 0L; var g = 0L; var bl = 0L
                val n = (yEnd - by) * (xEnd - bx)
                for (y in by until yEnd) for (x in bx until xEnd) {
                    val p = img.argb[y * img.width + x]
                    a += (p ushr 24) and 0xFF; r += (p ushr 16) and 0xFF; g += (p ushr 8) and 0xFF; bl += p and 0xFF
                }
                val mean = ((a / n).toInt() shl 24) or ((r / n).toInt() shl 16) or ((g / n).toInt() shl 8) or (bl / n).toInt()
                for (y in by until yEnd) for (x in bx until xEnd) img.argb[y * img.width + x] = mean
                bx += bs
            }
            by += bs
        }
    }
}
