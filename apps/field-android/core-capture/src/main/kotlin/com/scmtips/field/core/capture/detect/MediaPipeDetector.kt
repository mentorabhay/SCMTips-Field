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
 * Runs the int8 TFLite model through MediaPipe on Android. Not implemented in this module yet:
 * no model asset is shipped (docs/models: status NOT_PROVIDED), so there is no engine to inject
 * outside tests. UNVERIFIED.
 */
fun interface DetectorEngine {
    fun infer(frame: PreviewFrame): List<DetectedObject>
}

/**
 * Object detector wrapper (Task T2.020 / FR2.016): keeps only the classes carton, label, nameplate,
 * gauge, tag and device at score >= 0.50, highest score first, at most 10 results.
 * The inference itself is delegated to [DetectorEngine]; this class adds the post-filter only.
 */
class MediaPipeDetector(
    private val engine: DetectorEngine,
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

    fun detect(frame: PreviewFrame): List<DetectedObject> = filterAndSort(engine.infer(frame))
}
