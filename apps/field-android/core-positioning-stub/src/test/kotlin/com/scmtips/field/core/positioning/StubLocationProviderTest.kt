package com.scmtips.field.core.positioning

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Phase 2 positioning is manual or QR-anchor only (T2.002); no inferred location. */
class StubLocationProviderTest {
    @Test
    fun manualAndQrAnchorLocationsAreReportedAsSetAndCanBeCleared() {
        val p = StubLocationProvider()
        assertNull(p.currentLocation.value)
        p.setManualLocation("S-1", zone = "Z1", bin = "B-01")
        assertEquals(AnchorType.MANUAL, p.currentLocation.value!!.anchorType)
        assertEquals("B-01", p.currentLocation.value!!.bin)
        p.setQrAnchorLocation("S-1", qrPayload = "QR:Z2", zone = "Z2")
        assertEquals(AnchorType.QR_ANCHOR, p.currentLocation.value!!.anchorType)
        assertEquals("QR:Z2", p.currentLocation.value!!.qrPayload)
        assertNull(p.currentLocation.value!!.bin)
        p.clearLocation()
        assertNull(p.currentLocation.value)
    }
}
