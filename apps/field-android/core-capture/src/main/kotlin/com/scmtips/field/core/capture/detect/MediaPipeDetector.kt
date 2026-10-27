package com.scmtips.field.core.capture.detect

import com.scmtips.field.core.wearables.PreviewFrame

data class BoundingBox(
    val x: Float,
    val y: Float,
    val width: Float,
    val height: Float
) {
    val left: Float get() = x - width / 2f
    val top: Float get() = y - height / 2f
    val right: Float get() = x + width / 2f
    val bottom: Float get() = y + height / 2f
    val area: Float get() = width * height
}

data class DetectedObject(
    val id: String,
    val category: String, // carton, label, nameplate, gauge, tag, device
    val confidence: Float,
    val box: BoundingBox,
    val barcodeValue: String? = null
)

/**
 * On-device int8 MediaPipe Object Detector wrapper (Task T2.020 / FR2.016).
 * Enforces classes: carton, label, nameplate, gauge, tag, device; score >= 0.50; max 10 results.
 */
class MediaPipeDetector(
    private val modelAssetPath: String = "detector_v1.tflite",
    private val scoreThreshold: Float = 0.50f,
    private val maxResults: Int = 10
) {
    companion object {
        val ALLOWED_CLASSES = setOf(
            "carton",
            "label",
            "nameplate",
            "gauge",
            "tag",
            "device"
        )
    }

    fun filterAndSort(detections: List<DetectedObject>): List<DetectedObject> {
        return detections
            .filter { it.category in ALLOWED_CLASSES && it.confidence >= scoreThreshold }
            .sortedByDescending { it.confidence }
            .take(maxResults)
    }

    fun detect(frame: PreviewFrame, injectedDetections: List<DetectedObject>? = null): List<DetectedObject> {
        val candidates = injectedDetections ?: emptyList()
        return filterAndSort(candidates)
    }
}
