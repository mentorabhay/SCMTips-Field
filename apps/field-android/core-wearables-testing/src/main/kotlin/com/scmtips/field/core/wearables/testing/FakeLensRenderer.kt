package com.scmtips.field.core.wearables.testing

import com.scmtips.field.core.wearables.DrawCall
import com.scmtips.field.core.wearables.lens.RayBanLensRenderer

/**
 * Test double for the display drawing toolkit (T2.014; TC2.113): records every draw call that the
 * production [RayBanLensRenderer] layout produces. Lives in :core-wearables-testing (rule 2.4).
 */
class FakeLensRenderer private constructor(
    private val recordedDrawCalls: MutableList<DrawCall>,
) : RayBanLensRenderer({ call -> synchronized(recordedDrawCalls) { recordedDrawCalls.add(call) } }) {

    constructor() : this(mutableListOf())

    fun getDrawCalls(): List<DrawCall> = synchronized(recordedDrawCalls) { recordedDrawCalls.toList() }

    fun getLastDrawCall(): DrawCall? = synchronized(recordedDrawCalls) { recordedDrawCalls.lastOrNull() }

    fun clear() = synchronized(recordedDrawCalls) { recordedDrawCalls.clear() }
}
