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
    val accumulatedDwellMs: Long,
    /** Whether the box centre was inside the capture circle on the last update. */
    val insideCircle: Boolean = false
) {
    /** Dwell component of the rank score: 0 at 0 ms, 1 at 800 ms or more (FR2.027). */
    val dwellScore: Float get() = min(1f, accumulatedDwellMs.toFloat() / Ranker.DWELL_MAX_MS)
}

/**
 * IoU-based multi-object tracker and head-gaze dwell accumulator (Task T2.025 / FR2.027 / TC2.125).
 *
 * Dwell grows by the elapsed time between consecutive frames on which the tracked box centre is
 * inside the capture circle, reaches full score at 0.8 s, and resets to 0 when the centre leaves.
 * Time spent outside is never counted: on re-entry accumulation restarts from 0.
 * Tracks not matched in a frame (IoU < threshold) are dropped.
 */
class DwellTracker(
    private val viewWidth: Float = 504f,
    private val viewHeight: Float = 896f,
    private val iouThreshold: Float = 0.40f
) {
    private val circleRadius = viewWidth * 0.135f
    private val centerX = viewWidth / 2f
    private val centerY = viewHeight / 2f

    private val activeTracks = linkedMapOf<String, TrackedObject>()
    private var nextTrackNumber = 1

    companion object {
        fun computeIoU(boxA: BoundingBox, boxB: BoundingBox): Float {
            val interWidth = max(0f, min(boxA.right, boxB.right) - max(boxA.left, boxB.left))
            val interHeight = max(0f, min(boxA.bottom, boxB.bottom) - max(boxA.top, boxB.top))
            val interArea = interWidth * interHeight
            val unionArea = boxA.area + boxB.area - interArea
            return if (unionArea <= 0f) 0f else interArea / unionArea
        }
    }

    fun isCenterInsideCircle(x: Float, y: Float): Boolean = hypot(x - centerX, y - centerY) <= circleRadius

    /** Updates tracks with the detections of one frame and returns the tracks seen in it. */
    fun update(detections: List<DetectedObject>, timestampMs: Long): List<TrackedObject> {
        val kept = mutableSetOf<String>()
        val updatedTracks = mutableListOf<TrackedObject>()

        for (det in detections) {
            var bestTrackId: String? = null
            var bestIoU = iouThreshold
            for ((tId, track) in activeTracks) {
                if (tId in kept) continue
                val iou = computeIoU(track.detection.box, det.box)
                if (iou >= bestIoU) {
                    bestIoU = iou
                    bestTrackId = tId
                }
            }

            val isInside = isCenterInsideCircle(det.box.x, det.box.y)
            val track = if (bestTrackId != null) {
                val existing = activeTracks.getValue(bestTrackId)
                val deltaMs = max(0L, timestampMs - existing.lastSeenMs)
                val newDwell = when {
                    !isInside -> 0L
                    existing.insideCircle -> existing.accumulatedDwellMs + deltaMs
                    else -> 0L // just entered: start counting from this frame
                }
                existing.copy(detection = det, lastSeenMs = timestampMs, accumulatedDwellMs = newDwell, insideCircle = isInside)
            } else {
                TrackedObject(
                    trackId = "trk-${nextTrackNumber++}",
                    detection = det,
                    firstSeenMs = timestampMs,
                    lastSeenMs = timestampMs,
                    accumulatedDwellMs = 0L,
                    insideCircle = isInside
                )
            }
            activeTracks[track.trackId] = track
            kept.add(track.trackId)
            updatedTracks.add(track)
        }

        activeTracks.keys.retainAll(kept)
        return updatedTracks
    }

    fun activeTrackCount(): Int = activeTracks.size

    fun resetLook() {
        activeTracks.clear()
    }
}
