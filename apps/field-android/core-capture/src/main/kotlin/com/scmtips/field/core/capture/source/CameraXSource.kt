package com.scmtips.field.core.capture.source

import com.scmtips.field.core.wearables.CapturedPhoto
import com.scmtips.field.core.wearables.PreviewFrame
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import java.util.UUID

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
    private val isPhoneCameraAllowed: () -> Boolean = { true }
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
            println("[CameraXSource] Phone camera mode blocked by MDM policy.")
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
        val traceId = UUID.randomUUID().toString().replace("-", "")
        val spanId = UUID.randomUUID().toString().replace("-", "").take(16)
        return CapturedPhoto(
            jpegBytes = ByteArray(2048) { 0xAA.toByte() }, // Simulated high-res JPEG
            width = 1920,
            height = 1080,
            timestampMs = System.currentTimeMillis(),
            traceparent = "00-$traceId-$spanId-01"
        )
    }
}
