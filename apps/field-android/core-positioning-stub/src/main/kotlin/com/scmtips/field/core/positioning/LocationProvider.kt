package com.scmtips.field.core.positioning

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Data class representing a location in the warehouse or site hierarchy.
 */
data class FieldLocation(
    val siteId: String,
    val zone: String? = null,
    val aisle: String? = null,
    val rack: String? = null,
    val bin: String? = null,
    val anchorType: AnchorType = AnchorType.MANUAL,
    val qrPayload: String? = null,
    val timestampMs: Long = System.currentTimeMillis()
)

enum class AnchorType {
    MANUAL,
    QR_ANCHOR
}

/**
 * LocationProvider contract for Phase 2 (:core-positioning-stub).
 * Exposes the manually chosen or QR-anchor location only (T2.002 / FR2.006).
 */
interface LocationProvider {
    val currentLocation: StateFlow<FieldLocation?>
    fun setManualLocation(siteId: String, zone: String? = null, bin: String? = null)
    fun setQrAnchorLocation(siteId: String, qrPayload: String, zone: String? = null, bin: String? = null)
    fun clearLocation()
}

class StubLocationProvider : LocationProvider {
    private val _currentLocation = MutableStateFlow<FieldLocation?>(null)
    override val currentLocation: StateFlow<FieldLocation?> = _currentLocation.asStateFlow()

    override fun setManualLocation(siteId: String, zone: String?, bin: String?) {
        _currentLocation.value = FieldLocation(
            siteId = siteId,
            zone = zone,
            bin = bin,
            anchorType = AnchorType.MANUAL
        )
    }

    override fun setQrAnchorLocation(siteId: String, qrPayload: String, zone: String?, bin: String?) {
        _currentLocation.value = FieldLocation(
            siteId = siteId,
            zone = zone,
            bin = bin,
            anchorType = AnchorType.QR_ANCHOR,
            qrPayload = qrPayload
        )
    }

    override fun clearLocation() {
        _currentLocation.value = null
    }
}
