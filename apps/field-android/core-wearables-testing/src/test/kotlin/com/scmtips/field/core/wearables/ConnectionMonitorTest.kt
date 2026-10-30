package com.scmtips.field.core.wearables

import com.scmtips.field.core.wearables.mock.MockWearablesKit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** ConnectionMonitor against FR2.015: backoff 1,2,4,8,16,30 s capped, same pairing, look discarded, preview resumed. */
class ConnectionMonitorTest {

    private class Listener : DisconnectRecoveryListener {
        var discarded = 0
        var resumed = 0
        override fun onLookInProgressDiscarded() { discarded++ }
        override fun onPreviewResumed() { resumed++ }
    }

    @Test
    fun fr2_015_backoffScheduleIsCappedAt30s() {
        val m = ConnectionMonitor(MockWearablesKit())
        assertEquals(listOf(1_000L, 2_000L, 4_000L, 8_000L, 16_000L, 30_000L, 30_000L, 30_000L), (0..7).map { m.getNextDelayMs(it) })
    }

    @Test
    fun fr2_015_twentyDisconnectsReconnectToTheSameDeviceWithBackoff() = runBlocking {
        val kit = MockWearablesKit()
        kit.connect("AA:BB:CC", "Ray-Ban Meta Gen 2")
        kit.previewStream.startStream()
        val listener = Listener()
        val sleeps = mutableListOf<Long>()
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val monitor = ConnectionMonitor(kit, listener, scope, sleep = { synchronized(sleeps) { sleeps += it } })
        monitor.onConnected("AA:BB:CC", "Ray-Ban Meta Gen 2")

        repeat(20) { i ->
            val failures = i % 8 // 0..7 failed attempts before success
            kit.failNextConnects = failures
            kit.injectDisconnect()
            synchronized(sleeps) { sleeps.clear() }
            monitor.onDisconnected()
            withTimeout(5_000) { while (monitor.reconnectCount.value < i + 1) yield() }
            val expected = (0..failures).map { monitor.getNextDelayMs(it) }
            assertEquals("disconnect $i", expected, synchronized(sleeps) { sleeps.toList() })
            assertTrue("preview resumed after disconnect $i", kit.previewStream.isStreaming())
        }
        assertEquals(20, listener.discarded)
        assertEquals(20, listener.resumed)
        assertTrue("no new pairing: always the stored address", kit.connectAddresses.all { it == "AA:BB:CC" })
        monitor.stopMonitoring()
    }

    @Test
    fun disconnectBeforeAnyConnectionOnlyDiscardsTheLook() {
        val listener = Listener()
        val m = ConnectionMonitor(MockWearablesKit(), listener, sleep = { error("must not retry") })
        m.onDisconnected()
        assertEquals(1, listener.discarded)
        assertEquals(0, m.reconnectCount.value)
    }
}
