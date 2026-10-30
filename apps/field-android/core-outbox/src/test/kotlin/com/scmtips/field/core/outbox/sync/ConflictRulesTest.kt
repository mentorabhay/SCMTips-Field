package com.scmtips.field.core.outbox.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** ConflictPolicy against the BR2.11 conflict rules (FR2.041) and the FR2.045 retry ladder. */
class ConflictRulesTest {
    private fun eval(code: Int, body: String? = null, attempts: Int = 0, recompressed: Boolean = false, net: Boolean = false) =
        ConflictPolicy.evaluate(code, body, attempts, recompressed, net)

    @Test
    fun fr2_041_responseCodesMapToBr2_11States() {
        assertEquals(SyncDecision.Ack("srv-1", false), eval(201, """{"id":"srv-1"}"""))
        assertEquals(
            SyncDecision.Ack("cap-9", true),
            eval(409, """{"code":"FIELD-CAP-409-DUPLICATE","errors":[{"duplicate_of":"cap-9"}]}"""),
        )
        assertTrue(eval(410) is SyncDecision.Reject)
        assertTrue(eval(422, """{"code":"FIELD-IDEM-422-KEY-REUSE"}""") is SyncDecision.Quarantine)
        assertTrue(eval(401) is SyncDecision.PauseAll)
        assertTrue(eval(403) is SyncDecision.PauseAll)
        assertEquals(SyncDecision.RecompressAndRetry, eval(413))
        assertTrue("413 after recompression", eval(413, recompressed = true) is SyncDecision.Quarantine)
        assertTrue(eval(503) is SyncDecision.Retry)
        assertTrue(eval(429) is SyncDecision.Retry)
        assertTrue(eval(0, net = true) is SyncDecision.Retry)
        assertTrue(eval(418) is SyncDecision.Quarantine)
    }

    @Test
    fun aNonDuplicate409IsNeverAcked() {
        assertTrue(eval(409, """{"code":"FIELD-TASK-409-STATE"}""") is SyncDecision.Quarantine)
        assertTrue(eval(409) is SyncDecision.Quarantine)
    }

    @Test
    fun fr2_045_retryLadderIs2_4_8_16_32ThenExponentialFrom30sCappedAt300s() {
        val delays = (0..10).map { ConflictPolicy.calculateRetryDelayMs(it) / 1000 }
        assertEquals(listOf(2L, 4L, 8L, 16L, 32L, 30L, 60L, 120L, 240L, 300L, 300L), delays)
        assertEquals(SyncDecision.Retry(8_000, "Server error (503): retrying in 8s"), eval(503, attempts = 2))
    }
}
