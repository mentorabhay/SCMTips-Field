package com.scmtips.field.core.wearables.testing

import com.scmtips.field.core.wearables.DrawCall
import com.scmtips.field.core.wearables.lens.RayBanLensRenderer

/**
 * FakeLensRenderer for unit and instrumented tests (T2.014 / TC2.113).
 * Records every render call in memory because Mock Device Kit does not simulate display hardware.
 * Resides in :core-wearables-testing to preserve architectural firewall (Rule 2.2 / Finding F-07).
 */
class FakeLensRenderer : RayBanLensRenderer() {
    private val recordedDrawCalls = mutableListOf<DrawCall>()

    override fun executeHardwareDraw(drawCall: DrawCall) {
        synchronized(recordedDrawCalls) {
            recordedDrawCalls.add(drawCall)
        }
    }

    fun getDrawCalls(): List<DrawCall> = synchronized(recordedDrawCalls) {
        recordedDrawCalls.toList()
    }

    fun getLastDrawCall(): DrawCall? = synchronized(recordedDrawCalls) {
        recordedDrawCalls.lastOrNull()
    }

    fun clear() {
        synchronized(recordedDrawCalls) {
            recordedDrawCalls.clear()
        }
    }
}
