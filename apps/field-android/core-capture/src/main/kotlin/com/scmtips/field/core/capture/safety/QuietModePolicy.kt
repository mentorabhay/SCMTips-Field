package com.scmtips.field.core.capture.safety

/**
 * Safety and Data Minimisation Policy (Task T2.071 / FR2.065, FR2.066, TC2.110, TC2.156).
 *
 * 1. Walking-Quiet: Suppresses lens prompts and spoken TTS when walking speed > 1.2 m/s
 *    or when walking-quiet zone flag / config is active.
 * 2. Data Minimisation: Enforces crop dimensions cap of 640x640, EXIF tag stripping,
 *    and forbids persisting full camera frames to disk.
 */
class QuietModePolicy(
    var walkingQuietConfigEnabled: Boolean = false,
    var zoneWalkingQuietFlag: Boolean = false,
    val walkingSpeedThresholdMps: Float = 1.2f,
    val maxCropDimensionPx: Int = 640
) {
    companion object {
        const val SPEED_THRESHOLD_MPS = 1.2f
        const val MAX_CROP_DIMENSION = 640
    }

    /**
     * Determines whether Quiet Mode is active based on speed, zone flag, or user config (FR2.065).
     */
    fun isQuietModeActive(currentSpeedMps: Float): Boolean {
        if (walkingQuietConfigEnabled || zoneWalkingQuietFlag) {
            return true
        }
        return currentSpeedMps > walkingSpeedThresholdMps
    }

    /**
     * Determines whether an audio cue / TTS readback should be spoken.
     * Errors and emergency alerts are ALWAYS permitted; conversational prompts are suppressed (TC2.156).
     */
    fun shouldSpeakAudio(isErrorOrCritical: Boolean, currentSpeedMps: Float): Boolean {
        if (isErrorOrCritical) {
            return true
        }
        return !isQuietModeActive(currentSpeedMps)
    }

    /**
     * Determines whether a visual prompt should be rendered on the lens HUD.
     * In quiet mode, only compact status marks or error cues are shown (TC2.110).
     */
    fun shouldRenderPromptOnLens(isErrorOrCritical: Boolean, currentSpeedMps: Float): Boolean {
        if (isErrorOrCritical) {
            return true
        }
        return !isQuietModeActive(currentSpeedMps)
    }

    /**
     * Validates that crop image dimensions obey the 640x640 bounding cap (FR2.066).
     */
    fun validateCropDimensions(width: Int, height: Int): Boolean {
        return width <= maxCropDimensionPx && height <= maxCropDimensionPx
    }

    /**
     * Validates that full-frame persistence is prevented and only bounding box crops are stored (FR2.066).
     */
    fun allowStorage(isFullFrame: Boolean, hasExif: Boolean): Boolean {
        if (isFullFrame) {
            return false // Strict ban: no full-frame persistence
        }
        if (hasExif) {
            return false // Strict ban: EXIF metadata must be stripped
        }
        return true
    }
}
