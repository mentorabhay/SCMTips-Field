package com.scmtips.field.core.capture.rank

import com.scmtips.field.core.capture.detect.BoundingBox
import com.scmtips.field.core.capture.detect.DetectedObject
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min

data class TrackedObject(
    val trackId: String,
    val detection: DetectedObject,
    val firstSeenMs: Long,
    val lastSeenMs: Long,
    val accumulatedDwellMs: Long
)

/**
 * IoU-based multi-object tracker and Gaze Dwell accumulator (Task T2.025 / FR2.027 / TC2.125).
 */
class DwellTracker(
    private val viewWidth: Float = 504f,
    private val viewHeight: Float = 896f,
    private val iouThreshold: Float = 0.40f
) {
    private val circleRadius = viewWidth * 0.135f
    private val centerX = viewWidth / 2f
    private val centerY = viewHeight / 2f

    private val activeTracks = mutableMapOf<String, TrackedObject>()
    private var nextTrackNumber = 1

    companion object {
        fun computeIoU(boxA: BoundingBox, boxB: BoundingBox): Float {
            val interLeft = max(boxA.left, boxB.left)
            val interTop = max(boxA.top, boxB.top)
            val interRight = min(boxA.right, boxB.right)
            val interBottom = min(boxA.bottom, boxB.bottom)

            val interWidth = max(0f, interRight - interLeft)
            val interHeight = max(0f, interBottom - interTop)
            val interArea = interWidth * interHeight

            val unionArea = boxA.area + boxB.area - interArea
            return if (unionArea <= 0f) 0f else interArea / unionArea
        }
    }

    fun isCenterInsideCircle(x: Float, y: Float): Boolean {
        return hypot(x - centerX, y - centerY) <= circleRadius
    }

    /**
     * Updates tracks with newly detected objects for current frame timestamp.
     */
    fun update(
        detections: List<DetectedObject>,
        timestampMs: Long = System.currentTimeMillis()
    ): List<TrackedObject> {
        val matchedTrackIds = mutableSetOf<String>()
        val updatedTracks = mutableListOf<TrackedObject>()

        for (det in detections) {
            // Find best matching track with IoU >= 0.40
            var bestTrackId: String? = null
            var bestIoU = iouThreshold

            for ((tId, track) in activeTracks) {
                if (tId in matchedTrackIds) continue
                val iou = computeIoU(track.detection.box, det.box)
                if (iou >= bestIoU) {
                    bestIoU = iou
                    bestTrackId = tId
                }
            }

            val isInside = isCenterInsideCircle(det.box.x, det.box.y)

            if (bestTrackId != null) {
                matchedTrackIds.add(bestTrackId)
                val existing = activeTracks[bestTrackId]!!
                val deltaMs = timestampMs - existing.lastSeenMs
                val newDwell = if (isInside) existing.accumulatedDwellMs + deltaMs else 0L

                val updated = existing.copy(
                    detection = det,
                    lastSeenMs = timestampMs,
                    accumulatedDwellMs = newDwell
                )
                activeTracks[bestTrackId] = updated
                updatedTracks.add(updated)
            } else {
                // New track
                val newId = "trk-${nextTrackNumber++}"
                val initialDwell = if (isInside) 50L else 0L
                val newTrack = TrackedObject(
                    trackId = newId,
                    detection = det,
                    firstSeenMs = timestampMs,
                    lastSeenMs = timestampMs,
                    accumulatedDwellMs = initialDwell
                )
                activeTracks[newId] = newTrack
                updatedTracks.add(newTrack)
            }
        }

        // Prune stale tracks that disappeared
        activeTracks.keys.retainAll(matchedTrackIds)
        return updatedTracks
    }

    fun resetLook() {
        activeTracks.clear()
    }
}
