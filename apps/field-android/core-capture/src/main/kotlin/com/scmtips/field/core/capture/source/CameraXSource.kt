package com.scmtips.field.core.capture.source

import com.scmtips.field.core.wearables.CapturedPhoto
import com.scmtips.field.core.wearables.PreviewFrame
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow

data class PhoneImuReading(
    val angularSpeedRadPerSec: Float,
    val isStationary: Boolean,
    val timestampMs: Long = System.currentTimeMillis()
)

/**
 * CameraX video analysis and still capture source for phone-only operation (Task T2.018 / FR2.008 / TC2.165).
 * Feeds 640x480 YUV frames and stills into the perception pipeline when glasses are not paired.
 */
class CameraXSource(
    private val isPhoneCameraAllowed: () -> Boolean = { true },
    /** Platform still capture (CameraX ImageCapture). Not wired yet: UNVERIFIED. */
    private val stillCapture: (suspend () -> CapturedPhoto)? = null
) {
    companion object {
        const val FRAME_WIDTH = 640
        const val FRAME_HEIGHT = 480
        const val STATIONARY_SPEED_THRESHOLD = 0.35f // rad/sec
    }

    private val _frameFlow = MutableSharedFlow<PreviewFrame>(replay = 1)
    val frames: Flow<PreviewFrame> = _frameFlow.asSharedFlow()

    private var isAnalysisActive = false
    private var lastImuReading = PhoneImuReading(angularSpeedRadPerSec = 0.05f, isStationary = true)

    fun startAnalysis(): Boolean {
        if (!isPhoneCameraAllowed()) {
            return false
        }
        isAnalysisActive = true
        return true
    }

    fun stopAnalysis() {
        isAnalysisActive = false
    }

    fun updateImu(angularSpeedRadPerSec: Float) {
        val stationary = angularSpeedRadPerSec < STATIONARY_SPEED_THRESHOLD
        lastImuReading = PhoneImuReading(
            angularSpeedRadPerSec = angularSpeedRadPerSec,
            isStationary = stationary
        )
    }

    fun getHeadSpeedEquivalent(): Float = lastImuReading.angularSpeedRadPerSec

    fun isStationary(): Boolean = lastImuReading.isStationary

    suspend fun emitCameraFrame(yuvBytes: ByteArray) {
        if (!isAnalysisActive) return
        val frame = PreviewFrame(
            width = FRAME_WIDTH,
            height = FRAME_HEIGHT,
            data = yuvBytes,
            timestampMs = System.currentTimeMillis()
        )
        _frameFlow.emit(frame)
    }

    suspend fun captureStillPhoto(): CapturedPhoto {
        check(isPhoneCameraAllowed()) { "Phone camera capture disallowed by MDM" }
        val capture = checkNotNull(stillCapture) { "CameraX still capture is not wired (UNVERIFIED)" }
        return capture()
    }
}
