package com.scmtips.field.app.look

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.graphics.PointF
import android.media.ExifInterface
import android.media.FaceDetector
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * Android side of a look photo: scale to [LookApi.MAX_PX], find faces with the platform's
 * android.media.FaceDetector, pixelate them ([FacePixels], FaceBlurStage rules), JPEG at most
 * [LookApi.MAX_BYTES]. A photo whose face check fails is never returned, so it cannot be uploaded.
 */
object LookPhotos {
    private const val MAX_FACES = 8

    fun prepare(src: Bitmap, camera: CameraUsed, takenAtMs: Long, captureMs: Long): LookPhoto? {
        val (w, h) = FacePixels.scaledSize(src.width, src.height)
        val scaled = Bitmap.createScaledBitmap(src, w, h, true)
        val faces = try {
            findFaces(scaled)
        } catch (e: RuntimeException) {
            return null // no face check, no upload (FR2.022)
        }
        val argb = IntArray(w * h)
        scaled.getPixels(argb, 0, w, 0, 0, w, h)
        FacePixels.pixelate(argb, w, h, faces)
        val out = Bitmap.createBitmap(argb, w, h, Bitmap.Config.ARGB_8888)
        for (q in listOf(88, 75, 60, 45)) {
            val bytes = ByteArrayOutputStream().also { out.compress(Bitmap.CompressFormat.JPEG, q, it) }.toByteArray()
            if (bytes.size <= LookApi.MAX_BYTES) return LookPhoto(bytes, w, h, camera, takenAtMs, captureMs, faces.size)
        }
        return null
    }

    private fun findFaces(bmp: Bitmap): List<PixelBox> {
        val rgb565 = bmp.copy(Bitmap.Config.RGB_565, false) ?: throw IllegalStateException("no RGB_565 copy")
        val found = arrayOfNulls<FaceDetector.Face>(MAX_FACES)
        val n = FaceDetector(rgb565.width, rgb565.height, MAX_FACES).findFaces(rgb565, found)
        val mid = PointF()
        return found.take(n).filterNotNull().filter { it.confidence() >= FacePixels.MIN_CONFIDENCE }.mapNotNull { f ->
            f.getMidPoint(mid)
            FacePixels.faceBox(mid.x, mid.y, f.eyesDistance(), bmp.width, bmp.height)
        }
    }

    /** The phone camera app's photo file, decoded at about 2x the upload size and turned upright (EXIF). */
    fun decodePhoneFile(file: File): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= LookApi.MAX_PX * 2) sample *= 2
        val bmp = BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample }) ?: return null
        val degrees = runCatching {
            when (ExifInterface(file.path).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
                ExifInterface.ORIENTATION_ROTATE_90 -> 90f
                ExifInterface.ORIENTATION_ROTATE_180 -> 180f
                ExifInterface.ORIENTATION_ROTATE_270 -> 270f
                else -> 0f
            }
        }.getOrDefault(0f)
        if (degrees == 0f) return bmp
        return Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, Matrix().apply { postRotate(degrees) }, true)
    }
}
